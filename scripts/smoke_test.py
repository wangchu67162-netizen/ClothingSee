#!/usr/bin/env python
"""衣见 ATELIER 后端冒烟测试（可对运行中的服务执行）。

默认目标：``http://127.0.0.1:8000``。只使用 Python 标准库，因此系统 Python
或后端 venv 均可运行。

覆盖：健康检查 / 元信息 / 注册登录 / 商品搜索与详情 / 以图搜衣 /
购物车 / 平台下单与取消 / 小模型状态与切比雪夫 / 云裳商城商品接口。
无 Key（Mock 模式）下应全部通过；任何失败都会在摘要中以 ``[FAIL]`` 展示，
脚本以非零退出码结束。

用法::

    backend/.venv/Scripts/python.exe scripts/smoke_test.py
    python scripts/smoke_test.py --base-url http://127.0.0.1:8000
    python scripts/smoke_test.py --username demo --password demo123

注意：脚本会注册一个一次性冒烟用户（或使用你指定的账号），并创建一笔
已取消的演示订单，以便完整验证下单链路；不会连接任何外部服务。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error, request

DEFAULT_BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_TIMEOUT = 30.0
PASSWORD = "smoke123456"

# 1x1 透明 PNG，足够触发 Pillow 校验与视觉 stub。
PNG_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

SHIPPING = {
    "name": "冒烟测试收货人",
    "phone": "13800000000",
    "address": "上海市测试路 1 号 衣见大厦",
}


# --------------------------------------------------------------------- runner
@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""


class Runner:
    def __init__(self) -> None:
        self.results: list[Result] = []

    def run(self, name: str, action: Callable[[], str | None]) -> bool:
        started = time.perf_counter()
        try:
            detail = action() or "OK"
            ok = True
        except Exception as exc:  # noqa: BLE001 - 冒烟脚本需要兜住一切
            detail = f"{type(exc).__name__}: {exc}"
            ok = False
        elapsed = int((time.perf_counter() - started) * 1000)
        self.results.append(Result(name=name, ok=ok, detail=detail))
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}（{elapsed}ms）{'' if ok else ' → ' + detail}")
        return ok

    @property
    def failures(self) -> list[Result]:
        return [item for item in self.results if not item.ok]

    def summary(self) -> int:
        total = len(self.results)
        passed = total - len(self.failures)
        print("\n" + "=" * 62)
        print(f"冒烟摘要：通过 {passed}/{total}，失败 {len(self.failures)}")
        if self.failures:
            print("-" * 62)
            for item in self.failures:
                print(f"  [FAIL] {item.name}: {item.detail}")
        print("=" * 62)
        return 0 if not self.failures else 1


# --------------------------------------------------------------------- HTTP
def http(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json_body: Any | None = None,
    data: bytes | None = None,
    content_type: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, bytes]:
    headers: dict[str, str] = {"Accept": "application/json"}
    body = data
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    elif content_type:
        headers["Content-Type"] = content_type
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
        message = payload.get("message")
        if isinstance(message, str):
            return message
    return str(payload)[:200]


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def json_or_fail(status: int, raw: bytes, label: str, expected: int = 200) -> Any:
    payload = as_json(raw)
    expect(
        status == expected,
        f"{label} 期望 HTTP {expected}，实际 {status}：{detail_of(payload) if payload is not None else raw[:160]!r}",
    )
    return payload


def multipart(
    fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]
) -> tuple[bytes, str]:
    boundary = f"----yijian-smoke-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    for name, (filename, content, content_type) in files.items():
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(content)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


# --------------------------------------------------------------------- state
class SmokeContext:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token: str | None = None
        self.username: str | None = None
        self.user_id: int | None = None
        self.product: dict[str, Any] | None = None

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get(self, path: str, token: str | None = None, **kwargs) -> tuple[int, bytes]:
        return http(
            "GET",
            self.url(path),
            token=token if token is not None else self.token,
            timeout=self.timeout,
            **kwargs,
        )

    def post(self, path: str, token: str | None = None, **kwargs) -> tuple[int, bytes]:
        return http(
            "POST",
            self.url(path),
            token=token if token is not None else self.token,
            timeout=self.timeout,
            **kwargs,
        )

    def patch(self, path: str, **kwargs) -> tuple[int, bytes]:
        return http(
            "PATCH", self.url(path), token=self.token, timeout=self.timeout, **kwargs
        )

    def delete(self, path: str) -> tuple[int, bytes]:
        return http("DELETE", self.url(path), token=self.token, timeout=self.timeout)


# --------------------------------------------------------------------- checks
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="衣见 ATELIER 后端冒烟测试（Mock/无 Key 可跑）"
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"后端地址（默认 {DEFAULT_BASE_URL}）",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, help="单请求超时秒数（默认 30）"
    )
    parser.add_argument("--username", help="使用已有账号登录（默认自动注册冒烟账号）")
    parser.add_argument("--password", help="已有账号密码（与 --username 搭配）")
    args = parser.parse_args(argv)

    base_url = args.base_url
    if not re.match(r"^https?://", base_url):
        base_url = "http://" + base_url

    print("衣见 ATELIER 后端冒烟测试")
    print(f"目标：{base_url}")
    print(f"Python：{sys.version.split()[0]}  （Mock 模式无需 API Key）\n")

    ctx = SmokeContext(base_url, args.timeout)
    runner = Runner()

    # ------------------------------------------------------------- 健康 / 元信息
    def check_health() -> str:
        status, raw = ctx.get("/api/health", token="")
        payload = json_or_fail(status, raw, "健康检查")
        expect(payload.get("status") == "ok", f"health.status 异常：{payload}")
        return f"status=ok, version={payload.get('version')}"

    if not runner.run("健康检查 /api/health", check_health):
        print("\n无法连接后端服务。请先启动：")
        print("  cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
        return runner.summary()

    def check_meta() -> str:
        status, raw = ctx.get("/api/meta", token="")
        payload = json_or_fail(status, raw, "元信息")
        expect(payload.get("app_name") == "衣见 ATELIER", f"app_name 异常：{payload.get('app_name')}")
        expect(payload.get("mode") in ("mock", "qwen"), f"mode 异常：{payload.get('mode')}")
        expect(payload.get("features", {}).get("multi_agent") is True, "meta 未声明多智能体能力")
        return f"app={payload.get('app_name')}, mode={payload.get('mode')}, 小模型={payload.get('small_model_mode')}"

    runner.run("元信息 /api/meta", check_meta)

    # ------------------------------------------------------------- 认证
    def check_auth() -> str:
        if args.username:
            username = args.username.strip()
            password = args.password or "demo123"
            status, raw = ctx.post(
                "/api/auth/login", token="", json_body={"username": username, "password": password}
            )
            payload = json_or_fail(status, raw, "登录")
            ctx.token = payload["access_token"]
            ctx.username = username
            ctx.user_id = payload["user"]["id"]
            return f"登录已有账号 {username}"

        username = f"smoke_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        status, raw = ctx.post(
            "/api/auth/register",
            token="",
            json_body={"username": username, "password": PASSWORD, "nickname": "冒烟测试员"},
        )
        if status == 409:  # 极低概率撞名，退化为登录
            status, raw = ctx.post(
                "/api/auth/login",
                token="",
                json_body={"username": username, "password": PASSWORD},
            )
            label = "登录"
        else:
            label = "注册"
        payload = json_or_fail(status, raw, label)
        ctx.token = payload["access_token"]
        ctx.username = username
        ctx.user_id = payload["user"]["id"]

        me_status, me_raw = ctx.get("/api/auth/me")
        me = json_or_fail(me_status, me_raw, "当前用户")
        expect(me.get("username") == username, f"/me 用户名不一致：{me}")
        return f"注册并登录 {username}（id={ctx.user_id}）"

    if not runner.run("注册 / 登录 / 当前用户", check_auth):
        return runner.summary()

    def check_auth_negative() -> str:
        status, raw = ctx.post(
            "/api/auth/login",
            token="",
            json_body={"username": ctx.username, "password": "definitely-wrong"},
        )
        payload = as_json(raw)
        expect(status == 401, f"错误密码应返回 401，实际 {status}")
        expect("用户名或密码错误" in detail_of(payload), f"错误提示不是中文：{detail_of(payload)}")
        return "错误密码返回 401 中文提示"

    runner.run("登录失败防护", check_auth_negative)

    # ------------------------------------------------------------- 商品搜索
    def check_search() -> str:
        status, raw = ctx.get("/api/products", token="")
        listing = json_or_fail(status, raw, "商品列表")
        expect(listing.get("total", 0) >= 1, "商品库为空，请确认种子数据已写入")
        expect(listing.get("items"), "商品列表没有返回 items")

        status, raw = ctx.get("/api/products?q=%E7%9C%9F%E4%B8%9D", token="")
        silk = json_or_fail(status, raw, "关键词搜索")
        expect(silk.get("total", 0) >= 1, "搜索「真丝」无结果")
        for item in silk.get("items", [])[:3]:
            haystack = (
                (item.get("name") or "")
                + (item.get("subtitle") or "")
                + (item.get("description") or "")
                + "".join(item.get("style_tags") or [])
            )
            expect("真丝" in haystack, f"搜索结果与关键词不符：{item.get('name')}")

        status, raw = ctx.get("/api/products/categories", token="")
        categories = json_or_fail(status, raw, "分类列表")
        expect(isinstance(categories, list) and categories, "分类为空")
        expect(sum(item.get("count", 0) for item in categories) >= 1, "分类计数异常")

        chosen = next(
            (item for item in silk.get("items", []) if item.get("stock", 0) >= 1),
            listing["items"][0],
        )
        status, raw = ctx.get(f"/api/products/{chosen['id']}", token="")
        detail = json_or_fail(status, raw, "商品详情")
        expect(detail.get("id") == chosen["id"], "商品详情 id 不一致")
        ctx.product = detail

        status, raw = ctx.get("/api/products/999999", token="")
        expect(status == 404, f"不存在的商品应返回 404，实际 {status}")
        expect("商品不存在" in detail_of(as_json(raw)), "商品 404 提示不是中文")

        return f"共 {listing['total']} 件商品，搜索「真丝」{silk['total']} 件，详情 {detail.get('name')}"

    runner.run("商品列表 / 搜索 / 分类 / 详情", check_search)

    def check_image_search() -> str:
        expect(ctx.product is not None, "缺少商品上下文")
        image_path = ctx.product.get("image") or ""
        expect(image_path.startswith("/static/"), f"商品图路径异常：{image_path}")
        status, image_bytes = ctx.get(image_path, token="")
        expect(status == 200 and image_bytes, f"下载本地商品图失败（HTTP {status}）")
        body, content_type = multipart(
            {"top_k": "3"},
            {"file": (image_path.rsplit("/", 1)[-1] or "query.webp", image_bytes, "image/webp")},
        )
        status, raw = http(
            "POST",
            ctx.url("/api/products/search-by-image"),
            data=body,
            content_type=content_type,
            timeout=ctx.timeout,
        )
        payload = json_or_fail(status, raw, "以图搜衣")
        expect(payload.get("distance_metric") == "chebyshev", "distance_metric 不是 chebyshev")
        expect(payload.get("items"), "以图搜衣没有返回结果")
        expect(
            payload["items"][0].get("id") == ctx.product.get("id"),
            "原始商品图应排在第一（相似度最高）",
        )
        return f"返回 {len(payload['items'])} 件，Top1={payload['items'][0].get('name')}"

    runner.run("以图搜衣（视觉小模型）", check_image_search)

    # ------------------------------------------------------------- 购物车
    def check_cart() -> str:
        expect(ctx.product is not None, "缺少商品上下文")
        ctx.delete("/api/cart")  # 清空，保证可重复运行
        sizes = ctx.product.get("sizes") or []
        colors = ctx.product.get("colors") or []
        payload = {
            "product_id": ctx.product["id"],
            "quantity": 1,
            "size": sizes[0] if sizes else "",
            "color": colors[0] if colors else "",
        }
        status, raw = ctx.post("/api/cart", json_body=payload)
        cart = json_or_fail(status, raw, "加入购物车")
        expect(cart.get("total_quantity") == 1, f"购物车数量异常：{cart.get('total_quantity')}")
        expect(abs(cart.get("total_amount", 0) - ctx.product["price"]) < 0.01, "购物车金额异常")
        item_id = cart["items"][0]["id"]

        quantity = 2 if ctx.product.get("stock", 0) >= 2 else 1
        status, raw = ctx.patch(f"/api/cart/{item_id}", json_body={"quantity": quantity})
        cart = json_or_fail(status, raw, "修改购物车数量")
        expect(cart.get("total_quantity") == quantity, "修改数量未生效")
        expected = ctx.product["price"] * quantity
        expect(abs(cart.get("total_amount", 0) - expected) < 0.01, "修改后金额异常")
        return f"商品 {ctx.product.get('name')} × {quantity}，金额 ¥{cart['total_amount']}"

    runner.run("购物车增改查", check_cart)

    # ------------------------------------------------------------- 订单
    def check_order() -> str:
        status, raw = ctx.post(
            "/api/orders",
            json_body={"shipping": SHIPPING, "note": "T11 冒烟测试订单"},
        )
        order = json_or_fail(status, raw, "结算下单")
        expect(re.fullmatch(r"YJ\d{18}", order.get("order_no", "")), f"订单号格式异常：{order.get('order_no')}")
        expect(order.get("status") == "paid", f"订单状态异常：{order.get('status')}")
        expect(order.get("source") == "platform", f"订单来源异常：{order.get('source')}")
        expect(order.get("items"), "订单没有明细")

        status, raw = ctx.get(f"/api/orders/{order['id']}")
        detail = json_or_fail(status, raw, "订单详情")
        expect(detail.get("order_no") == order["order_no"], "订单详情不一致")

        status, raw = ctx.get("/api/orders")
        orders = json_or_fail(status, raw, "订单列表")
        expect(any(item.get("id") == order["id"] for item in orders), "订单列表缺少新订单")

        status, raw = ctx.post(f"/api/orders/{order['id']}/cancel", json_body={})
        cancelled = json_or_fail(status, raw, "取消订单")
        expect(cancelled.get("status") == "cancelled", "订单取消失败")

        cart_status, cart_raw = ctx.get("/api/cart")
        cart = json_or_fail(cart_status, cart_raw, "下单后购物车")
        expect(cart.get("items") == [], "下单后购物车未清空")
        return f"订单 {order['order_no']}，合计 ¥{order['total']}，已取消（不产生真实扣款）"

    runner.run("下单 / 订单列表 / 取消", check_order)

    # ------------------------------------------------------------- 小模型
    def check_small_models() -> str:
        status, raw = ctx.get("/api/small-models/status", token="")
        status_body = json_or_fail(status, raw, "小模型状态")
        expect(status_body.get("vision", {}).get("dim", 0) > 0, "视觉模型维度异常")
        expect(
            status_body.get("nlp_kg", {}).get("metric") == "chebyshev",
            "NLP-KG 度量不是 chebyshev",
        )

        status, raw = ctx.post(
            "/api/small-models/kg/chebyshev",
            token="",
            json_body={"a": [1, 5], "b": [3, 2]},
        )
        cheb = json_or_fail(status, raw, "切比雪夫距离")
        expect(abs(cheb.get("distance", -1) - 3.0) < 1e-9, f"距离计算错误：{cheb}")
        expect(abs(cheb.get("similarity", -1) - 0.25) < 1e-9, f"相似度计算错误：{cheb}")

        body, content_type = multipart({}, {"file": ("pixel.png", PNG_PIXEL, "image/png")})
        status, raw = http(
            "POST",
            ctx.url("/api/small-models/vision/embed"),
            data=body,
            content_type=content_type,
            timeout=ctx.timeout,
        )
        embed = json_or_fail(status, raw, "视觉 embedding")
        expect(embed.get("dim") == 256, f"embedding 维度异常：{embed.get('dim')}")

        status, raw = ctx.get("/api/small-models/kg/graph?limit=20", token="")
        graph = json_or_fail(status, raw, "知识图谱")
        expect(graph.get("metric") == "chebyshev", "图谱度量不是 chebyshev")
        expect(graph.get("nodes"), "知识图谱为空（请确认小模型已完成预热）")
        return (
            f"模式={status_body.get('mode')}，视觉维度={status_body['vision']['dim']}，"
            f"切比雪夫(3.0/0.25)，图谱 {len(graph['nodes'])} 节点"
        )

    runner.run("小模型状态 / 切比雪夫 3.0 / 视觉 / 图谱", check_small_models)

    # ------------------------------------------------------------- 云裳商城
    def check_demo_mall() -> str:
        status, raw = ctx.get("/demo-mall/api/products?q=%E9%A3%8E%E8%A1%A3", token="")
        payload = json_or_fail(status, raw, "云裳商城商品")
        expect(payload.get("total", 0) >= 1, "云裳商城搜索「风衣」无结果")
        return f"商城搜索「风衣」返回 {payload['total']} 件（内置模拟商城）"

    runner.run("云裳商城商品接口", check_demo_mall)

    return runner.summary()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    sys.exit(main())
