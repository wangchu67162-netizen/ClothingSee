"""Shared types and errors for the demo mall browser engines.

All browser work for the single shopping assistant flows through one of the
engines in this package:

* :class:`app.browser.shopper.MallShopper`  — real Playwright (Edge / Chromium)
* :class:`app.browser.mock_driver.MockMallShopper` — deterministic test double

The engines share the request/response dataclasses declared here so the
assistant service never needs to know which engine is running.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


class BrowserUnavailable(RuntimeError):
    """Raised when a headless browser cannot be started or a step fails.

    The assistant must surface this as a Chinese error event; it must never be
    converted into a fake "下单成功" response.
    """

    def __init__(self, message: str, screenshot: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.screenshot = screenshot


@dataclass(slots=True)
class ShopRequest:
    """Everything the browser needs to complete one demo-mall checkout."""

    session_id: str
    task_token: str
    base_url: str
    product_id: int
    product_name: str
    query: str = ""
    size: str = ""
    color: str = ""
    quantity: int = 1
    customer: dict[str, str] = field(default_factory=dict)
    expected_total: float = 0.0


@dataclass(slots=True)
class ShopResult:
    """Outcome reported back by an engine after reaching the success page."""

    order_no: str
    total: float = 0.0
    steps: list[dict[str, Any]] = field(default_factory=list)


# Callback invoked once per browser step; the assistant service persists the
# step and forwards it over SSE.
StepCallback = Callable[[dict[str, Any]], Awaitable[None]]
