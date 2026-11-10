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

# (ISO weekday 1=Mon, slot, kind). A tuple of kinds alternates by ISO week (week % len).
SCHEDULE: list[tuple[int, str, str | tuple[str, ...]]] = [
    (1, "post", "airing_week"),
    (3, "post", "feature"),
    (6, "post", "top5"),
    (1, "story", "story_anime_of_day"),
    (2, "story", "story_tip"),
    (3, "story", "story_your_pick"),
    (4, "story", "story_download"),
    (5, "story", "story_weekend"),
    (2, "reel", "reel_quiz"),
    (4, "reel", ("reel_recs", "reel_weekend")),
    (7, "reel", ("reel_tierlist", "reel_top5")),
]
POST_KINDS = ["airing_week", "feature", "top5"]
STORY_KINDS = ["story_anime_of_day", "story_tip", "story_your_pick", "story_download", "story_weekend"]
REEL_KINDS = ["reel_quiz", "reel_recs", "reel_tierlist", "reel_app_demo", "reel_weekend", "reel_top5", "reel_teaser"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

KEEP_FIELDS = ["id", "idMal", "title", "format", "status", "episodes", "season", "seasonYear",
               "averageScore", "popularity", "duration", "genres", "siteUrl", "nextAiringEpisode", "airing", "coverImage"]


# ---------------------------------------------------------------- helpers

def week_id(day: date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def week_monday(week: str) -> date:
    return date.fromisocalendar(int(week[:4]), int(week.split("W")[1]), 1)


def slot_key(day: date, slot: str) -> str:
    return f"{day.isoformat()}:{slot}"


def kind_for(day: date, slot: str) -> str | None:
    kind = next((k for wd, s, k in SCHEDULE if wd == day.isoweekday() and s == slot), None)
    if isinstance(kind, tuple):
        kind = kind[day.isocalendar()[1] % len(kind)]
    return kind


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


# ---------------------------------------------------------------- Top 5 "lenses"
# The season's score ranking barely moves week to week, so Saturday's carousel and Sunday's
# reel rotate through different angles. Saturday uses lens i, Sunday lens i+2 of the same
# week, so the two never show the same list. Override per slot with "lens" in the plan file.

TOP5_LENSES = ["trending", "hidden_gems", "alltime_genre", "season_genre", "season_score"]
GENRE_ROTATION = ["Action", "Romance", "Fantasy", "Comedy", "Drama", "Slice of Life", "Sci-Fi", "Mystery",
                  "Sports", "Supernatural", "Psychological", "Adventure"]


def top5_lens(day: date, kind: str) -> str:
    i = day.isocalendar()[1] % len(TOP5_LENSES)
    return TOP5_LENSES[(i + 2) % len(TOP5_LENSES) if kind == "reel_top5" else i]


def _scored(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Scored entries, one per franchise (no Gintama S2 / S2 Part 2 / S3 in the same list)."""
    seen, out = set(), []
    for m in pool:
        if not m.get("averageScore"):
            continue
        title = m.get("title") or {}
        key = captions._slug(captions._name_core(title.get("romaji") or title.get("english") or ""))[:12]
        if key and key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out


def _genre_pool(ctx: Ctx, offset: int, fetch) -> tuple[str, list[dict[str, Any]]]:
    """First genre (starting at this week's rotation slot) with at least 5 results."""
    size = ctx.sel["top5_size"]
    start = ctx.day.isocalendar()[1] + offset
    for k in range(len(GENRE_ROTATION)):
        genre = GENRE_ROTATION[(start + k) % len(GENRE_ROTATION)]
        pool = _scored(fetch(genre))
        if len(pool) >= size:
            return genre, pool
        warn(f"Top 5: only {len(pool)} {genre} anime found, trying the next genre")
    raise MadError("Top 5: no genre has enough anime right now")


def _top5(ctx: Ctx, kind: str, lens: str) -> dict[str, Any]:
    sel, size = ctx.sel, ctx.sel["top5_size"]
    season, year = ctx.season, ctx.year
    label = captions.season_label(season, year)
    extra_tags: list[str] = []
    season_tag = True
    badge = None

    if lens == "season_score":
        for _ in range(2):
            pool = _scored(anilist.season_ranked(season, year, sel["top5_min_popularity"]))
            if len(pool) >= size:
                break
            warn(f"Top 5: only {len(pool)} scored {season} {year} anime yet; using the previous season")
            season, year = anilist.previous_season(season, year)
        else:
            raise MadError("Top 5: not enough scored anime in the current or previous season")
        label = captions.season_label(season, year)
        pool.sort(key=lambda m: (-m["averageScore"], -(m.get("popularity") or 0)))
        chosen = pool[:size]
        meta = {"hook": ["TOP 5", "ANIME THIS", "SEASON"], "cover_title": "THIS SEASON",
                "banner": "RANKED BY FAN SCORE", "header": "TOP 5 THIS SEASON", "chip": label.upper(),
                "footnote": f"Popular titles only ({_fmt_count(sel['top5_min_popularity'])}+ on lists)"}
        headline, cta = None, None

    elif lens == "trending":
        pool = _scored(anilist.find_media(status="RELEASING", popularity_greater=sel["pick_min_popularity"],
                                          sort=["TRENDING_DESC"]))
        chosen = pool[:size]
        badge = "TRENDING"
        meta = {"hook": ["TOP 5", "TRENDING", "THIS WEEK"], "cover_title": "TRENDING NOW",
                "banner": "WHAT FANS ARE WATCHING", "header": "TRENDING THIS WEEK", "chip": "THIS WEEK",
                "footnote": "Ranked by AniList trending activity this week"}
        headline = "Top 5 trending anime this week"
        cta = "Which one are you watching right now? 👇"

    elif lens == "hidden_gems":
        cap = sel.get("hidden_gem_max_popularity", 25000)
        pool = []
        for _ in range(2):
            pool = _scored(anilist.find_media(season=season, seasonYear=year, popularity_greater=2000,
                                              popularity_lesser=cap, averageScore_greater=69,
                                              sort=["SCORE_DESC"], pages=2))
            if len(pool) >= size:
                break
            season, year = anilist.previous_season(season, year)
        label = captions.season_label(season, year)
        chosen = _pick(pool, size, ctx.blocked, "Hidden gems")
        badge = "UNDERRATED"
        meta = {"hook": ["TOP 5", "HIDDEN", "GEMS"], "cover_title": "HIDDEN GEMS",
                "banner": "HIGH SCORES, LOW HYPE", "header": f"HIDDEN GEMS · {label.upper()}", "chip": label.upper(),
                "footnote": f"7.0+ fan score, under {_fmt_count(cap)} on lists"}
        headline = f"Top 5 hidden gem anime of {label}"
        cta = "Did you know them? Save this for your next binge 👀"

    elif lens == "season_genre":
        genre, pool = _genre_pool(ctx, 0, lambda g: anilist.find_media(
            season=season, seasonYear=year, genre=g, popularity_greater=3000, sort=["SCORE_DESC"]))
        chosen = pool[:size]
        badge = genre.upper()
        extra_tags = [captions.genre_tag(genre)]
        meta = {"hook": ["TOP 5", genre.upper(), "THIS SEASON"], "cover_title": f"{genre.upper()} ANIME",
                "banner": "THIS SEASON · BY FAN SCORE", "header": f"TOP 5 {genre.upper()} · {label.upper()}",
                "chip": label.upper(), "footnote": f"{genre} anime airing in {label}"}
        headline = f"Top 5 {genre.lower()} anime this season ({label})"
        cta = f"What's the best {genre.lower()} anime of the season? 👇"

    elif lens == "alltime_genre":
        genre, pool = _genre_pool(ctx, 6, lambda g: anilist.find_media(
            genre=g, status="FINISHED", popularity_greater=50000, sort=["SCORE_DESC"]))
        chosen = pool[:size]
        extra_tags = [captions.genre_tag(genre)]
        season_tag = False
        meta = {"hook": ["ALL-TIME", "TOP 5", genre.upper()], "cover_title": f"ALL-TIME {genre.upper()}",
                "banner": "THE BEST EVER, BY FAN SCORE", "header": f"ALL-TIME TOP 5 {genre.upper()}",
                "chip": "ALL-TIME", "footnote": "Finished series with 50K+ fans on AniList"}
        headline = f"The best {genre.lower()} anime of all time — our Top 5"
        cta = "What's missing from this list? 👇"
    else:
        raise MadError(f"Unknown Top 5 lens '{lens}'. Valid: {', '.join(TOP5_LENSES)}")

    if len(chosen) < size:
        raise MadError(f"Top 5 ({lens}): AniList returned only {len(chosen)} anime")
    last = ctx.state.get("top5_last") or []
    items = []
    for rank, m in enumerate(chosen, 1):
        snap = snapshot(m)
        snap["rank"] = rank
        if lens == "season_score":
            snap["movement"] = "new" if m["id"] not in last else last.index(m["id"]) + 1 - rank
        else:
            snap["badge"] = badge or str(m.get("seasonYear") or "")
        items.append(snap)
    lines = "\n".join(f"#{m['rank']} {captions.display_title(m)} — {captions.score10(m)}/10" for m in items)
    tags = captions.hashtags(season, year, items[0], extra=extra_tags, season_tag=season_tag)
    if lens == "season_score":
        fields = {"season_label": label, "top_title": captions.display_title(items[0]),
                  "top_score": captions.score10(items[0]), "list": lines}
        caption = captions.build(kind, ctx.seed, fields, tags)
    else:
        fields = {"headline": headline, "cta": cta, "list": lines, "top_title": captions.display_title(items[0])}
        caption = captions.build(f"{kind}_lens", ctx.seed, fields, tags)
    log(f"Top 5 lens: {lens} ({meta['header']})")
    return {
        "data": {"items": items, "season": season, "year": year, "lens": {"id": lens, **meta},
                 "min_popularity_label": _fmt_count(sel["top5_min_popularity"]), "seed": ctx.seed},
        "anime_ids": [m["id"] for m in items],
        "caption": caption,
    }


def build_top5(ctx: Ctx) -> dict[str, Any]:
    return _top5(ctx, "top5", top5_lens(ctx.day, "top5"))


def build_feature(ctx: Ctx) -> dict[str, Any]:
    feature = _rotate(load_yaml("features.yaml").get("features") or [], ctx.state["features"]["last_id"], "features")
    fields = {"season_label": captions.season_label(ctx.season, ctx.year),
              "title": feature["title"], "description": feature["description"].strip()}
    tags = captions.hashtags(ctx.season, ctx.year, None, season_tag=False)
    swipe = "👉 Swipe to see it in the app." if feature.get("screenshot") else None
    if feature.get("caption"):
        body = feature["caption"].strip() + (f"\n\n{swipe}" if swipe else "")
        caption = f"{body}\n\n{' '.join(captions.with_format_tags('feature', tags))}"
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


def build_reel_top5(ctx: Ctx) -> dict[str, Any]:
    """Sunday reel: a Top 5 countdown with a different lens than Saturday's carousel."""
    return _top5(ctx, "reel_top5", top5_lens(ctx.day, "reel_top5"))


def build_reel_weekend(ctx: Ctx) -> dict[str, Any]:
    """Thursday reel: episodes airing Friday–Sunday, most popular first."""
    friday = ctx.day + timedelta(days=(4 - ctx.day.weekday()) % 7)
    start = datetime.combine(friday, time(), timezone.utc)
    pool = [m for m in anilist.airing_between(start, start + timedelta(days=3))
            if (m.get("popularity") or 0) >= ctx.sel["airing_min_popularity"]]
    pool.sort(key=lambda m: -(m.get("popularity") or 0))
    anilist.log_count("anime airing this weekend (above popularity floor)", pool)
    chosen = _pick(pool, ctx.sel["airing_slides"], ctx.blocked, "Weekend episodes")
    items = []
    for m in chosen:
        snap = snapshot(m)
        snap["airing_day"] = WEEKDAYS[datetime.fromtimestamp(m["airing"]["airingAt"], timezone.utc).weekday()]
        items.append(snap)
    end = friday + timedelta(days=2)
    date_range = f"{friday:%b %-d} – {end:%-d}" if end.month == friday.month else f"{friday:%b %-d} – {end:%b %-d}"
    fields = {
        "season_label": captions.season_label(ctx.season, ctx.year),
        "date_range": date_range,
        "top_title": captions.display_title(items[0]),
        "list": "\n".join(f"{i}. {captions.display_title(m)} — Ep {m['airing']['episode']} ({m['airing_day']})"
                          for i, m in enumerate(items, 1)),
    }
    tags = captions.hashtags(ctx.season, ctx.year, items[0])
    return {"data": {"items": items, "date_range": date_range, "seed": ctx.seed},
            "anime_ids": [m["id"] for m in items],
            "caption": captions.build("reel_weekend", ctx.seed, fields, tags)}


def build_reel_app_demo(ctx: Ctx) -> dict[str, Any]:
    demo = _rotate(load_yaml("reels.yaml").get("demos") or [], ctx.state["reel_demos"]["last_id"], "reels")
    fields = {"season_label": captions.season_label(ctx.season, ctx.year),
              "hook": demo["hook"].capitalize(), "title": demo["title"], "sub": demo["sub"]}
    tags = captions.hashtags(ctx.season, ctx.year, None)
    return {"data": {"demo": demo, "seed": ctx.seed}, "anime_ids": [],
            "caption": captions.build("reel_app_demo", ctx.seed, fields, tags)}


def build_reel_teaser(ctx: Ctx) -> dict[str, Any]:
    teaser = load_yaml("reels.yaml")["teaser"]
    tags = captions.hashtags(ctx.season, ctx.year, None)
    fields = {"season_label": captions.season_label(ctx.season, ctx.year)}
    return {"data": dict(teaser), "anime_ids": [], "caption": captions.build("reel_teaser", 0, fields, tags)}


# ---------------------------------------------------------------- engagement reels

def _used_recently(st: dict[str, Any], bucket: str, day: date, days: int) -> set[int]:
    cutoff = (day - timedelta(days=days)).isoformat()
    return {int(k) for k, d in st.get(bucket, {}).items() if d >= cutoff}


def build_reel_quiz(ctx: Ctx) -> dict[str, Any]:
    """Tuesday reel: "Guess the anime" — 3 zoomed/pixelated posters, easy -> hard, answers revealed."""
    import random

    pool = [m for m in anilist.find_media(popularity_greater=120000, sort=["POPULARITY_DESC"], pages=3)
            if (m.get("coverImage") or {}).get("extraLarge")]
    pool = _scored(pool)  # one per franchise
    used = _used_recently(ctx.state, "quiz_used", ctx.day, 180) | ctx.taken
    fresh = [m for m in pool if m["id"] not in used] or pool
    rnd = random.Random(ctx.day.toordinal())
    third = max(1, len(fresh) // 3)
    tiers = [fresh[:third], fresh[third:2 * third], fresh[2 * third:]]
    rounds: list[dict[str, Any]] = []
    for level, tier in zip(("EASY", "MEDIUM", "HARD"), tiers):
        options = [m for m in (tier or fresh) if m["id"] not in {r["id"] for r in rounds}]
        m = rnd.choice(options)
        snap = snapshot(m)
        snap["level"] = level
        snap["focus"] = [round(rnd.uniform(0.3, 0.7), 2), round(rnd.uniform(0.25, 0.6), 2)]
        rounds.append(snap)
    tags = captions.hashtags(ctx.season, ctx.year, None, extra=["#animequiz"], season_tag=False)
    fields = {"count": len(rounds)}
    return {"data": {"rounds": rounds, "seed": ctx.seed}, "anime_ids": [m["id"] for m in rounds],
            "caption": captions.build("reel_quiz", ctx.seed, fields, tags)}


RECS_QUERY = """
query ($id: Int) {
  Media(id: $id) {
    recommendations(sort: [RATING_DESC], perPage: 25) {
      nodes { rating mediaRecommendation { %s } }
    }
  }
}"""


def build_reel_recs(ctx: Ctx) -> dict[str, Any]:
    """Thursday reel (alternating): "If you liked X, watch these 3" from AniList community recommendations."""
    anchors = _scored(anilist.find_media(status="FINISHED", popularity_greater=200000, sort=["POPULARITY_DESC"],
                                         pages=2))
    used = _used_recently(ctx.state, "recs_used", ctx.day, 365)
    anchors = [m for m in anchors if m["id"] not in used] or anchors
    anchor = anchors[ctx.day.toordinal() % min(len(anchors), 25)]
    nodes = anilist.graphql(RECS_QUERY % anilist.MEDIA_FIELDS, {"id": anchor["id"]})["Media"]["recommendations"]["nodes"]
    anchor_key = captions._slug(captions._name_core((anchor.get("title") or {}).get("romaji") or ""))[:12]
    recs = []
    for n in nodes:
        m = n.get("mediaRecommendation")
        if not m or not anilist._eligible(m) or not m.get("averageScore") or m["id"] in ctx.blocked:
            continue
        key = captions._slug(captions._name_core((m.get("title") or {}).get("romaji") or ""))[:12]
        if key == anchor_key or any(key == r["_key"] for r in recs):
            continue
        snap = snapshot(m)
        snap["_key"] = key
        snap["shared"] = [g for g in (m.get("genres") or []) if g in (anchor.get("genres") or [])][:2]
        recs.append(snap)
        if len(recs) == 3:
            break
    if len(recs) < 3:
        raise MadError(f"Recs: only {len(recs)} usable recommendations for {captions.display_title(anchor)}")
    for r in recs:
        r.pop("_key", None)
    a = snapshot(anchor)
    tags = captions.hashtags(ctx.season, ctx.year, anchor, season_tag=False)
    fields = {"anchor": captions.display_title(a),
              "list": "\n".join(f"{i}. {captions.display_title(m)} — {captions.score10(m)}/10"
                                for i, m in enumerate(recs, 1))}
    return {"data": {"anchor": a, "recs": recs, "seed": ctx.seed}, "anime_ids": [m["id"] for m in recs],
            "caption": captions.build("reel_recs", ctx.seed, fields, tags)}


TIERS = [("S", 85), ("A", 80), ("B", 75), ("C", 70), ("D", 0)]


def build_reel_tierlist(ctx: Ctx) -> dict[str, Any]:
    """Sunday reel (alternating): the season's most popular shows sorted into S–D tiers by fan score."""
    season, year = ctx.season, ctx.year
    for _ in range(2):
        pool = _scored(anilist.season_ranked(season, year, 10000, "POPULARITY_DESC"))
        if len(pool) >= 10:
            break
        season, year = anilist.previous_season(season, year)
    pool = pool[:12]
    if len(pool) < 8:
        raise MadError("Tier list: not enough scored anime this season")
    items = []
    for m in pool:
        snap = snapshot(m)
        snap["tier"] = next(t for t, floor in TIERS if m["averageScore"] >= floor)
        items.append(snap)
    label = captions.season_label(season, year)
    by_tier = {t: [captions.display_title(m) for m in items if m["tier"] == t] for t, _ in TIERS}
    fields = {"season_label": label,
              "list": "\n".join(f"{t}: {', '.join(names)}" for t, names in by_tier.items() if names)}
    tags = captions.hashtags(season, year, None, extra=["#animetierlist"])
    return {"data": {"items": items, "season": season, "year": year, "seed": ctx.seed},
            "anime_ids": [m["id"] for m in items],
            "caption": captions.build("reel_tierlist", ctx.seed, fields, tags)}



BUILDERS: dict[str, Callable[[Ctx], dict[str, Any]]] = {
    "airing_week": build_airing_week,
    "feature": build_feature,
    "top5": build_top5,
    "story_anime_of_day": build_story_anime_of_day,
    "story_tip": build_story_tip,
    "story_your_pick": build_story_your_pick,
    "story_download": build_story_download,
    "story_weekend": build_story_weekend,
    "reel_app_demo": build_reel_app_demo,
    "reel_weekend": build_reel_weekend,
    "reel_top5": build_reel_top5,
    "reel_teaser": build_reel_teaser,
    "reel_quiz": build_reel_quiz,
    "reel_recs": build_reel_recs,
    "reel_tierlist": build_reel_tierlist,
}


def slot_of(kind: str) -> str:
    return "post" if kind in POST_KINDS else "reel" if kind in REEL_KINDS else "story"


def build_slot(kind: str, day: date, st: dict[str, Any], taken: set[int] | None = None) -> dict[str, Any]:
    if kind not in BUILDERS:
        raise MadError(f"Unknown content type '{kind}'. Valid: {', '.join(BUILDERS)}")
    taken = taken if taken is not None else set()
    log(f"Building {kind} for {day.isoformat()}")
    built = BUILDERS[kind](Ctx(day, st, taken))
    taken.update(built["anime_ids"])
    slot = slot_of(kind)
    return {"kind": kind, "slot": slot, "date": day.isoformat(), **built}


# ---------------------------------------------------------------- plans

def plan_path(week: str):
    return PLANS_DIR / f"{week}.json"


def build_plan(week: str, st: dict[str, Any]) -> dict[str, Any]:
    monday = week_monday(week)
    taken: set[int] = set()
    slots: dict[str, Any] = {}
    errors: dict[str, str] = {}
    # Posts first so they get first choice of anime, stories fill around them.
    order = {"post": 0, "reel": 1, "story": 2}
    for weekday, slot, _ in sorted(SCHEDULE, key=lambda s: (order[s[1]], s[0])):
        day = monday + timedelta(days=weekday - 1)
        kind = kind_for(day, slot)
        try:
            slots[slot_key(day, slot)] = build_slot(kind, day, st, taken)
        except MadError as exc:
            # One broken slot must not block the whole week: leave it out of the plan, the publish
            # run rebuilds just that slot (add_slot) and the preview issue flags it.
            warn(f"Could not build {kind} for {day}: {exc}")
            errors[slot_key(day, slot)] = f"{kind}: {exc}"
    plan = {"week": week, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "slots": dict(sorted(slots.items()))}
    if errors:
        plan["errors"] = errors
    return plan


def add_slot(plan: dict[str, Any], day: date, slot: str, st: dict[str, Any]) -> dict[str, Any]:
    """Build one missing slot into an existing plan without touching the other picks."""
    kind = kind_for(day, slot)
    if not kind:
        raise MadError(f"No {slot} is scheduled on {day:%A}")
    taken = {aid for s in plan["slots"].values() for aid in s.get("anime_ids", [])}
    plan["slots"][slot_key(day, slot)] = build_slot(kind, day, st, taken)
    plan["slots"] = dict(sorted(plan["slots"].items()))
    plan.get("errors", {}).pop(slot_key(day, slot), None)
    return plan


def load_plan(week: str) -> dict[str, Any] | None:
    path = plan_path(week)
    return json.loads(path.read_text("utf-8")) if path.exists() else None


def save_plan(plan: dict[str, Any]) -> None:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    plan_path(plan["week"]).write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", "utf-8")
