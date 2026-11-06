"""Cross-posting to the Facebook Page after Instagram has published.

Best effort: called only after the Instagram post is live, and a failure here never
undoes or retries the Instagram post (the caller logs a warning instead).
Needs pages_manage_posts + pages_read_engagement on the token and the Page assigned
to the System User (README → Facebook).

  single image  -> POST {page}/photos
  carousel      -> unpublished {page}/photos for each image, then one {page}/feed post
  reel          -> Reels API: video_reels start -> rupload file_url -> finish (PUBLISHED)
Stories are not cross-posted (the Page API has no story publishing for photos from URLs).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from .config import MadError, log, settings, warn
from .instagram import GraphError, Instagram


def fb_caption(caption: str) -> str:
    """Instagram captions say "link in bio"; Facebook posts can carry a real link."""
    link = settings()["facebook"].get("link", "https://myanimedex.com")
    text = re.sub(r"\(link in bio\)", f"({link})", caption, flags=re.I)
    text = re.sub(r"from the link in bio", f"at {link}", text, flags=re.I)
    text = re.sub(r"(?<=[.!] )Link in bio\.", f"Get the app: {link}", text)
    return re.sub(r"link in bio", link, text, flags=re.I)


class FacebookPage:
    def __init__(self, ig: Instagram, page_id: str | None = None):
        self.page_id = str(page_id or settings()["facebook"]["page_id"])
        try:
            token = ig._call("GET", self.page_id, {"fields": "access_token"}, retry=False).get("access_token")
        except GraphError as exc:
            raise MadError(f"Could not get a Page token for {self.page_id} (is the Page assigned to the System "
                           f"User with pages_manage_posts?): {exc}") from exc
        if not token:
            raise MadError(f"No Page access token returned for {self.page_id}")
        self.api = Instagram(ig.ig_user_id, token)  # same Graph client, Page token

    def name(self) -> str:
        return self.api._call("GET", self.page_id, {"fields": "name"}).get("name", self.page_id)

    # ------------------------------------------------------------ publishing

    def photo(self, url: str, caption: str) -> str:
        res = self.api._call("POST", f"{self.page_id}/photos", {"url": url, "message": caption, "published": "true"})
        return res.get("post_id") or res["id"]

    def album(self, urls: list[str], caption: str) -> str:
        ids = [self.api._call("POST", f"{self.page_id}/photos", {"url": u, "published": "false"})["id"]
               for u in urls]
        params: dict[str, Any] = {"message": caption}
        for i, fbid in enumerate(ids):
            params[f"attached_media[{i}]"] = json.dumps({"media_fbid": fbid})
        return self.api._call("POST", f"{self.page_id}/feed", params, retry=False)["id"]

    def reel(self, video_url: str, caption: str) -> str:
        start = self.api._call("POST", f"{self.page_id}/video_reels", {"upload_phase": "start"})
        video_id = start["video_id"]
        upload_url = start.get("upload_url") or \
            f"https://rupload.facebook.com/video-upload/{settings()['instagram']['graph_version']}/{video_id}"
        resp = requests.post(upload_url, headers={"Authorization": f"OAuth {self.api.token}", "file_url": video_url},
                             timeout=120)
        if not resp.ok or not (resp.json() if resp.content else {}).get("success"):
            raise MadError(f"Facebook reel upload failed (HTTP {resp.status_code}): {resp.text[:300]}")
        self.api._call("POST", f"{self.page_id}/video_reels", {
            "upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED", "description": caption,
        }, retry=False)
        self._wait_reel(video_id)
        return video_id

    def _wait_reel(self, video_id: str, timeout: int = 600) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.api._call("GET", video_id, {"fields": "status"}).get("status") or {}
            if status.get("video_status") == "error":
                raise MadError(f"Facebook reel {video_id} failed processing: {status}")
            if (status.get("publishing_phase") or {}).get("status") == "complete":
                return
            time.sleep(10)
        warn(f"Facebook reel {video_id} still processing after {timeout}s — it publishes when processing ends")


def cross_post(ig: Instagram, slot_name: str, urls: list[str], caption: str) -> str | None:
    if slot_name == "story" or not settings().get("facebook", {}).get("enabled"):
        return None
    page = FacebookPage(ig)
    text = fb_caption(caption)
    if slot_name == "reel":
        return page.reel(next(u for u in urls if u.endswith(".mp4")), text)
    images = [u for u in urls if u.endswith((".jpg", ".png"))]
    fb_id = page.album(images, text) if len(images) > 1 else page.photo(images[0], text)
    log(f"Facebook post {fb_id}")
    return fb_id
