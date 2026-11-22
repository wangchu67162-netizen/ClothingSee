"""Optional browser-use 1.x engine for the single shopping agent.

Default demo engine is Playwright for deterministic classroom runs. When
``BROWSER_ENGINE=browser_use`` and the optional dependency is installed, this
adapter hands the demo-mall checkout to browser-use's natural-language Agent,
which drives a local Chromium/Edge over CDP and writes Python in a REPL.

Requirements:
    backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-optional.txt
    DASHSCOPE_API_KEY=...   (browser-use needs an LLM to decide what to click)

If the optional package or key is missing, the adapter raises a Chinese
``BrowserUnavailable`` (or delegates to Playwright when
``BROWSER_USE_FALLBACK_TO_PLAYWRIGHT=true``). It never fabricates an order.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from ..config import settings
from ..models import BrowseTask, Order
from .base import BrowserUnavailable, ShopRequest, ShopResult, StepCallback
from .shopper import MallShopper

logger = logging.getLogger("yijian.browser.browser_use")

ORDER_RE = re.compile(r"YJ\d{10,}")
_SEMAPHORE = asyncio.Semaphore(1)


def _browser_executable() -> str | None:
    """Prefer an explicitly configured browser, then the local Edge/Chrome."""
    configured = (settings.browser_use_executable_path or "").strip()
    if configured and Path(configured).exists():
        return configured
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    for name in ("msedge", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


class BrowserUseShopper:
    """browser-use-backed engine implementing the same ``shop`` contract."""

    engine = "browser_use"

    def __init__(self, base_url: str, *, session_factory: Any = None) -> None:
        self.base_url = (base_url or "http://127.0.0.1:8000").rstrip("/")
        self.session_factory = session_factory

    # ------------------------------------------------------------------ API
    async def shop(self, request: ShopRequest, on_step: StepCallback) -> ShopResult:
        availability = self._availability_error()
        if availability is not None:
            return await self._fallback_or_raise(request, on_step, availability)

        async with _SEMAPHORE:
            return await self._run_agent(request, on_step)

    # ------------------------------------------------------------- internals
    def _availability_error(self) -> BrowserUnavailable | None:
        if importlib.util.find_spec("browser_use") is None:
            return BrowserUnavailable(
                "未安装可选的 browser-use 引擎。请在后端虚拟环境执行 "
                "`.venv/Scripts/python.exe -m pip install -r requirements-optional.txt`，"
                "或把 backend/.env 的 BROWSER_ENGINE 改回 playwright。"
            )
        if not (settings.dashscope_api_key or "").strip():
            return BrowserUnavailable(
                "browser-use 需要大模型驱动浏览器，但 DASHSCOPE_API_KEY 为空。"
                "请在 backend/.env 配置 Key，或把 BROWSER_ENGINE 改回 playwright。"
            )
        return None

    async def _fallback_or_raise(
        self,
        request: ShopRequest,
        on_step: StepCallback,
        error: BrowserUnavailable,
    ) -> ShopResult:
        if settings.browser_use_fallback_to_playwright:
            await on_step(
                {
                    "action": "browser-use 不可用，回退 Playwright",
                    "status": "done",
                    "detail": str(error),
                    "screenshot": None,
                }
            )
            logger.warning("browser-use unavailable, falling back to Playwright: %s", error)
            return await MallShopper(self.base_url, headless=settings.browser_headless).shop(request, on_step)
        raise error

    def _lookup_order(self, task_token: str) -> tuple[str | None, float | None]:
        """Read the order the browser just created, using the BrowseTask token."""
        if self.session_factory is None:
            return None, None
        with self.session_factory() as db:
            task = db.query(BrowseTask).filter(BrowseTask.task_token == task_token).one_or_none()
            if task is None or not task.order_no:
                return None, None
            order = db.query(Order).filter(Order.external_ref == task.order_no).one_or_none()
            return task.order_no, (float(order.total) if order else None)

    async def _run_agent(self, request: ShopRequest, on_step: StepCallback) -> ShopResult:
        # Imports are deliberately lazy: browser-use remains an optional extra.
        try:
            from browser_use import Agent, Browser
            from browser_use.llm import ChatOpenAI
        except Exception as exc:  # ImportError or a dependency/version conflict
            raise BrowserUnavailable(
                f"browser-use 已安装但无法加载：{exc}。请检查 requirements-optional.txt 与 Python 版本。"
            ) from exc

        product_url = (
            f"{self.base_url}/demo-mall/product.html?id={int(request.product_id)}"
            f"&token={request.task_token}"
        )
        customer = request.customer or {}
        size = request.size or "默认尺码"
        color = request.color or "默认颜色"
        task = (
            "你正在操作一个本地课程演示用的模拟商城「云裳商城」，请完成一次模拟下单，不要访问其他网站。\n"
            f"1. 打开商品页：{product_url}\n"
            f"2. 选择尺码 {size}，颜色 {color}，数量 {max(1, int(request.quantity or 1))}。"
            "尺码按钮有 data-size 属性，颜色按钮有 data-color 属性。\n"
            "3. 点击 [data-testid='mall-buy-now'] 进入结算页。\n"
            f"4. 结算页填写：收货人 #ship-name = {customer.get('name', '')}，"
            f"手机 #ship-phone = {customer.get('phone', '')}，"
            f"地址 #ship-address = {customer.get('address', '')}。\n"
            "5. 点击 [data-testid='mall-place-order'] 提交订单（这是模拟支付）。\n"
            "6. 等待成功页，读取 [data-testid='mall-order-no'] 的订单号。\n"
            "7. 最后只输出一行：ORDER_NO: <订单号>。不要编造订单号；若失败请说明失败原因。"
        )

        await on_step(
            {
                "action": "启动 browser-use 浏览器",
                "status": "running",
                "detail": "browser-use 1.x · 本地 Chromium/Edge · CDP",
                "screenshot": None,
            }
        )

        executable = _browser_executable()
        browser_kwargs: dict[str, Any] = {
            "headless": bool(settings.browser_headless),
            "allowed_domains": ["127.0.0.1", "localhost"],
        }
        if executable:
            browser_kwargs["executable_path"] = executable
        browser = None
        try:
            browser = Browser("chromium", **browser_kwargs)
            llm = ChatOpenAI(
                model=(settings.browser_use_model or settings.qwen_text_model),
                api_key=settings.dashscope_api_key,
                base_url=settings.dashscope_base_url,
                temperature=0.1,
            )
            agent = Agent(task, llm=llm, browser=browser)
            await on_step(
                {
                    "action": "browser-use 智能体执行自然语言下单",
                    "status": "running",
                    "detail": f"{request.product_name} · {size} · {color}",
                    "screenshot": None,
                }
            )
            result = await agent.run(
                max_steps=int(settings.browser_use_max_steps),
                timeout=float(settings.browser_use_timeout),
            )
            final_text = (result.final_result() or "").strip()
            await on_step(
                {
                    "action": "browser-use 读取成功页",
                    "status": "done" if result.status == "completed" else "failed",
                    "detail": final_text[:240] or f"browser-use status={result.status}",
                    "screenshot": None,
                }
            )
        except BrowserUnavailable:
            raise
        except Exception as exc:
            raise BrowserUnavailable(f"browser-use 执行失败：{exc}") from exc
        finally:
            if browser is not None:
                with contextlib.suppress(Exception):
                    await browser.stop()

        match = ORDER_RE.search(final_text)
        order_no = match.group(0) if match else None
        total: float | None = None
        # A robust fallback: the browser hit our own mall API, so the task row
        # knows the order number even if the agent's final text omitted it.
        db_order_no, db_total = self._lookup_order(request.task_token)
        if db_order_no:
            order_no = order_no or db_order_no
            total = db_total if db_total is not None else float(request.expected_total or 0)
        if not order_no:
            raise BrowserUnavailable(
                "browser-use 已结束，但未产生有效订单号。请检查云裳商城页面或改用 playwright。"
            )
        if total is None:
            total = float(request.expected_total or 0)
        await on_step(
            {
                "action": "下单成功",
                "status": "done",
                "detail": f"browser-use 完成下单 · 订单号 {order_no} · ¥{total:.2f}",
                "screenshot": None,
            }
        )
        return ShopResult(order_no=order_no, total=total, steps=[])
