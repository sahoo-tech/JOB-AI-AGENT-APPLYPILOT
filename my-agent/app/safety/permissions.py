"""
ApplyPilot — Per-platform permission registry.

Every platform needs explicit permissions.  SUBMIT_APPLICATION is disabled by
default for all platforms.  The LLM cannot override these at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class Permission(Enum):
    READ_JOBS = auto()
    SEARCH_JOBS = auto()
    READ_APPLICATION = auto()
    FILL_APPLICATION = auto()
    UPLOAD_CV = auto()
    SUBMIT_APPLICATION = auto()   # DISABLED by default — user must grant per-session
    SEND_MESSAGES = auto()
    READ_PROFILE = auto()


@dataclass
class PlatformPermissions:
    platform: str
    allowed: set[Permission] = field(default_factory=set)

    def can(self, perm: Permission) -> bool:
        return perm in self.allowed

    def require(self, perm: Permission) -> None:
        if not self.can(perm):
            raise PermissionError(
                f"Platform '{self.platform}' does not have permission: {perm.name}"
            )


# ── Default platform registry ─────────────────────────────────────────────────
# SUBMIT_APPLICATION is intentionally absent from all defaults.

_DEFAULTS: dict[str, set[Permission]] = {
    "linkedin": {
        Permission.READ_JOBS,
        Permission.SEARCH_JOBS,
        Permission.READ_APPLICATION,
        Permission.FILL_APPLICATION,
        Permission.UPLOAD_CV,
    },
    "naukri": {
        Permission.READ_JOBS,
        Permission.SEARCH_JOBS,
        Permission.READ_APPLICATION,
        Permission.FILL_APPLICATION,
        Permission.UPLOAD_CV,
    },
    "indeed": {
        Permission.READ_JOBS,
        Permission.SEARCH_JOBS,
    },
    "greenhouse": {
        Permission.READ_JOBS,
        Permission.FILL_APPLICATION,
        Permission.UPLOAD_CV,
    },
    "lever": {
        Permission.READ_JOBS,
        Permission.FILL_APPLICATION,
        Permission.UPLOAD_CV,
    },
    "mock": {
        Permission.READ_JOBS,
        Permission.SEARCH_JOBS,
        Permission.READ_APPLICATION,
        Permission.FILL_APPLICATION,
        Permission.UPLOAD_CV,
        Permission.SUBMIT_APPLICATION,  # allowed in mock/test environment
    },
}


class PermissionRegistry:
    def __init__(self) -> None:
        self._registry: dict[str, PlatformPermissions] = {
            name: PlatformPermissions(platform=name, allowed=perms.copy())
            for name, perms in _DEFAULTS.items()
        }

    def get(self, platform: str) -> PlatformPermissions:
        platform = platform.lower()
        if platform not in self._registry:
            # Unknown platform — minimal safe defaults
            self._registry[platform] = PlatformPermissions(
                platform=platform,
                allowed={Permission.READ_JOBS},
            )
        return self._registry[platform]

    def grant_submit(self, platform: str) -> None:
        """Grant SUBMIT_APPLICATION for this session (requires explicit user action)."""
        self.get(platform).allowed.add(Permission.SUBMIT_APPLICATION)

    def revoke_submit(self, platform: str) -> None:
        self.get(platform).allowed.discard(Permission.SUBMIT_APPLICATION)


# Singleton
permissions = PermissionRegistry()
