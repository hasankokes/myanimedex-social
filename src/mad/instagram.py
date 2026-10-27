"""Instagram Graph API content publishing (Instagram API with Facebook Login).

Flow, all-or-nothing:
  1. create every media container (carousel children first, then the parent)
  2. poll each container until status_code == FINISHED (any ERROR/EXPIRED aborts)
  3. only then call media_publish — once.
If anything fails before step 3 nothing is visible on the account; unpublished
containers simply expire after 24 h.
"""
from __future__ import annotations

import os
import random
import time
from typing import Any

import requests

from .config import MadError, log, settings, warn

# Graph error codes worth retrying (rate limits / temporary).
TRANSIENT_CODES = {1, 2, 4, 17, 32, 341, 613, 9004, 2207001, 2207003, 2207020}
TOKEN_CODES = {102, 190, 463, 467}
PERMISSION_CODES = {10, 200, 3, 299}


class GraphError(MadError):
    def __init__(self, message: str, code: int | None = None, transient: bool = False):
        super().__init__(message)
        self.code = code
        self.transient = transient


class Instagram:
    def __init__(self, ig_user_id: str | None = None, token: str | None = None):
        self.ig_user_id = (ig_user_id or os.environ.get("IG_USER_ID", "")).strip()
        self.token = (token or os.environ.get("ACCESS_TOKEN", "")).strip()
        missing = [n for n, v in (("IG_USER_ID", self.ig_user_id), ("ACCESS_TOKEN", self.token)) if not v]
        if missing:
            raise MadError(f"Missing secret(s): {', '.join(missing)}. Add them in GitHub → Settings → "
                           "Secrets and variables → Actions, or run with --dry-run.")
        cfg = settings()["instagram"]
        self.base = f"{cfg['graph_base_url']}/{cfg['graph_version']}"
        self.cfg = cfg

    # ------------------------------------------------------------ http

    def _call(self, method: str, path: str, params: dict[str, Any] | None = None, retry: bool = True) -> dict:
        attempts = self.cfg["max_retries"] if retry else 1
        for attempt in range(1, attempts + 1):
            try:
                resp = requests.request(
                    method, f"{self.base}/{path}",
                    params=params if method == "GET" else None,
                    data=params if method != "GET" else None,
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=60,
                )
                body = resp.json() if resp.content else {}
            except (requests.RequestException, ValueError) as exc:
                err = GraphError(f"Network error calling Graph API {path}: {type(exc).__name__}", transient=True)
            else:
                if resp.ok and "error" not in body:
                    return body
                err = self._error(body.get("error") or {}, resp.status_code, path)
            if not err.transient or attempt == attempts:
                raise err
            delay = min(120, 5 * 2 ** attempt) + random.random() * 3
            warn(f"{err} — retry {attempt}/{attempts - 1} in {delay:.0f}s")
            time.sleep(delay)
        raise AssertionError("unreachable")

    def _error(self, e: dict, status: int, path: str) -> GraphError:
        code = e.get("code")
        sub = e.get("error_subcode")
        msg = (e.get("error_user_msg") or e.get("message") or f"HTTP {status}").replace(self.token, "***")
        detail = f"Graph API {path} failed (code {code}{f'/{sub}' if sub else ''}, trace {e.get('fbtrace_id')}): {msg}"
        if code in TOKEN_CODES:
            return GraphError(f"ACCESS_TOKEN is invalid or expired. Generate a new token (see README → Token) "
                              f"and update the secret. {detail}", code)
        if code in PERMISSION_CODES:
            return GraphError(f"Missing permission. The token needs instagram_basic, instagram_content_publish, "
                              f"pages_show_list, pages_read_engagement and business_management. {detail}", code)
        if code == 9004 or sub == 2207052:
            return GraphError(f"Instagram could not download the image URL (is GitHub Pages live and public?). "
                              f"{detail}", code, transient=True)
        return GraphError(detail, code, transient=code in TRANSIENT_CODES or status >= 500)

    # ------------------------------------------------------------ checks

    def check(self) -> dict[str, Any]:
        account = self._call("GET", self.ig_user_id, {"fields": "id,username,name"})
        quota = self.quota()
        try:
            perms = self._call("GET", "me/permissions", retry=False).get("data", [])
            granted = sorted(p["permission"] for p in perms if p.get("status") == "granted")
        except GraphError:
            granted = []
        return {"username": account.get("username"), "quota": quota, "permissions": granted}

    def quota(self) -> dict[str, Any]:
        data = self._call("GET", f"{self.ig_user_id}/content_publishing_limit",
                          {"fields": "quota_usage,config"}).get("data") or [{}]
        return data[0]

    # ------------------------------------------------------------ containers

    def _create(self, params: dict[str, Any]) -> str:
        return self._call("POST", f"{self.ig_user_id}/media", params)["id"]

    def _status(self, container_id: str) -> str:
        return self._call("GET", container_id, {"fields": "status_code,status"}).get("status_code", "")

    def _wait_ready(self, ids: list[str]) -> None:
        deadline = time.time() + self.cfg["status_timeout_seconds"]
        pending = set(ids)
        while pending:
            for cid in sorted(pending):
                status = self._status(cid)
                if status == "FINISHED":
                    pending.discard(cid)
                elif status in {"ERROR", "EXPIRED"}:
                    detail = self._call("GET", cid, {"fields": "status"}).get("status", "")
                    raise MadError(f"Container {cid} failed processing ({status}): {detail}. Nothing was published.")
            if pending:
                if time.time() > deadline:
                    raise MadError(f"Containers still processing after {self.cfg['status_timeout_seconds']}s: "
                                   f"{sorted(pending)}. Nothing was published.")
                time.sleep(self.cfg["status_poll_seconds"])
        log(f"All {len(ids)} container(s) FINISHED")

    def _publish(self, creation_id: str) -> str:
        """media_publish is never blindly retried: a timeout might still have published."""
        try:
            return self._call("POST", f"{self.ig_user_id}/media_publish", {"creation_id": creation_id},
                              retry=False)["id"]
        except GraphError as exc:
            warn(f"media_publish returned an error, checking whether it went through: {exc}")
            time.sleep(10)
            if self._status(creation_id) == "PUBLISHED":
                log("Container reports PUBLISHED — treating as success")
                return f"container:{creation_id}"
            if exc.transient:
                time.sleep(30)
                return self._call("POST", f"{self.ig_user_id}/media_publish", {"creation_id": creation_id},
                                  retry=False)["id"]
            raise

    # ------------------------------------------------------------ public API

    def publish_image(self, url: str, caption: str) -> str:
        cid = self._create({"image_url": url, "caption": caption})
        log(f"Created image container {cid}")
        self._wait_ready([cid])
        return self._publish(cid)

    def publish_carousel(self, urls: list[str], caption: str) -> str:
        if not 2 <= len(urls) <= 10:
            raise MadError(f"A carousel needs 2–10 images, got {len(urls)}")
        children = []
        for i, url in enumerate(urls, 1):
            children.append(self._create({"image_url": url, "is_carousel_item": "true"}))
            log(f"Created carousel item {i}/{len(urls)}: {children[-1]}")
        self._wait_ready(children)
        parent = self._create({"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})
        log(f"Created carousel container {parent}")
        self._wait_ready([parent])
        return self._publish(parent)

    def publish_story(self, url: str) -> str:
        cid = self._create({"image_url": url, "media_type": "STORIES"})
        log(f"Created story container {cid}")
        self._wait_ready([cid])
        return self._publish(cid)

    def ensure_quota(self, needed: int = 1) -> None:
        q = self.quota()
        usage = q.get("quota_usage", 0)
        total = (q.get("config") or {}).get("quota_total", 100)
        log(f"Publishing quota: {usage}/{total} used in the last 24h")
        if usage + needed > total:
            raise MadError(f"Instagram publishing limit reached ({usage}/{total} in 24h). Nothing was published.")
