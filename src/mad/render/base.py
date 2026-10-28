"""Comic-style drawing primitives on top of Pillow.

Everything is typographic: halftone dots, speed lines, starbursts, inked panels and
stroked lettering. No posters or character art are ever drawn.
"""
from __future__ import annotations

import math
import re
import random
import unicodedata
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

from ..config import ASSETS_DIR, FONTS_DIR, ROOT, settings

# Brand palette (sampled from the logo + app primary)
YELLOW = (250, 204, 21)      # #FACC15
TEAL = (94, 212, 217)        # #5ED4D9
MAGENTA = (240, 72, 122)     # #F0487A
INK = (19, 17, 30)           # #13111E
CREAM = (253, 243, 216)      # #FDF3D8
WHITE = (255, 255, 255)
ACCENTS = [TEAL, MAGENTA, YELLOW]

FONTS = {
    "comic": "Bangers-Regular.ttf",
    "display": "Anton-Regular.ttf",
    "body": "Barlow-SemiBold.ttf",
    "body_bold": "Barlow-Bold.ttf",
    "body_xbold": "Barlow-ExtraBold.ttf",
    "body_regular": "Barlow-Regular.ttf",
    "condensed": "BarlowCondensed-ExtraBold.ttf",
}

_REPLACE = {
    "–": "-", "—": "-", "‐": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "→": "->",
    "×": "x", "☆": "*", "★": "*", "♪": "", "♥": "", "…": "...", "・": " ", "～": "~", "〜": "~",
    "　": " ",
}


@lru_cache(maxsize=None)
def _cmap(name: str) -> frozenset[int]:
    return frozenset(TTFont(FONTS_DIR / FONTS[name]).getBestCmap())


@lru_cache(maxsize=None)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / FONTS[name]), size)


def clean(text: str, name: str) -> str:
    """Replace characters the font cannot draw (no tofu boxes in titles)."""
    cmap = _cmap(name)
    out = []
    for ch in text:
        if ord(ch) in cmap or ch in "\n ":
            out.append(ch)
            continue
        rep = _REPLACE.get(ch)
        if rep is None:
            rep = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
        out.append("".join(c for c in rep if ord(c) in cmap))
    return re.sub(r" {2,}", " ", "".join(out)).strip()


def mix(a, b, t: float):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Canvas:
    def __init__(self, size: tuple[int, int], bg=INK):
        self.w, self.h = size
        self.im = Image.new("RGB", size, bg)
        self.d = ImageDraw.Draw(self.im)

    # ------------------------------------------------------------ textures

    def halftone(self, color, box=None, spacing=26, max_r=10.0, origin="br", min_r=0.0):
        """Dot pattern fading from `origin` corner ('tl','tr','bl','br','c')."""
        x0, y0, x1, y1 = box or (0, 0, self.w, self.h)
        ox = {"l": x0, "r": x1, "c": (x0 + x1) / 2}[origin[-1] if origin != "c" else "c"]
        oy = {"t": y0, "b": y1, "c": (y0 + y1) / 2}[origin[0] if origin != "c" else "c"]
        diag = math.hypot(x1 - x0, y1 - y0)
        for row, y in enumerate(range(int(y0), int(y1) + spacing, spacing)):
            shift = spacing / 2 if row % 2 else 0
            for x in range(int(x0 + shift), int(x1) + spacing, spacing):
                t = 1 - min(1.0, math.hypot(x - ox, y - oy) / (diag * 0.75))
                r = min_r + (max_r - min_r) * t
                if r > 0.6:
                    self.d.ellipse((x - r, y - r, x + r, y + r), fill=color)

    def speed_lines(self, center, color, count=64, inner=260, outer=2400, width_deg=1.6, seed=7):
        rnd = random.Random(seed)
        cx, cy = center
        for i in range(count):
            a = (i / count) * math.tau + rnd.uniform(-0.03, 0.03)
            w = math.radians(width_deg * rnd.uniform(0.5, 1.4))
            r0 = inner * rnd.uniform(0.85, 1.25)
            pts = [
                (cx + math.cos(a) * r0, cy + math.sin(a) * r0),
                (cx + math.cos(a - w) * outer, cy + math.sin(a - w) * outer),
                (cx + math.cos(a + w) * outer, cy + math.sin(a + w) * outer),
            ]
            self.d.polygon(pts, fill=color)

    # ------------------------------------------------------------ shapes

    def burst(self, center, r_out, r_in, points=14, fill=MAGENTA, outline=INK, width=8,
              rotation=0.0, shadow=None, seed=3):
        rnd = random.Random(seed)
        cx, cy = center
        pts = []
        for i in range(points * 2):
            a = math.radians(rotation) + i * math.pi / points
            r = (r_out * rnd.uniform(0.9, 1.08)) if i % 2 == 0 else r_in
            pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
        if shadow:
            dx, dy = shadow
            self.d.polygon([(x + dx, y + dy) for x, y in pts], fill=INK)
        self.d.polygon(pts, fill=fill, outline=outline, width=width)

    def panel(self, box, fill=CREAM, border=8, shadow=14, radius=0, outline=INK, shadow_color=INK):
        x0, y0, x1, y1 = box
        if shadow:
            self.d.rounded_rectangle((x0 + shadow, y0 + shadow, x1 + shadow, y1 + shadow), radius, fill=shadow_color)
        self.d.rounded_rectangle(box, radius, fill=fill, outline=outline, width=border)

    def bubble(self, box, tail_to, fill=WHITE, border=8, shadow=12):
        """Comic speech bubble with a tail pointing at `tail_to`."""
        x0, y0, x1, y1 = box
        cx = (x0 + x1) / 2
        base_y = y1 - border
        tail = [(cx - 60, base_y), (cx + 40, base_y), tail_to]
        if shadow:
            self.d.rounded_rectangle((x0 + shadow, y0 + shadow, x1 + shadow, y1 + shadow), 60, fill=INK)
            self.d.polygon([(x + shadow, y + shadow) for x, y in tail], fill=INK)
        self.d.polygon(tail, fill=fill, outline=INK, width=border)
        self.d.rounded_rectangle(box, 60, fill=fill, outline=INK, width=border)
        self.d.polygon([(cx - 60 + border, base_y - 2), (cx + 40 - border, base_y - 2),
                        (tail_to[0], tail_to[1] - border * 2)], fill=fill)

    def arrow(self, xy, length=120, color=INK, thickness=22):
        x, y = xy
        self.d.rectangle((x, y - thickness / 2, x + length - 40, y + thickness / 2), fill=color)
        self.d.polygon([(x + length - 50, y - 38), (x + length, y), (x + length - 50, y + 38)], fill=color)

    def triangle(self, center, size, up=True, color=INK):
        cx, cy = center
        s = size / 2
        pts = [(cx - s, cy + s * 0.8), (cx + s, cy + s * 0.8), (cx, cy - s * 0.8)] if up else \
              [(cx - s, cy - s * 0.8), (cx + s, cy - s * 0.8), (cx, cy + s * 0.8)]
        self.d.polygon(pts, fill=color)

    # ------------------------------------------------------------ text

    def text(self, xy, text, name, size, fill=INK, anchor="la", stroke=0, stroke_fill=INK,
             shadow=None, shadow_fill=INK, spacing=0):
        f = font(name, size)
        text = clean(text, name)
        if shadow:
            dx, dy = shadow
            self.d.text((xy[0] + dx, xy[1] + dy), text, font=f, fill=shadow_fill, anchor=anchor,
                        stroke_width=stroke, stroke_fill=shadow_fill, spacing=spacing)
        self.d.text(xy, text, font=f, fill=fill, anchor=anchor, stroke_width=stroke,
                    stroke_fill=stroke_fill, spacing=spacing)
        return self.d.textbbox(xy, text, font=f, anchor=anchor, stroke_width=stroke, spacing=spacing)

    def width_of(self, text, name, size, stroke=0) -> float:
        text = clean(text, name)
        box = self.d.textbbox((0, 0), text, font=font(name, size), stroke_width=stroke)
        return box[2] - box[0]

    def fit(self, text, name, box_w, box_h, max_size, min_size=28, line_gap=0.02, stroke=0, max_lines=4):
        """Largest size where `text` wraps into box_w x box_h. Returns (size, lines, line_h)."""
        text = clean(text, name)
        words = text.split()
        for size in range(max_size, min_size - 1, -2):
            lines = wrap(words, lambda s: self.width_of(s, name, size, stroke), box_w)
            if lines is None or len(lines) > max_lines:
                continue
            if len(lines) > 1 and len(lines[-1]) <= 3 and size > min_size + 20:
                continue  # avoid a lonely "2" / "II" on the last line
            asc, desc = font(name, size).getmetrics()
            line_h = asc + desc * 0.15 + size * line_gap
            if line_h * len(lines) <= box_h:
                return size, lines, line_h
        size = min_size
        lines = wrap(words, lambda s: self.width_of(s, name, size, stroke), box_w, force=True)
        asc, desc = font(name, size).getmetrics()
        line_h = asc + desc * 0.15 + size * line_gap
        while len(lines) > 1 and line_h * len(lines) > box_h:
            lines = lines[:-1]
            lines[-1] = lines[-1].rstrip(".,:;") + "..."
        return size, lines, line_h

    def text_block(self, box, text, name, max_size, min_size=28, fill=INK, align="left", valign="top",
                   stroke=0, stroke_fill=INK, shadow=None, max_lines=4, line_gap=0.02):
        x0, y0, x1, y1 = box
        size, lines, line_h = self.fit(text, name, x1 - x0, y1 - y0, max_size, min_size,
                                       line_gap=line_gap, stroke=stroke, max_lines=max_lines)
        total = line_h * len(lines)
        y = y0 if valign == "top" else (y0 + (y1 - y0 - total) / 2 if valign == "middle" else y1 - total)
        for line in lines:
            if align == "center":
                x, anchor = (x0 + x1) / 2, "ma"
            elif align == "right":
                x, anchor = x1, "ra"
            else:
                x, anchor = x0, "la"
            self.text((x, y), line, name, size, fill=fill, anchor=anchor, stroke=stroke,
                      stroke_fill=stroke_fill, shadow=shadow)
            y += line_h
        return y

    def chip(self, xy, text, name="body_xbold", size=34, fill=YELLOW, fg=INK, pad=(22, 10),
             border=5, shadow=6, anchor="la"):
        tw = self.width_of(text, name, size)
        asc, desc = font(name, size).getmetrics()
        w, h = tw + pad[0] * 2, asc + pad[1] * 2
        x, y = xy
        if anchor == "ra":
            x -= w
        elif anchor == "ma":
            x -= w / 2
        self.panel((x, y, x + w, y + h), fill=fill, border=border, shadow=shadow, radius=h // 2)
        self.text((x + w / 2, y + h / 2 + 2), text, name, size, fill=fg, anchor="mm")
        return (x, y, x + w, y + h)

    # ------------------------------------------------------------ layers

    @classmethod
    def layer(cls, size) -> "Canvas":
        """A transparent RGBA canvas (for sprites and rotated elements)."""
        sub = cls.__new__(cls)
        sub.w, sub.h = int(size[0]), int(size[1])
        sub.im = Image.new("RGBA", (sub.w, sub.h), (0, 0, 0, 0))
        sub.d = ImageDraw.Draw(sub.im)
        return sub

    def rotated(self, size, draw_fn, center, angle):
        """Draw on a transparent layer via draw_fn(Canvas-like) and paste it rotated."""
        sub = Canvas.layer(size)
        draw_fn(sub)
        layer = sub.im.rotate(angle, resample=Image.BICUBIC, expand=True)
        self.im.paste(layer, (int(center[0] - layer.width / 2), int(center[1] - layer.height / 2)), layer)

    def logo(self, xy, height, anchor="la"):
        im = _logo()
        w = int(im.width * height / im.height)
        im = im.resize((w, height), Image.LANCZOS)
        x, y = xy
        if anchor == "ra":
            x -= w
        elif anchor == "ma":
            x -= w // 2
        self.im.paste(im, (int(x), int(y)), im)
        return (x, y, x + w, y + height)

    def image(self, path: Path, box, border=10, radius=48, shadow=18, masks=None):
        """Screenshot inside an inked phone frame, fitted into box (keeps aspect).

        `masks`: [[x0, y0, x1, y1], ...] in source-image pixels — areas (official posters,
        avatars) that are covered with flat brand-colored blocks before drawing.
        """
        src = Image.open(path).convert("RGB")
        if masks:
            md = ImageDraw.Draw(src)
            r = max(4, src.width // 70)
            for i, (mx0, my0, mx1, my1) in enumerate(masks):
                md.rounded_rectangle((mx0, my0, mx1, my1), r, fill=mix(ACCENTS[i % 3], INK, 0.15))
        x0, y0, x1, y1 = box
        scale = min((x1 - x0) / src.width, (y1 - y0) / src.height)
        w, h = int(src.width * scale), int(src.height * scale)
        x, y = int(x0 + (x1 - x0 - w) / 2), int(y0 + (y1 - y0 - h) / 2)
        pad = 18
        self.panel((x - pad, y - pad, x + w + pad, y + h + pad), fill=INK, border=border, shadow=shadow,
                   radius=radius + pad, outline=INK, shadow_color=MAGENTA)
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius, fill=255)
        self.im.paste(src.resize((w, h), Image.LANCZOS), (x, y), mask)

    def poster(self, path: Path, box, angle=0.0, border=9, shadow=16, shadow_color=INK):
        """Anime cover, center-cropped to the box, inked border + hard shadow, optionally tilted."""
        x0, y0, x1, y1 = (int(v) for v in box)
        w, h = x1 - x0, y1 - y0
        src = Image.open(path).convert("RGB")
        scale = max(w / src.width, h / src.height)
        src = src.resize((max(w, round(src.width * scale)), max(h, round(src.height * scale))), Image.LANCZOS)
        left, top = (src.width - w) // 2, (src.height - h) // 4
        src = src.crop((left, top, left + w, top + h))
        size = (w + border * 2 + shadow + 4, h + border * 2 + shadow + 4)

        def draw(sub: "Canvas"):
            sub.d.rectangle((shadow, shadow, shadow + w + border * 2, shadow + h + border * 2), fill=shadow_color)
            sub.d.rectangle((0, 0, w + border * 2, h + border * 2), fill=INK)
            sub.im.paste(src, (border, border))

        cx = x0 + w / 2 + (shadow) / 2
        cy = y0 + h / 2 + (shadow) / 2
        self.rotated(size, draw, (cx, cy), angle)

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.im.convert("RGB").save(path, "JPEG", quality=settings()["render"]["jpeg_quality"],
                                    optimize=True, progressive=True)
        return path


def wrap(words, measure, max_w, force=False):
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if measure(trial) <= max_w:
            cur = trial
            continue
        if not cur:  # single word wider than the box
            if not force:
                return None
            cur = word
            continue
        lines.append(cur)
        cur = word
        if measure(cur) > max_w and not force:
            return None
    if cur:
        lines.append(cur)
    return lines


@lru_cache(maxsize=1)
def _logo() -> Image.Image:
    im = Image.open(ASSETS_DIR / "logo.png").convert("RGBA")
    return im.crop(im.getbbox())


def resolve(path: str | None) -> Path | None:
    if not path:
        return None
    p = (ROOT / path).resolve()
    return p if p.exists() else None
