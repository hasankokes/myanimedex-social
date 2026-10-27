"""AniList GraphQL client: throttled, retried and disk-cached.

AniList is the free replacement for Jikan (MyAnimeList's unofficial API shut down in 2026).
Only factual fields and the cover image URL are requested — never synopsis text.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .config import ROOT, MadError, log, settings, warn

MEDIA_FIELDS = """
  id
  idMal
  title { romaji english }
  format
  status
  episodes
  duration
  season
  seasonYear
  averageScore
  popularity
  favourites
  genres
  isAdult
  countryOfOrigin
  siteUrl
  startDate { year month day }
  studios(isMain: true) { nodes { name } }
  nextAiringEpisode { airingAt episode }
  coverImage { extraLarge large color }
"""

_last_request_at = 0.0


def _cfg() -> dict[str, Any]:
    return settings()["anilist"]


def _cache_path(query: str, variables: dict[str, Any]) -> Path:
    key = hashlib.sha256(json.dumps([query, variables], sort_keys=True).encode()).hexdigest()[:32]
    return ROOT / _cfg()["cache_dir"] / f"{key}.json"


def graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a query and return `data`. Cached on disk for `cache_ttl_hours`."""
    global _last_request_at
    cfg = _cfg()
    variables = variables or {}
    cache_file = _cache_path(query, variables)
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < cfg["cache_ttl_hours"] * 3600:
        return json.loads(cache_file.read_text("utf-8"))

    last_err = "unknown error"
    for attempt in range(1, cfg["max_retries"] + 1):
        wait = cfg["min_interval_seconds"] - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()
        try:
            resp = requests.post(
                cfg["endpoint"],
                json={"query": query, "variables": variables},
                headers={"Accept": "application/json", "User-Agent": "myanimedex-social/1.0"},
                timeout=cfg["request_timeout_seconds"],
            )
        except requests.RequestException as exc:
            last_err = f"network error: {exc}"
            delay = min(60, 2 ** attempt) + random.random()
        else:
            if resp.status_code == 200:
                body = resp.json()
                if body.get("errors"):
                    raise MadError(f"AniList query error: {body['errors'][0].get('message')}")
                data = body["data"]
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(data), "utf-8")
                return data
            last_err = f"HTTP {resp.status_code}"
            if resp.status_code == 429:
                delay = float(resp.headers.get("Retry-After") or 60) + 1
            elif resp.status_code >= 500:
                delay = min(60, 2 ** attempt * 2) + random.random()
            else:
                raise MadError(f"AniList rejected the request ({last_err}): {resp.text[:300]}")
        if attempt < cfg["max_retries"]:
            warn(f"AniList {last_err}; retry {attempt}/{cfg['max_retries'] - 1} in {delay:.0f}s")
            time.sleep(delay)
    raise MadError(f"AniList unavailable after {cfg['max_retries']} attempts ({last_err})")


# ---------------------------------------------------------------- seasons

SEASONS = ["WINTER", "SPRING", "SUMMER", "FALL"]


def season_of(day: datetime) -> tuple[str, int]:
    return SEASONS[(day.month - 1) // 3], day.year


def previous_season(season: str, year: int) -> tuple[str, int]:
    i = SEASONS.index(season)
    return (SEASONS[i - 1], year) if i else ("FALL", year - 1)


# ---------------------------------------------------------------- filters

def _eligible(media: dict[str, Any]) -> bool:
    sel = settings()["selection"]
    if media.get("isAdult"):
        return False
    if sel["countries"] and media.get("countryOfOrigin") not in sel["countries"]:
        return False
    if sel["formats"] and media.get("format") not in sel["formats"]:
        return False
    if set(media.get("genres") or []) & set(sel["exclude_genres"]):
        return False
    return True


def _paged_media(filters: str, args: str, variables: dict[str, Any], pages: int) -> list[dict[str, Any]]:
    query = f"""
    query ($page: Int, {args}) {{
      Page(page: $page, perPage: 50) {{
        pageInfo {{ hasNextPage }}
        media(type: ANIME, isAdult: false, {filters}) {{ {MEDIA_FIELDS} }}
      }}
    }}"""
    out: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        data = graphql(query, {**variables, "page": page})["Page"]
        out.extend(m for m in data["media"] if _eligible(m))
        if not data["pageInfo"]["hasNextPage"]:
            break
    return out


# ---------------------------------------------------------------- queries

def airing_between(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Episodes airing in [start, end); one entry per anime (first episode in range)."""
    query = f"""
    query ($page: Int, $start: Int, $end: Int) {{
      Page(page: $page, perPage: 50) {{
        pageInfo {{ hasNextPage }}
        airingSchedules(airingAt_greater: $start, airingAt_lesser: $end, sort: TIME) {{
          airingAt
          episode
          media {{ {MEDIA_FIELDS} }}
        }}
      }}
    }}"""
    seen: dict[int, dict[str, Any]] = {}
    variables = {"start": int(start.timestamp()) - 1, "end": int(end.timestamp())}
    for page in range(1, 10):
        data = graphql(query, {**variables, "page": page})["Page"]
        for item in data["airingSchedules"]:
            media = item["media"]
            if media and _eligible(media) and media["id"] not in seen:
                seen[media["id"]] = {**media, "airing": {"airingAt": item["airingAt"], "episode": item["episode"]}}
        if not data["pageInfo"]["hasNextPage"]:
            break
    return list(seen.values())


def season_ranked(season: str, year: int, min_popularity: int, sort: str = "SCORE_DESC") -> list[dict[str, Any]]:
    return _paged_media(
        f"season: $season, seasonYear: $year, popularity_greater: $minPop, sort: [{sort}]",
        "$season: MediaSeason, $year: Int, $minPop: Int",
        {"season": season, "year": year, "minPop": min_popularity},
        pages=2,
    )


def finished_in_season(season: str, year: int, min_popularity: int, max_episodes: int) -> list[dict[str, Any]]:
    return _paged_media(
        "season: $season, seasonYear: $year, status: FINISHED, popularity_greater: $minPop, "
        "episodes_lesser: $maxEp, sort: [SCORE_DESC]",
        "$season: MediaSeason, $year: Int, $minPop: Int, $maxEp: Int",
        {"season": season, "year": year, "minPop": min_popularity, "maxEp": max_episodes + 1},
        pages=1,
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def log_count(label: str, items: list[Any]) -> None:
    log(f"AniList: {len(items)} {label}")
