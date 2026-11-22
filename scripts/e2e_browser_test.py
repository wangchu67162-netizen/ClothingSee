#!/usr/bin/env python
"""衣见 ATELIER 浏览器端到端测试（可选，默认跳过）。

默认行为：打印说明后以 0 退出，不启动浏览器、不访问网络。

使用 ``--browser`` 时：

1. 校验后端 ``/api/health`` 可访问；
2. 通过 API 注册/登录一个一次性账号；
3. 在本地数据库中创建一个合法的 ``BrowseTask`` 任务令牌（脚本与被测后端
   运行在同一台机器、同一个默认 SQLite 库；可用 ``--task-token`` 覆盖）；
4. 启动 Playwright + Microsoft Edge（``channel=msedge``，无头），真实打开
   内置模拟商城「云裳商城」：搜索 → 商品详情 → 选规格 → 结算 → 填写收货
   信息 → 提交订单 → 成功页读取订单号；
5. 回到平台 API 校验该订单已以 ``source="agent"`` 落库（失败绝不假装成功）；
6. 保存成功页截图到 ``backend/runtime/screenshots/e2e/``。

云裳商城是课程演示用的本地模拟商城，不接真实电商与真实支付。

用法::

    backend/.venv/Scripts/python.exe scripts/e2e_browser_test.py            # 跳过
    backend/.venv/Scripts/python.exe scripts/e2e_browser_test.py --browser  # 执行
    backend/.venv/Scripts/python.exe scripts/e2e_browser_test.py --browser --headed

退出码：0 = 成功或按默认跳过；1 = 业务断言失败；2 = 浏览器环境不可用。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
DEFAULT_BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_TIMEOUT = 30.0
PASSWORD = "e2e123456"
SHIPPING = {
    "name": "浏览器 E2E 收货人",
    "phone": "13800000000",
    "address": "上海市测试路 1 号 衣见大厦（模拟地址）",
}
ORDER_RE = re.compile(r"YJ\d{18}")


class BrowserEnvError(RuntimeError):
    """浏览器/Playwright 环境不可用（区别于业务断言失败）。"""


# --------------------------------------------------------------------- HTTP
def http(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json_body: Any | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, bytes]:
    headers: dict[str, str] = {"Accept": "application/json"}
    body = None
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except error.HTTPError as exc:
        return exc.code, exc.read()


def as_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def detail_of(payload: Any) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):
            return "；".join(
                str(item.get("msg", item)) if isinstance(item, dict) else str(item)
                for item in detail
            )
        if isinstance(payload.get("message"), str):
            return payload["message"]
    return str(payload)[:200]


def call_json(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: Any | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    status, raw = http(
        method, f"{base_url.rstrip('/')}{path}", token=token, json_body=payload, timeout=timeout
    )
    data = as_json(raw)
    if status != 200:
        raise RuntimeError(f"{method} {path} → HTTP {status}：{detail_of(data)}")
    return data


# --------------------------------------------------------------------- 环境
def preflight(base_url: str, timeout: float) -> None:
    data = call_json(base_url, "GET", "/api/health", timeout=timeout)
    if data.get("status") != "ok":
        raise RuntimeError(f"后端健康检查失败：{data}")


def login_or_register(base_url: str, timeout: float) -> tuple[str, dict]:
    username = f"e2e_{int(time.time())}_{uuid.uuid4().hex[:4]}"
    status, raw = http(
        "POST",
        f"{base_url.rstrip('/')}/api/auth/register",
        json_body={"username": username, "password": PASSWORD, "nickname": "浏览器 E2E"},
        timeout=timeout,
    )
    data = as_json(raw)
    if status != 200:
        raise RuntimeError(f"注册 E2E 账号失败：HTTP {status} {detail_of(data)}")
    return username, data


# --------------------------------------------------------------------- 任务令牌
def create_browse_task(user_id: int) -> str:
    """在本地默认数据库创建一个合法 BrowseTask，供商城结算页使用。

    仅测试脚本使用：真实用户从「AI 购物助理」发起下单时由服务端创建。
    """
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from app.database import SessionLocal
    from app.models import AgentSession, BrowseTask

    token = uuid.uuid4().hex
    with SessionLocal() as db:
        session = AgentSession(
            user_id=user_id,
            kind="assistant",
            status="running",
            mode="mock",
            result={},
        )
        db.add(session)
        db.flush()
        task = BrowseTask(
            session_id=session.id,
            task_token=token,
            status="running",
            steps=[],
        )
        db.add(task)
        db.commit()
    return token


# --------------------------------------------------------------------- 浏览器
async def browser_flow(
    base_url: str,
    *,
    task_token: str,
    quantity: int = 1,
    query: str = "风衣",
    headless: bool = True,
    channel: str = "msedge",
    slow_mo: int = 0,
) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    base = base_url.rstrip("/")
    shot_dir = BACKEND_DIR / "runtime" / "screenshots" / "e2e"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shot_dir / f"browser-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"

    result: dict[str, Any] = {
        "order_no": "",
        "total_text": "",
        "screenshot": str(shot_path),
        "steps": [],
    }

    async with async_playwright() as playwright:
        # 与 app/browser/playwright_driver.py 一致：优先本机 Edge，再回退内置 Chromium。
        attempts: list[str] = [channel] if channel else []
        attempts.append("")
        launch_errors: list[str] = []
        browser = None
        for attempt in attempts:
            launch_kwargs: dict[str, Any] = {"headless": headless}
            if attempt:
                launch_kwargs["channel"] = attempt
            if slow_mo:
                launch_kwargs["slow_mo"] = slow_mo
            try:
                browser = await playwright.chromium.launch(**launch_kwargs)
                if attempt != channel:
                    print(f"提示：{channel or 'Edge'} 启动失败，已回退到 Playwright 内置 Chromium。")
                break
            except Exception as exc:  # noqa: BLE001 - 环境问题单独归类
                launch_errors.append(f"{attempt or '内置 Chromium'}：{exc}")
        if browser is None:
            raise BrowserEnvError(
                "无法启动浏览器（已尝试本机 Edge 与 Playwright 内置 Chromium）。"
                "请确认已安装 Microsoft Edge，或在 backend venv 执行 "
                "`python -m playwright install chromium`。技术细节："
                + "；".join(launch_errors)
            )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            device_scale_factor=1,
        )
        page = await context.new_page()
        page.set_default_timeout(15_000)
        page.set_default_navigation_timeout(30_000)
        try:
            # 1. 商城首页 + 写入任务令牌（结算页从 sessionStorage 读取）。
            await page.goto(f"{base}/demo-mall/", wait_until="domcontentloaded")
            await page.wait_for_selector('[data-testid="mall-search"]')
            await page.evaluate(
                "(token) => sessionStorage.setItem('mall_task_token', token)",
                task_token,
            )
            body_text = await page.locator("body").inner_text()
            if "模拟商城" not in body_text:
                raise AssertionError("商城页面未标注「模拟商城」，请检查页面文案")
            result["steps"].append("打开云裳商城首页")

            # 2. 搜索并进入商品详情。
            search = page.locator('[data-testid="mall-search"]')
            await search.fill(query)
            await search.press("Enter")
            card = page.locator('[data-testid="mall-product-card"]').first
            await card.wait_for(state="visible", timeout=10_000)
            product_id = await card.get_attribute("data-product-id")
            if not product_id:
                raise AssertionError("商品卡片缺少 data-product-id")
            product_name = (
                await page.locator('[data-testid="mall-product-name"]').first.inner_text()
            ).strip()
            await card.click()
            await page.wait_for_selector('[data-testid="mall-buy-now"]', timeout=15_000)
            product_title = (
                await page.locator('[data-testid="mall-product-name"]').inner_text()
            ).strip()
            result["steps"].append(f"搜索「{query}」并打开「{product_title}」")
            result["product_id"] = int(product_id)
            result["product_name"] = product_title or product_name

            # 3. 选择尺码 / 颜色 / 数量。
            size_buttons = page.locator("button[data-size]")
            color_buttons = page.locator("button[data-color]")
            if await size_buttons.count() == 0:
                raise AssertionError("商品页没有可选尺码")
            if await color_buttons.count() == 0:
                raise AssertionError("商品页没有可选颜色")
            await size_buttons.first.click()
            await color_buttons.first.click()
            await page.fill("#mall-qty", str(max(1, quantity)))
            await page.locator("#mall-qty").press("Tab")  # 触发 change，同步数量状态
            size_text = (await size_buttons.first.inner_text()).strip()
            color_text = (await color_buttons.first.inner_text()).strip()
            result["steps"].append(f"选择规格 {size_text} / {color_text} × {quantity}")

            # 4. 立即购买 → 结算页。
            await page.locator('[data-testid="mall-buy-now"]').click()
            await page.wait_for_url("**/checkout.html*", timeout=20_000)
            await page.wait_for_selector('[data-testid="mall-place-order"]', timeout=15_000)

            # 5. 填写模拟收货信息并提交。
            await page.fill("#ship-name", SHIPPING["name"])
            await page.fill("#ship-phone", SHIPPING["phone"])
            await page.fill("#ship-address", SHIPPING["address"])
            result["steps"].append("填写模拟收货信息")
            await page.locator('[data-testid="mall-place-order"]').click()
            result["steps"].append("提交订单（模拟支付）")

            # 6. 成功页读取订单号；失败绝不跳转成功页。
            try:
                await page.wait_for_url("**/success.html*", timeout=30_000)
            except Exception as exc:  # noqa: BLE001
                message = ""
                box = page.locator("#checkout-error")
                if await box.count() and await box.is_visible():
                    message = (await box.inner_text()).strip()
                raise RuntimeError(
                    f"未进入成功页：{message or '云裳商城下单失败或超时'}"
                ) from exc

            await page.wait_for_selector('[data-testid="mall-order-no"]', timeout=10_000)
            order_no = (
                await page.locator('[data-testid="mall-order-no"]').inner_text()
            ).strip()
            total_text = (
                await page.locator('[data-testid="mall-order-total"]').inner_text()
            ).strip()
            success_text = await page.locator("body").inner_text()
            if "模拟支付" not in success_text:
                raise AssertionError("成功页未标注「模拟支付」")
            if not ORDER_RE.search(order_no):
                raise AssertionError(f"成功页订单号格式异常：{order_no!r}")
            result["order_no"] = ORDER_RE.search(order_no).group(0)
            result["total_text"] = total_text
            result["steps"].append(f"成功页显示订单号 {result['order_no']}")

            try:
                await page.screenshot(path=str(shot_path), full_page=True)
            except Exception:  # noqa: BLE001 - 截图失败不影响结论
                result["screenshot"] = ""
            return result
        finally:
            try:
                await context.close()
            finally:
                await browser.close()


# --------------------------------------------------------------------- 主流程
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="衣见 ATELIER 浏览器 E2E（默认跳过；--browser 启用）"
    )
    parser.add_argument("--browser", action="store_true", help="启用真实浏览器测试")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"后端地址（默认 {DEFAULT_BASE_URL}）")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="API 请求超时秒数")
    parser.add_argument("--query", default="风衣", help="在云裳商城搜索的关键词（默认 风衣）")
    parser.add_argument("--quantity", type=int, default=1, help="购买数量（默认 1）")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口（默认无头）")
    parser.add_argument("--channel", default="msedge", help="Playwright 浏览器通道（默认 msedge，可用空串回退内置 Chromium）")
    parser.add_argument("--slow-mo", type=int, default=0, help="每步放慢的毫秒数（演示用）")
    parser.add_argument("--task-token", help="使用已有 BrowseTask 令牌（默认脚本本地创建）")
    args = parser.parse_args(argv)

    base_url = args.base_url
    if not re.match(r"^https?://", base_url):
        base_url = "http://" + base_url

    if not args.browser:
        print("浏览器 E2E 默认跳过。")
        print("本项目演示可用真实 Microsoft Edge 驱动云裳商城下单；启用方式：")
        print("  backend/.venv/Scripts/python.exe scripts/e2e_browser_test.py --browser")
        print("可选参数：--headed（显示窗口）、--query 风衣、--quantity 1、--slow-mo 300。")
        print("未启用时不会启动浏览器，也不访问任何外部站点。")
        return 0

    print("衣见 ATELIER 浏览器 E2E（云裳商城 · 模拟支付）")
    print(f"目标：{base_url}  浏览器：{args.channel or 'Playwright 内置 Chromium'}")
    try:
        preflight(base_url, args.timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"无法连接后端：{exc}")
        print("请先启动后端：cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
        return 1

    try:
        username, auth = login_or_register(base_url, args.timeout)
        token = auth["access_token"]
        user_id = int(auth["user"]["id"])
        print(f"已准备 E2E 账号：{username}（id={user_id}）")
    except Exception as exc:  # noqa: BLE001
        print(f"账号准备失败：{exc}")
        return 1

    try:
        if args.task_token:
            task_token = args.task_token.strip()
            print("使用调用方提供的任务令牌。")
        else:
            task_token = create_browse_task(user_id)
            print("已创建本地 BrowseTask 任务令牌（仅测试用）。")
    except Exception as exc:  # noqa: BLE001
        print(f"创建任务令牌失败：{exc}")
        print("提示：本脚本需与被测后端使用同一默认数据库（backend/data/app.db），")
        print("      或通过 --task-token 传入已存在的令牌。")
        return 1

    try:
        result = asyncio.run(
            browser_flow(
                base_url,
                task_token=task_token,
                quantity=max(1, args.quantity),
                query=args.query,
                headless=not args.headed,
                channel=args.channel.strip(),
                slow_mo=max(0, args.slow_mo),
            )
        )
    except ImportError:
        print("未安装 Playwright Python 包。请在 backend venv 执行：")
        print("  .venv/Scripts/python.exe -m pip install playwright")
        return 2
    except BrowserEnvError as exc:
        print(f"浏览器环境不可用：{exc}")
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"浏览器流程失败：{exc}")
        if "任务令牌" in str(exc):
            print("提示：任务令牌仅存在于脚本连接的默认数据库。请确认脚本与被测后端")
            print("      使用同一个 backend/data/app.db，或用 --task-token 传入有效令牌。")
        return 1

    for index, step in enumerate(result.get("steps", []), start=1):
        print(f"  [{index}] {step}")
    if result.get("screenshot"):
        print(f"成功页截图：{result['screenshot']}")

    # 平台侧核验：订单必须以 source=agent 真实落库。
    try:
        orders = call_json(base_url, "GET", "/api/orders", token=token, timeout=args.timeout)
        order = next(
            (item for item in orders if item.get("order_no") == result["order_no"]), None
        )
        if order is None:
            print(f"[FAIL] 商城显示成功，但平台订单列表中找不到 {result['order_no']}")
            return 1
        if order.get("source") != "agent":
            print(f"[FAIL] 订单来源应为 agent，实际 {order.get('source')}")
            return 1
        item_names = "、".join(item.get("name", "") for item in order.get("items", []))
        print(
            f"[PASS] 订单 {order['order_no']} 已落库：source=agent，"
            f"合计 ¥{order.get('total')}，商品：{item_names}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 平台订单核验失败：{exc}")
        return 1

    print("\n浏览器 E2E 通过：Edge 已真实走完云裳商城搜索 → 结算 → 模拟支付 → 成功页。")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    sys.exit(main())
