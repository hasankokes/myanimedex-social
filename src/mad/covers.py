"""Anime cover images from AniList's CDN, cached on disk.

A missing cover never blocks a post: callers get None and the template falls back
to its typographic layout.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from .config import ROOT, warn

CACHE = ROOT / ".cache" / "covers"


def cover_path(media: dict[str, Any]) -> Path | None:
    cover = media.get("coverImage") or {}
    url = cover.get("extraLarge") or cover.get("large")
    if not url:
        return None
    target = CACHE / f"{media['id']}.jpg"
    if target.exists():
        return target
    CACHE.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "myanimedex-social/1.0"})
            resp.raise_for_status()
            tmp = target.with_suffix(".part")
            tmp.write_bytes(resp.content)
            Image.open(tmp).convert("RGB").save(target, "JPEG", quality=95)
            tmp.unlink()
            return target
        except (requests.RequestException, OSError) as exc:
            if attempt == 3:
                warn(f"Cover for anime {media['id']} unavailable ({exc}); using the typographic layout")
                return None
            time.sleep(2 * attempt)
    return None
