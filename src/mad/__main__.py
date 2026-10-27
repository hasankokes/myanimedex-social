"""Command line entry point.

  python -m mad run --slot post|story [--date YYYY-MM-DD] [--type KIND] [--dry-run] [--force]
  python -m mad plan [--week YYYY-Www | --next] [--force]
  python -m mad preview [--week YYYY-Www | --next] [--pages]
  python -m mad check
  python -m mad samples
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import hosting, planner, state as state_mod
from .config import OUT_DIR, ROOT, SAMPLES_DIR, MadError, env_flag, error, group, log, settings, summary, warn
from .render import templates

KIND_LABELS = {
    "airing_week": "Post · Airing this week (carousel)",
    "feature": "Post · App feature",
    "top5": "Post · Top 5 this season (carousel)",
    "story_anime_of_day": "Story · Anime of the day",
    "story_tip": "Story · App tip",
    "story_your_pick": "Story · Your pick (reply A/B)",
    "story_download": "Story · Download the app",
    "story_weekend": "Story · Weekend binge pick",
}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _week_arg(args) -> str:
    if getattr(args, "week", None):
        return args.week
    day = _today() + timedelta(days=1 if getattr(args, "next", False) else 0)
    return planner.week_id(day)


def _render_slot(slot: dict[str, Any], out_dir: Path) -> list[Path]:
    paths = templates.render(slot, out_dir)
    if slot.get("caption"):
        (out_dir / "caption.txt").write_text(slot["caption"] + "\n", "utf-8")
    log(f"Rendered {len(paths)} image(s) → {out_dir.relative_to(ROOT)}")
    return paths


def _safe(key: str) -> str:
    return key.replace(":", "_").replace("#", "_")


# ---------------------------------------------------------------- run

def cmd_run(args) -> int:
    day = date.fromisoformat(args.date) if args.date else _today()
    dry = args.dry_run or env_flag("DRY_RUN")
    st = state_mod.load()
    week = planner.week_id(day)

    if args.type:
        kind = args.type
        slot_name = "post" if kind in planner.POST_KINDS else "story"
        key = planner.slot_key(day, slot_name)
        if planner.kind_for(day, slot_name) != kind:
            key += f"#{kind}"  # manual extra post: don't collide with the scheduled slot
        with group(f"Build {kind} (manual)"):
            slot = planner.build_slot(kind, day, st)
    else:
        slot_name = args.slot
        kind = planner.kind_for(day, slot_name)
        if not kind:
            log(f"No {slot_name} is scheduled on {day:%A} ({day}). Use --type to post something anyway.")
            return 0
        key = planner.slot_key(day, slot_name)
        plan = planner.load_plan(week)
        if not plan or key not in plan["slots"]:
            warn(f"No plan for {week} — building it now (normally the Sunday preview does this)")
            with group(f"Build plan {week}"):
                plan = planner.build_plan(week, st)
                planner.save_plan(plan)
        slot = plan["slots"][key]
        if slot.get("skip"):
            log(f"{key} is marked skip in plans/{week}.json — nothing to do")
            return 0

    if key in st["slots"] and not args.force:
        log(f"{key} was already published ({st['slots'][key]['published_at']}). Use --force to post again.")
        return 0

    log(f"{key}: {KIND_LABELS[kind]}{' [DRY RUN]' if dry else ''}")
    with group("Render"):
        paths = _render_slot(slot, OUT_DIR / _safe(key))
    if slot.get("caption"):
        with group("Caption"):
            log(slot["caption"])

    if dry:
        log("DRY RUN: images and caption generated, nothing was uploaded or published.")
        summary(f"### {key} — {KIND_LABELS[kind]} (dry run)\n\n{len(paths)} image(s) rendered.\n\n"
                f"```\n{slot.get('caption', '(story — no caption)')}\n```")
        return 0

    from .instagram import Instagram  # needs secrets; imported late so dry runs work without them

    ig = Instagram()
    with group("Preflight"):
        ig.ensure_quota(1)
    with group("Upload images"):
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        folder = f"media/{day.isoformat()}-{_safe(key.split(':', 1)[1])}-{stamp}"
        urls = list(hosting.upload({f"{folder}/{p.name}": p for p in paths}, day, key).values())
        hosting.wait_live(urls)
    with group("Publish to Instagram"):
        if slot_name == "story":
            media_id = ig.publish_story(urls[0])
        elif len(urls) > 1:
            media_id = ig.publish_carousel(urls, slot["caption"])
        else:
            media_id = ig.publish_image(urls[0], slot["caption"])
    published_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state_mod.record_publish(st, key, slot, media_id, published_at)
    state_mod.save(st)
    log(f"Published {key} as media {media_id}")
    summary(f"### ✅ Published {key} — {KIND_LABELS[kind]}\n\nMedia id `{media_id}` · {len(urls)} image(s)")
    return 0


# ---------------------------------------------------------------- plan / preview

def cmd_plan(args) -> int:
    week = _week_arg(args)
    if planner.load_plan(week) and not args.force:
        log(f"plans/{week}.json already exists (use --force to rebuild)")
        return 0
    plan = planner.build_plan(week, state_mod.load())
    planner.save_plan(plan)
    log(f"Wrote plans/{week}.json with {len(plan['slots'])} slots")
    return 0


def cmd_preview(args) -> int:
    week = _week_arg(args)
    plan = planner.load_plan(week)
    if not plan or args.force:
        with group(f"Build plan {week}"):
            plan = planner.build_plan(week, state_mod.load())
            planner.save_plan(plan)
    out = OUT_DIR / "preview" / week
    if out.exists():
        shutil.rmtree(out)
    rendered: dict[str, list[Path]] = {}
    for key, slot in plan["slots"].items():
        with group(f"Render {key}"):
            rendered[key] = [] if slot.get("skip") else _render_slot(slot, out / _safe(key))

    base = None
    if args.pages:
        files = {f"preview/{week}/{_safe(k)}/{p.name}": p for k, ps in rendered.items() for p in ps}
        with group("Upload preview images"):
            hosting.upload(files, _today(), f"preview {week}")
        base = f"{settings()['hosting']['pages_base_url'].rstrip('/')}/preview/{week}"

    lines = [f"Content plan for **{week}** (`plans/{week}.json`). Images are rendered from the frozen plan, "
             "so this is exactly what will be posted.", "",
             "To change something: edit the caption in the plan file, set `\"skip\": true` on a slot, or rebuild "
             "with *Weekly preview → force*. Times: posts 19:00 UTC, stories 14:00 UTC.", ""]
    for key, slot in plan["slots"].items():
        day = date.fromisoformat(slot["date"])
        lines.append(f"### {day:%a %b %-d} — {KIND_LABELS[slot['kind']]}" + (" — ⏭️ SKIPPED" if slot.get("skip") else ""))
        if rendered[key]:
            width = 160 if slot["slot"] == "post" else 140
            for p in rendered[key]:
                src = f"{base}/{_safe(key)}/{p.name}" if base else f"{_safe(key)}/{p.name}"
                lines.append(f'<img src="{src}" width="{width}">')
            lines.append("")
        if slot.get("caption"):
            lines += ["<details><summary>Caption</summary>", "", "```", slot["caption"], "```", "", "</details>", ""]
    md = "\n".join(lines)
    (out / "preview.md").write_text(md, "utf-8")
    log(f"Preview written to {(out / 'preview.md').relative_to(ROOT)}")
    summary(md)
    return 0


# ---------------------------------------------------------------- misc

REQUIRED_PERMISSIONS = {"instagram_basic", "instagram_content_publish", "pages_show_list"}


def cmd_check(args) -> int:
    from .instagram import Instagram

    info = Instagram().check()
    log(f"Instagram account: @{info['username']}")
    log(f"Publishing quota: {info['quota']}")
    if info["permissions"]:
        log(f"Granted permissions: {', '.join(info['permissions'])}")
        missing = REQUIRED_PERMISSIONS - set(info["permissions"])
        if missing:
            raise MadError(f"Token is missing permissions: {', '.join(sorted(missing))}")
    log("Token OK")
    summary(f"Token OK for @{info['username']} · quota {info['quota'].get('quota_usage', '?')} used in 24h")
    return 0


def cmd_samples(args) -> int:
    """Render one example of every template into samples/ (uses live AniList data)."""
    from .config import load_yaml

    week = _week_arg(args)
    plan = planner.load_plan(week) or planner.build_plan(week, state_mod.load())
    if SAMPLES_DIR.exists():
        shutil.rmtree(SAMPLES_DIR)
    captions_md = ["# Sample captions", ""]
    for key, slot in plan["slots"].items():
        _render_slot(slot, SAMPLES_DIR / slot["kind"])
        if slot.get("caption"):
            captions_md += [f"## {KIND_LABELS[slot['kind']]}", "", "```", slot["caption"], "```", ""]
    features = [f for f in load_yaml("features.yaml").get("features", []) if f.get("enabled", True)]
    text_only = next((f for f in features if not f.get("screenshot")), None)
    if text_only:
        _render_slot({"kind": "feature", "data": {"feature": text_only}}, SAMPLES_DIR / "feature_text_only")
    (SAMPLES_DIR / "captions.md").write_text("\n".join(captions_md), "utf-8")
    for tmp in SAMPLES_DIR.rglob("caption.txt"):
        tmp.unlink()
    log(f"Samples written to {SAMPLES_DIR.relative_to(ROOT)}/")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mad", description="MyAnimeDex Instagram automation")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="render and publish today's scheduled post or story")
    r.add_argument("--slot", choices=["post", "story"], required=True)
    r.add_argument("--date", help="UTC date to act as (YYYY-MM-DD), default today")
    r.add_argument("--type", choices=list(planner.BUILDERS), help="ignore the schedule and build this type now")
    r.add_argument("--dry-run", action="store_true", help="render only, never upload or publish")
    r.add_argument("--force", action="store_true", help="publish even if this slot was already published")

    for name in ("plan", "preview", "samples"):
        s = sub.add_parser(name)
        s.add_argument("--week", help="ISO week, e.g. 2026-W45")
        s.add_argument("--next", action="store_true", help="the week starting tomorrow (use on Sundays)")
        if name != "samples":
            s.add_argument("--force", action="store_true", help="rebuild the plan even if it exists")
        if name == "preview":
            s.add_argument("--pages", action="store_true", help="upload preview images to GitHub Pages")

    sub.add_parser("check", help="verify IG_USER_ID / ACCESS_TOKEN and permissions")

    args = p.parse_args(argv)
    handler = {"run": cmd_run, "plan": cmd_plan, "preview": cmd_preview, "check": cmd_check,
               "samples": cmd_samples}[args.cmd]
    try:
        return handler(args)
    except MadError as exc:
        error(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
