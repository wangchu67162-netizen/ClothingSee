"""T11 全链路集成测试（Mock 模式，无 DASHSCOPE_API_KEY）。

与各任务自带的单元测试不同，本文件通过真实的 ``app.main:app`` 路由栈运行：

* 使用临时 SQLite 数据库（依赖覆盖 ``get_db``），种子数据由 ``seed_if_empty`` 生成；
* 小模型工厂指向同一临时库并执行 ``warm_up``，因此图片检索/知识图谱使用真实 stub；
* 浏览器引擎强制为 ``mock``（测试注入），但订单仍由 ``create_agent_order`` 真实落库；
* 五智能体荐衣走真实 SSE 路由与真实 Mock LLM，校验五智能体 / 两轮 / final。

不访问网络、不需要 API Key，测试结束后清理上传文件与依赖覆盖。
"""
from __future__ import annotations

import base64
import io
import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    AgentMessage,
    AgentSession,
    BrowseTask,
    Order,
    Product,
    User,
)
from app.seed import DEMO_ORDER_NO, seed_if_empty
from app.small_models import factory as small_factory
import app.services.assistant as assistant_service

PASSWORD = "secret123"
FIVE_AGENTS = {"fashion", "art", "aesthetics", "price", "comfort"}
SHIPPING = {
    "name": "集成测试收货人",
    "phone": "13800000000",
    "address": "上海市测试路 1 号 衣见大厦",
}
# 1x1 透明 PNG（仅用于需要合法图片的接口）。
PNG_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


# --------------------------------------------------------------------- fixture
@pytest.fixture()
def env(tmp_path, monkeypatch):
    """临时数据库 + Mock 大模型 + Mock 浏览器 + 真实路由栈。"""
    engine = create_engine(
        f"sqlite:///{(tmp_path / 't11-integration.db').as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    with Session() as db:
        seed_if_empty(db)

    # 无 Key → Mock；浏览器走测试注入引擎；assistant 内部落库指向临时库。
    monkeypatch.setattr(settings, "llm_mode", "mock", raising=False)
    monkeypatch.setattr(settings, "dashscope_api_key", "", raising=False)
    monkeypatch.setattr(settings, "browser_engine", "mock", raising=False)
    monkeypatch.setattr(assistant_service, "SessionLocal", Session)
    monkeypatch.setattr(small_factory, "SessionLocal", Session)

    small_factory.reset_models()
    warm = small_factory.warm_up()
    assert warm["ok"] is True, warm
    assert warm["product_count"] == 16

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    uploads_before = set(settings.uploads_dir.glob("stylist-*"))
    client = TestClient(app)
    try:
        yield SimpleNamespace(
            client=client,
            Session=Session,
            engine=engine,
            uploads_before=uploads_before,
        )
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)
        for path in set(settings.uploads_dir.glob("stylist-*")) - uploads_before:
            path.unlink(missing_ok=True)
        small_factory.reset_models()
        engine.dispose()


# --------------------------------------------------------------------- helpers
def _register(client: TestClient, tag: str) -> tuple[str, dict]:
    username = f"t11_{tag}_{uuid.uuid4().hex[:6]}"
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD, "nickname": f"集成{tag}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return username, body


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _product(env, sku: str) -> Product:
    with env.Session() as db:
        product = db.scalar(select(Product).where(Product.sku == sku))
        assert product is not None, sku
        return product


def _product_image(env, sku: str) -> tuple[Product, bytes]:
    product = _product(env, sku)
    relative = product.image[len("/static/") :]
    path = settings.static_dir / relative
    assert path.exists(), path
    return product, path.read_bytes()


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
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
            events.append(
                {"event": event, "data": json.loads("\n".join(data_lines)), "id": event_id}
            )
    return events


def _event(events: list[dict], name: str) -> dict:
    for item in events:
        if item["event"] == name:
            return item["data"]
    raise AssertionError(f"缺少 SSE 事件 {name}：{[item['event'] for item in events]}")


def _add_cart(client, token, product_id, quantity=1, size="M", color=""):
    response = client.post(
        "/api/cart",
        json={
            "product_id": product_id,
            "quantity": quantity,
            "size": size,
            "color": color,
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------- 基础
def test_health_and_meta_mock_mode(env):
    health = env.client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    meta = env.client.get("/api/meta")
    assert meta.status_code == 200
    body = meta.json()
    assert body["app_name"] == "衣见 ATELIER"
    assert body["mode"] == "mock"
    assert body["llm_mode"] == "mock"
    assert body["small_model_mode"] == "stub"
    assert body["features"]["qwen"] is False
    assert body["features"]["browser_automation"] is True


def test_auth_register_login_me_logout(env):
    client = env.client

    unauth = client.get("/api/auth/me")
    assert unauth.status_code == 401
    assert unauth.json()["detail"] == "请先登录"

    username, registered = _register(client, "auth")
    token = registered["access_token"]
    assert registered["user"]["username"] == username

    me = client.get("/api/auth/me", headers=_headers(token))
    assert me.status_code == 200
    assert me.json()["id"] == registered["user"]["id"]

    duplicate = client.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD},
    )
    assert duplicate.status_code == 409
    assert "已被注册" in duplicate.json()["detail"]

    login = client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert login.status_code == 200
    assert login.json()["access_token"]

    bad = client.post(
        "/api/auth/login", json={"username": username, "password": "wrong-pass"}
    )
    assert bad.status_code == 401
    assert bad.json()["detail"] == "用户名或密码错误"

    logout = client.post("/api/auth/logout", headers=_headers(token))
    assert logout.status_code == 200
    assert logout.json() == {"ok": True}


# --------------------------------------------------------------------- 商品
def test_products_search_detail_and_sort(env):
    client = env.client

    listing = client.get("/api/products").json()
    assert listing["total"] == 16
    assert len(listing["items"]) == 12
    assert listing["pages"] == 2

    silk = client.get("/api/products", params={"q": "真丝"}).json()
    assert silk["total"] == 4
    assert all(
        "真丝" in item["name"] + item["subtitle"] + item["description"]
        or "真丝" in "".join(item["style_tags"])
        for item in silk["items"]
    )

    accessory = client.get(
        "/api/products", params={"q": "真丝", "category": "配饰"}
    ).json()
    assert accessory["total"] == 2

    price_asc = client.get("/api/products", params={"sort": "price_asc"}).json()
    prices = [item["price"] for item in price_asc["items"]]
    assert prices == sorted(prices)

    bad_sort = client.get("/api/products", params={"sort": "unknown"})
    assert bad_sort.status_code == 400
    assert "排序" in bad_sort.json()["detail"]

    categories = client.get("/api/products/categories").json()
    assert [item["name"] for item in categories] == ["外套", "上装", "连衣裙", "下装", "配饰"]
    assert sum(item["count"] for item in categories) == 16

    trench = _product(env, "ys-ow-001")
    detail = client.get(f"/api/products/{trench.id}")
    assert detail.status_code == 200
    assert detail.json()["name"] == trench.name

    missing = client.get("/api/products/999999")
    assert missing.status_code == 404
    assert "商品不存在" in missing.json()["detail"]


def test_search_by_image_ranks_exact_product_first(env):
    product, image = _product_image(env, "ys-ow-001")
    response = env.client.post(
        "/api/products/search-by-image",
        data={"top_k": "3"},
        files={"file": ("query.webp", image, "image/webp")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["distance_metric"] == "chebyshev"
    assert body["backend"] != "fallback"
    assert body["items"], "应返回相似商品"
    assert body["items"][0]["sku"] == product.sku
    assert body["items"][0]["similarity"] == pytest.approx(1.0)
    similarities = [item["similarity"] for item in body["items"]]
    assert similarities == sorted(similarities, reverse=True)


# --------------------------------------------------------------------- 购物车
def test_cart_flow(env):
    client = env.client
    assert client.get("/api/cart").status_code == 401

    _, registered = _register(client, "cart")
    token = registered["access_token"]
    headers = _headers(token)
    shirt = _product(env, "ys-tp-001")

    added = _add_cart(client, token, shirt.id, quantity=1, size="M", color="月白")
    assert added["total_quantity"] == 1
    assert added["total_amount"] == pytest.approx(shirt.price)
    item_id = added["items"][0]["id"]

    merged = _add_cart(client, token, shirt.id, quantity=2, size="M", color="月白")
    assert len(merged["items"]) == 1
    assert merged["items"][0]["quantity"] == 3

    updated = client.patch(
        f"/api/cart/{item_id}", json={"quantity": 2}, headers=headers
    )
    assert updated.status_code == 200
    assert updated.json()["total_quantity"] == 2

    deleted = client.delete(f"/api/cart/{item_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["items"] == []

    _add_cart(client, token, shirt.id, quantity=1, size="M", color="月白")
    cleared = client.delete("/api/cart", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["items"] == []


# --------------------------------------------------------------------- 订单
def test_checkout_order_listing_and_cancel(env):
    client = env.client
    _, registered = _register(client, "order")
    token = registered["access_token"]
    headers = _headers(token)

    shirt = _product(env, "ys-tp-001")
    pants = _product(env, "ys-bt-001")
    _add_cart(client, token, shirt.id, quantity=2, size="M", color="月白")
    _add_cart(client, token, pants.id, quantity=1, size="M", color="流云灰")

    response = client.post(
        "/api/orders",
        json={"shipping": SHIPPING, "note": "集成测试订单"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    order = response.json()
    assert re.fullmatch(r"YJ\d{18}", order["order_no"])
    assert order["status"] == "paid"
    assert order["source"] == "platform"
    assert order["total"] == pytest.approx(shirt.price * 2 + pants.price)
    assert len(order["items"]) == 2
    assert order["shipping_name"] == SHIPPING["name"]

    cart = client.get("/api/cart", headers=headers).json()
    assert cart["items"] == []

    orders = client.get("/api/orders", headers=headers).json()
    assert [item["id"] for item in orders] == [order["id"]]
    assert all(item["order_no"] != DEMO_ORDER_NO for item in orders)

    detail = client.get(f"/api/orders/{order['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["order_no"] == order["order_no"]

    cancelled = client.post(f"/api/orders/{order['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    again = client.post(f"/api/orders/{order['id']}/cancel", headers=headers)
    assert again.status_code == 400

    empty = client.post(
        "/api/orders", json={"shipping": SHIPPING}, headers=headers
    )
    assert empty.status_code == 400
    assert "购物车" in empty.json()["detail"]


# --------------------------------------------------------------------- 小模型
def test_small_models_status_chebyshev_and_vision(env):
    client = env.client

    status = client.get("/api/small-models/status")
    assert status.status_code == 200
    body = status.json()
    assert body["mode"] == "stub"
    assert body["vision"]["dim"] == 256
    assert body["vision"]["backend"] == "stub"
    assert body["nlp_kg"]["metric"] == "chebyshev"
    assert body["nlp_kg"]["warm_up"]["product_count"] == 16

    chebyshev = client.post(
        "/api/small-models/kg/chebyshev", json={"a": [1, 5], "b": [3, 2]}
    )
    assert chebyshev.status_code == 200
    assert chebyshev.json()["distance"] == pytest.approx(3.0)
    assert chebyshev.json()["similarity"] == pytest.approx(0.25)

    mismatch = client.post(
        "/api/small-models/kg/chebyshev", json={"a": [1, 2], "b": [1]}
    )
    assert mismatch.status_code == 400
    assert "维度" in mismatch.json()["detail"]

    embed = client.post(
        "/api/small-models/vision/embed",
        files={"file": ("pixel.png", PNG_PIXEL, "image/png")},
    )
    assert embed.status_code == 200, embed.text
    assert embed.json()["dim"] == 256
    assert len(embed.json()["embedding"]) == 256

    broken = client.post(
        "/api/small-models/vision/embed",
        files={"file": ("broken.png", b"not-an-image", "image/png")},
    )
    assert broken.status_code == 400
    assert "图片" in broken.json()["detail"]


def test_small_models_similar_kg_query_and_graph(env):
    client = env.client
    product, image = _product_image(env, "ys-bt-001")

    similar = client.post(
        "/api/small-models/vision/similar?top_k=5",
        files={"file": ("query.webp", image, "image/webp")},
    )
    assert similar.status_code == 200, similar.text
    body = similar.json()
    assert body["matches"]
    assert body["matches"][0]["product"]["sku"] == product.sku
    distances = [item["distance"] for item in body["matches"]]
    assert distances == sorted(distances)

    query = client.post(
        "/api/small-models/kg/query",
        json={"text": "通勤真丝衬衫", "top_k": 6},
    )
    assert query.status_code == 200, query.text
    query_body = query.json()
    assert query_body["products"]
    assert isinstance(query_body["triples"], list)
    assert query_body["related_terms"]

    graph = client.get("/api/small-models/kg/graph?limit=80")
    assert graph.status_code == 200
    graph_body = graph.json()
    assert graph_body["metric"] == "chebyshev"
    assert graph_body["nodes"] and graph_body["edges"]
    assert any(edge["relation"] == "similar_to" for edge in graph_body["edges"])
    assert any(node["type"] == "product" for node in graph_body["nodes"])

    focused = client.get(f"/api/small-models/kg/graph?product_id={product.id}")
    assert focused.status_code == 200
    assert any(node["id"] == f"product:{product.id}" for node in focused.json()["nodes"])


# --------------------------------------------------------------------- 五智能体
def test_stylist_five_agents_two_rounds_and_final(env):
    client = env.client
    _, registered = _register(client, "stylist")
    token = registered["access_token"]

    product, image = _product_image(env, "ys-ow-001")
    response = client.post(
        "/api/recommend/image",
        files={"file": ("outfit.webp", image, "image/webp")},
        data={"budget": "3000", "note": "通勤"},
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers.get("x-accel-buffering") == "no"

    events = _parse_sse(response.text)
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
        assert required in names, f"缺少 SSE 事件：{required}"

    # 事件 id 严格递增。
    assert [item["id"] for item in events] == [
        str(index) for index in range(1, len(events) + 1)
    ]

    session_event = _event(events, "session")
    assert session_event["mode"] == "mock"
    session_id = session_event["session_id"]
    assert [stage["stage"] for stage in session_event["stages"]] == [
        "vision",
        "retrieval",
        "round1",
        "round2",
        "aggregate",
    ]

    candidates = _event(events, "candidates")
    assert 5 <= len(candidates["items"]) <= 12
    assert candidates["metric"] == "chebyshev"
    assert candidates["backend"] != "fallback"
    candidate_ids = {item["id"] for item in candidates["items"]}

    rounds = [item["data"]["round"] for item in events if item["event"] == "agent_round"]
    assert rounds == [1, 2]

    messages = [item["data"] for item in events if item["event"] == "agent_message"]
    round1 = [item for item in messages if item["round"] == 1]
    round2 = [item for item in messages if item["round"] == 2]
    assert {item["agent"] for item in round1} == FIVE_AGENTS
    assert {item["agent"] for item in round2} == FIVE_AGENTS
    assert len(round1) == len(round2) == 5
    for message in messages:
        assert message["agent_name"]
        assert message["message_type"] in {"opinion", "critique", "revision"}
        for recipient in message["recipients"]:
            assert recipient in FIVE_AGENTS
    assert all(item["scores"] for item in round1)
    assert all(
        score["product_id"] in candidate_ids
        for item in round1
        for score in item["scores"]
    )
    assert any(item["message_type"] == "revision" for item in round2)
    assert all(item["recipients"] for item in round2), "Round 2 必须向具名同伴发言"

    revisions = [item["data"] for item in events if item["event"] == "revision"]
    assert revisions, "Mock 模式应至少产生一次修订"
    for revision in revisions:
        assert revision["agent"] in FIVE_AGENTS
        assert revision["product_id"] in candidate_ids
        assert revision["reason"]

    final = _event(events, "final")
    assert final["session_id"] == session_id
    assert final["mode"] == "mock"
    assert len(final["recommendations"]) == 3
    assert len({item["product"]["id"] for item in final["recommendations"]}) == 3
    for item in final["recommendations"]:
        assert set(item["agent_scores"].keys()) == FIVE_AGENTS
        assert item["reasons"]
    assert final["outfit"], "必须返回整套穿搭"
    assert final["outfit_total"] > 0
    assert final["advice"]
    assert final["kg"]["metric"] == "chebyshev"

    done = _event(events, "done")
    assert done["session_id"] == session_id

    # 落库与回看。
    detail = client.get(f"/api/recommend/sessions/{session_id}", headers=_headers(token))
    assert detail.status_code == 200, detail.text
    assert detail.json()["session"]["status"] == "done"
    assert detail.json()["result"]["recommendations"]

    history = client.get("/api/recommend/history", headers=_headers(token))
    assert history.status_code == 200
    assert any(item["id"] == session_id for item in history.json())

    with env.Session() as db:
        session = db.get(AgentSession, session_id)
        assert session is not None
        assert session.kind == "stylist"
        assert session.status == "done"
        stored = (
            db.query(AgentMessage)
            .filter(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.seq.asc())
            .all()
        )
        assert len(stored) >= 10
        assert {item.agent for item in stored if item.round == 1} == FIVE_AGENTS
        assert any(item.round == 2 and item.recipients for item in stored)


# --------------------------------------------------------------------- 购物助理
def test_assistant_recommend_then_mock_browser_order(env):
    client = env.client
    _, registered = _register(client, "assistant")
    token = registered["access_token"]
    headers = _headers(token)

    recommend = client.post(
        "/api/assistant/chat",
        json={"message": "我想买一件适合秋天的风衣"},
        headers=headers,
    )
    assert recommend.status_code == 200, recommend.text
    events = _parse_sse(recommend.text)
    names = [item["event"] for item in events]
    assert names[0] == "session"
    assert names[1] == "intent"
    assert _event(events, "intent")["intent"] == "recommend"
    products_event = _event(events, "products")
    assert any(item["product"]["name"] == "暮色长风衣" for item in products_event["items"])
    assert "order_created" not in names
    assert names[-1] == "done"
    session_id = _event(events, "session")["session_id"]

    # 仅推荐不应产生任何订单。
    with env.Session() as db:
        assert db.query(Order).count() == 1  # 只有种子演示订单

    order_resp = client.post(
        "/api/assistant/chat",
        json={"message": "帮我下单暮色长风衣，M 码", "session_id": session_id},
        headers=headers,
    )
    assert order_resp.status_code == 200, order_resp.text
    order_events = _parse_sse(order_resp.text)
    order_names = [item["event"] for item in order_events]
    assert _event(order_events, "intent")["intent"] == "order"
    steps = [item["data"] for item in order_events if item["event"] == "browse_step"]
    assert len(steps) >= 6
    assert all(step["status"] in ("done", "failed") for step in steps)
    assert "error" not in order_names, (
        _event(order_events, "error") if "error" in order_names else ""
    )
    assert _event(order_events, "session")["session_id"] == session_id

    created = _event(order_events, "order_created")
    assert re.fullmatch(r"YJ\d{18}", created["order_no"])
    assert created["source"] == "agent"
    assert created["session_id"] == session_id
    trench = _product(env, "ys-ow-001")
    assert created["total"] == pytest.approx(trench.price)

    with env.Session() as db:
        order = db.scalar(
            select(Order).where(Order.external_ref == created["order_no"])
        )
        assert order is not None, "浏览器下单成功必须真实落库"
        assert order.source == "agent"
        assert order.status == "paid"
        assert order.user_id == registered["user"]["id"]
        assert order.agent_session_id == session_id
        assert len(order.items) == 1
        assert order.items[0].name == "暮色长风衣"
        assert order.items[0].size == "M"

        task = db.scalar(select(BrowseTask).where(BrowseTask.order_no == created["order_no"]))
        assert task is not None
        assert task.status == "done"
        assert len(task.steps or []) >= 6

        session = db.get(AgentSession, session_id)
        assert session is not None
        assert session.kind == "assistant"
        assert session.status == "done"
        assert session.result["order_no"] == created["order_no"]

    # 订单列表与助理会话回看。
    orders = client.get("/api/orders", headers=headers).json()
    assert any(
        item["order_no"] == created["order_no"] and item["source"] == "agent"
        for item in orders
    )

    detail = client.get(f"/api/assistant/sessions/{session_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["session"]["status"] == "done"
    assert detail_body["browse_task"]["status"] == "done"
    agents = [message["agent"] for message in detail_body["messages"]]
    assert "user" in agents and "assistant" in agents

    history = client.get("/api/assistant/history", headers=headers)
    assert history.status_code == 200
    assert any(item["id"] == session_id for item in history.json()["items"])


def test_assistant_browser_failure_never_fakes_order(env, monkeypatch):
    """浏览器不可用时必须报错，绝对不能伪造 order_created。"""
    from app.browser.base import BrowserUnavailable

    class FailingShopper:
        async def shop(self, request, on_step):
            raise BrowserUnavailable("无头浏览器不可用（T11 测试注入）")

    monkeypatch.setattr(
        assistant_service,
        "build_shopper",
        lambda engine, *, base_url, session_factory: FailingShopper(),
    )

    client = env.client
    _, registered = _register(client, "failorder")
    headers = _headers(registered["access_token"])

    response = client.post(
        "/api/assistant/chat",
        json={"message": "帮我下单暮色长风衣，M 码"},
        headers=headers,
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [item["event"] for item in events]
    assert "error" in names
    assert "order_created" not in names
    error = _event(events, "error")
    assert error["code"] == "browser_unavailable"
    assert "无头浏览器不可用" in error["message"]
    assert _event(events, "done")["status"] == "failed"

    with env.Session() as db:
        assert db.query(Order).count() == 1  # 仍只有种子订单
        task = db.query(BrowseTask).order_by(BrowseTask.id.desc()).first()
        assert task is not None
        assert task.status == "failed"
        assert task.order_no is None


# --------------------------------------------------------------------- 上传清理
def test_stylist_upload_is_written_outside_app(env):
    """拍照上传落在 runtime/uploads，而不是 app/ 源码目录。"""
    client = env.client
    _, registered = _register(client, "upload")
    image = io.BytesIO()
    Image.new("RGB", (64, 64), (120, 80, 60)).save(image, format="PNG")

    response = client.post(
        "/api/recommend/image",
        files={"file": ("outfit.png", image.getvalue(), "image/png")},
        data={"note": "约会"},
        headers=_headers(registered["access_token"]),
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    session_id = _event(events, "session")["session_id"]

    upload = Path(settings.uploads_dir) / f"stylist-{session_id}.png"
    assert upload.exists()
    assert settings.runtime_dir in upload.parents
    assert "app" not in upload.relative_to(settings.runtime_dir).parts
