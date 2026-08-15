"""
ApplyPilot — Browser manager.

Manages a single Playwright Chromium instance (headless=False so the user
can see the browser).  Includes:
  - Kill-switch flag (set from main thread; checked before every action)
  - Loop-protection counters (identical actions, unchanged screen)
  - Graceful crash recovery
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Optional

from app.utils.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

# ── Global kill switch ────────────────────────────────────────────────────────
_kill_switch = threading.Event()


def trigger_kill_switch() -> None:
    """Immediately stop all browser and agent actions (CTRL+SHIFT+X equivalent)."""
    _kill_switch.set()
    logger.critical("🛑 KILL SWITCH TRIGGERED — stopping all agent actions")


def reset_kill_switch() -> None:
    _kill_switch.clear()


def is_killed() -> bool:
    return _kill_switch.is_set()


def check_kill_switch() -> None:
    """Raise RuntimeError if kill switch has been triggered."""
    if _kill_switch.is_set():
        raise RuntimeError("Agent stopped by kill switch.")


# ── Browser Manager ───────────────────────────────────────────────────────────

class BrowserManager:
    """
    Async-capable Playwright browser manager.
    Uses a persistent browser profile per platform for session persistence.
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._current_platform: Optional[str] = None
        # Loop protection
        self._action_history: list[str] = []
        self._unchanged_screen_count: int = 0
        self._last_screenshot_hash: Optional[str] = None

    async def launch(self, platform: str = "default") -> None:
        check_kill_switch()
        if self._browser is not None:
            return  # already running

        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        profile_dir = settings.browser_profiles_dir / platform
        profile_dir.mkdir(parents=True, exist_ok=True)

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
        )
        self._current_platform = platform
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        logger.info("Browser launched for platform '%s'", platform)

    async def navigate(self, url: str) -> None:
        check_kill_switch()
        await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self._action_history.append(f"navigate:{url}")
        self._check_action_loop()

    async def get_page_text(self) -> str:
        check_kill_switch()
        return await self._page.inner_text("body")

    async def get_page_html(self) -> str:
        check_kill_switch()
        return await self._page.content()

    async def fill_field(self, selector: str, value: str) -> bool:
        """Fill a form field. Returns True on success."""
        check_kill_switch()
        try:
            await self._page.fill(selector, value, timeout=5000)
            self._action_history.append(f"fill:{selector}")
            self._check_action_loop()
            return True
        except Exception as exc:
            logger.warning("fill_field failed for '%s': %s", selector, exc)
            return False

    async def click(self, selector: str) -> bool:
        check_kill_switch()
        try:
            await self._page.click(selector, timeout=5000)
            self._action_history.append(f"click:{selector}")
            self._check_action_loop()
            return True
        except Exception as exc:
            logger.warning("click failed for '%s': %s", selector, exc)
            return False

    async def upload_file(self, selector: str, file_path: str) -> bool:
        """Upload a file. The path must be the approved master CV."""
        check_kill_switch()
        try:
            await self._page.set_input_files(selector, file_path)
            self._action_history.append(f"upload:{selector}")
            return True
        except Exception as exc:
            logger.warning("upload_file failed for '%s': %s", selector, exc)
            return False

    async def screenshot(self) -> bytes:
        check_kill_switch()
        img = await self._page.screenshot(type="png")
        # Track unchanged screen for loop protection
        import hashlib
        img_hash = hashlib.md5(img).hexdigest()
        if img_hash == self._last_screenshot_hash:
            self._unchanged_screen_count += 1
            if self._unchanged_screen_count >= settings.max_unchanged_screen_steps:
                raise RuntimeError(
                    f"Screen unchanged for {self._unchanged_screen_count} consecutive steps. "
                    "Possible agent loop detected — stopping."
                )
        else:
            self._unchanged_screen_count = 0
            self._last_screenshot_hash = img_hash
        return img

    async def close(self) -> None:
        try:
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            logger.warning("Browser close error: %s", exc)
        finally:
            self._browser = None
            self._context = None
            self._page = None
            self._playwright = None

    @property
    def page(self):
        return self._page

    def _check_action_loop(self) -> None:
        """Detect repeated identical actions."""
        recent = self._action_history[-settings.max_identical_actions:]
        if (
            len(recent) == settings.max_identical_actions
            and len(set(recent)) == 1
        ):
            raise RuntimeError(
                f"Agent loop detected: action '{recent[0]}' repeated "
                f"{settings.max_identical_actions} times consecutively."
            )

    def reset_loop_counters(self) -> None:
        self._action_history.clear()
        self._unchanged_screen_count = 0
        self._last_screenshot_hash = None


# Module-level singleton
browser_manager = BrowserManager()
