"""Caption and hashtag builder — template based, no AI service."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .config import MadError, load_yaml, settings, warn

MAX_CAPTION_CHARS = 2200  # Instagram limit
MAX_HASHTAGS = 30         # Instagram limit


def display_title(media: dict[str, Any]) -> str:
    title = media.get("title") or {}
    return (title.get("english") or title.get("romaji") or "Untitled").strip()


def season_label(season: str, year: int) -> str:
    return f"{season.title()} {year}"


def score10(media: dict[str, Any]) -> str | None:
    score = media.get("averageScore")
    return f"{score / 10:.1f}" if score else None


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return re.sub(r"[^a-z0-9]", "", text.encode("ascii", "ignore").decode().lower())


def _name_core(title: str) -> str:
    """'The Apothecary Diaries Season 3' -> 'The Apothecary Diaries'."""
    core = re.split(r"\s*[:\-–—]\s+|\s*:\s*", title, maxsplit=1)[0]
    core = re.split(
        r"\s+(?:season|part|cour|the movie|\d+(?:st|nd|rd|th)\b|ii+\b|\d+$)",
        core, maxsplit=1, flags=re.IGNORECASE,
    )[0]
    return core.strip() or title


def _is_banned(tag: str, banned: list[str]) -> bool:
    low = tag.lower()
    return any(b.replace(" ", "") in low for b in banned)


def anime_name_tag(media: dict[str, Any]) -> str | None:
    cfg = load_yaml("hashtags.yaml")
    overrides = cfg.get("name_overrides") or {}
    if media["id"] in overrides:
        return overrides[media["id"]]
    candidates = [display_title(media), (media.get("title") or {}).get("romaji") or ""]
    for title in candidates:
        slug = _slug(_name_core(title))
        if 3 <= len(slug) <= cfg["max_name_tag_length"]:
            tag = f"#{slug}"
            if _is_banned(tag, cfg["banned_substrings"]):
                warn(f"Skipping name hashtag {tag}: matches the banned list")
                return None
            return tag
    return None


def hashtags(season: str, year: int, media: dict[str, Any] | None) -> list[str]:
    cfg = load_yaml("hashtags.yaml")
    tags = list(cfg["base"])
    tags.append(cfg["season_format"].format(season=season.lower(), year=year))
    if media:
        name = anime_name_tag(media)
        if name and name not in tags:
            tags.append(name)
    tags.append(cfg["brand"])
    tags = tags[: cfg["max_tags"]]
    if cfg["brand"] not in tags:
        tags[-1] = cfg["brand"]
    for tag in tags:
        if not re.fullmatch(r"#[a-z0-9_]+", tag):
            raise MadError(f"Invalid hashtag {tag!r} (lowercase letters, digits, underscore only)")
        if _is_banned(tag, cfg["banned_substrings"]):
            raise MadError(f"Hashtag {tag} is on the banned list (content/hashtags.yaml)")
    if not 3 <= len(tags) <= 5:
        raise MadError(f"Expected 3–5 hashtags, got {len(tags)}: {tags}")
    return tags


def build(kind: str, variant_seed: int, fields: dict[str, Any], tags: list[str], extra: str | None = None) -> str:
    templates = load_yaml("captions.yaml").get(kind)
    if not templates:
        raise MadError(f"content/captions.yaml has no templates for '{kind}'")
    template = templates[variant_seed % len(templates)]
    fields = {"handle": settings()["brand"]["handle"], **fields}
    try:
        body = template.format(**fields).strip()
    except KeyError as exc:
        raise MadError(f"Caption template for '{kind}' uses unknown placeholder {exc}") from exc
    if extra:
        body = f"{body}\n\n{extra}"
    caption = f"{body}\n\n{' '.join(tags)}"
    if len(caption) > MAX_CAPTION_CHARS:
        raise MadError(f"Caption for '{kind}' is {len(caption)} chars (limit {MAX_CAPTION_CHARS})")
    if caption.count("#") > MAX_HASHTAGS:
        raise MadError(f"Caption for '{kind}' has more than {MAX_HASHTAGS} hashtags")
    return caption
