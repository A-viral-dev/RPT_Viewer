"""Shared helpers for the parser test-suite.

The tests live in ``tests/`` while the application modules live at the project
root, so the root is added to ``sys.path`` before anything is imported.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import PRESETS  # noqa: E402  (needs the path fix above)


def preset_options(preset: str, **overrides) -> dict:
    """Return the options dict ``parse_file`` expects for a named preset.

    ``preset_name`` is what routes the parser; without it ``parse_file``
    silently falls back to the generic fixed-width guess.
    """
    opts = {**PRESETS[preset], "enabled": True, "preset_name": preset}
    opts.update(overrides)
    return opts


def fixture_path(name: str) -> Path:
    return ROOT / name


def read_text(name: str) -> str:
    return fixture_path(name).read_text(encoding="utf-8", errors="replace")
