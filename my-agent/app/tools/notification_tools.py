"""
ApplyPilot — Notification tools.

Notifies the user of key events via console output.
Designed to be extended with OS desktop notifications (plyer / win10toast).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from app.utils.logging import get_logger

logger = get_logger(__name__)

_EVENT_ICONS = {
    "high_match_job": "🎯",
    "application_ready": "📋",
    "authentication_required": "🔐",
    "captcha_detected": "🤖",
    "application_failed": "❌",
    "interview_detected": "🎤",
    "follow_up_recommended": "📧",
    "quota_warning": "🟠",
    "quota_exhausted": "⛔",
    "safety_policy_triggered": "🚫",
    "application_submitted": "✅",
    "kill_switch": "🛑",
}


def notify(event: str, message: str) -> None:
    """
    Print a prominent notification to stdout.
    event: one of the keys in _EVENT_ICONS (or any string).
    """
    icon = _EVENT_ICONS.get(event, "ℹ️")
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    banner = f"\n{'─'*60}\n{icon}  [{ts}] {message}\n{'─'*60}\n"
    print(banner, flush=True)
    logger.info("NOTIFICATION [%s]: %s", event, message)
