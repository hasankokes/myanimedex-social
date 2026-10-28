"""posted_state.json: what was published, when, and which anime/features were used.

The state is only written after a successful publish, so a failed or dry run never
"consumes" an anime or a feature.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from .config import STATE_FILE

EMPTY: dict[str, Any] = {
    "version": 1,
    "slots": {},        # "2026-10-27:post" -> {kind, published_at, media_id, anime_ids}
    "anime": {},        # anilist id (str) -> last date featured (YYYY-MM-DD)
    "features": {"last_id": None},
    "tips": {"last_id": None},
    "reel_demos": {"last_id": None},
    "top5_last": [],    # anilist ids of the last published Top 5, rank order
}


def load() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return json.loads(json.dumps(EMPTY))
    data = json.loads(STATE_FILE.read_text("utf-8"))
    for key, value in EMPTY.items():
        data.setdefault(key, json.loads(json.dumps(value)))
    return data


def save(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n", "utf-8")


def recently_used(state: dict[str, Any], today: date, cooldown_days: int) -> set[int]:
    cutoff = today - timedelta(days=cooldown_days)
    return {int(k) for k, d in state["anime"].items() if date.fromisoformat(d) > cutoff}


def record_publish(state: dict[str, Any], slot_key: str, slot: dict[str, Any], media_id: str, published_at: str) -> None:
    day = slot_key.split(":")[0]
    anime_ids = slot.get("anime_ids", [])
    state["slots"][slot_key] = {
        "kind": slot["kind"],
        "published_at": published_at,
        "media_id": media_id,
        "anime_ids": anime_ids,
    }
    for aid in anime_ids:
        state["anime"][str(aid)] = day
    if slot["kind"] == "feature":
        state["features"]["last_id"] = slot["data"]["feature"]["id"]
    elif slot["kind"] == "reel_app_demo":
        state["reel_demos"]["last_id"] = slot["data"]["demo"]["id"]
    elif slot["kind"] == "story_tip":
        state["tips"]["last_id"] = slot["data"]["tip"]["id"]
    elif slot["kind"] == "top5":
        state["top5_last"] = [a["id"] for a in slot["data"]["items"]]
    # Keep the file small: drop anime entries older than a year.
    cutoff = (date.fromisoformat(day) - timedelta(days=365)).isoformat()
    state["anime"] = {k: v for k, v in state["anime"].items() if v >= cutoff}
