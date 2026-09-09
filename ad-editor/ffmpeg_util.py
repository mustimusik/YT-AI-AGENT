"""
ffmpeg_util.py — resolves a full-featured ffmpeg binary (needs libass +
freetype for render.py's subtitle/drawtext usage).

Why this exists: on some machines (confirmed on the dev machine this was
hardened on), Homebrew's default `ffmpeg` formula is a minimal build without
libass/freetype (no `subtitles`, `ass`, or `drawtext` filters). Homebrew also
ships a `ffmpeg-full` formula (keg-only) with everything enabled. This module
finds a working binary without requiring the user to change their PATH.

Override with the FFMPEG_BIN env var if your setup differs.
"""
import os
import shutil
import subprocess
from functools import lru_cache

_CANDIDATE_PATHS = [
    os.environ.get("FFMPEG_BIN"),
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
    shutil.which("ffmpeg"),
    "ffmpeg",
]

_REQUIRED_FILTERS = ("subtitles", "drawtext")


def _supports_required_filters(binary: str) -> bool:
    try:
        result = subprocess.run(
            [binary, "-filters"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return all(f" {name} " in result.stdout for name in _REQUIRED_FILTERS)


@lru_cache(maxsize=1)
def resolve_ffmpeg() -> str:
    """Return the path to an ffmpeg binary that has libass + freetype support."""
    checked = []
    for candidate in _CANDIDATE_PATHS:
        if not candidate:
            continue
        if candidate not in checked and (candidate == "ffmpeg" or os.path.exists(candidate)):
            checked.append(candidate)
            if _supports_required_filters(candidate):
                return candidate

    raise RuntimeError(
        "No ffmpeg binary with libass+freetype support found (need the "
        "`subtitles` and `drawtext` filters for captions/slides).\n"
        "Checked: " + ", ".join(checked) + "\n"
        "Fix: `brew install ffmpeg-full` (keg-only, won't disturb your "
        "regular `ffmpeg`), or set FFMPEG_BIN to a full-featured ffmpeg path."
    )
