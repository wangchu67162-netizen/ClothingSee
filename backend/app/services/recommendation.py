"""五智能体荐衣服务：图片校验/保存、视觉解析、检索、两轮评议、聚合与落库。

对外只暴露 :func:`stream_stylist` 异步生成器，产出 SSE 事件字典；路由层负责
包装成 text/event-stream 并发送心跳。所有智能体消息均写入 ``agent_messages``，
会话结果写入 ``agent_sessions.result``。
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import math
import random
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import numpy as np
from PIL import Image

from ..agents.base import AgentOpinion, DiscussionContext, clamp_score
from ..agents.bus import MessageBus
from ..agents.orchestrator import run_round1, run_round2
from ..agents.personas import DEFAULT_WEIGHTS, agent_name
from ..config import settings
from ..llm.mock import MockLLM
from ..llm.qwen import QwenAgentBackend, QwenClient, qwen_available
from ..models import AgentMessage, AgentSession, Embedding, Product
from ..schemas import (
    AgentMessageOut,
    ProductOut,
    RecommendationFinal,
    VisionAnalysis,
)

logger = logging.getLogger("yijian.services.recommendation")

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}
_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
}
_EXT_BY_FORMAT = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
    "GIF": "gif",
    "BMP": "bmp",
}
STAGE_PLAN: list[dict[str, Any]] = [
    {"stage": "vision", "label": "看懂照片"},
    {"stage": "retrieval", "label": "小模型检索"},
    {"stage": "round1", "label": "独立评议"},
    {"stage": "round2", "label": "交叉讨论"},
    {"stage": "aggregate", "label": "策展汇总"},
]

_COMPLEMENT_CATEGORIES = ("外套", "上装", "下装", "连衣裙")


class InvalidImageError(ValueError):
    """上传图片不合法（HTTP 400，中文提示）。"""


class NoCandidatesError(RuntimeError):
    """商品库无候选，属于硬错误。"""


class SmallModelUnavailable(RuntimeError):
    """小模型模块尚未就绪，可用内置回退检索。"""


# ---------------------------------------------------------------- 基础工具

def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}


def _stage(stage: str, label: str, progress: float) -> dict[str, Any]:
    return _event("stage", {"stage": stage, "label": label, "progress": round(progress, 2)})


def _iso(value: datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def sniff_image(image_bytes: bytes) -> str:
    """校验图片并返回 PIL 格式名；失败抛 :class:`InvalidImageError`。"""
    if not image_bytes:
        raise InvalidImageError("请上传一张图片")
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise InvalidImageError("图片请控制在 8MB 以内")
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image_format = (image.format or "").upper()
            image.verify()
    except Exception as exc:  # noqa: BLE001 - PIL 抛出的异常类型不稳定
        raise InvalidImageError("图片格式无法识别，请上传 JPG / PNG / WebP") from exc
    if image_format not in SUPPORTED_FORMATS:
        raise InvalidImageError("图片格式无法识别，请上传 JPG / PNG / WebP")
    return image_format


def _save_upload(session_id: str, image_bytes: bytes, image_format: str) -> str | None:
    try:
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        extension = _EXT_BY_FORMAT.get(image_format, "png")
        filename = f"stylist-{session_id}.{extension}"
        (settings.uploads_dir / filename).write_bytes(image_bytes)
        return f"/uploads/{filename}"
    except OSError:
        logger.exception("保存上传图片失败，会话继续运行")
        return None


def _fail_session(db: Any, session_id: str, message: str) -> None:
    try:
        obj = db.get(AgentSession, session_id)
        if obj is not None:
            obj.status = "failed"
            obj.error = message[:500]
            db.commit()
    except Exception:  # pragma: no cover - 会话最终状态不应阻塞错误推送
        logger.exception("写入会话失败状态时出错")
        try:
            db.rollback()
        except Exception:
            pass


def _save_message(db: Any, session_id: str, record: Any) -> dict[str, Any]:
    message = AgentMessage(
        session_id=session_id,
        seq=record.seq,
        agent=record.agent,
        round=record.round,
        role=record.role,
        message_type=record.message_type,
        recipients=list(record.recipients or []),
        content=record.content,
        payload=record.payload,
        scores=list(record.scores or []),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    payload = AgentMessageOut.model_validate(message).model_dump(mode="json")
    payload["agent_name"] = agent_name(message.agent)
    payload["created_at"] = _iso(message.created_at)
    return payload


# ---------------------------------------------------------------- 小模型检索

def _load_embedding_vectors(db: Any) -> dict[int, list[float]]:
    rows = db.query(Embedding).all()
    result: dict[int, list[float]] = {}
    for row in rows:
        vector = row.vector or []
        if vector:
            try:
                result[int(row.product_id)] = [float(value) for value in vector]
            except (TypeError, ValueError):
                continue
    return result


def _read_product_image(image_url: str | None) -> bytes | None:
    if not image_url:
        return None
    path = image_url
    if path.startswith("/static/"):
        path = path[len("/static/") :]
    try:
        return (settings.static_dir / path).read_bytes()
    except OSError:
        return None


def _chebyshev(nlp_model: Any, a: list[float], b: list[float]) -> float:
    try:
        if hasattr(nlp_model, "chebyshev"):
            return float(nlp_model.chebyshev(a, b))
    except Exception:
        pass
    if not a or len(a) != len(b):
        raise ValueError("向量维度不一致")
    return max(abs(float(x) - float(y)) for x, y in zip(a, b))


def _neighbor_id(item: Any) -> int | None:
    """兼容 T3 ``neighbors`` 的返回：``{"id": "product:3", "type": "product"}``。"""
    if isinstance(item, dict):
        node_type = item.get("type")
        if node_type and node_type != "product":
            return None
        for key in ("product_id", "productId"):
            if item.get(key) is not None:
                try:
                    return int(item[key])
                except (TypeError, ValueError):
                    return None
        node_id = item.get("id")
        if isinstance(node_id, str) and node_id.startswith("product:"):
            try:
                return int(node_id.split(":", 1)[1])
            except (TypeError, ValueError):
                return None
        if node_id is not None and not isinstance(node_id, str):
            try:
                return int(node_id)
            except (TypeError, ValueError):
                return None
        return None
    value = getattr(item, "id", None)
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    try:
        return int(item)
    except (TypeError, ValueError):
        return None


async def _retrieve_with_small_models(
    db: Any,
    image_bytes: bytes,
    note: str,
    products: list[Any],
) -> tuple[list[Any], str] | None:
    """用 T3 视觉模型检索 Top-8，再用 NLP-KG 做邻域扩展。

    返回 ``(候选商品, 后端名)``；模块尚未就绪返回 ``None``，
    模块存在但调用失败抛异常，由业务层降级并推送 warning。
    """
    try:
        from ..small_models.factory import get_nlp_kg_model, get_vision_model
    except Exception as exc:  # 模块不存在或依赖未安装
        raise SmallModelUnavailable(str(exc)) from exc

    vision_model = get_vision_model()
    nlp_model = get_nlp_kg_model()
    if vision_model is None:
        raise SmallModelUnavailable("视觉小模型未注册")

    query_vector = await vision_model.embed(image_bytes)
    if not query_vector:
        raise ValueError("视觉小模型返回空向量")

    by_id = {int(item.id): item for item in products}
    vectors = _load_embedding_vectors(db)
    missing = [item for item in products if int(item.id) not in vectors]
    if missing:
        ids: list[int] = []
        images: list[bytes] = []
        for product in missing:
            data = _read_product_image(getattr(product, "image", None))
            if data:
                ids.append(int(product.id))
                images.append(data)
        if images:
            if hasattr(vision_model, "embed_many"):
                computed = await vision_model.embed_many(images)
            else:
                computed = [await vision_model.embed(image) for image in images]
            for product_id, vector in zip(ids, computed or []):
                if vector:
                    vectors[product_id] = [float(value) for value in vector]

    candidate_payload = [
        {"product_id": product_id, "embedding": vector}
        for product_id, vector in vectors.items()
        if product_id in by_id
    ]

    # 优先走 T3 的 NLP-KG rank（兼容 HTTP 远程实现），失败再用本地切比雪夫。
    ranked_ids: list[int] = []
    try:
        matches = await nlp_model.rank(query_vector, candidate_payload, 8)
        for item in matches or []:
            product_id = _neighbor_id(item)
            if product_id is not None and product_id in by_id and product_id not in ranked_ids:
                ranked_ids.append(product_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("NLP-KG rank 失败，改用本地切比雪夫排序：%s", exc)

    if len(ranked_ids) < 8:
        scored: list[tuple[float, int]] = []
        for product_id, vector in vectors.items():
            if product_id not in by_id or not vector:
                continue
            try:
                distance = _chebyshev(nlp_model, query_vector, vector)
            except Exception:
                continue
            scored.append((distance, product_id))
        scored.sort(key=lambda item: (item[0], item[1]))
        for _, product_id in scored:
            if len(ranked_ids) >= 8:
                break
            if product_id not in ranked_ids:
                ranked_ids.append(product_id)

    top_ids = ranked_ids[:8]
    if not top_ids:
        raise SmallModelUnavailable("视觉向量库为空")

    neighbor_ids: list[int] = []
    for product_id in top_ids[:3]:
        try:
            items = await nlp_model.neighbors(product_id, limit=4)
        except Exception:
            items = []
        for item in items or []:
            neighbor = _neighbor_id(item)
            if neighbor and neighbor in by_id and neighbor not in top_ids and neighbor not in neighbor_ids:
                neighbor_ids.append(neighbor)

    candidates = [by_id[product_id] for product_id in top_ids if product_id in by_id]
    for product_id in neighbor_ids:
        if len(candidates) >= 12:
            break
        if product_id not in top_ids:
            candidates.append(by_id[product_id])

    if not candidates:
        raise SmallModelUnavailable("检索结果为空")
    backend_name = getattr(vision_model, "name", None) or "small-model"
    return candidates, str(backend_name)


# ---------------------------------------------------------------- 回退检索

def _fallback_score(product: Any, vision: VisionAnalysis, note: str, image_hash: str) -> float:
    product_id = int(getattr(product, "id", 0))
    digest = hashlib.sha256(f"{image_hash}|fallback|{product_id}".encode()).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    score = 0.0
    category = str(getattr(product, "category", "") or "")
    if category == vision.category:
        score += 2.4
    occasion = str(getattr(product, "occasion", "") or "")
    tokens = [vision.occasion, *[word for word in ("通勤", "约会", "晚宴", "休闲", "校园", "度假") if note and word in note]]
    if any(token and token in occasion for token in tokens):
        score += 1.0
    tags = set(getattr(product, "style_tags", []) or [])
    style_hits = len(tags & set(vision.style))
    score += min(2.2, style_hits * 0.75)
    colors = set(getattr(product, "colors", []) or [])
    color_hits = len(colors & set(vision.colors))
    score += min(1.8, color_hits * 0.9)
    if getattr(product, "featured", False):
        score += 0.5
    score += min(0.7, max(0.0, float(getattr(product, "rating", 4.5) or 4.5) - 4.4) * 0.5)
    score += min(0.4, math.log1p(int(getattr(product, "sales", 0) or 0)) / 12)
    score += rng.uniform(0.0, 0.45)
    return score


def _fallback_retrieval(
    products: list[Any], vision: VisionAnalysis, note: str, image_bytes: bytes
) -> list[Any]:
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    ranked = sorted(
        products,
        key=lambda item: (
            -_fallback_score(item, vision, note, image_hash),
            int(getattr(item, "id", 0)),
        ),
    )
    return ranked[:8]


def _add_best_category(
    result: list[Any], selected_ids: set[int], products: list[Any], category: str
) -> bool:
    options = [
        item
        for item in products
        if getattr(item, "category", "") == category and int(item.id) not in selected_ids
    ]
    if not options:
        return False
    best = max(
        options,
        key=lambda item: (
            bool(getattr(item, "featured", False)),
            float(getattr(item, "rating", 0) or 0),
            int(getattr(item, "sales", 0) or 0),
            -int(item.id),
        ),
    )
    result.append(best)
    selected_ids.add(int(best.id))
    return True


def _ensure_complements(candidates: list[Any], products: list[Any]) -> list[Any]:
    """补齐外套/上装/下装（或裙装）与配饰，保证整套 outfit 可行。"""
    result = list(candidates)
    selected_ids = {int(item.id) for item in result}
    categories = {str(getattr(item, "category", "")) for item in result}

    def add(category: str) -> bool:
        if _add_best_category(result, selected_ids, products, category):
            categories.add(category)
            return True
        return False

    if "外套" not in categories:
        add("外套")
    if "上装" not in categories and "连衣裙" not in categories:
        if not add("连衣裙"):
            add("上装")
    if "下装" not in categories and "连衣裙" not in categories:
        add("下装")
    if len(result) < 12 and "配饰" not in categories:
        add("配饰")
    return result[:12]


# ---------------------------------------------------------------- KG 图

def _build_kg_payload(
    candidates: list[Any],
    bonus_ids: list[int],
    vision: VisionAnalysis,
    backend_name: str,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    def add_node(node_id: str, label: str, node_type: str, meta: dict[str, Any] | None = None) -> None:
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        nodes.append({"id": node_id, "label": label, "type": node_type, "meta": meta or {}})

    for product in candidates:
        product_id = int(product.id)
        add_node(
            f"p{product_id}",
            str(getattr(product, "name", "")),
            "product",
            {
                "category": str(getattr(product, "category", "")),
                "price": float(getattr(product, "price", 0) or 0),
                "image": str(getattr(product, "image", "") or ""),
                "sku": str(getattr(product, "sku", "") or ""),
                "subtitle": str(getattr(product, "subtitle", "") or ""),
                "href": f"/product/{product_id}",
            },
        )
        category = str(getattr(product, "category", ""))
        if category:
            category_id = f"cat:{category}"
            add_node(category_id, category, "category")
            edges.append(
                {
                    "source": f"p{product_id}",
                    "target": category_id,
                    "relation": "属于",
                    "weight": 1.0,
                }
            )

    ranked = candidates[:4]
    for index in range(len(ranked) - 1):
        left = int(ranked[index].id)
        right = int(ranked[index + 1].id)
        edges.append(
            {
                "source": f"p{left}",
                "target": f"p{right}",
                "relation": "相似",
                "weight": round(1.0 / (1.0 + index * 0.35), 2),
                "meta": {"method": "visual-chebyshev"},
            }
        )

    # Text-model semantic edges among the candidate set (BGE-small-zh-v1.5).
    edge_keys = {(edge["source"], edge["target"], edge["relation"]) for edge in edges}
    semantic_added = 0
    try:
        from ..small_models.text_embedding import get_text_embedder, product_text

        embedder = get_text_embedder()
        if embedder.available and len(candidates) >= 2:
            texts = [
                product_text(
                    {
                        "name": getattr(product, "name", ""),
                        "subtitle": getattr(product, "subtitle", ""),
                        "category": getattr(product, "category", ""),
                        "description": getattr(product, "description", ""),
                        "fabric": getattr(product, "fabric", ""),
                        "fit": getattr(product, "fit", ""),
                        "occasion": getattr(product, "occasion", ""),
                        "season": getattr(product, "season", ""),
                        "style_tags": getattr(product, "style_tags", []) or [],
                        "colors": getattr(product, "colors", []) or [],
                        "sizes": getattr(product, "sizes", []) or [],
                    }
                )
                for product in candidates
            ]
            vectors = embedder.embed(texts)
            if len(vectors) == len(candidates):
                similarities = vectors @ vectors.T
                np.fill_diagonal(similarities, -1.0)
                for index, product in enumerate(candidates):
                    for neighbor_index in np.argsort(-similarities[index])[:3]:
                        similarity = float(similarities[index, int(neighbor_index)])
                        if similarity < 0.55:
                            continue
                        left, right = sorted(
                            (int(product.id), int(candidates[int(neighbor_index)].id))
                        )
                        key = (f"p{left}", f"p{right}", "semantic_similar")
                        if key in edge_keys:
                            continue
                        edge_keys.add(key)
                        edges.append(
                            {
                                "source": f"p{left}",
                                "target": f"p{right}",
                                "relation": "semantic_similar",
                                "weight": round(similarity, 4),
                                "meta": {
                                    "method": "text-embedding",
                                    "model": embedder.name,
                                    "similarity": round(similarity, 4),
                                },
                            }
                        )
                        semantic_added += 1
    except Exception as exc:  # noqa: BLE001 - optional enrichment
        logger.debug("stylist text semantic edges skipped: %s", exc)

    if candidates:
        anchor = f"p{int(candidates[0].id)}"
        for product_id in bonus_ids:
            if f"p{int(product_id)}" not in node_ids:
                continue
            edges.append(
                {
                    "source": anchor,
                    "target": f"p{int(product_id)}",
                    "relation": "搭配",
                    "weight": 0.62,
                }
            )
        for tag in [*vision.style[:2], *vision.colors[:1]]:
            if not tag:
                continue
            node_id = f"attr:{tag}"
            add_node(node_id, tag, "attribute")
            edges.append(
                {
                    "source": anchor,
                    "target": node_id,
                    "relation": "风格呼应",
                    "weight": 0.5,
                }
            )

    seed_count = max(1, len(candidates) - len(bonus_ids))
    source_label = "视觉小模型" if backend_name != "fallback" else "内置回退检索"
    summary = (
        f"{source_label}以切比雪夫距离检索到 {max(1, seed_count)} 件相似单品，"
        f"NLP-KG 沿品类/风格边扩展 {len(bonus_ids)} 件搭配候选，"
        f"共 {len(nodes)} 个节点、{len(edges)} 条关系。"
    )
    if semantic_added:
        summary += f" 文本语义模型补充 {semantic_added} 条 semantic_similar 边。"
    return {
        "nodes": nodes,
        "edges": edges,
        "metric": "chebyshev",
        "summary": summary,
    }


# ---------------------------------------------------------------- 聚合

def _collect_score_matrix(
    opinions: dict[str, AgentOpinion],
) -> tuple[dict[int, dict[str, float]], dict[tuple[str, int], str]]:
    matrix: dict[int, dict[str, float]] = {}
    reasons: dict[tuple[str, int], str] = {}
    for agent, opinion in opinions.items():
        for item in opinion.scores:
            matrix.setdefault(int(item.product_id), {})[agent] = clamp_score(item.score)
            if item.reason:
                reasons[(agent, int(item.product_id))] = item.reason
    return matrix, reasons


def _scored_items(
    candidates: list[Any],
    opinions: dict[str, AgentOpinion],
    ml_bonus_ids: set[int],
    vision: VisionAnalysis,
) -> list[dict[str, Any]]:
    matrix, reasons = _collect_score_matrix(opinions)
    items: list[dict[str, Any]] = []
    for product in candidates:
        product_id = int(product.id)
        agent_scores = {
            agent: matrix.get(product_id, {}).get(agent, 5.0) for agent in DEFAULT_WEIGHTS
        }
        base = sum(DEFAULT_WEIGHTS[agent] * agent_scores[agent] for agent in DEFAULT_WEIGHTS)
        bonus = 0.0
        if product_id in ml_bonus_ids:
            bonus += 0.3
        if str(getattr(product, "category", "")) == vision.category:
            bonus += 0.15
        overlap = set(getattr(product, "style_tags", []) or []) & set(vision.style)
        bonus += min(0.3, len(overlap) * 0.1)
        contributions = sorted(
            agent_scores.items(),
            key=lambda pair: pair[1] * DEFAULT_WEIGHTS[pair[0]],
            reverse=True,
        )
        reason_list: list[str] = []
        for agent, _ in contributions:
            text = reasons.get((agent, product_id))
            if text:
                entry = f"{agent_name(agent)}：{text}"
                if entry not in reason_list:
                    reason_list.append(entry)
            if len(reason_list) >= 3:
                break
        if not reason_list:
            reason_list = ["五位智能体综合评分进入前列。"]
        items.append(
            {
                "product": product,
                "score": round(min(10.0, base + bonus), 2),
                "reasons": reason_list,
                "agent_scores": {agent: round(value, 2) for agent, value in agent_scores.items()},
            }
        )
    return items


def _select_top3(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    remaining = sorted(items, key=lambda item: (-item["score"], int(item["product"].id)))
    picked: list[dict[str, Any]] = []
    used_categories: Counter[str] = Counter()
    while remaining and len(picked) < 3:
        best = max(
            remaining,
            key=lambda item: item["score"] - 0.45 * used_categories[str(item["product"].category)],
        )
        picked.append(best)
        remaining.remove(best)
        used_categories[str(best["product"].category)] += 1
    return picked


def _supplement_item(product: Any, selected_ids: set[int]) -> dict[str, Any] | None:
    if int(product.id) in selected_ids:
        return None
    return {
        "product": product,
        "score": round(4.4 + float(getattr(product, "rating", 4.5) or 4.5) * 0.12, 2),
        "reasons": ["用于补齐整套造型的搭配单品。"],
    }


def _pick_outfit(
    items: list[dict[str, Any]],
    products: list[Any],
    budget: float | None,
) -> tuple[list[Any], float]:
    pool: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(items, key=lambda entry: -entry["score"]):
        pool.setdefault(str(item["product"].category), []).append(item)

    supplement_used: set[int] = {int(item["product"].id) for item in items}
    for category in _COMPLEMENT_CATEGORIES:
        if pool.get(category):
            continue
        for product in products:
            if str(getattr(product, "category", "")) != category:
                continue
            entry = _supplement_item(product, supplement_used)
            if entry:
                pool.setdefault(category, []).append(entry)
                supplement_used.add(int(product.id))
                break

    def options(category: str, limit: int = 2) -> list[dict[str, Any]]:
        return pool.get(category, [])[:limit]

    outers: list[dict[str, Any] | None] = [*options("外套"), None]
    tops = options("上装")
    bottoms = options("下装")
    dresses = options("连衣裙")
    accessories = options("配饰", 1)

    combos: list[list[dict[str, Any]]] = []
    for dress in dresses:
        for outer in outers:
            combo = [item for item in (outer, dress) if item is not None]
            combos.append(combo)
    for top in tops:
        for bottom in bottoms:
            for outer in outers:
                combo = [item for item in (outer, top, bottom) if item is not None]
                combos.append(combo)
    if not combos:
        combos = [[item] for item in sorted(items, key=lambda entry: -entry["score"])[:2]]
    if accessories:
        expanded: list[list[dict[str, Any]]] = []
        for combo in combos:
            expanded.append(combo)
            ids = {int(item["product"].id) for item in combo}
            if int(accessories[0]["product"].id) not in ids:
                expanded.append([*combo, accessories[0]])
        combos = expanded

    unique: list[list[dict[str, Any]]] = []
    seen_signatures: set[tuple[int, ...]] = set()
    for combo in combos:
        signature = tuple(sorted(int(item["product"].id) for item in combo))
        if signature and signature not in seen_signatures:
            seen_signatures.add(signature)
            unique.append(combo)
    if not unique:
        return [], 0.0

    def total_of(combo: list[dict[str, Any]]) -> float:
        return round(sum(float(getattr(item["product"], "price", 0) or 0) for item in combo), 2)

    def combo_score(combo: list[dict[str, Any]]) -> float:
        categories = {str(item["product"].category) for item in combo}
        completeness = 0.0
        if "外套" in categories:
            completeness += 0.2
        if {"上装", "下装"} <= categories or "连衣裙" in categories:
            completeness += 0.35
        return sum(item["score"] for item in combo) + completeness

    if budget and budget > 0:
        affordable = [combo for combo in unique if total_of(combo) <= budget]
        if affordable:
            best = max(affordable, key=lambda combo: (combo_score(combo), -total_of(combo)))
        else:
            best = min(unique, key=lambda combo: (total_of(combo), -combo_score(combo)))
    else:
        best = max(unique, key=lambda combo: (combo_score(combo), -total_of(combo)))
    outfit_products = [item["product"] for item in best]
    return outfit_products, total_of(best)


def _compose_advice(
    vision: VisionAnalysis,
    picked: list[dict[str, Any]],
    outfit_products: list[Any],
    outfit_total: float,
    budget: float | None,
) -> str:
    styles = "、".join(vision.style[:2]) or "克制"
    colors = "、".join(vision.colors[:2]) or "低饱和色"
    parts = [
        f"照片给我们的第一印象是{vision.occasion or '都市日常'}的{styles}气质，"
        f"主色以{colors}为主。"
    ]
    if picked:
        top = picked[0]
        reason = top["reasons"][0] if top.get("reasons") else ""
        parts.append(f"我们首推「{top['product'].name}」，{reason}")
    if outfit_products:
        names = "」「".join(str(getattr(item, "name", "")) for item in outfit_products)
        if budget and budget > 0:
            if outfit_total <= budget:
                budget_text = f"整套合计 {outfit_total:.0f} 元，控制在 {budget:.0f} 元预算内。"
            else:
                budget_text = (
                    f"整套合计 {outfit_total:.0f} 元，略超 {budget:.0f} 元预算，"
                    f"建议优先保留外套与下装。"
                )
        else:
            budget_text = f"整套合计 {outfit_total:.0f} 元。"
        parts.append(f"整套提案由「{names}」构成，{budget_text}")
    if len(picked) >= 2:
        parts.append(
            f"若想换一种表达，可以把主推单品替换为「{picked[1]['product'].name}」，气质会更轻松。"
        )
    return "".join(parts)


def _build_recommendations(
    candidates: list[Any],
    opinions: dict[str, AgentOpinion],
    ml_bonus_ids: set[int],
    vision: VisionAnalysis,
    products: list[Any],
    budget: float | None,
    session_id: str,
    mode: str,
    kg: dict[str, Any],
    elapsed_ms: int,
) -> dict[str, Any]:
    items = _scored_items(candidates, opinions, ml_bonus_ids, vision)
    picked = _select_top3(items)
    outfit_products, outfit_total = _pick_outfit(items, products, budget)
    advice = _compose_advice(vision, picked, outfit_products, outfit_total, budget)
    final = RecommendationFinal(
        session_id=session_id,
        mode=mode,
        vision=vision,
        candidates=[ProductOut.model_validate(item) for item in candidates],
        recommendations=[
            {
                "product": ProductOut.model_validate(item["product"]),
                "score": item["score"],
                "reasons": item["reasons"],
                "agent_scores": item["agent_scores"],
            }
            for item in picked
        ],
        outfit=[ProductOut.model_validate(item) for item in outfit_products],
        outfit_total=outfit_total,
        advice=advice,
        kg=kg,
        elapsed_ms=elapsed_ms,
    )
    return final.model_dump(mode="json")


# ---------------------------------------------------------------- 主流程

async def _build_candidates(
    db: Any,
    image_bytes: bytes,
    vision: VisionAnalysis,
    note: str,
) -> tuple[list[Any], dict[str, Any], set[int], list[dict[str, Any]], list[Any], str]:
    products = db.query(Product).order_by(Product.id.asc()).all()
    if not products:
        raise NoCandidatesError("商品库中还没有可推荐的单品，请稍后再试")

    warnings: list[dict[str, Any]] = []
    candidates: list[Any] | None = None
    backend_name = "fallback"
    try:
        result = await _retrieve_with_small_models(db, image_bytes, note, products)
        if result is not None:
            candidates, backend_name = result
    except SmallModelUnavailable:
        candidates = None
    except Exception as exc:  # noqa: BLE001 - 任何小模型异常都必须降级
        logger.warning("小模型检索失败，使用内置回退：%s", exc)
        warnings.append(
            {
                "code": "small_model_fallback",
                "message": "小模型检索失败，已使用内置回退方案完成候选筛选",
                "stage": "retrieval",
            }
        )
        candidates = None

    if not candidates:
        candidates = _fallback_retrieval(products, vision, note, image_bytes)
        backend_name = "fallback"

    base_ids = {int(item.id) for item in candidates}
    candidates = _ensure_complements(candidates, products)
    bonus_ids = {int(item.id) for item in candidates if int(item.id) not in base_ids}
    kg = _build_kg_payload(candidates, sorted(bonus_ids), vision, backend_name)
    return candidates, kg, bonus_ids, warnings, products, backend_name


def _create_qwen_backend() -> QwenAgentBackend:
    return QwenAgentBackend(QwenClient())


async def stream_stylist(
    db: Any,
    user: Any,
    image_bytes: bytes,
    *,
    image_format: str = "PNG",
    content_type: str = "",
    budget: float | None = None,
    note: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """执行一次完整的五智能体荐衣，产出 SSE 事件字典。"""
    started = time.perf_counter()
    session = AgentSession(
        user_id=int(getattr(user, "id", 0)),
        kind="stylist",
        status="running",
        mode="qwen" if qwen_available() else "mock",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    session_id = session.id
    configured_mode = "qwen" if qwen_available() else "mock"
    note = (note or "").strip()[:200]
    seen_warnings: set[tuple[str, str]] = set()

    def should_emit_warning(payload: dict[str, Any] | None) -> bool:
        if not payload:
            return False
        key = (str(payload.get("code", "")), str(payload.get("stage", "")))
        if key in seen_warnings:
            return False
        seen_warnings.add(key)
        return True

    try:
        session.input_image = _save_upload(session_id, image_bytes, image_format)
        db.commit()
        yield _event(
            "session",
            {
                "session_id": session_id,
                "mode": configured_mode,
                "stages": list(STAGE_PLAN),
            },
        )
        if configured_mode == "mock" and settings.llm_mode == "qwen":
            yield _event(
                "warning",
                {
                    "code": "qwen_no_key",
                    "message": "未配置 DASHSCOPE_API_KEY，已自动使用本地 Mock 模式",
                    "stage": "vision",
                },
            )

        fallback = MockLLM(image_bytes)
        qwen_backend: QwenAgentBackend | None = None
        if configured_mode == "qwen":
            try:
                qwen_backend = _create_qwen_backend()
            except Exception as exc:  # noqa: BLE001
                logger.warning("初始化 Qwen 失败：%s", exc)
                yield _event(
                    "warning",
                    {
                        "code": "qwen_fallback",
                        "message": "通义千问初始化失败，已降级为本地 Mock 模式",
                        "stage": "vision",
                    },
                )
                qwen_backend = None

        # ------------------------------------------------ 视觉
        yield _stage("vision", "看懂照片", 0.08)
        vision: VisionAnalysis | None = None
        if qwen_backend is not None:
            mime = content_type or _MIME_BY_FORMAT.get(image_format, "image/jpeg")
            try:
                vision = await qwen_backend.analyze_image(image_bytes, mime, note)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Qwen 视觉解析失败：%s", exc)
                warning = {
                    "code": "qwen_fallback",
                    "message": "通义千问视觉解析失败，已降级为本地 Mock 解析",
                    "stage": "vision",
                }
                if should_emit_warning(warning):
                    yield _event("warning", warning)
                vision = None
        if vision is None:
            vision = fallback.vision_analysis(note)
        yield _event("vision", vision.model_dump())

        # ------------------------------------------------ 检索
        yield _stage("retrieval", "小模型检索", 0.3)
        (
            candidates,
            kg,
            bonus_ids,
            retrieval_warnings,
            products,
            retrieval_backend,
        ) = await _build_candidates(db, image_bytes, vision, note)
        for warning in retrieval_warnings:
            if should_emit_warning(warning):
                yield _event("warning", warning)
        candidate_payload = [
            ProductOut.model_validate(item).model_dump(mode="json") for item in candidates
        ]
        yield _event(
            "candidates",
            {
                "items": candidate_payload,
                "metric": "chebyshev",
                "backend": retrieval_backend,
            },
        )
        yield _event("kg", kg)

        # 阶段边界落库：即使随后客户端断开，也能回看视觉解析与候选。
        try:
            partial = db.get(AgentSession, session_id)
            if partial is not None:
                partial.result = {
                    "vision": vision.model_dump(),
                    "candidates": candidate_payload,
                    "kg": kg,
                    "budget": budget,
                    "note": note,
                }
                db.commit()
        except Exception:  # pragma: no cover - 部分结果写入失败不影响主链路
            logger.exception("写入阶段性结果失败")
            try:
                db.rollback()
            except Exception:
                pass

        # ------------------------------------------------ 两轮评议
        ctx = DiscussionContext(
            vision=vision, candidates=candidates, budget=budget, note=note
        )
        bus = MessageBus(session_id=session_id)
        backend = qwen_backend or fallback
        opinions: dict[str, AgentOpinion] = {}

        yield _stage("round1", "独立评议", 0.48)
        yield _event("agent_round", {"round": 1, "label": "第一轮 · 独立评分"})
        async for record, opinion, warning in run_round1(bus, backend, fallback, ctx):
            if should_emit_warning(warning):
                yield _event("warning", warning)
            opinions[opinion.agent] = opinion
            message_payload = _save_message(db, session_id, record)
            yield _event("agent_message", message_payload)

        yield _stage("round2", "交叉讨论", 0.7)
        yield _event("agent_round", {"round": 2, "label": "第二轮 · 交叉讨论与修订"})
        round2_opinions: dict[str, AgentOpinion] = {}
        async for record, opinion, revisions, warning in run_round2(
            bus, backend, fallback, ctx, opinions
        ):
            if should_emit_warning(warning):
                yield _event("warning", warning)
            round2_opinions[opinion.agent] = opinion
            message_payload = _save_message(db, session_id, record)
            yield _event("agent_message", message_payload)
            for revision in revisions:
                yield _event("revision", revision.to_dict())

        # ------------------------------------------------ 聚合
        yield _stage("aggregate", "策展汇总", 0.92)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        final_payload = _build_recommendations(
            candidates=candidates,
            opinions=round2_opinions or opinions,
            ml_bonus_ids=bonus_ids,
            vision=vision,
            products=products,
            budget=budget,
            session_id=session_id,
            mode=configured_mode,
            kg=kg,
            elapsed_ms=elapsed_ms,
        )
        session = db.get(AgentSession, session_id)
        if session is not None:
            session.status = "done"
            session.mode = configured_mode
            session.error = None
            session.result = final_payload
            db.commit()
        yield _event("final", final_payload)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        yield _event("done", {"session_id": session_id, "elapsed_ms": elapsed_ms})

    except NoCandidatesError as exc:
        _fail_session(db, session_id, str(exc))
        yield _event("error", {"code": "no_candidates", "message": str(exc)})
        yield _event(
            "done",
            {
                "session_id": session_id,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            },
        )
    except asyncio.CancelledError:
        # 客户端主动断开：尽量把已完成的部分落库，并把会话标记为失败。
        try:
            db.rollback()
        except Exception:
            pass
        _fail_session(db, session_id, "客户端断开连接，推荐未完整结束")
        raise
    except Exception as exc:  # noqa: BLE001 - 流式接口不能以 500 收场
        logger.exception("五智能体荐衣失败")
        try:
            db.rollback()
        except Exception:
            pass
        _fail_session(db, session_id, f"推荐过程异常：{type(exc).__name__}")
        yield _event(
            "error",
            {"code": "recommend_failed", "message": "五智能体评议过程出错，请稍后重试"},
        )
        yield _event(
            "done",
            {
                "session_id": session_id,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            },
        )


__all__ = [
    "InvalidImageError",
    "NoCandidatesError",
    "SmallModelUnavailable",
    "sniff_image",
    "stream_stylist",
]
