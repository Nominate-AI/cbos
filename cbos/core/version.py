"""Version and build information for CBOS"""

import subprocess
from datetime import datetime
from functools import lru_cache
from importlib.metadata import version as pkg_version


@lru_cache(maxsize=1)
def get_version() -> str:
    """Get the package version"""
    try:
        return pkg_version("cbos")
    except Exception:
        return "0.0.0"


@lru_cache(maxsize=1)
def get_git_hash() -> str:
    """Get the short git commit hash"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def get_build_time() -> str:
    """Get current timestamp formatted for display"""
    return datetime.now().strftime("%b %d, %Y %H:%M:%S")


def get_version_string() -> str:
    """
    Get full version string for display.

    Example: v0.4.0 (71dbda2) · Jan 03, 2026 13:56:54
    """
    ver = get_version()
    git_hash = get_git_hash()
    timestamp = get_build_time()

    return f"v{ver} ({git_hash}) · {timestamp}"
