"""Weekly content plan: picks anime/features for every slot and freezes the data.

`plans/<YYYY-Www>.json` is created on Sunday (weekly preview) and the daily jobs render
exactly what is in it, so the preview you approve is what gets posted. Edit captions or set
`"skip": true` on a slot in that file to change the week by hand.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable

from . import anilist, captions, state as state_mod
from .config import PLANS_DIR, MadError, load_yaml, log, settings, warn

# (ISO weekday 1=Mon, slot, kind)
SCHEDULE: list[tuple[int, str, str]] = [
    (1, "post", "airing_week"),
    (3, "post", "feature"),
    (6, "post", "top5"),
    (1, "story", "story_anime_of_day"),
    (2, "story", "story_tip"),
    (3, "story", "story_your_pick"),
    (4, "story", "story_download"),
    (5, "story", "story_weekend"),
]
POST_KINDS = ["airing_week", "feature", "top5"]
STORY_KINDS = ["story_anime_of_day", "story_tip", "story_your_pick", "story_download", "story_weekend"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

KEEP_FIELDS = ["id", "idMal", "title", "format", "status", "episodes", "season", "seasonYear",
               "averageScore", "popularity", "duration", "genres", "siteUrl", "nextAiringEpisode", "airing"]


# ---------------------------------------------------------------- helpers

def week_id(day: date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def week_monday(week: str) -> date:
    return date.fromisocalendar(int(week[:4]), int(week.split("W")[1]), 1)


def slot_key(day: date, slot: str) -> str:
    return f"{day.isoformat()}:{slot}"


def kind_for(day: date, slot: str) -> str | None:
    return next((k for wd, s, k in SCHEDULE if wd == day.isoweekday() and s == slot), None)


def snapshot(media: dict[str, Any]) -> dict[str, Any]:
    snap = {k: media.get(k) for k in KEEP_FIELDS if k in media}
    snap["studio"] = next((n["name"] for n in (media.get("studios") or {}).get("nodes", [])), None)
    return snap


def _pick(pool: list[dict[str, Any]], n: int, blocked: set[int], label: str) -> list[dict[str, Any]]:
    """First n items not blocked (cooldown / already in this plan); falls back to blocked ones."""
    fresh = [m for m in pool if m["id"] not in blocked]
    chosen = fresh[:n]
    if len(chosen) < n:
        extra = [m for m in pool if m not in chosen][: n - len(chosen)]
        if extra:
            warn(f"{label}: only {len(fresh)} anime outside the cooldown, reusing {len(extra)}")
        chosen += extra
    if len(chosen) < n:
        raise MadError(f"{label}: AniList returned only {len(chosen)} eligible anime (need {n}). "
                       "Lower the popularity thresholds in config.yaml or try again later.")
    return chosen


def _rotate(items: list[dict[str, Any]], last_id: str | None, label: str) -> dict[str, Any]:
    items = [i for i in items if i.get("enabled", True)]
    if not items:
        raise MadError(f"content/{label}.yaml has no enabled entries")
    ids = [i["id"] for i in items]
    if len(set(ids)) != len(ids):
        raise MadError(f"content/{label}.yaml has duplicate ids")
    idx = (ids.index(last_id) + 1) % len(items) if last_id in ids else 0
    return items[idx]


def _date_range(start: date) -> str:
    end = start + timedelta(days=6)
    left = start.strftime("%b %-d")
    right = end.strftime("%-d") if end.month == start.month else end.strftime("%b %-d")
    return f"{left} – {right}"


def _fmt_count(n: int) -> str:
    return f"{n / 1000:.0f}K" if n >= 10_000 else f"{n / 1000:.1f}K" if n >= 1000 else str(n)


# ---------------------------------------------------------------- slot builders

class Ctx:
    def __init__(self, day: date, st: dict[str, Any], taken: set[int]):
        self.day = day
        self.state = st
        self.taken = taken
        self.sel = settings()["selection"]
        self.season, self.year = anilist.season_of(datetime.combine(day, time(), timezone.utc))
        self.blocked = state_mod.recently_used(st, day, self.sel["anime_cooldown_days"]) | taken
        self.seed = day.isocalendar()[1]


def _season_pool(ctx: Ctx, min_pop: int, sort: str) -> list[dict[str, Any]]:
    return anilist.season_ranked(ctx.season, ctx.year, min_pop, sort)


def build_airing_week(ctx: Ctx) -> dict[str, Any]:
    monday = ctx.day - timedelta(days=ctx.day.isoweekday() - 1)
    start = datetime.combine(monday, time(), timezone.utc)
    pool = [m for m in anilist.airing_between(start, start + timedelta(days=7))
            if (m.get("popularity") or 0) >= ctx.sel["airing_min_popularity"]]
    pool.sort(key=lambda m: -(m.get("popularity") or 0))
    anilist.log_count("anime airing this week (above popularity floor)", pool)
    chosen = _pick(pool, ctx.sel["airing_slides"], ctx.blocked, "Airing this week")
    items = []
    for m in chosen:
        snap = snapshot(m)
        snap["airing_day"] = WEEKDAYS[datetime.fromtimestamp(m["airing"]["airingAt"], timezone.utc).weekday()]
        items.append(snap)
    fields = {
        "season_label": captions.season_label(ctx.season, ctx.year),
        "date_range": _date_range(monday),
        "top_title": captions.display_title(items[0]),
        "list": "\n".join(f"{i}. {captions.display_title(m)} — Ep {m['airing']['episode']} ({m['airing_day']})"
                          for i, m in enumerate(items, 1)),
    }
    tags = captions.hashtags(ctx.season, ctx.year, items[0])
    return {
        "data": {"items": items, "date_range": fields["date_range"], "season": ctx.season, "year": ctx.year},
        "anime_ids": [m["id"] for m in items],
        "caption": captions.build("airing_week", ctx.seed, fields, tags),
    }


def build_top5(ctx: Ctx) -> dict[str, Any]:
    size = ctx.sel["top5_size"]
    season, year = ctx.season, ctx.year
    for _ in range(2):
        pool = [m for m in anilist.season_ranked(season, year, ctx.sel["top5_min_popularity"])
                if m.get("averageScore")]
        if len(pool) >= size:
            break
        warn(f"Top 5: only {len(pool)} scored {season} {year} anime yet; using the previous season")
        season, year = anilist.previous_season(season, year)
    else:
        raise MadError("Top 5: not enough scored anime in the current or previous season")
    pool.sort(key=lambda m: (-m["averageScore"], -(m.get("popularity") or 0)))
    last = ctx.state.get("top5_last") or []
    items = []
    for rank, m in enumerate(pool[:size], 1):
        snap = snapshot(m)
        snap["rank"] = rank
        snap["studio"] = snap.get("studio")
        snap["movement"] = "new" if m["id"] not in last else last.index(m["id"]) + 1 - rank
        items.append(snap)
    fields = {
        "season_label": captions.season_label(season, year),
        "top_title": captions.display_title(items[0]),
        "top_score": captions.score10(items[0]),
        "list": "\n".join(f"#{m['rank']} {captions.display_title(m)} — {captions.score10(m)}/10" for m in items),
    }
    tags = captions.hashtags(season, year, items[0])
    return {
        "data": {"items": items, "season": season, "year": year,
                 "min_popularity_label": _fmt_count(ctx.sel["top5_min_popularity"])},
        "anime_ids": [m["id"] for m in items],
        "caption": captions.build("top5", ctx.seed, fields, tags),
    }


def build_feature(ctx: Ctx) -> dict[str, Any]:
    feature = _rotate(load_yaml("features.yaml").get("features") or [], ctx.state["features"]["last_id"], "features")
    fields = {"season_label": captions.season_label(ctx.season, ctx.year),
              "title": feature["title"], "description": feature["description"].strip()}
    tags = captions.hashtags(ctx.season, ctx.year, None)
    swipe = "👉 Swipe to see it in the app." if feature.get("screenshot") else None
    if feature.get("caption"):
        body = feature["caption"].strip() + (f"\n\n{swipe}" if swipe else "")
        caption = f"{body}\n\n{' '.join(tags)}"
    else:
        caption = captions.build("feature", ctx.seed, fields, tags, extra=swipe)
    return {"data": {"feature": feature}, "anime_ids": [], "caption": caption}


def build_story_anime_of_day(ctx: Ctx) -> dict[str, Any]:
    pool = [m for m in _season_pool(ctx, ctx.sel["pick_min_popularity"], "POPULARITY_DESC")
            if (m.get("averageScore") or 0) >= ctx.sel["pick_min_score"] and m.get("status") == "RELEASING"]
    (m,) = _pick(pool, 1, ctx.blocked, "Anime of the day")
    return {"data": {"anime": snapshot(m), "season": ctx.season, "year": ctx.year}, "anime_ids": [m["id"]]}


def build_story_your_pick(ctx: Ctx) -> dict[str, Any]:
    pool = [m for m in _season_pool(ctx, ctx.sel["pick_min_popularity"], "POPULARITY_DESC")
            if m.get("status") == "RELEASING"]
    a, b = _pick(pool, 2, ctx.blocked, "Your pick")
    return {"data": {"a": snapshot(a), "b": snapshot(b), "season": ctx.season, "year": ctx.year},
            "anime_ids": [a["id"], b["id"]]}


def build_story_weekend(ctx: Ctx) -> dict[str, Any]:
    season, year = anilist.previous_season(ctx.season, ctx.year)
    pool: list[dict[str, Any]] = []
    for _ in range(3):
        pool += [m for m in anilist.finished_in_season(season, year, ctx.sel["pick_min_popularity"],
                                                       ctx.sel["weekend_max_episodes"])
                 if not m.get("nextAiringEpisode") and (m.get("averageScore") or 0) >= ctx.sel["pick_min_score"]
                 and m.get("episodes")]
        if any(m["id"] not in ctx.blocked for m in pool):
            break
        season, year = anilist.previous_season(season, year)
    (m,) = _pick(pool, 1, ctx.blocked, "Weekend pick")
    return {"data": {"anime": snapshot(m)}, "anime_ids": [m["id"]]}


def build_story_tip(ctx: Ctx) -> dict[str, Any]:
    tip = _rotate(load_yaml("tips.yaml").get("tips") or [], ctx.state["tips"]["last_id"], "tips")
    return {"data": {"tip": tip}, "anime_ids": []}


def build_story_download(ctx: Ctx) -> dict[str, Any]:
    return {"data": {"variant": ctx.seed % 2}, "anime_ids": []}


BUILDERS: dict[str, Callable[[Ctx], dict[str, Any]]] = {
    "airing_week": build_airing_week,
    "feature": build_feature,
    "top5": build_top5,
    "story_anime_of_day": build_story_anime_of_day,
    "story_tip": build_story_tip,
    "story_your_pick": build_story_your_pick,
    "story_download": build_story_download,
    "story_weekend": build_story_weekend,
}


def build_slot(kind: str, day: date, st: dict[str, Any], taken: set[int] | None = None) -> dict[str, Any]:
    if kind not in BUILDERS:
        raise MadError(f"Unknown content type '{kind}'. Valid: {', '.join(BUILDERS)}")
    taken = taken if taken is not None else set()
    log(f"Building {kind} for {day.isoformat()}")
    built = BUILDERS[kind](Ctx(day, st, taken))
    taken.update(built["anime_ids"])
    slot = "post" if kind in POST_KINDS else "story"
    return {"kind": kind, "slot": slot, "date": day.isoformat(), **built}


# ---------------------------------------------------------------- plans

def plan_path(week: str):
    return PLANS_DIR / f"{week}.json"


def build_plan(week: str, st: dict[str, Any]) -> dict[str, Any]:
    monday = week_monday(week)
    taken: set[int] = set()
    slots: dict[str, Any] = {}
    # Posts first so they get first choice of anime, stories fill around them.
    for weekday, slot, kind in sorted(SCHEDULE, key=lambda s: (s[1] != "post", s[0])):
        day = monday + timedelta(days=weekday - 1)
        slots[slot_key(day, slot)] = build_slot(kind, day, st, taken)
    return {"week": week, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "slots": dict(sorted(slots.items()))}


def load_plan(week: str) -> dict[str, Any] | None:
    path = plan_path(week)
    return json.loads(path.read_text("utf-8")) if path.exists() else None


def save_plan(plan: dict[str, Any]) -> None:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    plan_path(plan["week"]).write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", "utf-8")
