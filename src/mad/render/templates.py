"""Post (1080x1350) and story (1080x1920) templates.

Each `render_<kind>(data, out_dir)` returns the list of JPEG paths it wrote, in slide order.
Stories keep the top and bottom `story_safe_margin` px (250) free of content.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..captions import display_title, score10, season_label
from ..config import settings
from .base import (ACCENTS, CREAM, INK, MAGENTA, TEAL, WHITE, YELLOW, Canvas, font, mix,
                   resolve)

POST = tuple(settings()["render"]["post_size"])
STORY = tuple(settings()["render"]["story_size"])
SAFE = settings()["render"]["story_safe_margin"]
HANDLE = settings()["brand"]["handle"]


# ---------------------------------------------------------------- shared bits

def fmt_count(n: int | None) -> str:
    if not n:
        return "-"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1000:.0f}K" if n >= 10_000 else f"{n / 1000:.1f}K" if n >= 1000 else str(n)


def episodes_label(m: dict[str, Any]) -> str:
    return str(m["episodes"]) if m.get("episodes") else "TBA"


def footer(c: Canvas, fg=CREAM, data_credit=True, y=None):
    y = y if y is not None else c.h - 62
    c.text((60, y), HANDLE, "body_xbold", 32, fill=fg, anchor="lm")
    c.text((c.w - 60, y), settings()["brand"]["website"], "body_bold", 28, fill=fg, anchor="rm")
    if data_credit:
        c.text((c.w / 2, y), "Data: AniList", "body_regular", 24, fill=fg, anchor="mm")


def genre_chips(c: Canvas, y, genres, fill, fg=INK, x=70, center=False, size=32, limit=3):
    genres = [g.upper() for g in (genres or [])[:limit]]
    if not genres:
        return
    gap = 18
    widths = [c.width_of(g, "body_xbold", size) + 44 for g in genres]
    if center:
        x = (c.w - (sum(widths) + gap * (len(widths) - 1))) / 2
    for g, w in zip(genres, widths):
        c.chip((x, y), g, size=size, fill=fill, fg=fg, shadow=6)
        x += w + gap


def stat_columns(c: Canvas, box, stats, fill=CREAM, fg=INK, label_fg=None, shadow=14):
    """Inked panel split into columns of (LABEL, value)."""
    x0, y0, x1, y1 = box
    c.panel(box, fill=fill, shadow=shadow)
    col = (x1 - x0) / len(stats)
    for i, (label, value) in enumerate(stats):
        cx = x0 + col * i + col / 2
        if i:
            c.d.line((x0 + col * i, y0 + 26, x0 + col * i, y1 - 26), fill=INK, width=5)
        c.text((cx, y0 + 34), label, "body_xbold", 28, fill=label_fg or mix(fg, fill, 0.35), anchor="mt")
        size = 96
        while size > 34 and c.width_of(value, "display", size) > col - 36:
            size -= 4
        c.text((cx, y1 - 30), value, "display", size, fill=fg, anchor="ms")


def studio_line(c: Canvas, m, y, fg=CREAM):
    meta = "  ·  ".join(x for x in [m.get("studio"), (m.get("format") or "").replace("_", " ")] if x)
    if meta:
        c.text((c.w / 2, y), meta.upper(), "body_xbold", 34, fill=fg, anchor="mm")


def score_burst(c: Canvas, center, m, r=170, fill=YELLOW, seed=5):
    c.burst(center, r, r * 0.74, points=16, fill=fill, shadow=(12, 12), seed=seed)
    score = score10(m)
    cx, cy = center
    if score:
        c.text((cx, cy + 10), score, "display", int(r * 0.78), fill=INK, anchor="ms")
        c.text((cx, cy + 28), "FAN SCORE /10", "body_xbold", int(r * 0.17), fill=INK, anchor="mt")
    else:
        c.text((cx, cy), "NEW", "comic", int(r * 0.6), fill=INK, anchor="mm")


def banner(c: Canvas, center, text, size, fill=INK, fg=YELLOW, angle=-3, pad=(46, 26), name="comic"):
    tw = c.width_of(text, name, size)
    asc, desc = font(name, size).getmetrics()
    w, h = int(tw + pad[0] * 2 + 20), int(asc + desc * 0.3 + pad[1] * 2 + 20)

    def draw(sub: Canvas):
        sub.panel((0, 0, w - 20, h - 20), fill=fill, border=8, shadow=14,
                  shadow_color=INK if fill != INK else MAGENTA)
        sub.text(((w - 20) / 2, (h - 20) / 2 + 4), text, name, size, fill=fg, anchor="mm")

    c.rotated((w, h), draw, center, angle)


def save_all(canvases: list[Canvas], out_dir: Path) -> list[Path]:
    return [cv.save(out_dir / f"{i:02d}.jpg") for i, cv in enumerate(canvases, 1)]


# ---------------------------------------------------------------- carousels: shared closing slide

def closing_slide(headline: str, sub: str) -> Canvas:
    c = Canvas(POST, INK)
    c.speed_lines((540, 560), mix(INK, TEAL, 0.16), count=80, inner=320)
    c.halftone(mix(INK, MAGENTA, 0.45), origin="br", max_r=11)
    c.logo((540, 150), 380, anchor="ma")
    c.text_block((70, 600, 1010, 860), headline, "comic", 150, 80, fill=YELLOW, align="center",
                 valign="middle", stroke=8, stroke_fill=INK, shadow=(10, 10), max_lines=2)
    c.text_block((120, 880, 960, 990), sub, "body_bold", 44, 30, fill=CREAM, align="center", max_lines=2)
    c.chip((540, 1040), "FREE ON iOS & ANDROID", size=40, fill=TEAL, anchor="ma")
    c.chip((540, 1140), "LINK IN BIO", size=40, fill=MAGENTA, fg=WHITE, anchor="ma")
    footer(c, data_credit=False)
    return c


# ---------------------------------------------------------------- Monday: airing this week

def render_airing_week(data: dict[str, Any], out_dir: Path) -> list[Path]:
    items = data["items"]
    slides = [_airing_cover(data, len(items))]
    slides += [_airing_slide(m, i) for i, m in enumerate(items)]
    slides.append(closing_slide("NEVER MISS AN EPISODE",
                                "Airing calendar, reminders and your watchlist in MyAnimeDex."))
    return save_all(slides, out_dir)


def _airing_cover(data, count) -> Canvas:
    c = Canvas(POST, YELLOW)
    c.speed_lines((540, 620), mix(YELLOW, WHITE, 0.45), count=72, inner=300)
    c.halftone(mix(YELLOW, INK, 0.22), origin="br", max_r=12)
    c.logo((60, 50), 150)
    c.chip((1020, 92), season_label(data["season"], data["year"]).upper(), size=40, fill=MAGENTA,
           fg=WHITE, anchor="ra")
    c.text((540, 470), "AIRING", "comic", 290, fill=WHITE, anchor="ms", stroke=12, shadow=(18, 18))
    c.text((540, 720), "THIS WEEK", "comic", 230, fill=TEAL, anchor="ms", stroke=12, shadow=(18, 18))
    banner(c, (540, 860), data["date_range"].upper(), 92, fill=INK, fg=CREAM, angle=-3, name="display")
    c.panel((90, 1000, 990, 1160), fill=CREAM, shadow=14)
    c.text((540, 1080), f"{count} NEW EPISODES YOU CAN'T MISS", "condensed", 62, fill=INK, anchor="mm")
    c.text((850, 1240), "SWIPE", "comic", 64, fill=INK, anchor="rm")
    c.arrow((870, 1240), 130)
    footer(c, fg=INK, data_credit=False)
    return c


def _airing_slide(m, i) -> Canvas:
    accent = ACCENTS[i % 3]
    c = Canvas(POST, INK)
    c.halftone(mix(INK, accent, 0.4), origin="tr", max_r=13, spacing=28)
    c.burst((175, 190), 135, 98, points=14, fill=accent, shadow=(10, 10), seed=i + 1)
    c.text((175, 192), f"{i + 1:02d}", "display", 112, fill=INK, anchor="mm")
    ep = m["airing"]["episode"]
    c.chip((1020, 110), f"EP {ep}  ·  {m['airing_day'].upper()}", name="display", size=56,
           fill=CREAM, anchor="ra", pad=(28, 14))
    c.text((1020, 250), "NEW EPISODE THIS WEEK", "body_xbold", 32, fill=accent, anchor="ra")
    c.text_block((70, 360, 1010, 790), display_title(m).upper(), "display", 150, 62, fill=WHITE,
                 valign="middle", shadow=(9, 9), max_lines=4)
    stat_columns(c, (70, 830, 1010, 1060),
                 [("FAN SCORE", score10(m) or "NEW"), ("ON LISTS", fmt_count(m.get("popularity"))),
                  ("EPISODES", episodes_label(m))])
    genre_chips(c, 1105, m.get("genres"), fill=accent)
    meta = "  ·  ".join(x for x in [m.get("studio"), (m.get("format") or "").replace("_", " ")] if x)
    if meta:
        c.text((70, 1215), meta.upper(), "body_bold", 32, fill=mix(CREAM, INK, 0.25), anchor="la")
    footer(c)
    return c


# ---------------------------------------------------------------- Saturday: top 5 this season

def render_top5(data: dict[str, Any], out_dir: Path) -> list[Path]:
    items = data["items"]
    slides = [_top5_cover(data)]
    slides += [_top5_slide(m, data) for m in sorted(items, key=lambda m: -m["rank"])]  # countdown 5 -> 1
    slides.append(closing_slide("WHAT'S YOUR #1?", "Comment your pick and track the season in MyAnimeDex."))
    return save_all(slides, out_dir)


def _top5_cover(data) -> Canvas:
    c = Canvas(POST, MAGENTA)
    c.speed_lines((560, 520), mix(MAGENTA, WHITE, 0.22), count=76, inner=280)
    c.halftone(mix(MAGENTA, INK, 0.3), origin="bl", max_r=12)
    c.logo((60, 50), 150)
    c.chip((1020, 92), season_label(data["season"], data["year"]).upper(), size=40, fill=YELLOW, anchor="ra")
    c.text((90, 690), "TOP", "comic", 330, fill=YELLOW, anchor="ls", stroke=14, shadow=(20, 20))
    c.burst((800, 520), 250, 190, points=18, fill=YELLOW, shadow=(16, 16), seed=11)
    c.text((800, 540), "5", "display", 360, fill=INK, anchor="mm")
    c.text((540, 900), "THIS SEASON", "comic", 180, fill=WHITE, anchor="ms", stroke=12, shadow=(16, 16))
    banner(c, (540, 1035), "RANKED BY FAN SCORE", 64, fill=INK, fg=YELLOW, angle=-2, name="condensed")
    c.text((850, 1210), "SWIPE", "comic", 64, fill=INK, anchor="rm")
    c.arrow((870, 1210), 130)
    c.text((60, 1210), f"Popular titles only ({data['min_popularity_label']}+ on lists)", "body_bold", 28,
           fill=INK, anchor="lm")
    footer(c, fg=INK)
    return c


def _movement(m) -> tuple[str, tuple]:
    mv = m.get("movement")
    if mv == "new":
        return "NEW ENTRY", MAGENTA
    if not mv:
        return "SAME SPOT", TEAL
    return (f"UP {mv}", TEAL) if mv > 0 else (f"DOWN {-mv}", CREAM)


def _top5_slide(m, data) -> Canvas:
    rank = m["rank"]
    accent = [YELLOW, MAGENTA, TEAL, YELLOW, MAGENTA][rank - 1]
    c = Canvas(POST, CREAM)
    c.halftone(mix(CREAM, accent, 0.55), origin="bl", max_r=13, spacing=28)
    c.text((60, 40), "TOP 5 THIS SEASON", "comic", 56, fill=INK, anchor="la")
    c.text((70, 450), f"#{rank}", "display", 360, fill=accent, anchor="ls", stroke=10, shadow=(16, 16))
    score_burst(c, (800, 320), m, r=185, fill=YELLOW if accent != YELLOW else TEAL, seed=rank)
    label, color = _movement(m)
    c.chip((76, 500), label, size=36, fill=color, fg=WHITE if color == MAGENTA else INK)
    c.text_block((70, 600, 1010, 960), display_title(m).upper(), "display", 140, 60, fill=INK,
                 valign="middle", max_lines=4)
    stat_columns(c, (70, 990, 1010, 1170),
                 [("ON LISTS", fmt_count(m.get("popularity"))), ("EPISODES", episodes_label(m)),
                  ("STUDIO", (m.get("studio") or "-").upper())],
                 fill=INK, fg=CREAM, label_fg=accent, shadow=0)
    genre_chips(c, 1200, m.get("genres"), fill=accent, fg=WHITE if accent == MAGENTA else INK)
    footer(c, fg=INK)
    return c


# ---------------------------------------------------------------- Wednesday: app feature

def render_feature(data: dict[str, Any], out_dir: Path) -> list[Path]:
    """Slide 1: typographic feature card. Slide 2 (only with a screenshot): the app screen."""
    f = data["feature"]
    shot = resolve(f.get("screenshot"))
    slides = [_feature_card(f, carousel=bool(shot))]
    if shot:
        slides.append(_feature_screen(f, shot))
    return save_all(slides, out_dir)


def _feature_card(f, carousel: bool) -> Canvas:
    c = Canvas(POST, TEAL)
    c.halftone(mix(TEAL, INK, 0.25), origin="tl", max_r=12)
    c.speed_lines((900, 1100), mix(TEAL, WHITE, 0.25), count=50, inner=200, seed=4)
    c.logo((60, 50), 130)
    banner(c, (840, 110), (f.get("kicker") or "APP FEATURE").upper(), 54, fill=MAGENTA, fg=WHITE,
           angle=3, name="comic")
    c.text_block((60, 240, 1020, 640), f["title"].upper(), "comic", 170, 70, fill=WHITE,
                 valign="middle", stroke=10, shadow=(12, 12), max_lines=3)
    c.bubble((60, 690, 1020, 1010), tail_to=(330, 1110))
    c.text_block((110, 725, 970, 980), f["description"], "body_bold", 56, 30, fill=INK,
                 valign="middle", max_lines=5)
    if carousel:
        c.text((860, 1190), "SEE IT", "comic", 64, fill=INK, anchor="rm")
        c.arrow((880, 1190), 130)
    else:
        c.burst((860, 1130), 150, 110, points=14, fill=YELLOW, shadow=(10, 10), seed=8)
        c.text((860, 1130), "FREE!", "comic", 84, fill=INK, anchor="mm")
    c.chip((60, 1170), "MYANIMEDEX · LINK IN BIO", size=36, fill=YELLOW)
    footer(c, fg=INK, data_credit=False)
    return c


def _feature_screen(f, shot: Path) -> Canvas:
    c = Canvas(POST, INK)
    c.speed_lines((540, 700), mix(INK, TEAL, 0.18), count=80, inner=330)
    c.halftone(mix(INK, MAGENTA, 0.45), origin="br", max_r=12)
    banner(c, (540, 95), "IN THE APP", 76, fill=YELLOW, fg=INK, angle=-2)
    c.image(shot, (300, 190, 780, 1240), radius=40, masks=f.get("mask"))
    c.burst((945, 330), 100, 74, points=14, fill=MAGENTA, shadow=(10, 10), seed=6)
    c.text((945, 332), "FREE", "comic", 56, fill=WHITE, anchor="mm", stroke=4)
    footer(c, data_credit=False)
    return c


# ---------------------------------------------------------------- stories

def story_canvas(bg) -> Canvas:
    return Canvas(STORY, bg)


def story_credit(c: Canvas, fg=INK, data_credit=True):
    text = f"Data: AniList  ·  {HANDLE}" if data_credit else HANDLE
    c.text((c.w / 2, c.h - SAFE - 20), text, "body_bold", 26, fill=fg, anchor="ms")


def render_story_anime_of_day(data, out_dir):
    m = data["anime"]
    c = story_canvas(MAGENTA)
    c.speed_lines((540, 900), mix(MAGENTA, WHITE, 0.2), count=80, inner=360)
    c.halftone(mix(MAGENTA, INK, 0.3), origin="br", max_r=13)
    banner(c, (540, SAFE + 110), "ANIME OF THE DAY", 118, fill=INK, fg=YELLOW, angle=-3)
    c.chip((540, SAFE + 250), f"{season_label(data['season'], data['year']).upper()}  ·  AIRING NOW",
           size=36, fill=CREAM, anchor="ma")
    c.text_block((80, 600, 1000, 1000), display_title(m).upper(), "display", 160, 64, fill=WHITE,
                 valign="middle", stroke=6, shadow=(12, 12), max_lines=4)
    studio_line(c, m, 1030, fg=WHITE)
    score_burst(c, (290, 1180), m, r=165)
    stat_columns(c, (500, 1080, 1000, 1280),
                 [("ON LISTS", fmt_count(m.get("popularity"))), ("EPISODES", episodes_label(m))],
                 label_fg=MAGENTA)
    genre_chips(c, 1340, m.get("genres"), fill=YELLOW, center=True, size=34)
    c.panel((80, 1450, 1000, 1610), fill=INK, shadow=0, border=8)
    c.text((540, 1505), "ADD IT TO YOUR WATCHLIST", "condensed", 60, fill=YELLOW, anchor="mm")
    c.text((540, 1570), "MyAnimeDex  ·  link in bio", "body_bold", 36, fill=CREAM, anchor="mm")
    story_credit(c, fg=WHITE)
    return save_all([c], out_dir)


def render_story_tip(data, out_dir):
    tip = data["tip"]
    shot = resolve(tip.get("screenshot"))
    c = story_canvas(YELLOW)
    c.speed_lines((540, 1000), mix(YELLOW, WHITE, 0.45), count=70, inner=380)
    c.halftone(mix(YELLOW, INK, 0.2), origin="tr", max_r=13)
    c.burst((240, SAFE + 150), 175, 128, points=14, fill=MAGENTA, shadow=(12, 12), seed=2)
    c.text((240, SAFE + 152), "APP TIP", "comic", 78, fill=WHITE, anchor="mm", stroke=5)
    c.logo((1000, SAFE + 40), 190, anchor="ra")
    if shot:
        c.text_block((80, 520, 1000, 700), tip["title"].upper(), "comic", 130, 70, fill=INK, max_lines=2)
        c.bubble((80, 730, 1000, 1020), tail_to=(330, 1090), shadow=12)
        c.text_block((130, 760, 950, 990), tip["text"], "body_bold", 54, 30, fill=INK, valign="middle",
                     max_lines=4)
        c.rotated((520, 640), lambda s: s.image(shot, (24, 24, 480, 600), radius=36, masks=tip.get("mask")),
                  (540, 1360), 3)
    else:
        c.text_block((80, 560, 1000, 860), tip["title"].upper(), "comic", 170, 80, fill=INK,
                     valign="middle", max_lines=2)
        c.bubble((80, 900, 1000, 1280), tail_to=(330, 1370), shadow=14)
        c.text_block((130, 940, 950, 1240), tip["text"], "body_bold", 62, 32, fill=INK, valign="middle",
                     max_lines=5)
        c.chip((540, 1430), "TRY IT IN MYANIMEDEX", size=46, fill=INK, fg=YELLOW, anchor="ma")
        c.chip((540, 1530), "LINK IN BIO", size=40, fill=TEAL, anchor="ma")
    story_credit(c, data_credit=False)
    return save_all([c], out_dir)


def render_story_your_pick(data, out_dir):
    a, b = data["a"], data["b"]
    c = story_canvas(TEAL)
    c.halftone(mix(TEAL, INK, 0.2), origin="tl", max_r=12, box=(0, 0, 1080, 1000))
    c.d.polygon([(0, 1030), (1080, 900), (1080, 1920), (0, 1920)], fill=MAGENTA)
    c.halftone(mix(MAGENTA, INK, 0.25), origin="br", max_r=12, box=(0, 1000, 1080, 1920))
    c.d.line([(0, 1030), (1080, 900)], fill=INK, width=16)
    banner(c, (540, SAFE + 95), "WHICH ONE ARE YOU", 92, fill=INK, fg=YELLOW, angle=-2)
    banner(c, (540, SAFE + 225), "WATCHING THIS WEEK?", 92, fill=INK, fg=YELLOW, angle=-2)
    for letter, m, top, fill in (("A", a, 510, TEAL), ("B", b, 1110, MAGENTA)):
        c.burst((170, top + 160), 125, 92, points=12, fill=CREAM, shadow=(10, 10), seed=ord(letter))
        c.text((170, top + 165), letter, "comic", 150, fill=INK, anchor="mm")
        c.text_block((330, top, 1010, top + 250), display_title(m).upper(), "display", 104, 48, fill=WHITE,
                     valign="middle", stroke=5, shadow=(8, 8), max_lines=3)
        meta = "  ·  ".join(x for x in [f"{score10(m)}/10" if score10(m) else None,
                                         f"{fmt_count(m.get('popularity'))} ON LISTS",
                                         f"EP {m['nextAiringEpisode']['episode']} NEXT" if m.get("nextAiringEpisode") else None] if x)
        c.text((330, top + 285), meta, "body_xbold", 34, fill=INK, anchor="la")
    c.burst((540, 968), 110, 80, points=16, fill=YELLOW, shadow=(10, 10), seed=9)
    c.text((540, 972), "VS", "comic", 100, fill=INK, anchor="mm")
    c.chip((540, 1480), "REPLY WITH  A  OR  B", name="comic", size=78, fill=YELLOW, anchor="ma",
           pad=(40, 16))
    c.text((540, 1625), "Data: AniList  ·  " + HANDLE, "body_bold", 26, fill=WHITE, anchor="ms")
    return save_all([c], out_dir)


DOWNLOAD_TILES = [("AIRING", "CALENDAR", TEAL), ("WATCHLIST", "& RATINGS", YELLOW),
                  ("LISTS WITH", "FRIENDS", MAGENTA), ("15", "LANGUAGES", CREAM)]
DOWNLOAD_HEADLINES = [("YOUR ANIME,", "ALL IN ONE PLACE"), ("TRACK ANIME", "LIKE A PRO")]


def render_story_download(data, out_dir):
    c = story_canvas(INK)
    c.speed_lines((540, 760), mix(INK, MAGENTA, 0.3), count=80, inner=300)
    c.halftone(mix(INK, TEAL, 0.35), origin="br", max_r=12)
    c.logo((540, SAFE + 10), 330, anchor="ma")
    l1, l2 = DOWNLOAD_HEADLINES[data.get("variant", 0) % len(DOWNLOAD_HEADLINES)]
    c.text((540, 760), l1, "comic", 130, fill=WHITE, anchor="ms", stroke=7, shadow=(10, 10),
           shadow_fill=MAGENTA)
    c.text((540, 890), l2, "comic", 130, fill=YELLOW, anchor="ms", stroke=7, shadow=(10, 10),
           shadow_fill=MAGENTA)
    tw, th, gap = 440, 190, 40
    for i, (t1, t2, color) in enumerate(DOWNLOAD_TILES):
        x = 80 + (i % 2) * (tw + gap)
        y = 960 + (i // 2) * (th + gap)
        c.panel((x, y, x + tw, y + th), fill=color, shadow=12, shadow_color=WHITE)
        fg = WHITE if color == MAGENTA else INK
        c.text((x + tw / 2, y + th / 2 - 8), t1, "display", 60, fill=fg, anchor="ms")
        c.text((x + tw / 2, y + th / 2 + 8), t2, "condensed", 46, fill=fg, anchor="mt")
    c.chip((540, 1430), "FREE ON iOS & ANDROID", size=48, fill=YELLOW, anchor="ma", pad=(34, 14))
    c.chip((540, 1540), "LINK IN BIO", size=44, fill=MAGENTA, fg=WHITE, anchor="ma", pad=(34, 12))
    return save_all([c], out_dir)


def render_story_weekend(data, out_dir):
    m = data["anime"]
    c = story_canvas(TEAL)
    c.speed_lines((540, 900), mix(TEAL, WHITE, 0.25), count=80, inner=360)
    c.halftone(mix(TEAL, INK, 0.25), origin="bl", max_r=13)
    banner(c, (540, SAFE + 110), "WEEKEND BINGE PICK", 110, fill=YELLOW, fg=INK, angle=-3)
    season = f"{(m.get('season') or '').title()} {m.get('seasonYear') or ''}".strip()
    c.chip((540, SAFE + 250), f"FULL SEASON OUT  ·  {season.upper()}", size=36, fill=CREAM, anchor="ma")
    c.text_block((80, 600, 1000, 1000), display_title(m).upper(), "display", 160, 64, fill=WHITE,
                 valign="middle", stroke=6, shadow=(12, 12), max_lines=4)
    studio_line(c, m, 1030, fg=INK)
    score_burst(c, (290, 1180), m, r=165, fill=MAGENTA)
    eps = m.get("episodes") or 0
    minutes = eps * (m.get("duration") or 24)
    stat_columns(c, (500, 1080, 1000, 1280),
                 [("EPISODES", str(eps)), ("BINGE TIME", f"{minutes // 60}H {minutes % 60:02d}M")],
                 label_fg=MAGENTA)
    genre_chips(c, 1340, m.get("genres"), fill=YELLOW, center=True, size=34)
    c.panel((80, 1450, 1000, 1610), fill=INK, shadow=0, border=8)
    c.text((540, 1505), "SAVE IT FOR SATURDAY", "comic", 70, fill=YELLOW, anchor="mm")
    c.text((540, 1570), "Add it to your MyAnimeDex list  ·  link in bio", "body_bold", 34, fill=CREAM,
           anchor="mm")
    story_credit(c)
    return save_all([c], out_dir)


RENDERERS = {
    "airing_week": render_airing_week,
    "top5": render_top5,
    "feature": render_feature,
    "story_anime_of_day": render_story_anime_of_day,
    "story_tip": render_story_tip,
    "story_your_pick": render_story_your_pick,
    "story_download": render_story_download,
    "story_weekend": render_story_weekend,
}


def render(slot: dict[str, Any], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink()
    return RENDERERS[slot["kind"]](slot["data"], out_dir)
