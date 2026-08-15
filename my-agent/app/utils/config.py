"""
ApplyPilot — Centralised configuration.
All settings are loaded from environment variables / .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env from the project root (my-agent/)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)


@dataclass
class Settings:
    # ── Gemini ────────────────────────────────────────────────────────────────
    gemini_api_key: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""))

    def __post_init__(self) -> None:
        if self.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.gemini_api_key
    gemini_model: str = field(default_factory=lambda: os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"))
    gemini_fallback_model: str = field(
        default_factory=lambda: os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")
    )

    # ── Default CV path ───────────────────────────────────────────────────────
    default_cv_path: str = field(
        default_factory=lambda: os.environ.get("DEFAULT_CV_PATH", "")
    )

    # ── Internal quota ceilings (configurable, not Google's official limits) ─
    internal_max_rpm: int = field(default_factory=lambda: int(os.environ.get("INTERNAL_MAX_RPM", "8")))
    internal_max_tpm: int = field(default_factory=lambda: int(os.environ.get("INTERNAL_MAX_TPM", "150000")))
    internal_max_rpd: int = field(default_factory=lambda: int(os.environ.get("INTERNAL_MAX_RPD", "200")))

    # ── Retry / loop protection ───────────────────────────────────────────────
    max_retries: int = field(default_factory=lambda: int(os.environ.get("MAX_RETRIES", "3")))
    max_agent_steps: int = field(default_factory=lambda: int(os.environ.get("MAX_AGENT_STEPS", "100")))
    max_identical_actions: int = field(
        default_factory=lambda: int(os.environ.get("MAX_IDENTICAL_ACTIONS", "3"))
    )
    max_unchanged_screen_steps: int = field(
        default_factory=lambda: int(os.environ.get("MAX_UNCHANGED_SCREEN_STEPS", "5"))
    )
    max_applications_per_run: int = field(
        default_factory=lambda: int(os.environ.get("MAX_APPLICATIONS_PER_RUN", "5"))
    )

    # ── Application behaviour ─────────────────────────────────────────────────
    follow_up_days: int = field(default_factory=lambda: int(os.environ.get("FOLLOW_UP_DAYS", "7")))

    # ── Storage paths ─────────────────────────────────────────────────────────
    data_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / "data")
    _db_path_override: Optional[Path] = None

    @property
    def db_path(self) -> Path:
        if self._db_path_override:
            return self._db_path_override
        return self.data_dir / "applypilot.db"

    @db_path.setter
    def db_path(self, value: Path) -> None:
        self._db_path_override = value

    @property
    def cv_master_dir(self) -> Path:
        return self.data_dir / "cv" / "master"

    @property
    def browser_profiles_dir(self) -> Path:
        return self.data_dir / "browser_profiles"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        """Create all required data directories."""
        for d in [
            self.data_dir,
            self.cv_master_dir,
            self.browser_profiles_dir,
            self.logs_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


# Singleton
settings = Settings()
settings.ensure_dirs()
