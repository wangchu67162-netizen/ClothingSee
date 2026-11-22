"""Deterministic mock shopping engine — **tests only**.

Production defaults to ``BROWSER_ENGINE=playwright``. When
``BROWSER_ENGINE=mock`` (set by ``tests/test_assistant_mock.py``) the assistant
service uses this engine instead of launching a real browser. It emits the same
step callback shape, then creates the platform order through the *same*
:func:`app.browser.order_service.create_agent_order` helper as the real demo
mall API, so the rest of the pipeline (Order/OrderItem/BrowseTask/session
records) is exercised for real.

No screenshots are produced by the mock engine; ``screenshot`` is ``None``.
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..models import BrowseTask, Product
from .base import BrowserUnavailable, ShopRequest, ShopResult, StepCallback
from .order_service import MallOrderError, create_agent_order


class MockMallShopper:
    """Simulates the Playwright flow and writes a real platform order."""

    engine = "mock"

    def __init__(self, session_factory: sessionmaker[Session] | Any) -> None:
        self.session_factory = session_factory

    async def _pause(self) -> None:
        # Small delay keeps SSE visually streamable in tests/demos.
        await asyncio.sleep(0.02)

    async def shop(self, request: ShopRequest, on_step: StepCallback) -> ShopResult:
        state: dict[str, Any] = {"index": 0, "steps": []}

        async def emit(action: str, detail: str, *, status: str = "done") -> dict[str, Any]:
            state["index"] += 1
            step = {
                "index": state["index"],
                "action": action,
                "status": status,
                "detail": detail,
                "screenshot": None,
            }
            state["steps"].append(step)
            await on_step(step)
            return step

        await emit("打开云裳商城", f"（测试引擎）打开 {request.base_url}/demo-mall/")
        await self._pause()
        await emit(
            "搜索商品",
            f"（测试引擎）关键词「{request.query or request.product_name}」，定位商品 {request.product_name}",
        )
        await self._pause()
        await emit("进入商品详情", f"（测试引擎）打开商品「{request.product_name}」")
        await self._pause()
        await emit(
            "选择尺码与颜色",
            f"（测试引擎）{request.size or '默认尺码'} / {request.color or '默认颜色'} × {request.quantity}",
        )
        await self._pause()
        await emit("进入结算页", "（测试引擎）结算页已加载")
        await self._pause()
        customer = request.customer or {}
        await emit(
            "填写收货信息",
            f"（测试引擎）收货人 {customer.get('name', '')}，演示收货地址",
        )
        await self._pause()

        try:
            with self.session_factory() as db:
                task = (
                    db.query(BrowseTask)
                    .filter(BrowseTask.task_token == request.task_token)
                    .one_or_none()
                )
                product = db.get(Product, int(request.product_id))
                order, _created = create_agent_order(
                    db,
                    task=task,
                    product=product,
                    size=request.size,
                    color=request.color,
                    quantity=request.quantity,
                    customer=customer,
                )
                order_no = order.order_no
                total = float(order.total)
        except MallOrderError as exc:
            await emit("提交订单", f"（测试引擎）下单失败：{exc.message}", status="failed")
            raise BrowserUnavailable(exc.message) from exc
        except Exception as exc:  # pragma: no cover - defensive
            await emit("提交订单", f"（测试引擎）下单失败：{exc}", status="failed")
            raise BrowserUnavailable(f"云裳商城下单失败：{exc}") from exc

        await emit("提交订单", f"（测试引擎）平台已创建订单 {order_no}")
        await self._pause()
        await emit("下单成功", f"（测试引擎）成功页显示订单号 {order_no}，合计 ¥{total:.2f}")
        return ShopResult(order_no=order_no, total=total, steps=list(state["steps"]))
