"""Reels: comic-style motion graphics rendered frame by frame with Pillow, encoded by ffmpeg.

Every reel renderer returns [reel.mp4, cover.jpg] and also writes reel_silent.mp4 (same
video, no audio) for re-posting from the phone with a trending Instagram sound.
Content stays inside the Reels safe area: nothing important below ~1600 px (caption and
buttons) or in the right-hand 140 px of the lower half (like/comment/share icons).
"""
from __future__ import annotations

import math
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw

from ..captions import display_title, score10
from ..config import ROOT, MadError, load_yaml, log, settings
from ..covers import cover_path
from .base import CREAM, INK, MAGENTA, TEAL, WHITE, YELLOW, Canvas, mix

W, H = settings()["render"]["reel_size"]
FPS = settings()["render"]["reel_fps"]
HANDLE = settings()["brand"]["handle"]


# ---------------------------------------------------------------- easing

def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def seg(t: float, start: float, dur: float) -> float:
    """0..1 progress of t inside [start, start + dur]."""
    return clamp((t - start) / dur) if dur > 0 else float(t >= start)


def out_cubic(p: float) -> float:
    return 1 - (1 - p) ** 3


def out_back(p: float, k: float = 1.70158) -> float:
    p -= 1
    return 1 + (k + 1) * p ** 3 + k * p ** 2


def in_out_sine(p: float) -> float:
    return -(math.cos(math.pi * p) - 1) / 2


# ---------------------------------------------------------------- sprites

def place(frame: Image.Image, spr: Image.Image | None, center, scale=1.0, alpha=1.0, angle=0.0):
    if spr is None or scale <= 0.02 or alpha <= 0.01:
        return
    im = spr
    if abs(scale - 1) > 0.003:
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.BICUBIC)
    if abs(angle) > 0.05:
        im = im.rotate(angle, resample=Image.BICUBIC, expand=True)
    if alpha < 0.999:
        im = im.copy()
        im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
    frame.paste(im, (round(center[0] - im.width / 2), round(center[1] - im.height / 2)), im)


def crop_alpha(c: Canvas) -> Image.Image:
    box = c.im.getbbox()
    return c.im.crop(box) if box else c.im


def text_sprite(text, name, size, fill=WHITE, stroke=0, stroke_fill=INK, shadow=None, shadow_fill=INK):
    pad = size + 60
    c = Canvas.layer((int(Canvas.layer((10, 10)).width_of(text, name, size, stroke)) + pad * 2, size * 2 + pad))
    c.text((c.w / 2, c.h / 2), text, name, size, fill=fill, anchor="mm", stroke=stroke, stroke_fill=stroke_fill,
           shadow=shadow, shadow_fill=shadow_fill)
    return crop_alpha(c)


def block_sprite(box_w, box_h, text, name, max_size, min_size=40, fill=WHITE, stroke=0, shadow=None,
                 align="center", max_lines=3):
    c = Canvas.layer((box_w + 40, box_h + 40))
    c.text_block((20, 20, box_w + 20, box_h + 20), text, name, max_size, min_size, fill=fill, align=align,
                 valign="middle", stroke=stroke, shadow=shadow, max_lines=max_lines)
    return crop_alpha(c)


def chip_sprite(text, size=40, fill=YELLOW, fg=INK, name="body_xbold", pad=(26, 12)):
    c = Canvas.layer((int(Canvas.layer((10, 10)).width_of(text, name, size)) + pad[0] * 2 + 40, size * 3))
    c.chip((10, 10), text, name=name, size=size, fill=fill, fg=fg, pad=pad)
    return crop_alpha(c)


def burst_sprite(r, fill, text=None, text_size=None, fg=INK, sub=None, seed=3, name="display"):
    c = Canvas.layer((r * 2 + 60, r * 2 + 60))
    cx = cy = r + 24
    c.burst((cx, cy), r, r * 0.74, points=16, fill=fill, shadow=(10, 10), seed=seed)
    if text:
        if sub:
            c.text((cx, cy + 8), text, name, text_size or int(r * 0.75), fill=fg, anchor="ms")
            c.text((cx, cy + 22), sub, "body_xbold", int(r * 0.16), fill=fg, anchor="mt")
        else:
            c.text((cx, cy), text, name, text_size or int(r * 0.6), fill=fg, anchor="mm")
    return crop_alpha(c)


def poster_sprite(path: Path | None, w: int, h: int, shadow_color=INK, title: str = "", accent=TEAL):
    border, shadow = 10, 20
    c = Canvas.layer((w + border * 2 + shadow, h + border * 2 + shadow))
    c.d.rectangle((shadow, shadow, shadow + w + border * 2, shadow + h + border * 2), fill=shadow_color)
    c.d.rectangle((0, 0, w + border * 2, h + border * 2), fill=INK)
    if path:
        src = Image.open(path).convert("RGB")
        scale = max(w / src.width, h / src.height)
        src = src.resize((max(w, round(src.width * scale)), max(h, round(src.height * scale))), Image.LANCZOS)
        left, top = (src.width - w) // 2, (src.height - h) // 4
        c.im.paste(src.crop((left, top, left + w, top + h)), (border, border))
    else:  # typographic stand-in when the cover can't be downloaded
        c.d.rectangle((border, border, border + w, border + h), fill=accent)
        c.halftone(mix(accent, INK, 0.25), box=(border, border, border + w, border + h), max_r=9)
        c.text_block((border + 30, border + 30, border + w - 30, border + h - 30), title.upper(), "display", 110,
                     40, fill=WHITE, valign="middle", align="center", stroke=4, max_lines=5)
    return c.im


def background(color, accent_lines, dots, origin="br", center=(540, 900), seed=7):
    c = Canvas((W, H), color)
    c.speed_lines(center, accent_lines, count=84, inner=330, outer=2600, seed=seed)
    c.halftone(dots, origin=origin, max_r=13, spacing=28)
    return c.im


def shake(t: float, start: float, dur=0.18, amp=14, seed=1) -> tuple[int, int]:
    p = seg(t, start, dur)
    if p <= 0 or p >= 1:
        return 0, 0
    rnd = random.Random(int(t * FPS) * 31 + seed)
    k = amp * (1 - p)
    return int(rnd.uniform(-k, k)), int(rnd.uniform(-k, k))


def flash(frame: Image.Image, t: float, color=WHITE, dur=0.09):
    if t < dur:
        frame.paste(Image.blend(frame, Image.new("RGB", frame.size, color), 0.85 * (1 - t / dur)))


# ---------------------------------------------------------------- encoder

Scene = tuple[float, Callable[[float], Image.Image]]


def encode(scenes: list[Scene], out_dir: Path, cover_at: float, music_seed: int) -> list[Path]:
    if not shutil.which("ffmpeg"):
        raise MadError("ffmpeg is not installed (needed to render reels)")
    out_dir.mkdir(parents=True, exist_ok=True)
    silent, final, cover = out_dir / "reel_silent.mp4", out_dir / "reel.mp4", out_dir / "cover.jpg"
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-profile:v", "high", "-level", "4.1", "-g", str(FPS * 2), "-keyint_min", str(FPS * 2),
         "-sc_threshold", "0", "-movflags", "+faststart", str(silent)],
        stdin=subprocess.PIPE,
    )
    n, t0 = 0, 0.0
    for dur, draw in scenes:
        frames = round(dur * FPS)
        for i in range(frames):
            t = i / FPS
            img = draw(t).convert("RGB")
            if abs((t0 + t) - cover_at) < 0.5 / FPS:
                img.save(cover, "JPEG", quality=92)
            proc.stdin.write(img.tobytes())
            n += 1
        t0 += frames / FPS
    proc.stdin.close()
    if proc.wait() != 0:
        raise MadError("ffmpeg failed while encoding the reel")
    music = load_yaml("reels.yaml")["music"]
    bed = music[music_seed % len(music)]
    offset = bed["offsets"][(music_seed // len(music)) % len(bed["offsets"])]
    dur = n / FPS
    res = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(silent), "-ss", str(offset), "-t", f"{dur:.3f}",
         "-i", str(ROOT / bed["file"]), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-ar", "48000", "-ac", "2", "-af", f"afade=t=in:st=0:d=0.15,afade=t=out:st={max(0, dur - 0.9):.2f}:d=0.9",
         "-shortest", "-movflags", "+faststart", str(final)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise MadError(f"ffmpeg failed while adding music: {res.stderr[-300:]}")
    log(f"Reel encoded: {dur:.1f}s, {n} frames, music {Path(bed['file']).name} @ {offset}s")
    return [final, cover]


# ---------------------------------------------------------------- shared scenes

def hook_scene(lines: list[tuple[str, int, tuple]], chip: str | None, bg_color, chip_fill=YELLOW, dur=1.8,
               top=640) -> Scene:
    bg = background(bg_color, mix(bg_color, WHITE, 0.22), mix(bg_color, INK, 0.28), origin="bl")
    sprites = []
    for text, size, color in lines:
        spr = text_sprite(text, "comic", size, fill=color, stroke=14, shadow=(16, 16))
        if spr.width > 1000:
            spr = spr.resize((1000, round(spr.height * 1000 / spr.width)), Image.LANCZOS)
        sprites.append(spr)
    chip_spr = chip_sprite(chip, 46, fill=chip_fill, fg=YELLOW if chip_fill == INK else
                           WHITE if chip_fill == MAGENTA else INK) if chip else None

    def draw(t):
        f = bg.copy()
        y = top
        dx, dy = shake(t, 0.3)
        for i, spr in enumerate(sprites):
            start = 0.0 if i == 0 else 0.3 + 0.12 * i
            p = seg(t, start, 0.32)
            if i == 0:
                place(f, spr, (W / 2 + dx, y + spr.height / 2 + dy), scale=2.3 - 1.3 * out_back(p), alpha=p * 1.4)
            else:
                place(f, spr, (W / 2 + dx, y + spr.height / 2 + 120 * (1 - out_cubic(p)) + dy), alpha=p)
            y += spr.height + 10
        if chip_spr:
            p = seg(t, 0.75, 0.3)
            place(f, chip_spr, (W / 2, y + 70), scale=out_back(p), alpha=p)
        return f

    return dur, draw


def outro_scene(headline: str, sub: str, dur=1.6) -> Scene:
    bg = background(INK, mix(INK, TEAL, 0.18), mix(INK, MAGENTA, 0.45))
    logo_c = Canvas.layer((700, 520))
    logo_c.logo((350, 20), 470, anchor="ma")
    logo = crop_alpha(logo_c)
    head = block_sprite(940, 300, headline, "comic", 150, 80, fill=YELLOW, stroke=8, shadow=(10, 10))
    sub_spr = block_sprite(860, 120, sub, "body_bold", 50, 32, fill=CREAM)
    chips = [chip_sprite("FREE ON iOS & ANDROID", 44, fill=TEAL), chip_sprite("LINK IN BIO", 44, fill=MAGENTA, fg=WHITE)]

    def draw(t):
        f = bg.copy()
        flash(f, t, YELLOW)
        p = seg(t, 0, 0.35)
        place(f, logo, (W / 2, 560), scale=0.4 + 0.6 * out_back(p), alpha=p * 1.5)
        p = seg(t, 0.25, 0.3)
        place(f, head, (W / 2, 1000 + 60 * (1 - out_cubic(p))), alpha=p)
        p = seg(t, 0.45, 0.3)
        place(f, sub_spr, (W / 2, 1180), alpha=p)
        for i, ch in enumerate(chips):
            p = seg(t, 0.6 + 0.12 * i, 0.3)
            place(f, ch, (W / 2, 1310 + i * 110), scale=out_back(p), alpha=p)
        return f

    return dur, draw


def _fmt_count(n):
    if not n:
        return "-"
    return f"{n / 1_000_000:.1f}M" if n >= 1_000_000 else f"{n / 1000:.0f}K" if n >= 10_000 else f"{n / 1000:.1f}K"


# ---------------------------------------------------------------- Sunday: Top 5 countdown

RANK_COLORS = {5: MAGENTA, 4: TEAL, 3: YELLOW, 2: MAGENTA, 1: YELLOW}


def _rank_scene(m: dict[str, Any], dur=2.3) -> Scene:
    rank = m["rank"]
    accent = RANK_COLORS[rank]
    bg = background(CREAM, mix(CREAM, WHITE, 0.6), mix(CREAM, accent, 0.55), origin="bl", seed=rank)
    poster = poster_sprite(cover_path(m), 600, 846, shadow_color=accent, title=display_title(m), accent=accent)
    rank_spr = text_sprite(f"#{rank}", "display", 340, fill=accent, stroke=12, shadow=(16, 16))
    score = score10(m)
    burst = burst_sprite(185, YELLOW if accent != YELLOW else TEAL, score or "NEW", 150 if score else 110,
                         sub="FAN SCORE /10" if score else None, seed=rank)
    title = block_sprite(960, 220, display_title(m).upper(), "display", 124, 50, fill=INK, max_lines=2)
    mv = m.get("movement")
    if m.get("badge"):
        mv_chip = chip_sprite(m["badge"], 38, fill=MAGENTA, fg=WHITE)
    else:
        label = "NEW ENTRY" if mv == "new" else "SAME SPOT" if not mv else (f"UP {mv}" if mv > 0 else f"DOWN {-mv}")
        mv_chip = chip_sprite(label, 38, fill=MAGENTA if mv == "new" else TEAL, fg=WHITE if mv == "new" else INK)
    meta = chip_sprite(f"{_fmt_count(m.get('popularity'))} ON LISTS", 32, fill=INK, fg=CREAM)

    def draw(t):
        f = bg.copy()
        p = seg(t, 0, 0.42)
        kb = 1 + 0.045 * seg(t, 0.4, dur)  # slow Ken Burns push
        place(f, poster, (540 + 700 * (1 - out_cubic(p)), 950), scale=kb, angle=-3 + 10 * (1 - out_cubic(p)))
        dx, dy = shake(t, 0.42, seed=rank)
        p = seg(t, 0.1, 0.32)
        place(f, rank_spr, (270 + dx, 320 + dy), scale=2.0 - out_back(p), alpha=p * 1.6)
        p = seg(t, 0.55, 0.3)
        place(f, burst, (820, 360), scale=out_back(p), angle=-8 * (1 - p))
        p = seg(t, 0.8, 0.25)
        place(f, mv_chip, (270, 545), scale=out_back(p), alpha=p)
        p = seg(t, 0.35, 0.35)
        place(f, title, (540, 1490 + 70 * (1 - out_cubic(p))), alpha=p)
        p = seg(t, 0.95, 0.25)
        place(f, meta, (540, 1635), alpha=p)
        flash(f, t)
        return f

    return dur, draw


def render_reel_top5(data: dict[str, Any], out_dir: Path) -> list[Path]:
    from .templates import lens_style, top5_lens

    lens = top5_lens(data)
    st = lens_style(lens)
    hook = [(line, 400 if line == "TOP 5" else 170, st["top"] if line == "TOP 5" or i == 0 else WHITE)
            for i, line in enumerate(lens["hook"])]
    scenes = [hook_scene(hook, lens["chip"], st["bg"], chip_fill=st["chip"], top=470)]
    scenes += [_rank_scene(m) for m in sorted(data["items"], key=lambda m: -m["rank"])]
    scenes.append(outro_scene("WHAT'S YOUR #1?", "Comment below and track them in MyAnimeDex."))
    return encode(scenes, out_dir, cover_at=1.2, music_seed=data.get("seed", 0))


# ---------------------------------------------------------------- Thursday: this weekend's episodes

CARD_BG = [INK, TEAL, MAGENTA, INK, TEAL]


def _episode_scene(m: dict[str, Any], i: int, dur=1.9) -> Scene:
    color = CARD_BG[i % len(CARD_BG)]
    accent = YELLOW if color != YELLOW else MAGENTA
    bg = background(color, mix(color, WHITE, 0.14), mix(color, INK if color != INK else TEAL, 0.35), seed=i + 3)
    poster = poster_sprite(cover_path(m), 560, 790, shadow_color=accent, title=display_title(m), accent=TEAL)
    day = chip_sprite(f"{m['airing_day'].upper()}  ·  EP {m['airing']['episode']}", 60, fill=accent, name="display",
                      pad=(34, 14))
    num = burst_sprite(84, accent, f"{i + 1}", 92, seed=i + 1)
    title = block_sprite(940, 190, display_title(m).upper(), "display", 92, 44, fill=WHITE, stroke=5,
                         shadow=(8, 8), max_lines=2)
    score = score10(m)
    meta = chip_sprite(f"{score}/10  ·  {_fmt_count(m.get('popularity'))} ON LISTS" if score else
                       f"{_fmt_count(m.get('popularity'))} ON LISTS", 32, fill=CREAM)

    def draw(t):
        f = bg.copy()
        p = seg(t, 0, 0.35)
        kb = 1 + 0.04 * seg(t, 0.35, dur)
        place(f, poster, (540, 900 + 900 * (1 - out_cubic(p))), scale=kb, angle=3 * (1 - p) - 2)
        p = seg(t, 0.15, 0.3)
        dx, dy = shake(t, 0.45, seed=i)
        place(f, day, (540 + dx, 330 + dy), scale=1.8 - 0.8 * out_back(p), alpha=p * 1.5)
        p = seg(t, 0.35, 0.25)
        place(f, num, (230, 520), scale=out_back(p))
        p = seg(t, 0.4, 0.3)
        place(f, title, (540, 1440 + 60 * (1 - out_cubic(p))), alpha=p)
        p = seg(t, 0.7, 0.25)
        place(f, meta, (540, 1585), alpha=p)
        flash(f, t)
        return f

    return dur, draw


def render_reel_weekend(data: dict[str, Any], out_dir: Path) -> list[Path]:
    scenes = [hook_scene([("NEW EPISODES", 190, YELLOW), ("THIS", 210, WHITE), ("WEEKEND", 210, WHITE)],
                         data["date_range"].upper(), INK, chip_fill=MAGENTA, top=500)]
    scenes += [_episode_scene(m, i) for i, m in enumerate(data["items"])]
    scenes.append(outro_scene("NEVER MISS AN EPISODE", "Airing calendar and reminders in MyAnimeDex."))
    return encode(scenes, out_dir, cover_at=1.2, music_seed=data.get("seed", 0))


# ---------------------------------------------------------------- Tuesday: app demo

class ClipReader:
    """Streams frames of a screen recording at the reel frame rate; holds the last frame."""

    def __init__(self, path: Path, size: tuple[int, int]):
        self.size = size
        self.proc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={FPS},scale={size[0]}:{size[1]}",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        self.last: Image.Image | None = None

    def next(self) -> Image.Image:
        n = self.size[0] * self.size[1] * 3
        buf = self.proc.stdout.read(n) if self.proc.stdout else b""
        if len(buf) == n:
            self.last = Image.frombytes("RGB", self.size, buf)
        if self.last is None:
            raise MadError("Could not decode the demo clip")
        return self.last

    def close(self):
        if self.proc.stdout:
            self.proc.stdout.close()
        self.proc.wait()


def clip_duration(path: Path) -> float:
    res = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True)
    try:
        return float(res.stdout.strip())
    except ValueError as exc:
        raise MadError(f"Could not read the duration of {path.name}") from exc


def render_reel_app_demo(data: dict[str, Any], out_dir: Path) -> list[Path]:
    demo = data["demo"]
    clip = ROOT / demo["clip"]
    if not clip.exists():
        raise MadError(f"Demo clip not found: {demo['clip']}")
    hook = hook_scene([], None, YELLOW, dur=1.4)
    hook_text = block_sprite(960, 700, demo["hook"], "comic", 220, 90, fill=WHITE, stroke=14, shadow=(16, 16),
                             max_lines=4)
    hook_bg = hook[1]

    def hook_draw(t):
        f = hook_bg(t)
        p = seg(t, 0, 0.32)
        dx, dy = shake(t, 0.32)
        place(f, hook_text, (W / 2 + dx, 860 + dy), scale=2.2 - 1.2 * out_back(p), alpha=p * 1.5)
        return f

    # Phone: the clip inside an inked frame
    pw, ph = 600, round(600 * 1174 / 540)
    if ph > 1150:
        ph = 1150
        pw = round(ph * 540 / 1174)
    bg = background(INK, mix(INK, TEAL, 0.18), mix(INK, MAGENTA, 0.45), center=(540, 1000))
    frame_c = Canvas.layer((pw + 70, ph + 70))
    frame_c.panel((0, 0, pw + 36, ph + 36), fill=INK, border=10, shadow=22, radius=64, outline=INK,
                  shadow_color=MAGENTA)
    phone_frame = frame_c.im
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw, ph), 46, fill=255)
    title = text_sprite(demo["title"].upper(), "comic", 96, fill=YELLOW, stroke=8, shadow=(10, 10))
    if title.width > 980:
        title = title.resize((980, round(title.height * 980 / title.width)), Image.LANCZOS)
    sub = block_sprite(900, 110, demo["sub"], "body_bold", 48, 30, fill=CREAM, max_lines=2)
    reader = ClipReader(clip, (pw, ph))
    dur = max(clip_duration(clip), 4.5)
    phone_x, phone_y = (W - pw) // 2, 420

    def demo_draw(t):
        f = bg.copy()
        p = seg(t, 0, 0.4)
        y_off = int(700 * (1 - out_cubic(p)))
        f.paste(phone_frame, (phone_x - 18, phone_y - 18 + y_off), phone_frame)
        f.paste(reader.next(), (phone_x, phone_y + y_off), mask)
        p = seg(t, 0.1, 0.3)
        place(f, title, (W / 2, 200), scale=1.6 - 0.6 * out_back(p), alpha=p * 1.5)
        p = seg(t, 0.35, 0.3)
        place(f, sub, (W / 2, 330 + 30 * (1 - out_cubic(p))), alpha=p)
        flash(f, t)
        return f

    try:
        scenes = [(1.4, hook_draw), (dur, demo_draw),
                  outro_scene("TRY IT FREE", "MyAnimeDex · the anime tracker app.")]
        return encode(scenes, out_dir, cover_at=1.0, music_seed=data.get("seed", 0))
    finally:
        reader.close()


# ---------------------------------------------------------------- Tuesday: Guess the anime

def _cover_base(m: dict[str, Any], w: int, h: int) -> Image.Image | None:
    path = cover_path(m)
    if not path:
        return None
    src = Image.open(path).convert("RGB")
    scale = max(w / src.width, h / src.height)
    src = src.resize((max(w, round(src.width * scale)), max(h, round(src.height * scale))), Image.LANCZOS)
    left, top = (src.width - w) // 2, (src.height - h) // 4
    return src.crop((left, top, left + w, top + h))


def _quiz_round(m: dict[str, Any], i: int, total: int, dur=5.0) -> Scene:
    pw, ph = 640, 900
    base = _cover_base(m, pw, ph)
    if base is None:  # no cover -> typographic card, still guessable from the hint
        base = poster_sprite(None, pw, ph, title="?", accent=TEAL).convert("RGB").resize((pw, ph))
    bg = background(INK, mix(INK, MAGENTA, 0.22), mix(INK, TEAL, 0.4), seed=40 + i)
    frame_c = Canvas.layer((pw + 60, ph + 60))
    frame_c.panel((0, 0, pw + 24, ph + 24), fill=INK, border=10, shadow=22, shadow_color=YELLOW)
    frame = frame_c.im
    fx, fy = (m.get("focus") or [0.5, 0.4])
    level_fill = {"EASY": TEAL, "MEDIUM": YELLOW, "HARD": MAGENTA}.get(m.get("level"), YELLOW)
    head = chip_sprite(f"ROUND {i}/{total}  ·  {m.get('level', '')}", 62, fill=level_fill,
                       fg=WHITE if level_fill == MAGENTA else INK, name="display", pad=(30, 12))
    hint_parts = [str(m.get("seasonYear") or ""), (m.get("genres") or [""])[0],
                  f"{m['episodes']} EPS" if m.get("episodes") else ""]
    hint = chip_sprite("HINT: " + "  ·  ".join(x for x in hint_parts if x), 46, fill=CREAM)
    counts = [burst_sprite(95, YELLOW, str(n), 110, seed=n) for n in (3, 2, 1)]
    title = block_sprite(960, 200, display_title(m).upper(), "display", 110, 50, fill=YELLOW, stroke=6,
                         shadow=(8, 8), max_lines=2)
    score = score10(m)
    meta = chip_sprite(f"{score}/10  ·  {_fmt_count(m.get('popularity'))} FANS" if score else "", 42, fill=TEAL)
    reveal_at = 3.3
    px, py = (W - pw) // 2, 470

    def view(t):
        if t >= reveal_at:
            return base
        p = in_out_sine(clamp(t / reveal_at))
        z = 4.2 - 3.0 * p                       # 4.2x -> 1.2x zoom while guessing
        cw, ch = pw / z, ph / z
        cx = min(max(fx * pw, cw / 2), pw - cw / 2)
        cy = min(max(fy * ph, ch / 2), ph - ch / 2)
        img = base.crop((round(cx - cw / 2), round(cy - ch / 2), round(cx + cw / 2), round(cy + ch / 2)))
        img = img.resize((pw, ph), Image.BICUBIC)
        block = max(1, round(34 * (1 - p) ** 1.5))
        if block > 1:
            img = img.resize((max(1, pw // block), max(1, ph // block)), Image.NEAREST).resize((pw, ph), Image.NEAREST)
        return img

    def draw(t):
        f = bg.copy()
        f.paste(frame, (px - 12, py - 12), frame)
        f.paste(view(t), (px, py))
        place(f, head, (W / 2, 330), scale=out_back(seg(t, 0, 0.3)))
        if t < reveal_at:
            k = min(2, int(t / 1.1))
            place(f, counts[k], (900, 520), scale=out_back(seg(t - k * 1.1, 0, 0.25)))
            place(f, hint, (W / 2, 1480), alpha=seg(t, 0.6, 0.3))
        else:
            dx, dy = shake(t, reveal_at, seed=i)
            p = seg(t, reveal_at, 0.3)
            place(f, title, (W / 2 + dx, 1480 + 60 * (1 - out_cubic(p)) + dy), alpha=p)
            place(f, meta, (W / 2, 1620), alpha=seg(t, reveal_at + 0.2, 0.3))
            flash(f, t - reveal_at, WHITE)
        flash(f, t)
        return f

    return dur, draw


def render_reel_quiz(data: dict[str, Any], out_dir: Path) -> list[Path]:
    rounds = data["rounds"]
    scenes = [hook_scene([("GUESS", 330, YELLOW), ("THE ANIME", 200, WHITE)],
                         f"{len(rounds)} ROUNDS  ·  EASY TO HARD", MAGENTA, chip_fill=YELLOW, top=560)]
    scenes += [_quiz_round(m, i, len(rounds)) for i, m in enumerate(rounds, 1)]
    scenes.append(outro_scene("HOW MANY DID YOU GET?", f"Comment your score /{len(rounds)} · new quiz every Tuesday"))
    return encode(scenes, out_dir, cover_at=1.3, music_seed=data.get("seed", 0))


# ---------------------------------------------------------------- Thursday: If you liked X

def render_reel_recs(data: dict[str, Any], out_dir: Path) -> list[Path]:
    a = data["anchor"]
    bg = background(TEAL, mix(TEAL, WHITE, 0.22), mix(TEAL, INK, 0.25), origin="bl")
    poster = poster_sprite(cover_path(a), 470, 663, shadow_color=INK, title=display_title(a), accent=MAGENTA)
    liked = text_sprite("IF YOU LIKED", "comic", 150, fill=YELLOW, stroke=12, shadow=(14, 14))
    name = block_sprite(960, 190, display_title(a).upper(), "display", 100, 46, fill=WHITE, stroke=6,
                        shadow=(8, 8), max_lines=2)
    watch = chip_sprite("WATCH THESE 3 NEXT", 62, fill=MAGENTA, fg=WHITE, name="display", pad=(34, 14))

    def hook(t):
        f = bg.copy()
        dx, dy = shake(t, 0.3)
        place(f, liked, (W / 2 + dx, 300 + dy), scale=2.0 - out_back(seg(t, 0, 0.3)), alpha=seg(t, 0, 0.2) * 2)
        p = seg(t, 0.2, 0.4)
        place(f, poster, (W / 2, 880 + 700 * (1 - out_cubic(p))), angle=-3, scale=1 + 0.03 * seg(t, 0.6, 1.6))
        place(f, name, (W / 2, 1330), alpha=seg(t, 0.5, 0.3))
        place(f, watch, (W / 2, 1520), scale=out_back(seg(t, 1.2, 0.3)))
        return f

    scenes: list[Scene] = [(2.4, hook)]
    for i, m in enumerate(data["recs"]):
        dur, card = _episode_like_card(m, i, f"PICK {i + 1}", " · ".join(g.upper() for g in m.get("shared") or [])
                                       or (m.get("genres") or [""])[0].upper())
        scenes.append((dur, card))
    scenes.append(outro_scene("SAVE THIS FOR LATER", "Follow for new picks every week · MyAnimeDex"))
    return encode(scenes, out_dir, cover_at=1.9, music_seed=data.get("seed", 0))


def _episode_like_card(m: dict[str, Any], i: int, label: str, sub: str, dur=2.4) -> Scene:
    color = [INK, MAGENTA, INK][i % 3]
    accent = [YELLOW, YELLOW, TEAL][i % 3]
    bg = background(color, mix(color, WHITE, 0.14), mix(color, TEAL if color == INK else INK, 0.35), seed=i + 9)
    poster = poster_sprite(cover_path(m), 560, 790, shadow_color=accent, title=display_title(m), accent=TEAL)
    top = chip_sprite(label, 60, fill=accent, name="display", pad=(34, 14))
    title = block_sprite(940, 190, display_title(m).upper(), "display", 92, 44, fill=WHITE, stroke=5,
                         shadow=(8, 8), max_lines=2)
    score = score10(m)
    burst = burst_sprite(110, accent, score or "NEW", 92 if score else 70, sub="FAN SCORE" if score else None,
                         seed=i + 2)
    subchip = chip_sprite(sub, 42, fill=CREAM) if sub else None

    def draw(t):
        f = bg.copy()
        p = seg(t, 0, 0.35)
        place(f, poster, (540, 900 + 900 * (1 - out_cubic(p))), scale=1 + 0.04 * seg(t, 0.35, dur), angle=-2)
        place(f, top, (540, 330), scale=1.8 - 0.8 * out_back(seg(t, 0.12, 0.3)), alpha=seg(t, 0.12, 0.2) * 2)
        place(f, burst, (850, 560), scale=out_back(seg(t, 0.45, 0.3)))
        place(f, title, (540, 1440 + 60 * (1 - out_cubic(seg(t, 0.4, 0.3)))), alpha=seg(t, 0.4, 0.3))
        if subchip:
            place(f, subchip, (540, 1590), alpha=seg(t, 0.7, 0.25))
        flash(f, t)
        return f

    return dur, draw


# ---------------------------------------------------------------- Sunday: season tier list

TIER_COLORS = {"S": MAGENTA, "A": YELLOW, "B": TEAL, "C": CREAM, "D": mix(CREAM, INK, 0.35)}


def render_reel_tierlist(data: dict[str, Any], out_dir: Path) -> list[Path]:
    items = data["items"]
    label = f"{(data['season'] or '').upper()} {data['year']}"
    tiers = list(TIER_COLORS)
    top_y, row_h, gap = 360, 232, 14
    lab_w, x0, x1 = 150, 70, 1010
    # board background (static)
    board_c = Canvas((W, H), INK)
    board_c.halftone(mix(INK, MAGENTA, 0.35), origin="br", max_r=11)
    board_c.text((W / 2, 250), f"{label} TIER LIST", "comic", 96, fill=YELLOW, anchor="ms", stroke=6,
                 shadow=(8, 8))
    for r, t in enumerate(tiers):
        y = top_y + r * (row_h + gap)
        board_c.panel((x0, y, x1, y + row_h), fill=mix(INK, WHITE, 0.08), border=4, shadow=0,
                      outline=mix(INK, WHITE, 0.25))
        board_c.d.rectangle((x0, y, x0 + lab_w, y + row_h), fill=TIER_COLORS[t])
        board_c.text((x0 + lab_w / 2, y + row_h / 2), t, "comic", 130, fill=INK if t != "S" else WHITE,
                     anchor="mm")
    board_c.text((W / 2, top_y + 5 * (row_h + gap) + 30), "Ranked by AniList fan score", "body_bold", 30,
                 fill=CREAM, anchor="mt")
    board = board_c.im
    # slot positions
    th = row_h - 24
    pos: list[tuple[float, float, int]] = []
    counters = {t: 0 for t in tiers}
    per_row = {t: sum(1 for m in items if m["tier"] == t) for t in tiers}
    for m in items:
        t = m["tier"]
        r = tiers.index(t)
        n = max(per_row[t], 1)
        avail = x1 - (x0 + lab_w) - 24
        tw = min(round(th * 0.71), (avail - (n - 1) * 10) // n)
        k = counters[t]
        counters[t] += 1
        cx = x0 + lab_w + 12 + k * (tw + 10) + tw / 2
        cy = top_y + r * (row_h + gap) + row_h / 2
        pos.append((cx, cy, tw))
    thumbs = []
    for m, (_, _, tw) in zip(items, pos):
        base = _cover_base(m, tw, round(tw / 0.71)) or poster_sprite(None, tw, round(tw / 0.71),
                                                                    title=display_title(m)).convert("RGB")
        thumbs.append(base.resize((tw, min(th, round(tw / 0.71)))))
    big = [poster_sprite(cover_path(m), 420, 592, shadow_color=TIER_COLORS[m["tier"]], title=display_title(m))
           for m in items]
    names = [chip_sprite(f"{display_title(m)[:30].upper()}  ·  {score10(m)}", 44, fill=TIER_COLORS[m["tier"]],
                         fg=WHITE if m["tier"] == "S" else INK) for m in items]
    step = 0.62

    def draw(t):
        f = board.copy()
        cur = min(len(items) - 1, int(t / step))
        for j in range(len(items)):
            start = j * step
            if t < start:
                break
            cx, cy, tw = pos[j]
            p = out_cubic(seg(t, start + 0.25, 0.3))
            if p >= 1:
                f.paste(thumbs[j], (round(cx - tw / 2), round(cy - thumbs[j].height / 2)))
            elif j == cur:
                # big poster pops in the middle, then flies to its slot
                sx, sy = W / 2 + (cx - W / 2) * p, 960 + (cy - 960) * p
                scale = (1 - p) + p * (tw / 420)
                place(f, big[j], (sx, sy), scale=scale * (0.6 + 0.4 * out_back(seg(t, start, 0.2))))
        if t < len(items) * step:
            place(f, names[cur], (W / 2, 1650), alpha=seg(t, cur * step, 0.1))
        return f

    dur = len(items) * step + 1.8
    hook = hook_scene([("TIER LIST", 280, YELLOW), (label, 170, WHITE)], "S  ·  A  ·  B  ·  C  ·  D", MAGENTA,
                      top=560, dur=1.5)
    scenes = [hook, (dur, draw), outro_scene("AGREE OR NOT?", "Tell us which one is in the wrong tier.")]
    return encode(scenes, out_dir, cover_at=1.5 + dur - 0.5, music_seed=data.get("seed", 0))


# ---------------------------------------------------------------- teaser (pre-made video)

def render_reel_teaser(data: dict[str, Any], out_dir: Path) -> list[Path]:
    src = ROOT / data["file"]
    if not src.exists():
        raise MadError(f"Teaser video not found: {data['file']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / "reel.mp4"
    shutil.copy2(src, final)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(final), "-an", "-c:v", "copy", "-movflags", "+faststart",
                    str(out_dir / "reel_silent.mp4")], check=True)
    cover = out_dir / "cover.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(data.get("thumb_offset_ms", 1000) / 1000), "-i",
                    str(final), "-frames:v", "1", "-q:v", "2", str(cover)], check=True)
    return [final, cover]


REEL_RENDERERS = {
    "reel_quiz": render_reel_quiz,
    "reel_recs": render_reel_recs,
    "reel_tierlist": render_reel_tierlist,
    "reel_top5": render_reel_top5,
    "reel_weekend": render_reel_weekend,
    "reel_app_demo": render_reel_app_demo,
    "reel_teaser": render_reel_teaser,
}
