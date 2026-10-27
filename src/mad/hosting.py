"""Public image hosting on GitHub Pages (free).

Images are pushed to the `gh-pages` branch, which GitHub Pages serves at
`hosting.pages_base_url`. The branch is rewritten as a single orphan commit every
time, so old images never pile up in git history; files older than the retention
window are pruned.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from .config import ROOT, MadError, log, settings, warn


def _git(*args: str, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise MadError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[:500]}")
    return proc


def _prune(site: Path, today: date) -> None:
    cfg = settings()["hosting"]
    media_cutoff = (today - timedelta(days=cfg["media_retention_days"])).isoformat()
    for d in (site / "media").glob("*"):
        if d.is_dir() and d.name[:10] < media_cutoff:
            shutil.rmtree(d)
    week_cutoff = today - timedelta(weeks=cfg["preview_retention_weeks"])
    for d in (site / "preview").glob("*"):
        m = re.fullmatch(r"(\d{4})-W(\d{2})", d.name)
        if d.is_dir() and m and date.fromisocalendar(int(m[1]), int(m[2]), 1) < week_cutoff:
            shutil.rmtree(d)


def upload(files: dict[str, Path], today: date, label: str) -> dict[str, str]:
    """Copy {published/path.jpg: local file} to the Pages branch, push, return public URLs."""
    cfg = settings()["hosting"]
    branch = cfg["branch"]
    base = cfg["pages_base_url"].rstrip("/")
    with tempfile.TemporaryDirectory(prefix="mad-pages-") as tmp:
        site = Path(tmp) / "site"
        has_branch = _git("ls-remote", "--exit-code", "--heads", "origin", branch, check=False).returncode == 0
        if has_branch:
            _git("fetch", "--depth=1", "origin", f"+{branch}:refs/remotes/origin/{branch}")
            _git("worktree", "add", "--detach", str(site), f"origin/{branch}")
        else:
            warn(f"Branch {branch} does not exist yet; creating it")
            _git("worktree", "add", "--detach", str(site))
            _git("rm", "-rf", "--quiet", ".", cwd=site)
        try:
            for dest in {str(Path(p).parent) for p in files}:
                if (site / dest).exists():
                    shutil.rmtree(site / dest)
            for dest, src in files.items():
                (site / dest).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, site / dest)
            _prune(site, today)
            (site / ".nojekyll").touch()
            if not (site / "index.html").exists():
                (site / "index.html").write_text(
                    '<!doctype html><meta charset="utf-8"><title>MyAnimeDex media</title>'
                    '<meta http-equiv="refresh" content="0; url=https://myanimedex.com">', "utf-8")
            _git("add", "-A", cwd=site)
            tree = _git("write-tree", cwd=site).stdout.strip()
            env_author = ["-c", "user.name=myanimedex-bot", "-c", "user.email=bot@myanimedex.com"]
            commit = subprocess.run(["git", *env_author, "commit-tree", tree, "-m", f"media: {label}"],
                                    cwd=site, capture_output=True, text=True, check=True).stdout.strip()
            for attempt in range(3):
                if _git("push", "--force", "origin", f"{commit}:refs/heads/{branch}", check=False).returncode == 0:
                    break
                time.sleep(5 * (attempt + 1))
            else:
                raise MadError(f"Could not push images to the {branch} branch")
        finally:
            _git("worktree", "remove", "--force", str(site), check=False)
    log(f"Pushed {len(files)} file(s) to {branch} ({label})")
    _request_pages_build()
    return {dest: f"{base}/{dest}" for dest in files}


def _request_pages_build() -> None:
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not (repo and token):
        return
    try:
        resp = requests.post(f"https://api.github.com/repos/{repo}/pages/builds",
                             headers={"Authorization": f"Bearer {token}",
                                      "Accept": "application/vnd.github+json"}, timeout=30)
        if resp.status_code >= 300:
            warn(f"Pages build request returned HTTP {resp.status_code} (the push usually triggers it anyway)")
    except requests.RequestException as exc:
        warn(f"Pages build request failed: {exc}")


def wait_live(urls: list[str]) -> None:
    """Block until every URL serves a JPEG — Instagram fetches them right away."""
    timeout = settings()["hosting"]["live_timeout_seconds"]
    deadline = time.time() + timeout
    pending = list(urls)
    while pending:
        still = []
        for url in pending:
            try:
                r = requests.head(url, timeout=20, allow_redirects=True)
                ok = r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/jpeg")
            except requests.RequestException:
                ok = False
            if not ok:
                still.append(url)
        pending = still
        if pending:
            if time.time() > deadline:
                raise MadError(f"GitHub Pages did not serve {len(pending)} image(s) within {timeout}s "
                               f"(first: {pending[0]}). Check Settings → Pages (source: {settings()['hosting']['branch']} "
                               "branch). Nothing was published.")
            time.sleep(10)
    log(f"All {len(urls)} image URL(s) are live")
