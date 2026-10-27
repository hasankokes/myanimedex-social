"""Settings, paths and logging helpers shared by every module."""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTENT_DIR = ROOT / "content"
ASSETS_DIR = ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
STATE_FILE = ROOT / "state" / "posted_state.json"
PLANS_DIR = ROOT / "plans"
OUT_DIR = ROOT / "out"
SAMPLES_DIR = ROOT / "samples"


class MadError(RuntimeError):
    """An expected failure with a message that is safe and useful to print in CI logs."""


@lru_cache(maxsize=1)
def settings() -> dict[str, Any]:
    with open(ROOT / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_yaml(name: str) -> dict[str, Any]:
    path = CONTENT_DIR / name
    if not path.exists():
        raise MadError(f"Missing content file: {path.relative_to(ROOT)}")
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise MadError(f"{path.relative_to(ROOT)} must contain a mapping at the top level")
    return data


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


_IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def log(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print(f"::warning::{msg}" if _IN_ACTIONS else f"WARNING: {msg}", flush=True)


def error(msg: str) -> None:
    print(f"::error::{msg}" if _IN_ACTIONS else f"ERROR: {msg}", file=sys.stderr, flush=True)


def group(title: str):
    """Collapsible log section in GitHub Actions; plain header locally."""

    class _Group:
        def __enter__(self):
            print(f"::group::{title}" if _IN_ACTIONS else f"\n== {title} ==", flush=True)

        def __exit__(self, *exc):
            if _IN_ACTIONS:
                print("::endgroup::", flush=True)
            return False

    return _Group()


def summary(markdown: str) -> None:
    """Append to the GitHub Actions job summary when available."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
