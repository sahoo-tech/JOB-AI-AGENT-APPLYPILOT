"""
ApplyPilot — Safety policy engine.

Checks proposed actions against the prohibited list defined in Agent.md §53.
Returns ALLOW / WARN / BLOCK — the LLM cannot override BLOCK decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from app.utils.logging import get_logger

logger = get_logger(__name__)


class PolicyResult(Enum):
    ALLOW = auto()
    WARN = auto()
    BLOCK = auto()


@dataclass
class PolicyDecision:
    result: PolicyResult
    reason: str


# Actions that are unconditionally prohibited
_PROHIBITED_ACTIONS = {
    "BYPASS_CAPTCHA",
    "BYPASS_ANTI_BOT",
    "ADD_FAKE_QUALIFICATION",
    "ADD_FAKE_EXPERIENCE",
    "ADD_FAKE_EDUCATION",
    "ADD_FAKE_CERTIFICATION",
    "ADD_FAKE_REFERENCE",
    "ADD_FAKE_EMPLOYMENT",
    "STEAL_CREDENTIAL",
    "EXTRACT_PASSWORD",
    "ACCESS_UNAUTHORIZED_ACCOUNT",
    "MASS_APPLICATION_SPAM",
    "ROTATE_API_KEY",
    "CIRCUMVENT_QUOTA",
    "HIDE_BROWSER_CONTROL",
    "FINANCIAL_TRANSACTION",
    "SUBMIT_WITHOUT_APPROVAL",        # enforced here AND in ApprovalGate
    "REPLACE_CV_WITHOUT_USER_ACTION", # enforced here AND in cv upload gate
    "MODIFY_CV",
    "GENERATE_REPLACEMENT_CV",
    "LOG_CREDENTIALS",
    "SEND_CREDENTIALS_TO_MODEL",
}


class SafetyPolicy:
    """
    Evaluate whether an agent action is permitted.
    This check runs at the tool layer — the LLM cannot override it.
    """

    def check(self, action: str, context: dict | None = None) -> PolicyDecision:
        action_upper = action.upper().replace(" ", "_")

        if action_upper in _PROHIBITED_ACTIONS:
            reason = f"Action '{action}' is prohibited by ApplyPilot safety policy."
            logger.error("🚫 SAFETY BLOCK: %s | context=%s", action, context)
            return PolicyDecision(result=PolicyResult.BLOCK, reason=reason)

        # Warn on potentially sensitive actions
        sensitive_warn = {
            "SEND_MESSAGE_TO_RECRUITER",
            "UPLOAD_ALTERNATE_FILE",
            "ACCESS_BROWSER_STORAGE",
        }
        if action_upper in sensitive_warn:
            reason = f"Action '{action}' requires extra caution."
            logger.warning("⚠️  SAFETY WARN: %s | context=%s", action, context)
            return PolicyDecision(result=PolicyResult.WARN, reason=reason)

        return PolicyDecision(result=PolicyResult.ALLOW, reason="")

    def require_allow(self, action: str, context: dict | None = None) -> None:
        """Raise RuntimeError if action is not ALLOW."""
        decision = self.check(action, context)
        if decision.result == PolicyResult.BLOCK:
            raise RuntimeError(decision.reason)


# Singleton
safety_policy = SafetyPolicy()
