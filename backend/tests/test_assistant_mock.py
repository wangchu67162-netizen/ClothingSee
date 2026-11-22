"""T5 tests: demo mall API + assistant SSE with the mock browser engine.

No real browser is launched here. ``BROWSER_ENGINE`` is patched to ``mock`` for
each test; the mock engine still writes a genuine ``Order``/``OrderItem`` through
the same order service used by the demo mall checkout API.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config as app_config
from app.browser.base import BrowserUnavailable
from app.catalog_data import PRODUCTS
from app.database import Base, get_db
from app.models import (
    AgentMessage,
    AgentSession,
    BrowseTask,
    Order,
    OrderItem,
    Product,
    User,
)
from app.routers import assistant as assistant_router
from app.routers import demo_mall as demo_mall_router
from app.security import create_access_token, hash_password
import app.services.assistant as assistant_service

MALL_DIR = Path(__file__).resolve().parents[1] / "app" / "demo_mall"
WINDOW_BREAKER = "暮色长风衣"


# --------------------------------------------------------------------- helpers
def parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in re.split(r"\r?\n\r?\n", text):
        event = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if event and data_lines:
            events.append((event, json.loads("\n".join(data_lines))))
    return events


def event_names(events: list[tuple[str, dict]]) -> list[str]:
    return [name for name, _ in events]


def first_event(events: list[tuple[str, dict]], name: str) -> dict:
    for event, data in events:
        if event == name:
            return data
    raise AssertionError(f"missing SSE event {name}: {event_names(events)}")


# -------------------------------------------------------------------- fixtures
@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 't5-test.db').as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    TestingSession = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    Base.metadata.create_all(engine)

    monkeypatch.setattr(assistant_service, "SessionLocal", TestingSession)
    monkeypatch.setattr(app_config.settings, "browser_engine", "mock")
    monkeypatch.setattr(app_config.settings, "llm_mode", "mock")

    with TestingSession() as db:
        user = User(
            username="demo",
            password_hash=hash_password("demo123"),
            nickname="云裳体验官",
        )
        db.add(user)
        db.flush()
        for item in PRODUCTS:
            payload = dict(item)
            payload["search_text"] = " ".join(
                [
                    payload["name"],
                    payload.get("subtitle", ""),
                    payload["category"],
                    *payload.get("style_tags", []),
                    payload.get("occasion", ""),
                ]
            )
            db.add(Product(**payload))
        db.commit()
        windbreaker = (
            db.query(Product).filter(Product.name == WINDOW_BREAKER).one()
        )
        user_id = user.id
        product_id = windbreaker.id
        product_price = float(windbreaker.price)

    app = FastAPI()
    app.include_router(assistant_router.router, prefix="/api")
    app.include_router(demo_mall_router.router)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    auth = {"Authorization": f"Bearer {create_access_token(user_id, 'demo')}"}

    yield SimpleNamespace(
        client=client,
        app=app,
        Session=TestingSession,
        user_id=user_id,
        product_id=product_id,
        product_price=product_price,
        auth=auth,
    )

    app.dependency_overrides.clear()
    engine.dispose()


# ----------------------------------------------------------------------- tests
def test_demo_mall_products_and_detail(ctx):
    response = ctx.client.get("/demo-mall/api/products", params={"q": "风衣"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    names = [item["name"] for item in payload["items"]]
    assert WINDOW_BREAKER in names
    item = next(item for item in payload["items"] if item["name"] == WINDOW_BREAKER)
    assert item["image"].startswith("/static/images/")
    assert item["price"] == ctx.product_price

    detail = ctx.client.get(f"/demo-mall/api/products/{ctx.product_id}")
    assert detail.status_code == 200
    assert detail.json()["name"] == WINDOW_BREAKER

    missing = ctx.client.get("/demo-mall/api/products/999999")
    assert missing.status_code == 404
    assert "商品不存在" in missing.json()["detail"]

    # Keyword search that matches no product returns an empty list, not a 404.
    empty = ctx.client.get("/demo-mall/api/products", params={"q": "潜水艇"})
    assert empty.status_code == 200
    assert empty.json()["items"] == []


def test_demo_mall_pages_and_selectors_are_stable():
    files = {
        "index": (MALL_DIR / "index.html").read_text(encoding="utf-8"),
        "product": (MALL_DIR / "product.html").read_text(encoding="utf-8"),
        "checkout": (MALL_DIR / "checkout.html").read_text(encoding="utf-8"),
        "success": (MALL_DIR / "success.html").read_text(encoding="utf-8"),
        "js": (MALL_DIR / "mall.js").read_text(encoding="utf-8"),
        "css": (MALL_DIR / "mall.css").read_text(encoding="utf-8"),
    }
    combined = "\n".join(files.values())

    for testid in (
        "mall-search",
        "mall-product-name",
        "mall-buy-now",
        "mall-place-order",
        "mall-order-no",
    ):
        assert f'data-testid="{testid}"' in combined, testid
    # Product cards are rendered by mall.js, so their test ids live there.
    assert 'data-testid="mall-product-card"' in files["js"]
    for field_id in ('id="ship-name"', 'id="ship-phone"', 'id="ship-address"'):
        assert field_id in files["checkout"], field_id

    # Local-only assets: no CDN / external fonts / remote images.
    assert "http://" not in combined
    assert "https://" not in combined
    assert "//cdn" not in combined
    assert "云裳商城" in files["index"]
    assert "模拟" in files["success"]


def test_assistant_recommend_sse(ctx):
    response = ctx.client.post(
        "/api/assistant/chat",
        json={"message": "我想买一件适合秋天的风衣"},
        headers=ctx.auth,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers.get("x-accel-buffering") == "no"

    events = parse_sse(response.text)
    names = event_names(events)
    assert names[0] == "session"
    assert names[1] == "intent"
    assert "assistant_message" in names
    assert "products" in names
    assert "order_created" not in names
    assert names[-1] == "done"

    session_event = first_event(events, "session")
    assert session_event["kind"] == "assistant"
    assert session_event["engine"] == "mock"

    intent_event = first_event(events, "intent")
    assert intent_event["intent"] == "recommend"

    products_event = first_event(events, "products")
    assert products_event["items"], "recommendation should include cards"
    card = next(
        item for item in products_event["items"] if item["product"]["name"] == WINDOW_BREAKER
    )
    assert card["platform_url"] == f"/product/{ctx.product_id}"
    assert card["mall_url"] == f"/demo-mall/product.html?id={ctx.product_id}"
    assert card["product"]["image"].startswith("/static/images/")

    done = first_event(events, "done")
    assert done["status"] == "done"

    with ctx.Session() as db:
        session = db.get(AgentSession, session_event["session_id"])
        assert session is not None
        assert session.kind == "assistant"
        assert session.status == "done"
        assert session.result["intent"]["intent"] == "recommend"
        assert db.query(Order).count() == 0


def test_assistant_order_mock_creates_platform_order(ctx):
    response = ctx.client.post(
        "/api/assistant/chat",
        json={"message": "帮我下单暮色长风衣，M 码"},
        headers=ctx.auth,
    )
    assert response.status_code == 200
    events = parse_sse(response.text)
    names = event_names(events)

    assert names[0] == "session"
    assert "intent" in names
    assert first_event(events, "intent")["intent"] == "order"
    steps = [data for event, data in events if event == "browse_step"]
    assert len(steps) >= 6
    assert all(step["status"] in ("done", "failed") for step in steps)

    order_event = first_event(events, "order_created")
    order_no = order_event["order_no"]
    assert re.fullmatch(r"YJ\d{18}", order_no), order_no
    assert order_event["source"] == "agent"
    assert order_event["total"] == ctx.product_price
    assert "error" not in names

    with ctx.Session() as db:
        order = (
            db.query(Order).filter(Order.external_ref == order_no).one_or_none()
        )
        assert order is not None, "browser success must map to a platform order"
        assert order.order_no == order_no
        assert order.source == "agent"
        assert order.status == "paid"
        assert order.total == ctx.product_price
        assert order.agent_session_id == order_event["session_id"]
        assert order.user_id == ctx.user_id
        assert len(order.items) == 1
        item = order.items[0]
        assert item.name == WINDOW_BREAKER
        assert item.size == "M"
        assert item.color in ("雾灰", "曜石黑", "燕麦")
        assert item.quantity == 1

        task = db.query(BrowseTask).one()
        assert task.status == "done"
        assert task.order_no == order_no
        assert len(task.steps or []) >= 6

        session = db.get(AgentSession, order_event["session_id"])
        assert session is not None
        assert session.status == "done"
        assert session.result["order_no"] == order_no
        messages = (
            db.query(AgentMessage)
            .filter(AgentMessage.session_id == session.id)
            .order_by(AgentMessage.seq.asc())
            .all()
        )
        assert any(message.agent == "user" for message in messages)
        assert any(message.agent == "assistant" for message in messages)


def test_demo_mall_order_token_validation_and_idempotency(ctx):
    with ctx.Session() as db:
        session = AgentSession(user_id=ctx.user_id, kind="assistant", status="running")
        db.add(session)
        db.flush()
        task = BrowseTask(
            session_id=session.id,
            task_token="a" * 32,
            status="running",
            steps=[],
        )
        db.add(task)
        db.commit()
        session_id = session.id
        token = task.task_token

    payload = {
        "task_token": token,
        "product_id": ctx.product_id,
        "size": "M",
        "color": "雾灰",
        "quantity": 2,
        "customer": {
            "name": "云裳体验官",
            "phone": "13800000000",
            "address": "上海市黄浦区云裳路 88 号",
        },
    }

    unknown = ctx.client.post(
        "/demo-mall/api/orders", json={**payload, "task_token": "b" * 32}
    )
    assert unknown.status_code == 404
    assert "任务令牌" in unknown.json()["detail"]

    bad_size = ctx.client.post(
        "/demo-mall/api/orders", json={**payload, "size": "XXXL"}
    )
    assert bad_size.status_code == 400
    assert "尺码" in bad_size.json()["detail"]

    first = ctx.client.post("/demo-mall/api/orders", json=payload)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["total"] == round(ctx.product_price * 2, 2)
    assert first_body["idempotent"] is False
    assert re.fullmatch(r"YJ\d{18}", first_body["order_no"])

    replay = ctx.client.post("/demo-mall/api/orders", json=payload)
    assert replay.status_code == 200
    assert replay.json()["order_no"] == first_body["order_no"]
    assert replay.json()["idempotent"] is True

    with ctx.Session() as db:
        assert db.query(Order).count() == 1
        order = db.query(Order).one()
        assert order.source == "agent"
        assert order.external_ref == order.order_no
        assert order.agent_session_id == session_id
        assert order.total == round(ctx.product_price * 2, 2)
        task = db.query(BrowseTask).one()
        assert task.status == "done"
        assert task.order_no == order.order_no


def test_assistant_browser_failure_is_reported_not_faked(ctx, monkeypatch):
    class FailingShopper:
        async def shop(self, request, on_step):
            raise BrowserUnavailable("无头浏览器不可用（测试注入）")

    def fake_build(engine, *, base_url, session_factory):
        return FailingShopper()

    monkeypatch.setattr(assistant_service, "build_shopper", fake_build)

    response = ctx.client.post(
        "/api/assistant/chat",
        json={"message": "帮我下单暮色长风衣，M 码"},
        headers=ctx.auth,
    )
    assert response.status_code == 200
    events = parse_sse(response.text)
    names = event_names(events)

    assert "error" in names
    assert "order_created" not in names
    error = first_event(events, "error")
    assert error["code"] == "browser_unavailable"
    assert "无头浏览器不可用" in error["message"]
    assert first_event(events, "done")["status"] == "failed"

    with ctx.Session() as db:
        assert db.query(Order).count() == 0
        session = db.query(AgentSession).filter(AgentSession.kind == "assistant").one()
        assert session.status == "failed"
        assert "无头浏览器" in (session.error or "")
        task = db.query(BrowseTask).one()
        assert task.status == "failed"
        assert task.order_no is None


def test_assistant_reuses_provided_session(ctx):
    first = ctx.client.post(
        "/api/assistant/chat",
        json={"message": "我想买一件风衣"},
        headers=ctx.auth,
    )
    assert first.status_code == 200
    session_id = first_event(parse_sse(first.text), "session")["session_id"]

    second = ctx.client.post(
        "/api/assistant/chat",
        json={"message": "推荐一条适合晚宴的裙子", "session_id": session_id},
        headers=ctx.auth,
    )
    assert second.status_code == 200
    events = parse_sse(second.text)
    assert first_event(events, "session")["session_id"] == session_id

    with ctx.Session() as db:
        sessions = db.query(AgentSession).filter(AgentSession.kind == "assistant").all()
        assert len(sessions) == 1
        messages = (
            db.query(AgentMessage)
            .filter(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.seq.asc())
            .all()
        )
        # Two user turns + two assistant replies share one session.
        assert [message.agent for message in messages].count("user") == 2
        assert [message.agent for message in messages].count("assistant") == 2


def test_assistant_session_detail_and_history(ctx):
    response = ctx.client.post(
        "/api/assistant/chat",
        json={"message": "推荐一条适合晚宴的裙子"},
        headers=ctx.auth,
    )
    assert response.status_code == 200
    events = parse_sse(response.text)
    session_id = first_event(events, "session")["session_id"]

    history = ctx.client.get("/api/assistant/history", headers=ctx.auth)
    assert history.status_code == 200
    ids = [item["id"] for item in history.json()["items"]]
    assert session_id in ids

    detail = ctx.client.get(
        f"/api/assistant/sessions/{session_id}", headers=ctx.auth
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["session"]["id"] == session_id
    assert body["session"]["status"] == "done"
    agents = [message["agent"] for message in body["messages"]]
    assert "user" in agents and "assistant" in agents
    assert body["browse_task"] is None

    # Unauthenticated / cross-user access is rejected.
    assert ctx.client.get(f"/api/assistant/sessions/{session_id}").status_code == 401

    with ctx.Session() as db:
        other = User(username="other", password_hash="x", nickname="路人")
        db.add(other)
        db.commit()
        other_token = create_access_token(other.id, "other")
    foreign = ctx.client.get(
        f"/api/assistant/sessions/{session_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert foreign.status_code == 404
