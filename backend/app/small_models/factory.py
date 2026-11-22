"""小模型工厂：单例、模式切换、启动预热与 embedding 补算。

对外 API：

* ``get_vision_model()`` / ``get_nlp_kg_model()``：按 ``SMALL_MODEL_MODE=stub|http``
  返回单例（http 模式附带自动降级）。
* ``warm_up()``：同步函数（main.py 在 threadpool 中调用，可安全 ``asyncio.run``）。
  从 ``SessionLocal`` 读取商品，补算缺失 embedding 写入 ``embeddings`` 表，
  并构建内存知识图谱。空库不报错。
* ``ensure_embeddings(db)``：同步补算，供 T2 种子流程 / 其他模块可选调用。
* ``ensure_graph(db)`` / ``rebuild_graph(db)``：路由按需刷新图谱。
* ``reset_models()``：清空单例（测试或切换模式后使用）。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, init_db
from ..models import Embedding, Product
from .base import NLPKGModel, VisionModel
from .http_adapters import HttpNLPKGModel, HttpVisionModel
from .nlp_kg_stub import NLPKGStub
from .vision_stub import FEATURE_DIM, VisionStub

logger = logging.getLogger("yijian.small_models.factory")

_lock = threading.RLock()
_embedding_lock = threading.RLock()
_vision_model: VisionModel | None = None
_nlp_kg_model: NLPKGModel | None = None

_warm_state: dict[str, Any] = {
    "ready": False,
    "graph_ready": False,
    "mode": "",
    "product_count": 0,
    "embedding_count": 0,
    "computed": 0,
    "cached": 0,
    "node_count": 0,
    "edge_count": 0,
    "elapsed_ms": 0,
    "last_error": None,
    "warmed_at": None,
    "metric": "chebyshev",
    "dim": FEATURE_DIM,
}


# ------------------------------------------------------------------ 单例
def get_model_mode() -> str:
    mode = (settings.small_model_mode or "stub").strip().lower()
    return "http" if mode == "http" else "stub"


def get_vision_model() -> VisionModel:
    global _vision_model
    with _lock:
        if _vision_model is None:
            if get_model_mode() == "http":
                logger.info("视觉小模型：HTTP 模式（失败按 SMALL_MODEL_FALLBACK_TO_STUB 降级）")
                _vision_model = HttpVisionModel()
            else:
                logger.info("视觉小模型：Stub 基线（REPLACEABLE BASELINE）")
                _vision_model = VisionStub()
        return _vision_model


def get_nlp_kg_model() -> NLPKGModel:
    global _nlp_kg_model
    with _lock:
        if _nlp_kg_model is None:
            if get_model_mode() == "http":
                logger.info("NLP-KG 小模型：HTTP 模式（失败按 SMALL_MODEL_FALLBACK_TO_STUB 降级）")
                _nlp_kg_model = HttpNLPKGModel()
            else:
                logger.info("NLP-KG 小模型：Stub 基线（REPLACEABLE BASELINE）")
                _nlp_kg_model = NLPKGStub()
        return _nlp_kg_model


def reset_models() -> None:
    """清空单例与预热状态（测试、切换模式后调用）。"""
    global _vision_model, _nlp_kg_model
    with _lock:
        _vision_model = None
        _nlp_kg_model = None
        _warm_state.update(
            {
                "ready": False,
                "graph_ready": False,
                "mode": "",
                "product_count": 0,
                "embedding_count": 0,
                "computed": 0,
                "cached": 0,
                "node_count": 0,
                "edge_count": 0,
                "elapsed_ms": 0,
                "last_error": None,
                "warmed_at": None,
                "metric": "chebyshev",
                "dim": FEATURE_DIM,
            }
        )


def get_warm_up_state() -> dict[str, Any]:
    with _lock:
        return dict(_warm_state)


def current_graph() -> dict[str, Any]:
    """返回当前内存图谱快照（stub 与 http 适配器共用内部本地图）。"""
    nlp = get_nlp_kg_model()
    source = getattr(nlp, "_stub", nlp)
    lock = getattr(source, "_lock", None)
    if lock is not None:
        with lock:
            return {
                "nodes": [dict(node) for node in getattr(source, "nodes", {}).values()],
                "edges": [dict(edge) for edge in getattr(source, "edges", [])],
                "meta": dict(getattr(source, "meta", {}) or {}),
            }
    return {"nodes": [], "edges": [], "meta": {}}


def models_status() -> dict[str, Any]:
    vision = get_vision_model()
    nlp = get_nlp_kg_model()
    return {
        "mode": get_model_mode(),
        "vision": vision.info(),
        "nlp_kg": nlp.info(),
        "warm_up": get_warm_up_state(),
    }


# ------------------------------------------------------------------ 同步/异步桥
def _run_sync(coro: Any) -> Any:
    """在同步上下文中运行协程；若当前线程已有事件循环，则放到临时线程执行。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    box: dict[str, Any] = {}

    def _runner() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - 原样抛回调用线程
            box["error"] = exc

    thread = threading.Thread(target=_runner, name="yijian-small-model-sync", daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


# ------------------------------------------------------------------ embedding 工具
def _product_to_dict(product: Product) -> dict[str, Any]:
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "subtitle": product.subtitle,
        "category": product.category,
        "price": product.price,
        "description": product.description,
        "fabric": product.fabric,
        "fit": product.fit,
        "style_tags": list(product.style_tags or []),
        "colors": list(product.colors or []),
        "sizes": list(product.sizes or []),
        "image": product.image,
        "occasion": product.occasion,
        "season": product.season,
        "featured": bool(product.featured),
    }


def _resolve_image_path(image: str) -> Path | None:
    if not image:
        return None
    image = image.strip()
    if image.startswith(("http://", "https://")):
        # 不访问外部资源；交由文本兜底向量
        return None
    if image.startswith("/static/"):
        return settings.static_dir / image[len("/static/") :]
    stripped = image.lstrip("/")
    candidates = [settings.static_dir / stripped, settings.images_dir / stripped]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _read_image_bytes(product: Product) -> bytes | None:
    path = _resolve_image_path(product.image or "")
    if path is None or not path.exists():
        return None
    try:
        return path.read_bytes()
    except OSError as exc:  # pragma: no cover - 文件被占用等
        logger.warning("读取商品图片失败 %s：%s", path, exc)
        return None


def text_fallback_embedding(product: Product, dim: int = FEATURE_DIM) -> list[float]:
    """图片缺失/损坏时的确定性兜底向量（sha256 派生，L2 归一化）。

    仅用于保证知识图谱完整；真实项目应使用有效商品图。
    """
    seed = "|".join(
        [
            str(product.sku or ""),
            str(product.name or ""),
            str(product.category or ""),
            " ".join(str(item) for item in (product.colors or [])),
            str(product.fabric or ""),
            str(product.style_tags or ""),
        ]
    ).encode("utf-8")
    raw = hashlib.shake_256(seed).digest(max(4, int(dim)) * 4)
    vector = np.frombuffer(raw, dtype=np.uint32).astype(np.float64)
    vector = (vector / np.float64(0xFFFFFFFF)) * 2.0 - 1.0
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:  # pragma: no cover - 理论上不会发生
        vector = np.zeros(int(dim), dtype=np.float64)
        vector[0] = 1.0
        norm = 1.0
    return [float(value) for value in (vector / norm)]


def _compute_pending_vectors(
    vision: VisionModel,
    pending: list[tuple[Product, bytes | None]],
) -> tuple[dict[int, list[float]], int]:
    """为待补算商品生成向量；图片缺失/失败时回退到文本派生向量。"""
    vectors: dict[int, list[float]] = {}
    with_images = [(product, data) for product, data in pending if data is not None]
    if with_images:
        try:
            batch = _run_sync(vision.embed_many([data for _, data in with_images]))
            if len(batch) == len(with_images):
                for (product, _), vector in zip(with_images, batch):
                    vectors[product.id] = [float(value) for value in vector]
        except Exception as exc:  # noqa: BLE001 - 批量失败后逐个重试
            logger.warning("小模型批量编码失败，逐个重试：%s", exc)
            for product, data in with_images:
                try:
                    vector = _run_sync(vision.embed(data))  # type: ignore[arg-type]
                    vectors[product.id] = [float(value) for value in vector]
                except Exception as item_exc:  # noqa: BLE001
                    logger.warning("商品 %s 图片编码失败，使用文本兜底向量：%s", product.id, item_exc)

    fallback_count = 0
    for product, data in pending:
        vector = vectors.get(product.id)
        if not vector:
            vector = text_fallback_embedding(product, getattr(vision, "dim", FEATURE_DIM) or FEATURE_DIM)
            vectors[product.id] = vector
            fallback_count += 1
    return vectors, fallback_count


def ensure_embeddings(db: Session, *, force: bool = False) -> dict[str, Any]:
    """补算缺失/过期 embedding 并写入 ``embeddings`` 表（同步，可安全在线程池调用）。

    判定缺失：没有记录、向量为空、维度与当前模型不一致、模型版本不一致。
    ``force=True`` 时全部重算（维度变化后重建 embedding 用）。
    """
    with _embedding_lock:
        return _ensure_embeddings_locked(db, force=force)


def _ensure_embeddings_locked(db: Session, *, force: bool = False) -> dict[str, Any]:
    vision = get_vision_model()
    model_dim = int(getattr(vision, "dim", FEATURE_DIM) or FEATURE_DIM)
    model_version = str(getattr(vision, "version", "stub-v1"))
    products = db.query(Product).order_by(Product.id).all()
    existing = {row.product_id: row for row in db.query(Embedding).all()}

    pending: list[tuple[Product, bytes | None]] = []
    cached = 0
    for product in products:
        row = existing.get(product.id)
        if (
            not force
            and row is not None
            and row.vector
            and int(row.dim or 0) == model_dim
            and (row.model_version or "") == model_version
        ):
            cached += 1
            continue
        pending.append((product, _read_image_bytes(product)))

    vectors, fallback_count = _compute_pending_vectors(vision, pending)

    # HTTP 适配器在首次调用后才拿到远程 dim/model_version，这里读取最新值，
    # 避免写入过期版本导致下一次调用重复重算。
    model_dim = int(getattr(vision, "dim", model_dim) or model_dim)
    model_version = str(getattr(vision, "version", model_version))

    now = datetime.now(timezone.utc)
    for product, _data in pending:
        vector = vectors[product.id]
        row = existing.get(product.id)
        if row is None:
            row = Embedding(product_id=product.id, vector=vector, dim=len(vector), model_version=model_version)
            db.add(row)
        else:
            row.vector = vector
            row.dim = len(vector)
            row.model_version = model_version
            row.updated_at = now
    if pending:
        db.commit()

    total_embeddings = db.query(func.count(Embedding.product_id)).scalar() or 0
    summary = {
        "total": len(products),
        "computed": len(pending),
        "cached": cached,
        "fallback_text": fallback_count,
        "dim": model_dim,
        "model_version": model_version,
        "backend": getattr(vision, "backend", "stub"),
        "embedding_count": int(total_embeddings),
    }
    logger.info(
        "小模型 embedding 就绪：商品 %s，补算 %s，缓存 %s，维度 %s",
        summary["total"],
        summary["computed"],
        summary["cached"],
        summary["dim"],
    )
    return summary


def load_embedding_rows(db: Session) -> list[dict[str, Any]]:
    rows = db.query(Embedding).order_by(Embedding.product_id).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        if not row.vector:
            continue
        result.append(
            {
                "product_id": row.product_id,
                "embedding": [float(value) for value in row.vector],
                "dim": row.dim,
                "model_version": row.model_version,
            }
        )
    return result


def build_graph_from_db(db: Session) -> dict[str, Any]:
    """从当前数据库构建内存图谱并更新预热状态。"""
    products = [_product_to_dict(product) for product in db.query(Product).order_by(Product.id).all()]
    embeddings = load_embedding_rows(db)
    nlp = get_nlp_kg_model()
    graph = _run_sync(nlp.build_graph(products, embeddings))
    meta = graph.get("meta", {}) if isinstance(graph, dict) else {}
    with _lock:
        _warm_state.update(
            {
                "graph_ready": True,
                "mode": get_model_mode(),
                "product_count": len(products),
                "embedding_count": len(embeddings),
                "node_count": int(meta.get("node_count", len(graph.get("nodes", [])))),
                "edge_count": int(meta.get("edge_count", len(graph.get("edges", [])))),
                "metric": "chebyshev",
            }
        )
    return graph


def rebuild_graph(db: Session) -> dict[str, Any]:
    """补算 embedding + 重建图谱（路由按需调用）。"""
    ensure_embeddings(db)
    return build_graph_from_db(db)


def ensure_graph(db: Session) -> dict[str, Any]:
    """确保内存图谱与数据库商品数量一致；必要时自动补算并重建。"""
    state = get_warm_up_state()
    current_count = int(db.query(func.count(Product.id)).scalar() or 0)
    if state.get("graph_ready") and int(state.get("product_count", -1)) == current_count:
        return {
            "rebuilt": False,
            "product_count": current_count,
            "node_count": state.get("node_count", 0),
            "edge_count": state.get("edge_count", 0),
        }
    graph = rebuild_graph(db)
    meta = graph.get("meta", {}) if isinstance(graph, dict) else {}
    return {"rebuilt": True, **meta}


# ------------------------------------------------------------------ 预热
def warm_up() -> dict[str, Any]:
    """启动预热（同步）：补 embedding、建 KG；空库不报错。"""
    started = time.monotonic()
    init_db()
    summary = {
        "ok": True,
        "mode": get_model_mode(),
        "product_count": 0,
        "computed": 0,
        "cached": 0,
        "embedding_count": 0,
        "node_count": 0,
        "edge_count": 0,
        "elapsed_ms": 0,
        "last_error": None,
    }
    try:
        with SessionLocal() as db:
            products = db.query(Product).order_by(Product.id).all()
            summary["product_count"] = len(products)
            emb_summary = ensure_embeddings(db)
            summary.update(
                {
                    "computed": emb_summary["computed"],
                    "cached": emb_summary["cached"],
                    "embedding_count": emb_summary["embedding_count"],
                    "dim": emb_summary["dim"],
                    "model_version": emb_summary["model_version"],
                }
            )
            product_rows = [_product_to_dict(product) for product in products]
            embedding_rows = load_embedding_rows(db)

        nlp = get_nlp_kg_model()
        graph = _run_sync(nlp.build_graph(product_rows, embedding_rows))
        meta = graph.get("meta", {}) if isinstance(graph, dict) else {}
        summary["node_count"] = int(meta.get("node_count", 0))
        summary["edge_count"] = int(meta.get("edge_count", 0))
        summary["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        with _lock:
            _warm_state.update(
                {
                    "ready": True,
                    "graph_ready": True,
                    "mode": summary["mode"],
                    "product_count": summary["product_count"],
                    "embedding_count": summary["embedding_count"],
                    "computed": summary["computed"],
                    "cached": summary["cached"],
                    "node_count": summary["node_count"],
                    "edge_count": summary["edge_count"],
                    "elapsed_ms": summary["elapsed_ms"],
                    "last_error": None,
                    "warmed_at": datetime.now(timezone.utc).isoformat(),
                    "dim": summary.get("dim", FEATURE_DIM),
                    "metric": "chebyshev",
                }
            )
        logger.info(
            "小模型预热完成：商品 %s，embedding %s，节点 %s，边 %s，耗时 %sms",
            summary["product_count"],
            summary["embedding_count"],
            summary["node_count"],
            summary["edge_count"],
            summary["elapsed_ms"],
        )
    except Exception as exc:  # noqa: BLE001 - 预热失败不应阻塞应用启动
        logger.exception("小模型预热失败，将以空图谱继续运行")
        summary["ok"] = False
        summary["last_error"] = f"小模型预热失败：{exc}"
        summary["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        with _lock:
            _warm_state.update(
                {
                    "ready": False,
                    "graph_ready": False,
                    "mode": summary["mode"],
                    "last_error": summary["last_error"],
                    "elapsed_ms": summary["elapsed_ms"],
                }
            )
    return summary


__all__ = [
    "get_vision_model",
    "get_nlp_kg_model",
    "get_model_mode",
    "reset_models",
    "warm_up",
    "ensure_embeddings",
    "ensure_graph",
    "rebuild_graph",
    "build_graph_from_db",
    "load_embedding_rows",
    "get_warm_up_state",
    "current_graph",
    "models_status",
    "text_fallback_embedding",
]
