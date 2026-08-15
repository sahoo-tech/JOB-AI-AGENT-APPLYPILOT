"""
ApplyPilot — Per-application approval gate.

Submission is blocked until the user explicitly calls grant_approval(app_id).
Approval tokens are tied to a specific application ID; a previous approval
cannot authorise a different application.
"""
from __future__ import annotations

import threading
from typing import Optional

from app.utils.logging import get_logger

logger = get_logger(__name__)


class ApprovalGate:
    """
    Tracks which applications the user has explicitly approved for submission.
    Thread-safe via a simple lock.
    """

    def __init__(self) -> None:
        self._approved: set[str] = set()
        self._lock = threading.Lock()

    def grant_approval(self, app_id: str) -> None:
        """
        Called when the user explicitly approves submission of a specific application.
        """
        with self._lock:
            self._approved.add(app_id)
        logger.info("✅ Submission approved by user for application %s", app_id)

    def is_approved(self, app_id: str) -> bool:
        with self._lock:
            return app_id in self._approved

    def require_approval(self, app_id: str) -> None:
        """
        Raise PermissionError if the user has not approved this specific application.
        The LLM cannot call grant_approval on its own — it can only request user action.
        """
        if not self.is_approved(app_id):
            raise PermissionError(
                f"Submission of application {app_id} requires explicit user approval. "
                "Please review the application and type 'submit' or 'approve' to proceed."
            )

    def consume_approval(self, app_id: str) -> None:
        """Consume the approval token after submission (single-use)."""
        with self._lock:
            self._approved.discard(app_id)
        logger.info("Approval token consumed for application %s", app_id)


# Singleton
approval_gate = ApprovalGate()
