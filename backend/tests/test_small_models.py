"""T3 小模型适配层测试：切比雪夫、视觉 embedding、KG 建图、HTTP 路由与预热。

使用临时 SQLite，不依赖 T2 种子数据；图片使用 Pillow 现场生成。
"""
from __future__ import annotations

import asyncio
import io
import math

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers, UploadFile as StarletteUploadFile

from app.catalog_data import PRODUCTS
from app.database import Base, get_db
from app.models import Embedding, Product
from app.small_models import factory, http_adapters
from app.small_models.http_adapters import HttpVisionModel, SmallModelServiceError
from app.small_models.metrics import chebyshev_distance, chebyshev_similarity
from app.small_models.nlp_kg_stub import NLPKGStub, extract_attributes
from app.small_models.vision_stub import FEATURE_DIM, VisionStub
from app.routers import small_models as small_models_router


# ------------------------------------------------------------------ 工具
def make_image(color: tuple[int, int, int] = (200, 30, 40), fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (96, 96), color).save(buffer, format=fmt)
    return buffer.getvalue()


def gradient_image() -> bytes:
    image = Image.new("RGB", (96, 96))
    pixels = image.load()
    for x in range(96):
        for y in range(96):
            pixels[x, y] = (x * 2, y * 2, (x + y) % 256)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def product_rows() -> list[Product]:
    indexes = [0, 3, 10, 13]  # 外套 / 上装 / 下装 / 配饰
    return [Product(**PRODUCTS[index]) for index in indexes]


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'small_models_test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(factory, "SessionLocal", Session)
    factory.reset_models()
    try:
        yield Session
    finally:
        engine.dispose()
        factory.reset_models()


@pytest.fixture()
def api_client(temp_db):
    Session = temp_db

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    test_app = FastAPI()
    test_app.include_router(small_models_router.router, prefix="/api")
    test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(test_app) as client:
        yield client


# ------------------------------------------------------------------ 切比雪夫
def test_chebyshev_known_values():
    a = [1.0, 5.0]
    b = [3.0, 2.0]
    assert chebyshev_distance(a, b) == pytest.approx(3.0)
    assert chebyshev_similarity(a, b) == pytest.approx(1.0 / 4.0)
    assert chebyshev_similarity([1, 2], [1, 2]) == pytest.approx(1.0)


def test_chebyshev_rejects_invalid_vectors():
    with pytest.raises(ValueError):
        chebyshev_distance([1, 2], [1, 2, 3])
    with pytest.raises(ValueError):
        chebyshev_distance([], [])
    with pytest.raises(ValueError):
        chebyshev_similarity([], [1.0])


# ------------------------------------------------------------------ 视觉 stub
def test_vision_embedding_dim_normalized_and_deterministic():
    stub = VisionStub()
    image = make_image()
    first = asyncio.run(stub.embed(image))
    second = asyncio.run(stub.embed(image))
    assert len(first) == FEATURE_DIM == 256
    assert stub.dim == 256
    assert first == second, "同一图片的 embedding 必须确定性一致"
    assert norm(first) == pytest.approx(1.0, abs=1e-5)
    assert all(math.isfinite(value) for value in first)


def test_vision_embed_many_matches_single():
    stub = VisionStub()
    red = make_image((220, 20, 30))
    blue = make_image((20, 40, 220))
    batch = asyncio.run(stub.embed_many([red, blue]))
    assert len(batch) == 2
    assert batch[0] == asyncio.run(stub.embed(red))
    assert batch[1] == asyncio.run(stub.embed(blue))
    assert chebyshev_distance(batch[0], batch[1]) > 0.01
    assert asyncio.run(stub.embed_many([])) == []


def test_vision_rejects_bad_image():
    stub = VisionStub()
    with pytest.raises(ValueError):
        asyncio.run(stub.embed(b""))
    with pytest.raises(ValueError):
        asyncio.run(stub.embed(b"definitely not an image"))


def test_vision_info_contract():
    info = VisionStub().info()
    assert info["name"] and info["version"] and info["dim"] == 256
    assert info["backend"] == "stub"
    assert info["replaceable_baseline"] is True


# ------------------------------------------------------------------ NLP-KG stub
def test_extract_chinese_attributes():
    extraction = extract_attributes("想找一件通勤的黑色真丝衬衫，M码，适合约会")
    attributes = extraction
    assert "上装" in attributes["category"]
    assert "黑" in attributes["colors"]
    assert "真丝" in attributes["materials"]
    assert "通勤" in attributes["styles"]
    assert "约会" in attributes["occasions"]
    assert "M" in attributes["sizes"]


def test_nlp_rank_sorted_by_distance():
    nlp = NLPKGStub()
    query = [0.0, 0.0, 0.0]
    candidates = [
        {"product_id": 3, "embedding": [0.3, 0.1, 0.0]},
        {"product_id": 1, "embedding": [0.1, 0.0, 0.0]},
        {"product_id": 2, "embedding": [0.2, 0.4, 0.1]},
    ]
    result = asyncio.run(nlp.rank(query, candidates, top_k=2))
    # 距离：id=1 → 0.1，id=3 → 0.3，id=2 → 0.4
    assert [item["product_id"] for item in result] == [1, 3]
    assert result[0]["distance"] == pytest.approx(0.1)
    assert result[0]["similarity"] == pytest.approx(1 / 1.1, abs=1e-6)
    assert result[0]["distance"] <= result[1]["distance"]


def test_kg_build_graph_has_similar_to_and_attribute_edges():
    nlp = NLPKGStub()
    products = [
        {"id": 1, "name": "云缎真丝衬衫", "category": "上装", "colors": ["月白"],
         "sizes": ["M"], "style_tags": ["通勤", "真丝"], "fabric": "100% 桑蚕丝",
         "occasion": "通勤", "price": 699.0},
        {"id": 2, "name": "流云阔腿裤", "category": "下装", "colors": ["墨黑"],
         "sizes": ["M"], "style_tags": ["通勤"], "fabric": "聚酯纤维",
         "occasion": "通勤", "price": 599.0},
        {"id": 3, "name": "墨影吊带长裙", "category": "连衣裙", "colors": ["墨黑"],
         "sizes": ["S"], "style_tags": ["晚宴"], "fabric": "醋酸",
         "occasion": "晚宴", "price": 899.0},
    ]
    embeddings = [
        {"product_id": 1, "embedding": [1.0, 0.0, 0.0]},
        {"product_id": 2, "embedding": [0.9, 0.1, 0.0]},
        {"product_id": 3, "embedding": [0.0, 1.0, 0.0]},
    ]
    graph = asyncio.run(nlp.build_graph(products, embeddings))
    relations = {edge["relation"] for edge in graph["edges"]}
    assert "similar_to" in relations
    assert "belongs_to" in relations
    assert "has_color" in relations
    assert "has_material" in relations
    assert "has_style" in relations
    assert "pairs_with" in relations
    assert graph["meta"]["product_count"] == 3
    node_ids = {node["id"] for node in graph["nodes"]}
    assert {"product:1", "product:2", "product:3", "category:上装"} <= node_ids

    similar_edges = [edge for edge in graph["edges"] if edge["relation"] == "similar_to"]
    assert similar_edges
    # 商品 1 的 Top-3 近邻里必然包含 2（距离 0.1），且无自环
    assert all(edge["source"] != edge["target"] for edge in similar_edges)

    neighbors = asyncio.run(nlp.neighbors(1, limit=10))
    assert any(item["relation"] == "similar_to" and item["id"] == "product:2" for item in neighbors)
    pair_edges = [edge for edge in graph["edges"] if edge["relation"] == "pairs_with"]
    assert any(
        {edge["source"], edge["target"]} == {"product:1", "product:2"} for edge in pair_edges
    )


def test_kg_query_expands_and_returns_terms():
    nlp = NLPKGStub()
    products = [
        {"id": 1, "name": "云缎真丝衬衫", "subtitle": "通勤衬衫", "category": "上装",
         "colors": ["月白"], "sizes": ["M"], "style_tags": ["通勤"], "fabric": "桑蚕丝",
         "occasion": "通勤", "price": 699.0},
        {"id": 2, "name": "流云阔腿裤", "subtitle": "通勤西裤", "category": "下装",
         "colors": ["墨黑"], "sizes": ["M"], "style_tags": ["通勤"], "fabric": "聚酯",
         "occasion": "通勤", "price": 599.0},
    ]
    embeddings = [
        {"product_id": 1, "embedding": [1.0, 0.0]},
        {"product_id": 2, "embedding": [0.8, 0.2]},
    ]
    asyncio.run(nlp.build_graph(products, embeddings))
    result = asyncio.run(nlp.query("上班通勤想穿真丝衬衫", top_k=5))
    assert result["product_ids"], "查询应命中商品"
    assert result["product_ids"][0] == 1
    assert any(term in result["related_terms"] for term in ("通勤", "上装", "下装"))
    assert result["triples"]
    # 邻域扩展应把下装也带出来
    assert 2 in result["product_ids"]


# ------------------------------------------------------------------ 预热 / embedding 表
def test_warm_up_computes_embeddings_and_graph(temp_db):
    Session = temp_db
    with Session() as db:
        db.add_all(product_rows())
        db.commit()

    summary = factory.warm_up()
    assert summary["ok"] is True
    assert summary["product_count"] == 4
    assert summary["embedding_count"] == 4
    assert summary["computed"] == 4
    assert summary["node_count"] > 0
    assert summary["edge_count"] > 0

    with Session() as db:
        assert db.query(func.count(Embedding.product_id)).scalar() == 4
        embeddings = db.query(Embedding).all()
        assert all(row.dim == 256 for row in embeddings)
        assert all(len(row.vector) == 256 for row in embeddings)
        assert all(abs(norm(row.vector) - 1.0) < 1e-4 for row in embeddings)
        assert all(row.model_version == VisionStub.version for row in embeddings)

    graph = factory.current_graph()
    assert any(edge["relation"] == "similar_to" for edge in graph["edges"])
    assert any(edge["relation"] == "pairs_with" for edge in graph["edges"])

    again = factory.warm_up()
    assert again["ok"] is True
    assert again["computed"] == 0
    assert again["cached"] == 4
    assert again["embedding_count"] == 4


def test_warm_up_empty_database_does_not_fail(temp_db):
    summary = factory.warm_up()
    assert summary["ok"] is True
    assert summary["product_count"] == 0
    assert summary["embedding_count"] == 0
    assert summary["node_count"] == 0
    assert summary["edge_count"] == 0
    assert factory.get_warm_up_state()["graph_ready"] is True


def test_ensure_embeddings_is_idempotent_and_force_rebuilds(temp_db):
    Session = temp_db
    with Session() as db:
        db.add_all(product_rows())
        db.commit()
        first = factory.ensure_embeddings(db)
        assert first["computed"] == 4
        second = factory.ensure_embeddings(db)
        assert second["computed"] == 0
        assert second["cached"] == 4
        forced = factory.ensure_embeddings(db, force=True)
        assert forced["computed"] == 4


# ------------------------------------------------------------------ HTTP 适配器
class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


def test_http_vision_adapter_parses_remote_response(monkeypatch):
    calls: dict = {}

    class FakeClient:
        def __init__(self, timeout=None):
            calls["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            calls.update(url=url, json=json, headers=headers)
            return _FakeResponse(
                200, {"embeddings": [[0.6, 0.8]], "dim": 2, "model_version": "remote-x"}
            )

    monkeypatch.setattr(http_adapters.httpx, "AsyncClient", FakeClient)
    model = HttpVisionModel(
        "http://unit.test/", timeout=5, token="secret-token", fallback_to_stub=False
    )
    vector = asyncio.run(model.embed(make_image()))
    assert vector == [0.6, 0.8]
    assert model.dim == 2
    assert model.version == "remote-x"
    assert calls["url"] == "http://unit.test/embed"
    assert calls["timeout"] == 5
    assert calls["headers"]["Authorization"] == "Bearer secret-token"
    assert calls["json"]["normalize"] is True
    assert len(calls["json"]["images_base64"]) == 1
    assert model.info()["healthy"] is True


def test_http_vision_adapter_failure_falls_back_to_stub(monkeypatch):
    class FailClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            return _FakeResponse(503, {"detail": "down"})

    monkeypatch.setattr(http_adapters.httpx, "AsyncClient", FailClient)
    resilient = HttpVisionModel("http://unit.test", timeout=1, fallback_to_stub=True)
    vector = asyncio.run(resilient.embed(make_image()))
    assert len(vector) == FEATURE_DIM == 256
    assert resilient.info()["degraded"] is True
    assert resilient.info()["last_error"]

    strict = HttpVisionModel("http://unit.test", timeout=1, fallback_to_stub=False)
    with pytest.raises(SmallModelServiceError):
        asyncio.run(strict.embed(make_image()))


# ------------------------------------------------------------------ HTTP 路由
def test_status_endpoint(api_client):
    response = api_client.get("/api/small-models/status")
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "stub"
    assert data["vision"]["dim"] == 256
    assert data["vision"]["backend"] == "stub"
    assert data["nlp_kg"]["metric"] == "chebyshev"
    assert "warm_up" in data["nlp_kg"]


def test_chebyshev_endpoint_and_validation(api_client):
    response = api_client.post("/api/small-models/kg/chebyshev", json={"a": [1, 5], "b": [3, 2]})
    assert response.status_code == 200
    data = response.json()
    assert data["distance"] == pytest.approx(3.0)
    assert data["similarity"] == pytest.approx(0.25)

    bad = api_client.post("/api/small-models/kg/chebyshev", json={"a": [1, 2], "b": [1]})
    assert bad.status_code == 400
    assert "维度" in bad.json()["detail"]


def test_vision_embed_endpoint(api_client):
    response = api_client.post(
        "/api/small-models/vision/embed",
        files={"file": ("red.png", make_image(), "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["dim"] == 256
    assert len(data["embedding"]) == 256
    assert data["backend"] == "stub"

    invalid = api_client.post(
        "/api/small-models/vision/embed",
        files={"file": ("broken.png", b"not-an-image", "image/png")},
    )
    assert invalid.status_code == 400
    assert "图片" in invalid.json()["detail"]


def test_vision_embed_upload_validation():
    from app.routers.small_models import MAX_UPLOAD_BYTES, _read_valid_image

    oversized = StarletteUploadFile(
        io.BytesIO(b"x" * (MAX_UPLOAD_BYTES + 1)),
        filename="huge.png",
        headers=Headers({"content-type": "image/png"}),
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_read_valid_image(oversized))
    assert exc_info.value.status_code == 400
    assert "8MB" in exc_info.value.detail

    empty = StarletteUploadFile(
        io.BytesIO(b""), filename="empty.png", headers=Headers({"content-type": "image/png"})
    )
    with pytest.raises(HTTPException):
        asyncio.run(_read_valid_image(empty))


def test_vision_similar_endpoint_orders_by_distance(api_client, temp_db):
    Session = temp_db
    with Session() as db:
        db.add_all(product_rows())
        db.commit()
    assert factory.warm_up()["ok"] is True

    response = api_client.post(
        "/api/small-models/vision/similar?top_k=3",
        files={"file": ("query.png", make_image((210, 40, 60)), "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "stub"
    assert len(data["query_embedding"]) == 256
    assert data["matches"], "有商品 embedding 时应返回相似结果"
    distances = [match["distance"] for match in data["matches"]]
    assert distances == sorted(distances)
    assert all(match["product"]["id"] for match in data["matches"])


def test_kg_query_and_graph_endpoints(api_client, temp_db):
    Session = temp_db
    with Session() as db:
        db.add_all(product_rows())
        db.commit()
    assert factory.warm_up()["ok"] is True

    query = api_client.post(
        "/api/small-models/kg/query",
        json={"text": "通勤真丝衬衫", "top_k": 4},
    )
    assert query.status_code == 200
    data = query.json()
    assert isinstance(data["triples"], list)
    assert data["products"], "查询应返回相关商品"
    assert data["related_terms"]

    graph = api_client.get("/api/small-models/kg/graph?limit=100")
    assert graph.status_code == 200
    graph_data = graph.json()
    assert graph_data["metric"] == "chebyshev"
    assert graph_data["nodes"] and graph_data["edges"]
    assert any(node["type"] == "product" for node in graph_data["nodes"])
    assert any(edge["relation"] == "similar_to" for edge in graph_data["edges"])

    focused = api_client.get("/api/small-models/kg/graph?product_id=1")
    assert focused.status_code == 200
    focused_data = focused.json()
    assert any(node["id"] == "product:1" for node in focused_data["nodes"])

    missing = api_client.get("/api/small-models/kg/graph?product_id=9999")
    assert missing.status_code == 200
    assert missing.json()["nodes"] == []
