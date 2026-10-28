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
    "reel_app_demo": "Reel · App demo",
    "reel_weekend": "Reel · Episodes this weekend",
    "reel_top5": "Reel · Top 5 countdown",
    "reel_teaser": "Reel · App teaser",
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

def _scheduled_day(slot: str) -> date | None:
    """The day whose cron slot this (possibly late) scheduled run belongs to, or None if too late."""
    cfg = settings()["schedule"]
    now = datetime.now(timezone.utc)
    hour = cfg[f"{slot}_hour_utc"]
    slot_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if now < slot_time:
        slot_time -= timedelta(days=1)
    late = now - slot_time
    if late > timedelta(hours=cfg["max_delay_hours"]):
        warn(f"Scheduled run started {late.total_seconds() / 3600:.1f}h after the {slot_time:%Y-%m-%d %H:%M} UTC "
             f"slot (limit {cfg['max_delay_hours']}h) — skipping. Run it manually if you still want it.")
        return None
    if late > timedelta(minutes=30):
        log(f"Note: GitHub started this scheduled run {late.total_seconds() / 60:.0f} min late")
    return slot_time.date()


def _resolve_scheduled(day: date, slot_name: str, st: dict[str, Any]):
    """(kind, key, slot) for the planned slot of `day`, or None when nothing should be posted."""
    week = planner.week_id(day)
    kind = planner.kind_for(day, slot_name)
    if not kind:
        log(f"No {slot_name} is scheduled on {day:%A} ({day}). Use --type to post something anyway.")
        return None
    key = planner.slot_key(day, slot_name)
    plan = planner.load_plan(week)
    if not plan:
        warn(f"No plan for {week} — building it now (normally the Sunday preview does this)")
        with group(f"Build plan {week}"):
            plan = planner.build_plan(week, st)
            planner.save_plan(plan)
    elif key not in plan["slots"]:
        warn(f"plans/{week}.json has no {key} slot — adding just that one, other picks stay as they are")
        with group(f"Build {kind}"):
            plan = planner.add_slot(plan, day, slot_name, st)
            planner.save_plan(plan)
    slot = plan["slots"][key]
    if slot.get("skip"):
        log(f"{key} is marked skip in plans/{week}.json — nothing to do")
        return None
    return kind, key, slot


def _publish(day: date, slot_name: str, kind: str, key: str, slot: dict[str, Any], st: dict[str, Any],
             dry: bool) -> None:
    log(f"{key}: {KIND_LABELS[kind]}{' [DRY RUN]' if dry else ''}")
    with group("Render"):
        paths = _render_slot(slot, OUT_DIR / _safe(key))
    if slot.get("caption"):
        with group("Caption"):
            log(slot["caption"])

    if dry:
        log("DRY RUN: images and caption generated, nothing was uploaded or published.")
        summary(f"### {key} — {KIND_LABELS[kind]} (dry run)\n\n{len(paths)} file(s) rendered.\n\n"
                f"```\n{slot.get('caption', '(story — no caption)')}\n```")
        return

    from .instagram import Instagram  # needs secrets; imported late so dry runs work without them

    ig = Instagram()
    with group("Preflight"):
        ig.ensure_quota(1)
    with group("Upload media"):
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        folder = f"media/{day.isoformat()}-{_safe(key.split(':', 1)[1])}-{stamp}"
        urls = list(hosting.upload({f"{folder}/{p.name}": p for p in paths}, day, key).values())
        hosting.wait_live(urls)
    with group("Publish to Instagram"):
        if slot_name == "reel":
            cover = next((u for u in urls if u.endswith(".jpg")), None)
            video = next(u for u in urls if u.endswith(".mp4"))
            media_id = ig.publish_reel(video, slot["caption"], cover_url=cover)
        elif slot_name == "story":
            media_id = ig.publish_story(urls[0])
        elif len(urls) > 1:
            media_id = ig.publish_carousel(urls, slot["caption"])
        else:
            media_id = ig.publish_image(urls[0], slot["caption"])
    published_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state_mod.record_publish(st, key, slot, media_id, published_at)
    state_mod.save(st)
    log(f"Published {key} as media {media_id}")
    summary(f"### ✅ Published {key} — {KIND_LABELS[kind]}\n\nMedia id `{media_id}` · {len(urls)} file(s)")


def cmd_run(args) -> int:
    if args.scheduled and not args.date:
        scheduled = _scheduled_day(args.slot)
        if scheduled is None:
            return 0
        args.date = scheduled.isoformat()
    day = date.fromisoformat(args.date) if args.date else _today()
    dry = args.dry_run or env_flag("DRY_RUN")
    st = state_mod.load()

    if args.type:
        kind = args.type
        slot_name = planner.slot_of(kind)
        key = planner.slot_key(day, slot_name)
        if planner.kind_for(day, slot_name) != kind:
            key += f"#{kind}"  # manual extra post: don't collide with the scheduled slot
        with group(f"Build {kind} (manual)"):
            slot = planner.build_slot(kind, day, st)
    else:
        slot_name = args.slot
        resolved = _resolve_scheduled(day, slot_name, st)
        if not resolved:
            return 0
        kind, key, slot = resolved

    if key in st["slots"] and not args.force:
        log(f"{key} was already published ({st['slots'][key]['published_at']}). Use --force to post again.")
        return 0
    _publish(day, slot_name, kind, key, slot, st, dry)
    return 0


# ---------------------------------------------------------------- tick (the scheduler)

def _due(now: datetime, st: dict[str, Any]) -> list[tuple[date, str, str]]:
    """Slots whose time has come (within the max delay window) and that weren't published yet."""
    cfg = settings()["schedule"]
    due = []
    for slot_name in ("story", "post", "reel"):
        for back in (1, 0):
            day = (now - timedelta(days=back)).date()
            at = datetime.combine(day, datetime.min.time(), timezone.utc).replace(hour=cfg[f"{slot_name}_hour_utc"])
            key = planner.slot_key(day, slot_name)
            if at <= now <= at + timedelta(hours=cfg["max_delay_hours"]) and planner.kind_for(day, slot_name) \
                    and key not in st["slots"] and key not in st.get("dry_done", {}):
                due.append((at, day, slot_name))
    return [(day, slot_name, planner.slot_key(day, slot_name)) for _, day, slot_name in sorted(due)]


def cmd_tick(args) -> int:
    """Runs every few minutes: publishes whatever is due, retries failures with back-off."""
    cfg = settings()["schedule"]
    now = datetime.now(timezone.utc)
    st = state_mod.load()
    fails = st.setdefault("failures", {})
    ready = []
    for day, slot_name, key in _due(now, st):
        f = fails.get(key)
        if f and f["count"] >= cfg["max_attempts"]:
            continue
        if f and now - datetime.fromisoformat(f["last"]) < timedelta(minutes=cfg["retry_minutes"]):
            continue
        ready.append((day, slot_name, key))
    if args.list:
        for _, slot_name, key in ready:
            print(f"{slot_name} {key}")
        return 0
    if not ready:
        log(f"{now:%Y-%m-%d %H:%M} UTC — nothing due")
        return 0
    dry = env_flag("DRY_RUN")
    final_failure = False
    for day, slot_name, key in ready:
        log(f"Due: {key}")
        try:
            resolved = _resolve_scheduled(day, slot_name, st)
            if resolved:
                kind, key, slot = resolved
                _publish(day, slot_name, kind, key, slot, st, dry)
            if dry or not resolved:
                st.setdefault("dry_done", {})[key] = now.isoformat(timespec="seconds")
            fails.pop(key, None)
        except Exception as exc:  # isolate slots: one failure must not block the others
            f = fails.setdefault(key, {"count": 0})
            f["count"] += 1
            f["last"] = now.isoformat(timespec="seconds")
            f["error"] = str(exc)[:300]
            last = f["count"] >= cfg["max_attempts"]
            final_failure |= last
            msg = f"{key} failed (attempt {f['count']}/{cfg['max_attempts']}): {exc}"
            if last:
                error(msg + " — giving up; run it manually from Actions when the cause is fixed.")
            else:
                warn(msg + f" — retrying in {cfg['retry_minutes']} min")
        state_mod.save(st)
    # keep the bookkeeping small
    cutoff = (now - timedelta(days=3)).isoformat()
    st["dry_done"] = {k: v for k, v in st.get("dry_done", {}).items() if v >= cutoff}
    st["failures"] = {k: v for k, v in fails.items() if v.get("last", "") >= cutoff}
    state_mod.save(st)
    return 1 if final_failure else 0


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
        for k, ps in rendered.items():
            silent = next((p.parent / "reel_silent.mp4" for p in ps if p.suffix == ".mp4"), None)
            if silent and silent.exists():
                files[f"preview/{week}/{_safe(k)}/{silent.name}"] = silent
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
            url = (lambda name: f"{base}/{_safe(key)}/{name}" if base else f"{_safe(key)}/{name}")
            if slot["slot"] == "reel":
                lines.append(f'<a href="{url("reel.mp4")}"><img src="{url("cover.jpg")}" width="{width}"></a>')
                lines.append("")
                lines.append(f'▶️ [Reel with music]({url("reel.mp4")}) · 🔇 [Silent version for a trending sound]'
                             f'({url("reel_silent.mp4")})')
            else:
                for p in rendered[key]:
                    lines.append(f'<img src="{url(p.name)}" width="{width}">')
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
    # Reels: keep only the cover in samples/ (videos would bloat the repo on every regeneration)
    for tmp in [*SAMPLES_DIR.rglob("caption.txt"), *SAMPLES_DIR.rglob("*.mp4")]:
        tmp.unlink()
    log(f"Samples written to {SAMPLES_DIR.relative_to(ROOT)}/")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mad", description="MyAnimeDex Instagram automation")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="render and publish today's scheduled post or story")
    r.add_argument("--slot", choices=["post", "story", "reel"], required=True)
    r.add_argument("--date", help="UTC date to act as (YYYY-MM-DD), default today")
    r.add_argument("--type", choices=list(planner.BUILDERS), help="ignore the schedule and build this type now")
    r.add_argument("--dry-run", action="store_true", help="render only, never upload or publish")
    r.add_argument("--force", action="store_true", help="publish even if this slot was already published")
    r.add_argument("--scheduled", action="store_true",
                   help="cron run: resolve the slot's day from the schedule and skip if far too late")

    for name in ("plan", "preview", "samples"):
        s = sub.add_parser(name)
        s.add_argument("--week", help="ISO week, e.g. 2026-W45")
        s.add_argument("--next", action="store_true", help="the week starting tomorrow (use on Sundays)")
        if name != "samples":
            s.add_argument("--force", action="store_true", help="rebuild the plan even if it exists")
        if name == "preview":
            s.add_argument("--pages", action="store_true", help="upload preview images to GitHub Pages")

    sub.add_parser("check", help="verify IG_USER_ID / ACCESS_TOKEN and permissions")
    tk = sub.add_parser("tick", help="publish every slot that is due now (run by cron every few minutes)")
    tk.add_argument("--list", action="store_true", help="only print the due slots")

    args = p.parse_args(argv)
    handler = {"run": cmd_run, "plan": cmd_plan, "preview": cmd_preview, "check": cmd_check,
               "samples": cmd_samples, "tick": cmd_tick}[args.cmd]
    try:
        return handler(args)
    except MadError as exc:
        error(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
