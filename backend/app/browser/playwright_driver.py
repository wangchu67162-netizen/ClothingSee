"""Playwright driver for the built-in demo mall.

Launch strategy (per project contract):

1. ``chromium.launch(channel="msedge", headless=True)`` — uses the Edge that
   ships with Windows 11, no download required.
2. Fallback to Playwright's bundled Chromium (``playwright install chromium``).
3. If both fail, raise :class:`BrowserUnavailable` with a Chinese message; the
   assistant must report the failure instead of pretending the order succeeded.

Screenshots are written to ``backend/runtime/screenshots/{session}/NN.png``
(outside ``app/`` so uvicorn's reloader never restarts on a screenshot) and are
served to the UI at ``/screenshots/{session}/NN.png``.

Only one browser may run at a time (``asyncio.Semaphore(1)``) so the demo does
not open several Edge windows in parallel. The browser is always closed in
``__aexit__``.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from ..config import settings
from .base import BrowserUnavailable

logger = logging.getLogger("yijian.browser")

try:  # pragma: no cover - import guard only
    from playwright.async_api import async_playwright
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
except Exception as exc:  # pragma: no cover - Playwright is in requirements
    async_playwright = None  # type: ignore[assignment]
    PlaywrightTimeoutError = TimeoutError  # type: ignore[assignment,misc]
    _IMPORT_ERROR: Exception | None = exc
else:
    _IMPORT_ERROR = None

_launch_semaphore = asyncio.Semaphore(1)
_active_browsers: set[Any] = set()

VIEWPORT = {"width": 1280, "height": 900}
DEFAULT_TIMEOUT_MS = 15_000
NAVIGATION_TIMEOUT_MS = 25_000


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]", "", value or "")
    return cleaned or "session"


class PlaywrightDriver:
    """Async context manager owning one browser, context, page and screenshots."""

    def __init__(self, session_id: str, *, headless: bool | None = None) -> None:
        self.session_id = _safe_component(session_id)
        self.headless = settings.browser_headless if headless is None else headless
        self.page: Any = None
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._locked = False

    # ------------------------------------------------------------- lifecycle
    async def __aenter__(self) -> "PlaywrightDriver":
        if async_playwright is None:
            raise BrowserUnavailable(
                "未安装 Playwright，无法启动无头浏览器。请在后端虚拟环境执行 `pip install playwright`。"
            )
        await _launch_semaphore.acquire()
        self._locked = True
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._launch_browser()
            _active_browsers.add(self._browser)
            self._context = await self._browser.new_context(
                viewport=VIEWPORT,
                locale="zh-CN",
                device_scale_factor=1,
            )
            self.page = await self._context.new_page()
            self.page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            self.page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
            return self
        except BrowserUnavailable:
            await self._cleanup()
            raise
        except Exception as exc:  # pragma: no cover - defensive
            await self._cleanup()
            raise BrowserUnavailable(
                f"无法启动无头浏览器：{exc}。请确认已安装 Microsoft Edge，或执行 `playwright install chromium`。"
            ) from exc

    async def _launch_browser(self) -> Any:
        assert self._playwright is not None
        channel = (settings.playwright_channel or "").strip()
        reasons: list[str] = []

        if channel:
            try:
                logger.info("Launching %s via channel=%s", "chromium", channel)
                return await self._playwright.chromium.launch(channel=channel, headless=self.headless)
            except Exception as exc:  # Edge missing / blocked by policy
                reasons.append(f"Edge({channel})：{exc}")
                logger.warning("Edge launch failed, trying bundled Chromium: %s", exc)

        try:
            return await self._playwright.chromium.launch(headless=self.headless)
        except Exception as exc:  # bundled browser missing
            reasons.append(f"内置 Chromium：{exc}")
            detail = "；".join(reasons)
            raise BrowserUnavailable(
                "无法启动无头浏览器（已尝试本机 Edge 与 Playwright 内置 Chromium）。"
                "请安装 Microsoft Edge，或在后端虚拟环境执行 `playwright install chromium`。"
                f"（技术细节：{detail}）"
            ) from exc

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._cleanup()

    async def _cleanup(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            _active_browsers.discard(self._browser)
            self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self.page = None
        if self._locked:
            self._locked = False
            _launch_semaphore.release()

    # ------------------------------------------------------------ screenshots
    async def screenshot(self, name: str) -> str:
        """Capture the viewport to ``runtime/screenshots/{session}/{name}.png``.

        Returns the public URL path, or ``""`` when the capture failed (a
        screenshot failure must never abort the shopping flow).
        """
        if self.page is None:
            return ""
        safe = _safe_component(str(name))
        directory = settings.screenshots_dir / self.session_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{safe}.png"
        try:
            await self.page.screenshot(path=str(path), full_page=False, animations="disabled")
        except Exception as exc:  # page navigating / closing
            logger.warning("Screenshot %s failed: %s", name, exc)
            return ""
        return f"/screenshots/{self.session_id}/{safe}.png"

    async def capture_error_screenshot(self) -> str | None:
        """Best-effort ``99-error.png`` for failed flows."""
        shot = await self.screenshot("99-error")
        return shot or None


async def shutdown_browser() -> None:
    """Close any browsers that somehow survived a cancelled request.

    Called from ``app.main``'s lifespan shutdown hook.
    """
    for browser in list(_active_browsers):
        try:
            await browser.close()
        except Exception:
            pass
        _active_browsers.discard(browser)
