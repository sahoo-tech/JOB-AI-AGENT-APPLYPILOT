"""
ApplyPilot — Quota limiter with conservation mode and exponential backoff.

Quota tiers (based on internal configurable ceilings, NOT official Google limits):
  < 80%  → Normal operation
  ≥ 80%  → Warning logged
  ≥ 90%  → Conservation mode (reduces unnecessary calls)
  ≥ 100% → Agent paused — raises QuotaExceededError

Handles API errors with exponential backoff: 1s → 2s → 4s → 8s (max_retries).
"""
from __future__ import annotations

import time
from enum import Enum, auto

from app.quota.token_tracker import tracker
from app.quota.usage_logger import log_api_usage
from app.utils.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class QuotaMode(Enum):
    NORMAL = auto()
    WARNING = auto()       # ≥ 80 %
    CONSERVATION = auto()  # ≥ 90 %
    EXCEEDED = auto()      # ≥ 100 %


class QuotaExceededError(Exception):
    """Raised when all internal quota ceilings are hit."""


class QuotaLimiter:
    """
    Central quota guard.  Call `check()` before any Gemini API request.
    Call `record(...)` after a successful request.
    """

    def check(self) -> QuotaMode:
        """
        Return current QuotaMode.
        Raise QuotaExceededError if any ceiling is at or above 100 %.
        Log a warning at ≥ 80 %, enter conservation mode at ≥ 90 %.
        """
        rpm_pct = tracker.rpm / max(settings.internal_max_rpm, 1)
        tpm_pct = tracker.tpm / max(settings.internal_max_tpm, 1)
        rpd_pct = tracker.rpd / max(settings.internal_max_rpd, 1)
        worst = max(rpm_pct, tpm_pct, rpd_pct)

        if worst >= 1.0:
            logger.error(
                "⛔ Quota ceiling reached — RPM %.0f%% TPM %.0f%% RPD %.0f%%",
                rpm_pct * 100, tpm_pct * 100, rpd_pct * 100,
            )
            raise QuotaExceededError(
                f"Internal quota ceiling reached (RPM {rpm_pct:.0%} / "
                f"TPM {tpm_pct:.0%} / RPD {rpd_pct:.0%}). Agent paused."
            )

        if worst >= 0.90:
            logger.warning(
                "🟡 Conservation mode — RPM %.0f%% TPM %.0f%% RPD %.0f%%",
                rpm_pct * 100, tpm_pct * 100, rpd_pct * 100,
            )
            return QuotaMode.CONSERVATION

        if worst >= 0.80:
            logger.warning(
                "🟠 Quota warning — RPM %.0f%% TPM %.0f%% RPD %.0f%%",
                rpm_pct * 100, tpm_pct * 100, rpd_pct * 100,
            )
            return QuotaMode.WARNING

        return QuotaMode.NORMAL

    def record(
        self,
        *,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        agent: str = "",
        action: str = "",
    ) -> None:
        """Record a completed API call in the tracker and usage log."""
        tracker.record_request(input_tokens=input_tokens, output_tokens=output_tokens)
        log_api_usage(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            agent=agent,
            action=action,
        )

    def with_retry(self, fn, *, agent: str = "", action: str = ""):
        """
        Call fn() with exponential backoff for retryable errors (429, 5xx).
        fn must be a zero-argument callable that returns the API response.
        Raises after max_retries attempts.
        """
        delays = [1, 2, 4, 8]
        last_exc: Exception | None = None
        for attempt, delay in enumerate(delays[: settings.max_retries + 1], 1):
            try:
                self.check()
                return fn()
            except QuotaExceededError:
                raise
            except Exception as exc:
                msg = str(exc)
                retryable = any(
                    code in msg for code in ("429", "RESOURCE_EXHAUSTED", "503", "500", "timeout")
                )
                if not retryable:
                    raise
                last_exc = exc
                if attempt <= settings.max_retries:
                    logger.warning(
                        "Attempt %d/%d failed (%s). Retrying in %ds.",
                        attempt, settings.max_retries, exc, delay,
                    )
                    time.sleep(delay)
        raise RuntimeError(f"All {settings.max_retries} retries exhausted") from last_exc


# Singleton
limiter = QuotaLimiter()
