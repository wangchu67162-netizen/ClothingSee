#!/usr/bin/env python
"""T17 无 Key 全链路 E2E（真实后端进程 + 真实浏览器，Mock 大模型）。

对运行中的后端（默认 ``http://127.0.0.1:8000``）按验收顺序执行：

1. ``/api/meta`` 必须是 ``mode=mock``（无 ``DASHSCOPE_API_KEY``）；
2. 注册一次性账号 + 登录 demo 账号；
3. 商品搜索 / 详情；
4. 加购 → 平台结算 → 订单列表；
5. 小模型 status / embed / similar / chebyshev(3.0) / KG；
6. 上传样例图 → 五智能体 SSE（五 agent、两轮、revision、final）；
7. 购物助理「我想买风衣」→ 商品卡；
8. 购物助理「帮我下单风衣」→ 真实 Playwright/Edge 浏览器步骤截图 +
   ``order_created`` + ``/api/orders`` 可查 ``source=agent``。

浏览器截图会同时复制到 ``docs/screenshots/t17/assistant-order/``，便于报告
长期引用。任何失败都会以中文输出并以非零退出码结束；浏览器不可用时明确
记录失败，不会把 Mock 引擎结果当作真实浏览器成功。

用法::

    cd C:/Users/cc/Desktop/服装平台项目
    backend/.venv/Scripts/python.exe scripts/e2e_full_mock.py
    # 可选参数
    backend/.venv/Scripts/python.exe scripts/e2e_full_mock.py \
        --base-url http://127.0.0.1:8000 --no-copy-screenshots

退出码：0 = 全链路通过；1 = 业务断言失败；2 = 后端不可达。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, parse, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
SCREENSHOTS_SRC = BACKEND_DIR / "runtime" / "screenshots"
DOCS_T17 = PROJECT_ROOT / "docs" / "screenshots" / "t17"
SAMPLE_IMAGE = BACKEND_DIR / "app" / "static" / "images" / "samples" / "outfit-demo.webp"
PRODUCT_IMAGE_DIR = BACKEND_DIR / "app" / "static" / "images" / "products"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
PASSWORD = "t17-pass-123456"
FIVE_AGENTS = {"fashion", "art", "aesthetics", "price", "comfort"}
FIVE_AGENT_NAMES = {"fashion", "art", "aesthetics", "price", "comfort"}
ORDER_RE = re.compile(r"YJ\d{18}")
SHIPPING = {
    "name": "T17 全链路收货人",
    "phone": "13800000000",
    "address": "上海市黄浦区云裳路 88 号 衣见公寓 3 栋 501（演示地址）",
}


class StepFailure(AssertionError):
    """业务断言失败。"""


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise StepFailure(message)


# --------------------------------------------------------------------- HTTP
def http(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json_body: Any | None = None,
    data: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 60.0,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    headers: dict[str, str] = {"Accept": "application/json"}
    body = data
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    elif content_type:
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


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
    return str(payload)[:300]


@dataclass
class Api:
    base_url: str
    token: str | None = None

    def url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def call_json(
        self,
        method: str,
        path: str,
        *,
        payload: Any | None = None,
        token: str | None = None,
        timeout: float = 60.0,
        expected: int = 200,
    ) -> Any:
        status, _, raw = http(
            method,
            self.url(path),
            token=self.token if token is None else token,
            json_body=payload,
            timeout=timeout,
        )
        body = as_json(raw)
        expect(
            status == expected,
            f"{method} {path} 期望 HTTP {expected}，实际 {status}：{detail_of(body) if body is not None else raw[:200]!r}",
        )
        return body

    def get(self, path: str, *, token: str | None = None, timeout: float = 60.0) -> Any:
        return self.call_json("GET", path, token=token, timeout=timeout)

    def post(
        self,
        path: str,
        payload: Any | None = None,
        *,
        token: str | None = None,
        timeout: float = 60.0,
        expected: int = 200,
    ) -> Any:
        return self.call_json(
            "POST", path, payload=payload, token=token, timeout=timeout, expected=expected
        )

    def delete(self, path: str, *, timeout: float = 60.0) -> Any:
        return self.call_json("DELETE", path, timeout=timeout)

    def post_multipart(
        self,
        path: str,
        *,
        fields: dict[str, str],
        file_field: str,
        filename: str,
        file_bytes: bytes,
        file_content_type: str,
        timeout: float = 120.0,
    ) -> tuple[Any, dict[str, str]]:
        data, content_type = multipart(
            fields, {file_field: (filename, file_bytes, file_content_type)}
        )
        status, headers, raw = http(
            "POST",
            self.url(path),
            token=self.token,
            data=data,
            content_type=content_type,
            timeout=timeout,
        )
        body = as_json(raw)
        expect(
            status == 200,
            f"POST {path} 期望 HTTP 200，实际 {status}：{detail_of(body) if body is not None else raw[:200]!r}",
        )
        return body, headers

    def post_sse(
        self,
        path: str,
        *,
        payload: Any | None = None,
        data: bytes | None = None,
        content_type: str | None = None,
        timeout: float = 240.0,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        status, headers, raw = http(
            "POST",
            self.url(path),
            token=self.token,
            json_body=payload,
            data=data,
            content_type=content_type,
            timeout=timeout,
            extra_headers={"Accept": "text/event-stream"},
        )
        text = raw.decode("utf-8", errors="replace")
        if status != 200:
            expect(False, f"POST {path} 期望 HTTP 200，实际 {status}：{text[:300]}")
        expect(
            headers.get("content-type", "").startswith("text/event-stream"),
            f"POST {path} Content-Type 不是 SSE：{headers.get('content-type')!r}",
        )
        expect(
            headers.get("x-accel-buffering") == "no",
            "SSE 缺少 X-Accel-Buffering: no",
        )
        return parse_sse(text), headers


# ------------------------------------------------------------------ helpers
def multipart(
    fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]
) -> tuple[bytes, str]:
    boundary = f"----yijian-t17-{uuid.uuid4().hex}"
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


def parse_sse(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        event = "message"
        event_id: str | None = None
        data_lines: list[str] = []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            value = value.lstrip(" ")
            if field == "event":
                event = value
            elif field == "data":
                data_lines.append(value)
            elif field == "id":
                event_id = value
        if data_lines:
            payload = "\n".join(data_lines)
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise StepFailure(f"SSE 事件 {event} 数据不是合法 JSON：{payload[:200]}") from exc
            events.append({"event": event, "id": event_id, "data": parsed})
    return events


def events_named(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [item["data"] for item in events if item["event"] == name]


def first_event(events: list[dict[str, Any]], name: str) -> dict[str, Any]:
    found = events_named(events, name)
    expect(bool(found), f"缺少 SSE 事件 {name}；实际事件：{[item['event'] for item in events]}")
    return found[0]


def assert_event_ids(events: list[dict[str, Any]], label: str) -> None:
    ids = [item["id"] for item in events]
    expect(
        ids == [str(index) for index in range(1, len(events) + 1)],
        f"{label} SSE id 未从 1 连续递增：{ids[:10]}…",
    )


def read_sample_image() -> bytes:
    expect(SAMPLE_IMAGE.exists(), f"样例图不存在：{SAMPLE_IMAGE}")
    return SAMPLE_IMAGE.read_bytes()


# -------------------------------------------------------------------- steps
@dataclass
class Runner:
    api: Api
    results: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    def step(self, name: str, action) -> Any:
        started = time.perf_counter()
        try:
            detail = action()
            elapsed = int((time.perf_counter() - started) * 1000)
            self.results.append(
                {"name": name, "ok": True, "detail": str(detail or "OK"), "ms": elapsed}
            )
            print(f"[PASS] {name}（{elapsed}ms）{detail if detail else ''}")
            return detail
        except Exception as exc:  # noqa: BLE001 - E2E runner catches everything
            elapsed = int((time.perf_counter() - started) * 1000)
            message = f"{type(exc).__name__}: {exc}"
            self.results.append(
                {"name": name, "ok": False, "detail": message, "ms": elapsed}
            )
            print(f"[FAIL] {name}（{elapsed}ms）→ {message}")
            raise

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [item for item in self.results if not item["ok"]]

    def summary(self) -> int:
        total = len(self.results)
        passed = total - len(self.failures)
        print("\n" + "=" * 70)
        print(f"T17 全链路摘要：通过 {passed}/{total}，失败 {len(self.failures)}")
        for item in self.failures:
            print(f"  [FAIL] {item['name']}：{item['detail']}")
        print("=" * 70)
        return 0 if not self.failures else 1


def login_demo(api: Api) -> dict[str, Any]:
    auth = api.post(
        "/api/auth/login",
        {"username": "demo", "password": "demo123"},
        token="",
    )
    expect(auth.get("access_token"), "demo 登录未返回 access_token")
    expect(auth.get("user", {}).get("username") == "demo", "demo 登录用户不匹配")
    api.token = auth["access_token"]
    return auth


def register_once(api: Api) -> dict[str, Any]:
    username = f"t17_{int(time.time())}_{uuid.uuid4().hex[:5]}"
    auth = api.post(
        "/api/auth/register",
        {"username": username, "password": PASSWORD, "nickname": "T17 全链路测试员"},
        token="",
    )
    expect(auth.get("access_token"), "注册未返回 access_token")
    me = api.get("/api/auth/me", token=auth["access_token"])
    expect(me.get("username") == username, "注册后 /api/auth/me 用户名不一致")
    return {"username": username, "id": auth["user"]["id"]}


def pick_product(api: Api) -> dict[str, Any]:
    listing = api.get("/api/products?" + parse.urlencode({"q": "风衣"}))
    expect(listing.get("total", 0) >= 1, "搜索「风衣」没有结果")
    items = listing.get("items") or []
    trench = next(
        (item for item in items if item.get("name") == "暮色长风衣"),
        items[0],
    )
    expect("风衣" in (trench.get("name") or ""), f"风衣搜索结果异常：{trench.get('name')}")
    detail = api.get(f"/api/products/{trench['id']}")
    expect(detail.get("id") == trench["id"], "商品详情 id 不一致")
    expect(detail.get("sizes") and detail.get("colors"), "商品缺少尺码/颜色")
    expect((detail.get("image") or "").startswith("/static/"), "商品图不是本地静态路径")
    return detail


def run_small_models(api: Api) -> dict[str, Any]:
    status = api.get("/api/small-models/status")
    expect(status.get("mode") == "stub", f"小模型 mode 异常：{status.get('mode')}")
    expect(status.get("vision", {}).get("dim") == 256, "视觉模型的 dim 不是 256")
    expect(status.get("vision", {}).get("backend") == "stub", "视觉模型 backend 不是 stub")
    expect(status.get("nlp_kg", {}).get("metric") == "chebyshev", "NLP-KG 度量不是 chebyshev")
    expect(
        status.get("nlp_kg", {}).get("warm_up", {}).get("product_count") == 16,
        "小模型预热的商品数不是 16",
    )

    cheb = api.post(
        "/api/small-models/kg/chebyshev", {"a": [1, 5], "b": [3, 2]}, token=""
    )
    expect(abs(cheb.get("distance", -1) - 3.0) < 1e-9, f"切比雪夫距离不是 3.0：{cheb}")
    expect(abs(cheb.get("similarity", -1) - 0.25) < 1e-9, f"相似度不是 0.25：{cheb}")

    image = read_sample_image()
    embed, _ = api.post_multipart(
        "/api/small-models/vision/embed",
        fields={},
        file_field="file",
        filename="outfit-demo.webp",
        file_bytes=image,
        file_content_type="image/webp",
    )
    expect(embed.get("dim") == 256, f"embedding dim 异常：{embed.get('dim')}")
    expect(len(embed.get("embedding") or []) == 256, "embedding 长度不是 256")
    expect(embed.get("backend") == "stub", f"embedding backend 异常：{embed.get('backend')}")

    similar, _ = api.post_multipart(
        "/api/small-models/vision/similar?" + parse.urlencode({"top_k": "5"}),
        fields={},
        file_field="file",
        filename="outfit-demo.webp",
        file_bytes=image,
        file_content_type="image/webp",
    )
    matches = similar.get("matches") or []
    expect(bool(matches), "以图搜衣没有返回 matches")
    distances = [item.get("distance") for item in matches]
    expect(distances == sorted(distances), f"matches 未按距离升序：{distances}")
    expect(similar.get("backend") == "stub", f"similar backend 异常：{similar.get('backend')}")

    kg_query = api.post(
        "/api/small-models/kg/query", {"text": "通勤真丝衬衫", "top_k": 6}, token=""
    )
    expect(bool(kg_query.get("products")), "KG 查询没有返回商品")
    expect(isinstance(kg_query.get("triples"), list), "KG 查询 triples 不是数组")

    graph = api.get("/api/small-models/kg/graph?" + parse.urlencode({"limit": 40}))
    expect(graph.get("metric") == "chebyshev", "图谱度量不是 chebyshev")
    expect(bool(graph.get("nodes")), "知识图谱没有节点")
    expect(bool(graph.get("edges")), "知识图谱没有边")
    expect(
        any(node.get("type") == "product" for node in graph.get("nodes", [])),
        "知识图谱缺少 product 节点",
    )
    return {
        "vision_dim": embed["dim"],
        "chebyshev": cheb,
        "similar_top": matches[0].get("product", {}).get("name") if matches else "",
        "kg_nodes": len(graph.get("nodes", [])),
        "kg_edges": len(graph.get("edges", [])),
    }


def run_stylist(api: Api) -> dict[str, Any]:
    image = read_sample_image()
    data, content_type = multipart(
        {"budget": "3000", "note": "T17 通勤"},
        {"file": ("outfit-demo.webp", image, "image/webp")},
    )
    events, _ = api.post_sse(
        "/api/recommend/image", data=data, content_type=content_type, timeout=240.0
    )
    assert_event_ids(events, "荐衣")
    names = [item["event"] for item in events]
    for required in (
        "session",
        "stage",
        "vision",
        "candidates",
        "kg",
        "agent_round",
        "agent_message",
        "revision",
        "final",
        "done",
    ):
        expect(required in names, f"荐衣 SSE 缺少事件 {required}：{names}")

    session_event = first_event(events, "session")
    session_id = session_event.get("session_id")
    expect(bool(session_id), "session 事件缺少 session_id")
    expect(session_event.get("mode") == "mock", "session.mode 不是 mock")
    expect(
        [stage.get("stage") for stage in session_event.get("stages", [])]
        == ["vision", "retrieval", "round1", "round2", "aggregate"],
        f"阶段列表异常：{session_event.get('stages')}",
    )

    candidates = first_event(events, "candidates")
    expect(candidates.get("metric") == "chebyshev", "候选度量不是 chebyshev")
    expect(candidates.get("backend") != "fallback", "候选检索降级到了 fallback")
    candidate_items = candidates.get("items") or []
    expect(5 <= len(candidate_items) <= 12, f"候选数量异常：{len(candidate_items)}")
    candidate_ids = {item["id"] for item in candidate_items}

    rounds = [item["data"]["round"] for item in events if item["event"] == "agent_round"]
    expect(rounds == [1, 2], f"智能体轮次异常：{rounds}")

    messages = events_named(events, "agent_message")
    round1 = [item for item in messages if item.get("round") == 1]
    round2 = [item for item in messages if item.get("round") == 2]
    expect(len(round1) == 5, f"Round 1 应有 5 条发言，实际 {len(round1)}")
    expect(len(round2) == 5, f"Round 2 应有 5 条发言，实际 {len(round2)}")
    expect({item.get("agent") for item in round1} == FIVE_AGENTS, "Round 1 未覆盖五个智能体")
    expect({item.get("agent") for item in round2} == FIVE_AGENTS, "Round 2 未覆盖五个智能体")
    for message in messages:
        expect(bool(message.get("agent_name")), "消息缺少 agent_name")
        expect(
            message.get("message_type") in {"opinion", "critique", "revision"},
            f"消息类型异常：{message.get('message_type')}",
        )
    expect(
        all(item.get("scores") for item in round1), "Round 1 存在没有 scores 的智能体"
    )
    expect(
        all(
            score.get("product_id") in candidate_ids
            for item in round1
            for score in item.get("scores", [])
        ),
        "Round 1 评分引用了候选之外的商品",
    )
    expect(
        all(item.get("recipients") for item in round2), "Round 2 必须向具名同伴发言"
    )
    expect(
        any(item.get("message_type") == "revision" for item in round2),
        "Round 2 没有 revision 类型消息",
    )

    revisions = events_named(events, "revision")
    expect(bool(revisions), "缺少 revision 事件")
    for revision in revisions:
        expect(revision.get("agent") in FIVE_AGENTS, f"revision agent 异常：{revision}")
        expect(revision.get("product_id") in candidate_ids, "revision 商品不在候选中")
        expect(bool(revision.get("reason")), "revision 缺少中文理由")

    final = first_event(events, "final")
    expect(final.get("session_id") == session_id, "final.session_id 不一致")
    expect(final.get("mode") == "mock", "final.mode 不是 mock")
    recommendations = final.get("recommendations") or []
    expect(len(recommendations) == 3, f"Top3 数量异常：{len(recommendations)}")
    expect(
        len({item.get("product", {}).get("id") for item in recommendations}) == 3,
        "Top3 存在重复商品",
    )
    for item in recommendations:
        expect(
            set((item.get("agent_scores") or {}).keys()) == FIVE_AGENT_NAMES,
            "推荐项缺少五智能体评分",
        )
        expect(bool(item.get("reasons")), "推荐项缺少中文理由")
    expect(bool(final.get("outfit")), "final 缺少整套穿搭")
    expect(final.get("outfit_total", 0) > 0, "整套穿搭金额异常")
    expect(bool(final.get("advice")), "final 缺少中文建议")
    expect(final.get("kg", {}).get("metric") == "chebyshev", "final.kg 度量不是 chebyshev")

    done = first_event(events, "done")
    expect(done.get("session_id") == session_id, "done.session_id 不一致")

    detail = api.get(f"/api/recommend/sessions/{session_id}")
    expect(detail.get("session", {}).get("status") == "done", "荐衣会话未落库为 done")
    expect(
        len(detail.get("messages") or []) >= 10, "荐衣会话落库消息少于 10 条"
    )
    expect(
        bool((detail.get("result") or {}).get("recommendations")),
        "荐衣会话结果缺少 recommendations",
    )
    return {
        "session_id": session_id,
        "candidates": len(candidate_items),
        "messages": len(messages),
        "revisions": len(revisions),
        "top3": [item["product"]["name"] for item in recommendations],
        "outfit_total": final.get("outfit_total"),
    }


def run_assistant_recommend(api: Api) -> dict[str, Any]:
    events, _ = api.post_sse(
        "/api/assistant/chat", payload={"message": "我想买风衣"}, timeout=120.0
    )
    assert_event_ids(events, "助理推荐")
    names = [item["event"] for item in events]
    expect(names[0] == "session", f"SSE 首事件不是 session：{names}")
    expect(names[1] == "intent", f"SSE 第二事件不是 intent：{names}")
    intent = first_event(events, "intent")
    expect(intent.get("intent") == "recommend", f"意图不是 recommend：{intent}")
    products = first_event(events, "products")
    cards = products.get("items") or []
    expect(bool(cards), "商品卡事件没有 items")
    expect(
        any(item.get("product", {}).get("name") == "暮色长风衣" for item in cards),
        "商品卡中没有「暮色长风衣」",
    )
    for card in cards:
        expect(
            str(card.get("platform_url", "")).startswith("/product/"),
            f"platform_url 异常：{card.get('platform_url')}",
        )
        expect(
            str(card.get("mall_url", "")).startswith("/demo-mall/product.html?id="),
            f"mall_url 异常：{card.get('mall_url')}",
        )
    expect("order_created" not in names, "仅推荐不应创建订单")
    expect("error" not in names, f"推荐流出现 error：{events_named(events, 'error')}")
    done = first_event(events, "done")
    expect(done.get("status") == "done", f"推荐流 done 状态异常：{done}")
    return {
        "session_id": first_event(events, "session").get("session_id"),
        "cards": [item["product"]["name"] for item in cards],
        "reply": first_event(events, "assistant_message").get("content", "")[:80],
    }


def run_assistant_order(api: Api, session_id: str, product: dict[str, Any]) -> dict[str, Any]:
    events, _ = api.post_sse(
        "/api/assistant/chat",
        payload={"message": "帮我下单风衣，M 码", "session_id": session_id},
        timeout=300.0,
    )
    assert_event_ids(events, "助理下单")
    names = [item["event"] for item in events]
    session_event = first_event(events, "session")
    engine = str(session_event.get("engine") or "")
    expect(
        engine and engine != "mock",
        f"浏览器引擎为 {engine or '未知'}，不能视为真实浏览器成功",
    )
    expect("error" not in names, f"下单流出现 error：{events_named(events, 'error')}")

    steps = events_named(events, "browse_step")
    expect(len(steps) >= 6, f"浏览器步骤少于 6 步：{len(steps)}")
    expect(
        all(step.get("status") in ("done", "failed") for step in steps),
        "浏览器步骤存在非终态状态",
    )
    failed = [step for step in steps if step.get("status") == "failed"]
    expect(not failed, f"浏览器步骤失败：{[step.get('detail') for step in failed]}")

    shot_urls = [step.get("screenshot") for step in steps if step.get("screenshot")]
    expect(len(shot_urls) >= 6, f"带截图的步骤不足 6 步：{len(shot_urls)}")
    shot_files: list[Path] = []
    for url in shot_urls:
        expect(
            str(url).startswith(f"/screenshots/{session_id}/"),
            f"截图 URL 不属于当前会话：{url}",
        )
        path = SCREENSHOTS_SRC / session_id / Path(str(url)).name
        expect(path.exists() and path.stat().st_size > 1000, f"截图文件缺失或过小：{path}")
        status, headers, raw = http("GET", api.url(str(url)), token="", timeout=30.0)
        expect(status == 200, f"截图 URL 不可访问（HTTP {status}）：{url}")
        expect(
            headers.get("content-type", "").startswith("image/"),
            f"截图 URL Content-Type 异常：{headers.get('content-type')}",
        )
        expect(len(raw) > 1000, f"截图 URL 返回内容过小：{url}")
        shot_files.append(path)

    created = first_event(events, "order_created")
    order_no = created.get("order_no")
    expect(bool(order_no and ORDER_RE.fullmatch(order_no)), f"订单号格式异常：{order_no}")
    expect(created.get("source") == "agent", f"order_created.source 异常：{created.get('source')}")
    expect(created.get("session_id") == session_id, "order_created.session_id 不一致")
    expect(
        abs(float(created.get("total", 0)) - float(product["price"])) < 0.01,
        f"下单金额与商品价格不一致：{created.get('total')} vs {product['price']}",
    )
    done = first_event(events, "done")
    expect(done.get("status") == "done", f"下单流 done 状态异常：{done}")

    orders = api.get("/api/orders")
    order = next((item for item in orders if item.get("order_no") == order_no), None)
    expect(order is not None, f"订单列表找不到 {order_no}")
    expect(order.get("source") == "agent", f"订单来源不是 agent：{order.get('source')}")
    expect(order.get("status") == "paid", f"订单状态不是 paid：{order.get('status')}")
    expect(
        any(item.get("name") == product["name"] for item in order.get("items", [])),
        "订单明细缺少所购商品",
    )

    detail = api.get(f"/api/assistant/sessions/{session_id}")
    expect(detail.get("session", {}).get("status") == "done", "助理会话未落库为 done")
    task = detail.get("browse_task") or {}
    expect(task.get("status") == "done", f"浏览任务未落库为 done：{task.get('status')}")
    expect(task.get("order_no") == order_no, "浏览任务订单号不一致")
    expect(len(task.get("steps") or []) >= 6, "浏览任务落库步骤少于 6 步")

    return {
        "session_id": session_id,
        "engine": engine,
        "order_no": order_no,
        "total": created.get("total"),
        "steps": len(steps),
        "shot_files": [str(path) for path in shot_files],
    }


def copy_screenshots(session_id: str) -> dict[str, Any]:
    src = SCREENSHOTS_SRC / session_id
    expect(src.exists(), f"浏览器截图目录不存在：{src}")
    DOCS_T17.mkdir(parents=True, exist_ok=True)
    dest = DOCS_T17 / "assistant-order"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    files = sorted(src.glob("*.png"))
    expect(bool(files), f"截图目录为空：{src}")
    for path in files:
        shutil.copy2(path, dest / path.name)
    success = dest / files[-1].name
    shutil.copy2(files[-1], DOCS_T17 / "assistant-order-success.png")
    return {
        "dir": str(dest),
        "success": str(DOCS_T17 / "assistant-order-success.png"),
        "files": [path.name for path in files],
    }


# --------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T17 无 Key 全链路 E2E（Mock + 真实浏览器）")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--no-copy-screenshots", action="store_true", help="不复制截图到 docs/screenshots/t17"
    )
    args = parser.parse_args(argv)
    api = Api(args.base_url.rstrip("/"))
    runner = Runner(api)

    print("衣见 ATELIER · T17 无 Key 全链路 E2E")
    print(f"目标：{api.base_url}  样例图：{SAMPLE_IMAGE}")
    print("大模型：Mock（无 DASHSCOPE_API_KEY）；小模型：stub；浏览器：后端 Playwright/Edge\n")

    try:
        runner.step(
            "0. 后端健康检查 / Mock 元信息",
            lambda: _check_meta(api),
        )
        runner.step(
            "1. 注册一次性账号 / 登录 demo",
            lambda: _auth_flow(api),
        )
        product = runner.step("2. 商品搜索与详情", lambda: pick_product(api))
        runner.step("3. 加入购物车", lambda: _cart(api, product))
        platform_order = runner.step("4. 平台结算与订单列表", lambda: _checkout(api, product))
        small = runner.step("5. 小模型 status / embed / similar / chebyshev / KG", lambda: run_small_models(api))
        stylist = runner.step("6. 样品图五智能体 SSE（两轮 / revision / final）", lambda: run_stylist(api))
        recommend = runner.step("7. 助理「我想买风衣」商品卡", lambda: run_assistant_recommend(api))
        order = runner.step(
            "8. 助理「帮我下单风衣」真实浏览器下单",
            lambda: run_assistant_order(api, recommend["session_id"], product),
        )
        if not args.no_copy_screenshots:
            copied = runner.step(
                "9. 截图归档到 docs/screenshots/t17",
                lambda: copy_screenshots(order["session_id"]),
            )
            runner.artifacts["screenshots"] = copied
    except Exception:  # noqa: BLE001 - 已由 Runner.step 记录，直接输出摘要
        return runner.summary()

    runner.artifacts.update(
        {
            "demo_user": "demo",
            "platform_order_no": platform_order["order_no"],
            "small_models": small,
            "stylist": stylist,
            "assistant_recommend": recommend,
            "assistant_order": {
                key: value
                for key, value in order.items()
                if key != "shot_files"
            },
            "browser_screenshots": order["shot_files"],
        }
    )
    report_path = DOCS_T17 / "e2e-report.json"
    try:
        DOCS_T17.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(runner.artifacts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"机器可读结果：{report_path}")
    except OSError as exc:  # pragma: no cover
        print(f"提示：e2e-report.json 写入失败：{exc}")

    return runner.summary()


def _check_meta(api: Api) -> str:
    health = api.get("/api/health", token="")
    expect(health.get("status") == "ok", f"health 异常：{health}")
    meta = api.get("/api/meta", token="")
    expect(meta.get("mode") == "mock", f"/api/meta mode 必须是 mock，实际 {meta.get('mode')}")
    expect(meta.get("features", {}).get("qwen") is False, "features.qwen 应为 false")
    expect(meta.get("small_model_mode") == "stub", "small_model_mode 应为 stub")
    return f"mode=mock, llm_mode={meta.get('llm_mode')}, small_model={meta.get('small_model_mode')}"


def _auth_flow(api: Api) -> str:
    registered = register_once(api)
    login_demo(api)
    return f"注册 {registered['username']} OK，已登录 demo"


def _cart(api: Api, product: dict[str, Any]) -> str:
    api.delete("/api/cart")
    cart = api.post(
        "/api/cart",
        {
            "product_id": product["id"],
            "quantity": 1,
            "size": product["sizes"][0],
            "color": product["colors"][0],
        },
    )
    expect(cart.get("total_quantity") == 1, f"购物车数量异常：{cart.get('total_quantity')}")
    expect(
        abs(float(cart.get("total_amount", 0)) - float(product["price"])) < 0.01,
        "购物车金额异常",
    )
    expect(bool(cart.get("items")), "购物车没有 items")
    return f"{product['name']} × 1，合计 ¥{cart['total_amount']}"


def _checkout(api: Api, product: dict[str, Any]) -> dict[str, Any]:
    order = api.post(
        "/api/orders",
        {"shipping": SHIPPING, "note": "T17 无 Key 全链路 E2E（模拟支付）"},
    )
    expect(bool(ORDER_RE.fullmatch(order.get("order_no", ""))), f"订单号格式异常：{order.get('order_no')}")
    expect(order.get("status") == "paid", f"订单状态异常：{order.get('status')}")
    expect(order.get("source") == "platform", f"平台订单来源异常：{order.get('source')}")
    expect(
        any(item.get("name") == product["name"] for item in order.get("items", [])),
        "订单明细缺少商品",
    )
    cart = api.get("/api/cart")
    expect(cart.get("items") == [], "结算后购物车未清空")
    orders = api.get("/api/orders")
    expect(
        any(item.get("id") == order["id"] for item in orders),
        "订单列表缺少新订单",
    )
    detail = api.get(f"/api/orders/{order['id']}")
    expect(detail.get("order_no") == order["order_no"], "订单详情不一致")
    return order


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    sys.exit(main())
