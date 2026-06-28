"""Application version resolution.

The version is determined automatically, in this order:

1. `git describe --tags --always --dirty` run in the project directory.
   This changes on every commit (e.g. "v1.2.0-5-g3a4f1c"), so the version
   updates by itself each time you push — no manual edits needed.
2. If git is unavailable (typical for a built .exe), read `version.txt`
   from the project root. The CI/CD pipeline writes this file at build time.
3. If neither is available, fall back to "0.0.0-dev".

Usage:
    from core.version import get_version
    print(get_version())
"""
import os
import subprocess

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FALLBACK = "0.0.0-dev"
_cached = None


def _from_git():
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=_BASE_DIR,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if out.returncode == 0:
            tag = out.stdout.strip()
            if tag:
                return tag
    except Exception:
        pass
    return None


def _from_file():
    path = os.path.join(_BASE_DIR, "version.txt")
    try:
        with open(path, encoding="utf-8") as f:
            val = f.read().strip()
            if val:
                return val
    except Exception:
        pass
    return None


def get_version(refresh: bool = False) -> str:
    """Return the resolved version string. Result is cached after first call;
    pass refresh=True to recompute."""
    global _cached
    if _cached is not None and not refresh:
        return _cached
    _cached = _from_git() or _from_file() or _FALLBACK
    return _cached