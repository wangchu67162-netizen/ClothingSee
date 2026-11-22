"""Real-browser shopping flow for 云裳商城 (demo mall).

Flow: catalog → product → checkout → fill shipping → submit → success page.
Every step produces a screenshot through :class:`PlaywrightDriver`, and the
engine returns the order number that the success page displays.

Stable selectors (contract, see docs/CONTRACTS.md §3.8):
``[data-testid="mall-search"]``, ``[data-testid="mall-product-card"]``,
``[data-testid="mall-product-name"]``, ``[data-testid="mall-buy-now"]``,
``#ship-name``, ``#ship-phone``, ``#ship-address``,
``[data-testid="mall-place-order"]``, ``[data-testid="mall-order-no"]``.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from .base import BrowserUnavailable, ShopRequest, ShopResult, StepCallback
from .playwright_driver import PlaywrightDriver, PlaywrightTimeoutError

logger = logging.getLogger("yijian.browser.shopper")


class MallShopper:
    """Playwright implementation of the demo mall shopper."""

    engine = "playwright"

    def __init__(self, base_url: str, *, headless: bool | None = None) -> None:
        self.base_url = (base_url or "http://127.0.0.1:8000").rstrip("/")
        self.headless = headless

    async def shop(self, request: ShopRequest, on_step: StepCallback) -> ShopResult:
        driver = PlaywrightDriver(request.session_id, headless=self.headless)
        state: dict[str, Any] = {"index": 0, "steps": [], "failed": False}

        async def emit(action: str, detail: str = "", *, screenshot: bool = True) -> dict[str, Any]:
            state["index"] += 1
            shot = await driver.screenshot(f"{state['index']:02d}") if screenshot else ""
            step = {
                "index": state["index"],
                "action": action,
                "status": "done",
                "detail": detail,
                "screenshot": shot or None,
            }
            state["steps"].append(step)
            await on_step(step)
            return step

        async with driver:
            try:
                return await self._run(driver, request, emit, state)
            except BrowserUnavailable as exc:
                await self._emit_failure(driver, on_step, state, exc)
                raise
            except Exception as exc:  # unexpected page error
                screenshot = await driver.capture_error_screenshot()
                wrapped = BrowserUnavailable(f"云裳商城操作失败：{exc}", screenshot=screenshot)
                await self._emit_failure(driver, on_step, state, wrapped)
                raise wrapped from exc

    # --------------------------------------------------------------- helpers
    async def _emit_failure(
        self,
        driver: PlaywrightDriver,
        on_step: StepCallback,
        state: dict[str, Any],
        exc: BrowserUnavailable,
    ) -> None:
        if state.get("failed"):
            return
        state["failed"] = True
        state["index"] += 1
        screenshot = exc.screenshot or await driver.capture_error_screenshot()
        exc.screenshot = screenshot
        step = {
            "index": state["index"],
            "action": "浏览器执行失败",
            "status": "failed",
            "detail": exc.message,
            "screenshot": screenshot,
        }
        state["steps"].append(step)
        try:
            await on_step(step)
        except Exception:  # pragma: no cover - queue/disconnect
            logger.debug("failed to forward failure step", exc_info=True)

    async def _click_first(self, page: Any, selector: str) -> bool:
        locator = page.locator(selector).first
        try:
            if await locator.count() == 0:
                return False
            await locator.click(timeout=5000)
            return True
        except Exception:
            return False

    async def _run(self, driver: PlaywrightDriver, request: ShopRequest, emit, state) -> ShopResult:
        page = driver.page
        assert page is not None
        base = self.base_url
        product_id = int(request.product_id)
        direct_url = f"{base}/demo-mall/product.html?id={product_id}&token={request.task_token}"

        # 1. Catalog ---------------------------------------------------------
        await page.goto(f"{base}/demo-mall/", wait_until="domcontentloaded")
        await page.wait_for_selector('[data-testid="mall-search"]', timeout=10_000)
        # The checkout page picks the token up from sessionStorage (same tab).
        await page.evaluate(
            "(token) => { try { sessionStorage.setItem('mall_task_token', token); } catch (e) {} }",
            request.task_token,
        )
        await emit("打开云裳商城", "已进入云裳商城首页（内置模拟商城）")

        # 2. Search ----------------------------------------------------------
        search = page.locator('[data-testid="mall-search"]')
        await search.click()
        await search.fill(request.query or request.product_name)
        await search.press("Enter")

        target = page.locator(
            f'[data-testid="mall-product-card"][data-product-id="{product_id}"]'
        ).first
        navigated = False
        try:
            await target.wait_for(state="visible", timeout=8000)
        except PlaywrightTimeoutError:
            logger.info("Search did not surface product %s; opening detail directly", product_id)
            await page.goto(direct_url, wait_until="domcontentloaded")
            navigated = True

        if not navigated:
            for _ in range(2):
                if await self._click_first(
                    page, f'[data-testid="mall-product-card"][data-product-id="{product_id}"]'
                ):
                    navigated = True
                    break
                await page.wait_for_timeout(350)
            if not navigated:
                await page.goto(direct_url, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector('[data-testid="mall-buy-now"]', timeout=10_000)
        except PlaywrightTimeoutError:
            await page.goto(direct_url, wait_until="domcontentloaded")
            await page.wait_for_selector('[data-testid="mall-buy-now"]', timeout=10_000)

        # 3. Product page ----------------------------------------------------
        await emit(
            "搜索并进入商品详情",
            f"搜索「{request.query or request.product_name}」，打开「{request.product_name}」",
        )

        # 4. Variant ---------------------------------------------------------
        requested_size = (request.size or "").strip()
        if requested_size and await page.locator(f'button[data-size="{requested_size}"]').count():
            size_locator = page.locator(f'button[data-size="{requested_size}"]').first
        else:
            size_locator = page.locator("button[data-size]").first
        if await size_locator.count() == 0:
            raise BrowserUnavailable("商品页没有可选择的尺码")
        await size_locator.click()

        requested_color = (request.color or "").strip()
        if requested_color and await page.locator(f'button[data-color="{requested_color}"]').count():
            color_locator = page.locator(f'button[data-color="{requested_color}"]').first
        else:
            color_locator = page.locator("button[data-color]").first
        if await color_locator.count() == 0:
            raise BrowserUnavailable("商品页没有可选择的颜色")
        await color_locator.click()

        try:
            await page.fill("#mall-qty", str(max(1, int(request.quantity or 1))))
        except Exception:
            pass

        await emit(
            "选择尺码与颜色",
            f"{requested_size or '默认尺码'} / {requested_color or '默认颜色'} × {request.quantity}",
        )

        # 5. Buy now → checkout ---------------------------------------------
        await page.locator('[data-testid="mall-buy-now"]').click()
        try:
            await page.wait_for_url("**/checkout.html*", timeout=15_000)
        except PlaywrightTimeoutError:
            raise BrowserUnavailable("点击「立即购买」后未能进入云裳商城结算页") from None
        await page.wait_for_selector('[data-testid="mall-place-order"]', timeout=10_000)
        await emit("进入结算页", "商品与规格已带入云裳商城结算页")

        # 6. Shipping --------------------------------------------------------
        customer = request.customer or {}
        await page.fill("#ship-name", str(customer.get("name", "")))
        await page.fill("#ship-phone", str(customer.get("phone", "")))
        await page.fill("#ship-address", str(customer.get("address", "")))
        await emit(
            "填写收货信息",
            f"收货人 {customer.get('name', '')}，使用演示收货地址",
        )

        # 7. Submit ----------------------------------------------------------
        await page.locator('[data-testid="mall-place-order"]').click()
        await emit("提交订单", "已提交结算表单（云裳商城模拟支付）")

        try:
            await page.wait_for_url("**/success.html*", timeout=25_000)
        except PlaywrightTimeoutError:
            message = ""
            try:
                error_box = page.locator("#checkout-error")
                if await error_box.count() and await error_box.is_visible():
                    message = (await error_box.inner_text()).strip()
            except Exception:
                pass
            raise BrowserUnavailable(f"云裳商城下单失败：{message or '未跳转到成功页'}") from None

        # 8. Success page ----------------------------------------------------
        await page.wait_for_selector('[data-testid="mall-order-no"]', timeout=10_000)
        order_text = (await page.locator('[data-testid="mall-order-no"]').inner_text()).strip()
        match = re.search(r"YJ\d{10,}", order_text)
        if not match:
            raise BrowserUnavailable(f"成功页未显示有效订单号（页面内容：{order_text[:40]}）")
        order_no = match.group(0)

        total = float(request.expected_total or 0)
        try:
            total_text = await page.locator('[data-testid="mall-order-total"]').inner_text()
            number = re.search(r"\d+(?:\.\d+)?", total_text.replace(",", ""))
            if number:
                total = float(number.group(0))
        except Exception:
            pass

        await emit("下单成功", f"订单号 {order_no}，合计 ¥{total:.2f}")
        return ShopResult(order_no=order_no, total=total, steps=list(state["steps"]))
