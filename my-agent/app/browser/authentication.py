"""
ApplyPilot — Platform authentication manager.

The agent NEVER touches passwords, 2FA codes, or CAPTCHA solutions.
When authentication is required the agent pauses and waits for the user
to complete login manually in the visible browser window.

Credentials are never passed to the Gemini model — only status messages.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from app.utils.logging import get_logger, write_audit
from app.tools.notification_tools import notify

logger = get_logger(__name__)

# Common login-page indicators
_LOGIN_INDICATORS = [
    "sign in",
    "log in",
    "login",
    "signin",
    "authenticate",
    "enter your password",
    "email and password",
    "forgot password",
]

_CAPTCHA_INDICATORS = [
    "captcha",
    "recaptcha",
    "i'm not a robot",
    "verify you are human",
    "cloudflare",
    "challenge",
]


class AuthenticationManager:
    """
    Detects authentication requirements and pauses the agent.
    Never handles credentials — the user must authenticate manually.
    """

    async def check_and_handle(self, page_text: str, platform: str) -> bool:
        """
        Returns True if the page requires authentication (agent should pause).
        Returns False if the page appears authenticated.
        """
        text_lower = page_text.lower()

        # CAPTCHA check
        if any(ind in text_lower for ind in _CAPTCHA_INDICATORS):
            await self._handle_captcha(platform)
            return True

        # Login page check
        if any(ind in text_lower for ind in _LOGIN_INDICATORS):
            await self._handle_login(platform)
            return True

        return False

    async def _handle_login(self, platform: str) -> None:
        msg = (
            f"\n{'='*60}\n"
            f"🔐 AUTHENTICATION REQUIRED\n"
            f"Platform: {platform}\n\n"
            f"Please log in manually in the browser window.\n"
            f"• Enter your username/email and password\n"
            f"• Complete any 2FA prompts\n"
            f"The agent will wait until you are logged in.\n"
            f"Type 'continue' in the chat when done.\n"
            f"{'='*60}\n"
        )
        logger.info(msg)
        notify("authentication_required", f"Please log in to {platform} manually")
        write_audit(
            agent="authentication",
            action="LOGIN_REQUIRED",
            company=platform,
            approval_required=True,
            approval_status="WAITING",
        )
        # The agent pauses here; the ADK runner will wait for the user's next message

    async def _handle_captcha(self, platform: str) -> None:
        msg = (
            f"\n{'='*60}\n"
            f"🤖 CAPTCHA DETECTED\n"
            f"Platform: {platform}\n\n"
            f"Agent paused. Please complete the CAPTCHA manually.\n"
            f"Type 'continue' when done.\n"
            f"{'='*60}\n"
        )
        logger.info(msg)
        notify("captcha_detected", f"CAPTCHA detected on {platform} — please solve manually")
        write_audit(
            agent="authentication",
            action="CAPTCHA_DETECTED",
            company=platform,
            approval_required=True,
            approval_status="WAITING",
        )

    def authenticated_session_status(self) -> str:
        """Return a safe status string to pass to the model (no credentials)."""
        return "Authenticated session available."


# Singleton
auth_manager = AuthenticationManager()
