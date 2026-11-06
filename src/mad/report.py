"""Weekly performance report for the Sunday preview issue.

Followers come from the account (instagram_basic); per-post numbers need the
instagram_manage_insights permission — without it the report says so and shows followers only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import state as state_mod
from .config import log, warn
from .instagram import GraphError, Instagram

METRICS = {
    "reel": ["views", "reach", "saved", "shares", "likes", "comments", "ig_reels_avg_watch_time"],
    "post": ["views", "reach", "saved", "shares", "likes", "comments", "profile_visits", "follows"],
    "story": ["views", "reach", "replies", "shares"],
}
FALLBACK = ["reach", "likes", "comments", "saved", "shares"]
FAMILY = {
    "reel_quiz": "Quiz reel", "reel_recs": "Recs reel", "reel_tierlist": "Tier list reel",
    "reel_top5": "Top 5 reel", "reel_weekend": "Weekend reel", "reel_app_demo": "App demo reel",
    "reel_teaser": "Teaser reel", "top5": "Top 5 post", "airing_week": "Airing post", "feature": "Feature post",
}


def _value(item: dict[str, Any]) -> Any:
    if "total_value" in item:
        return (item.get("total_value") or {}).get("value")
    vals = item.get("values") or [{}]
    return vals[0].get("value")


def _insights(ig: Instagram, media_id: str, slot: str) -> dict[str, Any]:
    for metrics in (METRICS[slot], FALLBACK):
        try:
            data = ig._call("GET", f"{media_id}/insights", {"metric": ",".join(metrics)}, retry=False)
            return {d["name"]: _value(d) for d in data.get("data", [])}
        except GraphError as exc:
            if "not enough viewers" in str(exc).lower():
                return {}  # Instagram hides numbers for media seen by very few accounts
            if exc.code in (10, 200, 190):
                raise
            continue
    return {}


def build_report(days: int = 7) -> str:
    ig = Instagram()
    now = datetime.now(timezone.utc)
    st = state_mod.load()
    acct = ig._call("GET", ig.ig_user_id, {"fields": "followers_count,media_count"})
    followers = acct.get("followers_count")
    history = st.setdefault("followers", {})
    history[now.date().isoformat()] = followers
    st["followers"] = dict(sorted(history.items())[-60:])
    state_mod.save(st)
    week_ago = (now - timedelta(days=days)).date().isoformat()
    older = [v for d, v in sorted(history.items()) if d <= week_ago]
    delta = f" ({followers - older[-1]:+d} this week)" if older and followers is not None else ""
    lines = ["## 📈 Last week's performance", "",
             f"**Followers:** {followers}{delta} · **Posts on the account:** {acct.get('media_count')}", ""]

    cutoff = (now - timedelta(days=days)).isoformat()
    recent = [(k, v) for k, v in sorted(st["slots"].items())
              if v.get("published_at", "") >= cutoff and str(v.get("media_id", "")).isdigit()]
    rows, blocked = [], None
    for key, rec in recent:
        slot = key.split(":")[1].split("#")[0]
        try:
            ins = _insights(ig, rec["media_id"], slot if slot in METRICS else "post")
        except GraphError as exc:
            blocked = str(exc)
            break
        rows.append((key, rec["kind"], ins))
    if blocked:
        warn(f"Insights unavailable: {blocked}")
        lines += ["> Per-post numbers need the **instagram_manage_insights** permission on the token "
                  "(README → Token). Followers are tracked anyway.", ""]
        return "\n".join(lines)
    if not rows:
        lines.append("_No posts in the last 7 days._")
        return "\n".join(lines)

    lines += ["| Date | Content | Views | Reach | Saves | Shares | Likes | Comments | Avg watch |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    fam: dict[str, list[int]] = {}
    for key, kind, ins in rows:
        avg = ins.get("ig_reels_avg_watch_time")
        avg_s = f"{avg / 1000:.1f}s" if isinstance(avg, (int, float)) else "—"
        views = ins.get("views") or ins.get("reach") or 0
        lines.append(f"| {key[:10]} | {FAMILY.get(kind, kind)} | {ins.get('views', '—')} | {ins.get('reach', '—')} | "
                     f"{ins.get('saved', '—')} | {ins.get('shares', '—')} | {ins.get('likes', '—')} | "
                     f"{ins.get('comments', ins.get('replies', '—'))} | {avg_s} |")
        if not kind.startswith("story"):
            fam.setdefault(FAMILY.get(kind, kind), []).append(int(views or 0))
    if fam:
        best = sorted(((sum(v) / len(v), k) for k, v in fam.items()), reverse=True)
        lines += ["", "**Average views by format:** " + " · ".join(f"{k} {a:.0f}" for a, k in best)]
    log(f"Report: {len(rows)} posts, followers {followers}")
    return "\n".join(lines)
