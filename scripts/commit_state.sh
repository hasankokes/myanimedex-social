#!/usr/bin/env bash
# Commit state/ and plans/ back to the default branch (runs even after a failed step,
# so a successful publish is always recorded and never repeated).
set -euo pipefail
git config user.name "myanimedex-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add state plans
if git diff --cached --quiet; then
  echo "State unchanged"
  exit 0
fi
git commit -m "${1:-chore: update state}"
for attempt in 1 2 3 4 5; do
  if git pull --rebase --quiet && git push --quiet; then
    echo "State committed"
    exit 0
  fi
  echo "Push failed (attempt $attempt), retrying..."
  sleep $((attempt * 5))
done
echo "::error::Could not push state/plans. If something was published, update state/posted_state.json by hand to avoid a duplicate post."
exit 1
