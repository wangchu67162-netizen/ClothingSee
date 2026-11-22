"""T4 五智能体 Mock 链路测试。

不依赖 T1/T2/T3 的完成度：测试自带临时 SQLite 与商品数据，
并通过依赖覆盖绕过鉴权；小模型检索固定走内置回退。
"""
from __future__ import annotations

import asyncio
import io
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.base import AgentOpinion, AgentScore, DiscussionContext
from app.agents.personas import AGENT_IDS, AGENT_NAMES, DEFAULT_WEIGHTS, PERSONAS
from app.catalog_data import PRODUCTS
from app.config import settings
from app.database import Base, get_db
from app.deps import get_current_user
from app.llm.mock import MockLLM
from app.llm.qwen import (
    QwenClient,
    QwenError,
    parse_json_loose,
    round2_from_data,
)
from app.models import AgentMessage, AgentSession, Embedding, Product, User
from app.routers import recommend as recommend_router
from app.services import recommendation as recommendation_service
from app.services.recommendation import stream_stylist

FIVE_AGENTS = ["fashion", "art", "aesthetics", "price", "comfort"]


# ---------------------------------------------------------------- 基础 fixtures

@pytest.fixture()
def engine(tmp_path):
    database = tmp_path / "agents.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(engine):
    testing_session = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    session = testing_session()
    session.add(User(id=1, username="tester", password_hash="x", nickname="测试用户"))
    for item in PRODUCTS:
        session.add(Product(**item))
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def client(db_session, monkeypatch):
    monkeypatch.setattr(settings, "llm_mode", "mock", raising=False)
    monkeypatch.setattr(settings, "dashscope_api_key", "", raising=False)

    async def _no_small_models(*args, **kwargs):
        return None

    monkeypatch.setattr(
        recommendation_service, "_retrieve_with_small_models", _no_small_models
    )

    app = FastAPI()
    app.include_router(recommend_router.router, prefix="/api")

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: db_session.get(User, 1)

    existing = {
        path.name
        for path in Path(settings.uploads_dir).glob("stylist-*")
    } if Path(settings.uploads_dir).exists() else set()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        # 清理测试产生的上传文件，避免污染演示目录。
        for path in Path(settings.uploads_dir).glob("stylist-*"):
            if path.name not in existing:
                path.unlink(missing_ok=True)


# ---------------------------------------------------------------- 工具

def _image_bytes(color: tuple[int, int, int] = (122, 84, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (96, 128), color).save(buffer, format="PNG")
    return buffer.getvalue()


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


def _post_recommend(client: TestClient, note: str = "通勤", budget: str = "3000"):
    return client.post(
        "/api/recommend/image",
        files={"file": ("outfit.png", _image_bytes(), "image/png")},
        data={"budget": budget, "note": note},
        headers={"Authorization": "Bearer test-token"},
    )


async def _collect(source: AsyncIterator[dict]) -> list[dict]:
    return [item async for item in source]


# ---------------------------------------------------------------- 固定人设与 Mock 确定性

def test_personas_are_fixed_and_mock_is_deterministic(db_session):
    assert list(AGENT_IDS) == FIVE_AGENTS
    assert [AGENT_NAMES[agent] for agent in FIVE_AGENTS] == [
        "时尚智能体",
        "艺术智能体",
        "审美智能体",
        "价格智能体",
        "舒适度智能体",
    ]
    assert DEFAULT_WEIGHTS == {
        "fashion": 0.25,
        "art": 0.15,
        "aesthetics": 0.20,
        "price": 0.20,
        "comfort": 0.20,
    }
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9

    image = _image_bytes()
    vision_a = MockLLM(image).vision_analysis("通勤")
    vision_b = MockLLM(image).vision_analysis("通勤")
    assert vision_a == vision_b
    assert vision_a.category
    assert vision_a.colors and vision_a.style

    products = db_session.query(Product).order_by(Product.id.asc()).limit(6).all()
    assert len(products) == 6
    vectors: dict[str, list[float]] = {}
    for persona in PERSONAS:
        mock = MockLLM(image)
        vectors[persona.id] = [
            mock.score_product(persona.id, product, vision_a, 2000, "通勤")[0]
            for product in products
        ]
        assert all(0.0 <= value <= 10.0 for value in vectors[persona.id])

    # 五个公式互不相同：至少 4 种不同的评分向量
    assert len({tuple(values) for values in vectors.values()}) >= 4

    # 同图同商品，再算一次必须完全一致
    replay = [
        MockLLM(image).score_product("fashion", product, vision_a, 2000, "通勤")[0]
        for product in products
    ]
    assert replay == vectors["fashion"]

    ctx = DiscussionContext(candidates=products, vision=vision_a, budget=2000, note="通勤")
    opinion = asyncio.run(MockLLM(image).round1(PERSONAS[0], ctx))
    assert opinion.round == 1
    assert len(opinion.scores) == len(products)
    assert opinion.recipients and opinion.recipients[0] in AGENT_IDS


# ---------------------------------------------------------------- Qwen 容错与重试

def test_qwen_json_tolerance_and_retry(monkeypatch):
    assert parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_loose('说明文字 {"style": ["极简"], "confidence": 0.8} 后记') == {
        "style": ["极简"],
        "confidence": 0.8,
    }
    assert parse_json_loose('{"a": [1, 2,],}') == {"a": [1, 2]}
    assert parse_json_loose("这不是 JSON") is None

    from app.llm import qwen as qwen_module

    monkeypatch.setattr(qwen_module, "RETRY_DELAYS", (0.0, 0.0))

    calls = {"count": 0}

    def flaky_handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}
        )

    retrying = QwenClient(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        transport=httpx.MockTransport(flaky_handler),
        timeout=2,
    )
    assert asyncio.run(
        retrying.chat_json([{"role": "user", "content": "你好"}])
    ) == {"ok": True}
    assert calls["count"] == 3  # 首次 + 重试 2 次

    calls["count"] = 0

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            raise httpx.ConnectTimeout("模拟超时", request=request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}
        )

    timeout_client = QwenClient(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        transport=httpx.MockTransport(timeout_handler),
        timeout=2,
    )
    assert asyncio.run(
        timeout_client.chat_json([{"role": "user", "content": "你好"}])
    ) == {"ok": True}
    assert calls["count"] == 3

    calls["count"] = 0

    def unauthorized_handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    unauthorized = QwenClient(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        transport=httpx.MockTransport(unauthorized_handler),
        timeout=2,
    )
    with pytest.raises(QwenError):
        asyncio.run(unauthorized.chat_json([{"role": "user", "content": "你好"}]))
    assert calls["count"] == 1  # 401 不重试


def test_qwen_round2_caps_revisions_at_two():
    own = AgentOpinion(
        agent="fashion",
        round=1,
        scores=[AgentScore(1, 5.0), AgentScore(2, 5.0), AgentScore(3, 5.0)],
    )
    data = {
        "revisions": [
            {"product_id": 1, "new_score": 6.0, "reason": "回应艺术智能体"},
            {"product_id": 2, "new_score": 7.0, "reason": "回应审美智能体"},
            {"product_id": 3, "new_score": 8.0, "reason": "回应价格智能体"},
        ],
        "message_to_peers": "艺术智能体对色彩的判断说服了我。",
    }
    opinion, revisions = round2_from_data(
        data, PERSONAS[0], own, {"art": {1: 7.0, 2: 7.0, 3: 7.0}}
    )
    assert len(revisions) == 2
    assert opinion.message_type == "revision"
    assert opinion.recipients
    assert opinion.recipients[0] in AGENT_IDS


# ---------------------------------------------------------------- SSE 心跳

def test_sse_wrapper_emits_heartbeat(monkeypatch):
    from app.routers import recommend as router_module

    monkeypatch.setattr(router_module, "_HEARTBEAT_SECONDS", 0.05)

    async def slow_source():
        yield {"event": "session", "data": {"session_id": "test-session"}}
        await asyncio.sleep(0.12)
        yield {"event": "done", "data": {"session_id": "test-session"}}

    async def collect():
        return [
            chunk
            async for chunk in router_module._sse_wrapper(slow_source())
        ]

    text = "".join(asyncio.run(collect()))
    assert ": ping" in text
    assert "event: session" in text
    assert "event: done" in text
    assert "id: 1" in text and "id: 2" in text


# ---------------------------------------------------------------- T3 小模型集成

def test_small_model_retrieval_when_t3_available(db_session, monkeypatch):
    vision_stub = pytest.importorskip("app.small_models.vision_stub")
    nlp_kg_stub = pytest.importorskip("app.small_models.nlp_kg_stub")
    from app.small_models import factory

    products = db_session.query(Product).order_by(Product.id.asc()).all()
    vision_model = vision_stub.VisionStub()
    nlp_model = nlp_kg_stub.NLPKGStub()
    images: list[bytes] = []
    ids: list[int] = []
    for product in products:
        relative = product.image[len("/static/") :]
        images.append((Path(settings.static_dir) / relative).read_bytes())
        ids.append(int(product.id))
    vectors = asyncio.run(vision_model.embed_many(images))
    for product_id, vector in zip(ids, vectors):
        db_session.add(
            Embedding(
                product_id=product_id,
                vector=vector,
                dim=len(vector),
                model_version=vision_model.version,
            )
        )
    db_session.commit()
    asyncio.run(
        nlp_model.build_graph(
            products,
            [
                {"product_id": product_id, "embedding": vector}
                for product_id, vector in zip(ids, vectors)
            ],
        )
    )
    monkeypatch.setattr(factory, "_vision_model", vision_model)
    monkeypatch.setattr(factory, "_nlp_kg_model", nlp_model)

    result = asyncio.run(
        recommendation_service._retrieve_with_small_models(
            db_session, _image_bytes(), "通勤", products
        )
    )
    assert result is not None
    candidates, backend = result
    assert len(candidates) >= 8
    assert all(int(item.id) in ids for item in candidates)
    assert backend != "fallback"

    # T3 neighbors 使用 "product:<id>" 节点 id；集成层必须能解析。
    neighbor_ids = [
        recommendation_service._neighbor_id(item)
        for item in asyncio.run(nlp_model.neighbors(ids[0], limit=6))
    ]
    assert any(item is not None for item in neighbor_ids)


# ---------------------------------------------------------------- 主 SSE 链路

def test_recommend_stream_rounds_revision_and_final(client, db_session):
    response = _post_recommend(client)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")

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

    # SSE 事件 id 严格递增
    assert [item["id"] for item in events] == [
        str(index) for index in range(1, len(events) + 1)
    ]

    session_event = next(item for item in events if item["event"] == "session")["data"]
    assert session_event["mode"] == "mock"
    session_id = session_event["session_id"]
    assert isinstance(session_id, str) and session_id
    assert [stage["stage"] for stage in session_event["stages"]] == [
        "vision",
        "retrieval",
        "round1",
        "round2",
        "aggregate",
    ]

    stage_names = [
        item["data"]["stage"] for item in events if item["event"] == "stage"
    ]
    assert stage_names == ["vision", "retrieval", "round1", "round2", "aggregate"]

    vision = next(item for item in events if item["event"] == "vision")["data"]
    assert vision["summary"]
    assert 0.2 <= vision["confidence"] <= 0.99

    candidates_event = next(
        item for item in events if item["event"] == "candidates"
    )["data"]
    assert 5 <= len(candidates_event["items"]) <= 12
    assert candidates_event["metric"] == "chebyshev"
    assert candidates_event["backend"] == "fallback"
    candidate_ids = {item["id"] for item in candidates_event["items"]}

    kg = next(item for item in events if item["event"] == "kg")["data"]
    assert kg["metric"] == "chebyshev"
    assert kg["nodes"] and kg["edges"] and kg["summary"]

    rounds = [item["data"]["round"] for item in events if item["event"] == "agent_round"]
    assert rounds == [1, 2]

    messages = [item["data"] for item in events if item["event"] == "agent_message"]
    round1 = [item for item in messages if item["round"] == 1]
    round2 = [item for item in messages if item["round"] == 2]
    assert {item["agent"] for item in round1} == set(FIVE_AGENTS)
    assert {item["agent"] for item in round2} == set(FIVE_AGENTS)
    assert len(round1) == 5 and len(round2) == 5
    for message in messages:
        assert message["agent_name"]
        assert message["message_type"] in {"opinion", "critique", "revision"}
        assert message["seq"] >= 1
        for recipient in message["recipients"]:
            assert recipient in AGENT_IDS
    for message in round1:
        assert message["message_type"] == "opinion"
        assert message["scores"] and all(
            score["product_id"] in candidate_ids for score in message["scores"]
        )
    assert any(item["message_type"] == "revision" for item in round2)
    for message in round2:
        assert message["recipients"], "Round 2 必须向具名同伴发言"

    revisions = [item["data"] for item in events if item["event"] == "revision"]
    assert revisions, "Mock 模式必须至少产生一次分数修订"
    for revision in revisions:
        assert revision["agent"] in AGENT_IDS
        assert revision["product_id"] in candidate_ids
        assert revision["old_score"] != revision["new_score"]
        assert revision["reason"]

    final = next(item for item in events if item["event"] == "final")["data"]
    assert final["session_id"] == session_id
    assert final["mode"] == "mock"
    assert len(final["recommendations"]) == 3
    assert len({item["product"]["id"] for item in final["recommendations"]}) == 3
    for item in final["recommendations"]:
        assert set(item["agent_scores"].keys()) == set(FIVE_AGENTS)
        assert item["reasons"]
        assert 0 <= item["score"] <= 10
    assert final["outfit"], "必须给出整套 outfit"
    assert final["outfit_total"] > 0
    assert final["advice"]
    assert final["kg"]["metric"] == "chebyshev"
    assert final["elapsed_ms"] >= 0

    done = next(item for item in events if item["event"] == "done")["data"]
    assert done["session_id"] == session_id

    # ---------------------------------------------------------------- 落库检查
    session = db_session.query(AgentSession).one()
    assert session.id == session_id
    assert session.kind == "stylist"
    assert session.status == "done"
    assert session.mode == "mock"
    assert session.result and session.result["recommendations"]
    assert session.input_image and session.input_image.startswith("/uploads/")

    stored = (
        db_session.query(AgentMessage)
        .order_by(AgentMessage.seq.asc())
        .all()
    )
    assert len(stored) >= 10
    seqs = [item.seq for item in stored]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    assert {item.agent for item in stored if item.round == 1} == set(FIVE_AGENTS)
    assert any(
        item.round == 2 and item.message_type == "revision" for item in stored
    )
    assert any(item.round == 2 and item.recipients for item in stored)

    upload = Path(settings.uploads_dir) / f"stylist-{session.id}.png"
    if upload.exists():
        upload.unlink()


# ---------------------------------------------------------------- 会话回看

def test_session_detail_and_history(client):
    response = _post_recommend(client, note="约会")
    assert response.status_code == 200
    events = _parse_sse(response.text)
    session_id = next(
        item for item in events if item["event"] == "session"
    )["data"]["session_id"]

    detail = client.get(f"/api/recommend/sessions/{session_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["session"]["kind"] == "stylist"
    assert body["session"]["status"] == "done"
    assert len(body["messages"]) >= 10
    assert body["messages"][0]["agent_name"]
    assert body["result"]["recommendations"]

    history = client.get("/api/recommend/history")
    assert history.status_code == 200
    items = history.json()
    assert isinstance(items, list) and items
    assert any(item["id"] == session_id for item in items)

    missing = client.get("/api/recommend/sessions/not-exists")
    assert missing.status_code == 404
    assert "会话" in missing.json()["detail"]


# ---------------------------------------------------------------- 输入校验

def test_invalid_upload_and_budget(client):
    bad_file = client.post(
        "/api/recommend/image",
        files={"file": ("note.txt", b"not an image", "text/plain")},
    )
    assert bad_file.status_code == 400
    assert "图片" in bad_file.json()["detail"]

    bad_budget = client.post(
        "/api/recommend/image",
        files={"file": ("outfit.png", _image_bytes(), "image/png")},
        data={"budget": "abc"},
    )
    assert bad_budget.status_code == 400
    assert "预算" in bad_budget.json()["detail"]


# ---------------------------------------------------------------- Qwen 降级

def test_qwen_failure_degrades_to_mock(client, monkeypatch):
    class BrokenQwen:
        mode = "qwen"

        async def analyze_image(self, *args, **kwargs):
            raise QwenError("模拟视觉失败")

        async def round1(self, *args, **kwargs):
            raise QwenError("模拟评分失败")

        async def round2(self, *args, **kwargs):
            raise QwenError("模拟修订失败")

    monkeypatch.setattr(recommendation_service, "qwen_available", lambda: True)
    monkeypatch.setattr(
        recommendation_service, "_create_qwen_backend", lambda: BrokenQwen()
    )

    response = _post_recommend(client)
    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [item["event"] for item in events]
    assert "warning" in names
    warnings = [item["data"] for item in events if item["event"] == "warning"]
    assert any(item["code"] == "qwen_fallback" for item in warnings)
    assert any(item["stage"] in {"vision", "round1", "round2"} for item in warnings)
    # 降级后依然返回完整的 Mock 结果
    assert "vision" in names
    final = next(item for item in events if item["event"] == "final")["data"]
    assert len(final["recommendations"]) == 3
    assert final["outfit"]


# ---------------------------------------------------------------- 无候选硬错误

def test_no_candidates_is_hard_error(tmp_path):
    database = tmp_path / "empty.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    try:
        with testing_session() as db:
            user = User(id=1, username="empty", password_hash="x", nickname="空库")
            db.add(user)
            db.commit()
            events = asyncio.run(
                _collect(
                    stream_stylist(
                        db,
                        user,
                        _image_bytes(),
                        image_format="PNG",
                        content_type="image/png",
                    )
                )
            )
        names = [item["event"] for item in events]
        assert "error" in names
        assert "final" not in names
        error = next(item for item in events if item["event"] == "error")["data"]
        assert error["code"] == "no_candidates"
        assert error["message"]
        with testing_session() as db:
            session = db.query(AgentSession).one()
            assert session.status == "failed"
            (Path(settings.uploads_dir) / f"stylist-{session.id}.png").unlink(
                missing_ok=True
            )
    finally:
        engine.dispose()
