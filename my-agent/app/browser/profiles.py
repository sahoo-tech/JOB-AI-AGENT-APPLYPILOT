"""
ApplyPilot — Persistent browser profiles per platform.
"""
from __future__ import annotations

from pathlib import Path

from app.utils.config import settings


SUPPORTED_PLATFORMS = ["linkedin", "naukri", "indeed", "greenhouse", "lever"]


def get_profile_dir(platform: str) -> Path:
    """Return (and create) the profile directory for a given platform."""
    d = settings.browser_profiles_dir / platform.lower()
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_profiles() -> list[dict]:
    """Return status of all platform profiles."""
    results = []
    for platform in SUPPORTED_PLATFORMS:
        d = get_profile_dir(platform)
        # A profile is considered 'connected' if Chromium has written session data
        has_session = any(d.iterdir()) if d.exists() else False
        results.append({"platform": platform, "connected": has_session, "path": str(d)})
    return results
