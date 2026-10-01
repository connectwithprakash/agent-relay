"""Helpers shared by the PTY and tmux worker sessions."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

MIN_COLS, MAX_COLS = 20, 500
MIN_ROWS, MAX_ROWS = 5, 200


def _validate_window_size(cols: object, rows: object) -> tuple[int, int]:
    """Enforce the control-stream resize bounds (integers only, booleans rejected)."""
    for value, low, high in ((cols, MIN_COLS, MAX_COLS), (rows, MIN_ROWS, MAX_ROWS)):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"Terminal size must be integers within {low}..{high}")
    return cols, rows  # type: ignore[return-value]


def _resolve_claude_launch(workdir: str | None, executable: str | None) -> str:
    """Return the Claude Code executable after the shared fail-closed local checks."""
    claude = executable or shutil.which("claude")
    if not claude or not Path(claude).is_absolute() or not os.access(claude, os.X_OK):
        raise RuntimeError("Claude Code executable 'claude' is not installed")
    if not workdir or not Path(workdir).is_absolute() or not Path(workdir).is_dir():
        raise ValueError("Claude Code requires an existing absolute local workdir")
    return claude
