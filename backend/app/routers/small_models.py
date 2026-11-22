"""小模型 HTTP 路由：状态、视觉 embedding/相似检索、Chebyshev、KG 查询/图谱。

契约见 docs/CONTRACTS.md 3.5 与 docs/small-model-interface.md。
除 ``status`` 外均可选 Bearer（匿名可演示）；业务错误返回中文 detail。
"""
from __future__ import annotations

import io
import logging
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..database import get_db
from ..deps import get_optional_user
from ..models import Product, User
from ..schemas import (
    ChebyshevRequest,
    ChebyshevResponse,
    KGEdge,
    KGGraphOut,
    KGNode,
    KGQueryRequest,
    KGQueryResponse,
    SimilarMatch,
    SmallModelsStatus,
    VisionEmbedResponse,
    VisionSimilarResponse,
)
from ..small_models import factory
from ..small_models.http_adapters import SmallModelServiceError
from ..small_models.metrics import chebyshev_distance, chebyshev_similarity

logger = logging.getLogger("yijian.small_models.router")

router = APIRouter(prefix="/small-models", tags=["小模型"])

MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8MB
ALLOWED_HINT = "支持 JPG / PNG / WEBP / GIF / BMP 格式"

_PRODUCT_NODE = "product:{product_id}"


# ------------------------------------------------------------------ 工具
async def _read_valid_image(file: UploadFile | None) -> bytes:
    """读取 multipart 图片并做大小 + Pillow 校验；失败抛中文 400。"""
    if file is None or not file.filename:
        raise HTTPException(status_code=400, detail="请选择要上传的图片")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="图片内容为空，请重新选择图片")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="图片大小不能超过 8MB，请压缩后重试")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"无法识别该图片，请上传 {ALLOWED_HINT} 的图片文件",
        ) from exc
    except Exception as exc:  # Pillow verify 可能抛 OSError / SyntaxError / ValueError
        logger.info("图片校验失败：%s", exc)
        raise HTTPException(
            status_code=400,
            detail="图片已损坏或格式不受支持，请换一张图片重试",
        ) from exc
    return data


def _get_product_map(db: Session, product_ids: list[int]) -> dict[int, Product]:
    if not product_ids:
        return {}
    rows = db.query(Product).filter(Product.id.in_(product_ids)).all()
    return {product.id: product for product in rows}


def _service_error(exc: SmallModelServiceError, label: str) -> HTTPException:
    return HTTPException(status_code=502, detail=f"{label}暂不可用：{exc}")


# ------------------------------------------------------------------ 状态
@router.get("/status", response_model=SmallModelsStatus, summary="小模型状态")
def small_models_status(
    user: User | None = Depends(get_optional_user),
) -> SmallModelsStatus:
    data = factory.models_status()
    nlp_info = dict(data["nlp_kg"])
    nlp_info["warm_up"] = data["warm_up"]
    return SmallModelsStatus(mode=data["mode"], vision=data["vision"], nlp_kg=nlp_info)


# ------------------------------------------------------------------ 视觉
@router.post("/vision/embed", response_model=VisionEmbedResponse, summary="图片向量化")
async def vision_embed(
    file: UploadFile = File(..., description="商品图片（JPG/PNG/WEBP，≤8MB）"),
    user: User | None = Depends(get_optional_user),
) -> VisionEmbedResponse:
    data = await _read_valid_image(file)
    model = factory.get_vision_model()
    try:
        vector = await model.embed(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SmallModelServiceError as exc:
        raise _service_error(exc, "视觉小模型服务") from exc
    except Exception as exc:  # pragma: no cover - 兜底
        logger.exception("视觉 embedding 失败")
        raise HTTPException(status_code=500, detail="图片编码失败，请稍后重试") from exc
    if not vector:
        raise HTTPException(status_code=500, detail="视觉小模型没有返回有效向量，请稍后重试")
    info = model.info()
    return VisionEmbedResponse(
        embedding=[float(value) for value in vector],
        dim=len(vector),
        model_version=str(info.get("version", "")),
        backend=str(info.get("backend", "stub")),
    )


@router.post("/vision/similar", response_model=VisionSimilarResponse, summary="以图搜衣")
async def vision_similar(
    file: UploadFile = File(..., description="商品图片（JPG/PNG/WEBP，≤8MB）"),
    top_k: int = Query(default=8, ge=1, le=50, description="返回相似商品数量（query）"),
    top_k_form: int | None = Form(default=None, alias="top_k", ge=1, le=50, description="返回相似商品数量（multipart，前端使用）"),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> VisionSimilarResponse:
    started = time.monotonic()
    effective_top_k = top_k_form if top_k_form is not None else top_k
    data = await _read_valid_image(file)
    vision = factory.get_vision_model()
    try:
        query_embedding = await vision.embed(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SmallModelServiceError as exc:
        raise _service_error(exc, "视觉小模型服务") from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("相似检索编码失败")
        raise HTTPException(status_code=500, detail="图片编码失败，请稍后重试") from exc

    try:
        # 补算缺失 embedding（同步，放线程池，避免阻塞事件循环）
        await run_in_threadpool(factory.ensure_embeddings, db)
        embedding_rows = factory.load_embedding_rows(db)
        nlp = factory.get_nlp_kg_model()
        candidates = [
            {"product_id": row["product_id"], "embedding": row["embedding"]}
            for row in embedding_rows
        ]
        matches_raw = await nlp.rank(query_embedding, candidates, effective_top_k)
    except SmallModelServiceError as exc:
        raise _service_error(exc, "NLP 小模型服务") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"向量维度不匹配：{exc}") from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("相似检索失败")
        raise HTTPException(status_code=500, detail="相似检索失败，请稍后重试") from exc

    product_map = _get_product_map(db, [item["product_id"] for item in matches_raw])
    matches: list[SimilarMatch] = []
    for item in matches_raw:
        product = product_map.get(item["product_id"])
        if product is None:
            continue
        matches.append(
            SimilarMatch(
                product=product,  # type: ignore[arg-type] - from_attributes
                distance=float(item["distance"]),
                similarity=float(item["similarity"]),
            )
        )
    info = vision.info()
    return VisionSimilarResponse(
        query_embedding=[float(value) for value in query_embedding],
        matches=matches,
        backend=str(info.get("backend", "stub")),
        model_version=str(info.get("version", "")),
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


# ------------------------------------------------------------------ KG
@router.post("/kg/chebyshev", response_model=ChebyshevResponse, summary="切比雪夫距离")
async def kg_chebyshev(
    payload: ChebyshevRequest,
    user: User | None = Depends(get_optional_user),
) -> ChebyshevResponse:
    try:
        distance = chebyshev_distance(payload.a, payload.b)
        similarity = chebyshev_similarity(payload.a, payload.b)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChebyshevResponse(distance=round(distance, 6), similarity=round(similarity, 6))


@router.post("/kg/query", response_model=KGQueryResponse, summary="NLP-KG 查询与扩展")
async def kg_query(
    payload: KGQueryRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> KGQueryResponse:
    try:
        await run_in_threadpool(factory.ensure_graph, db)
        nlp = factory.get_nlp_kg_model()
        query_fn = getattr(nlp, "query", None)
        if query_fn is not None:
            result = await query_fn(payload.text, payload.top_k)
        else:
            # 自定义模型只实现 ABC 时，降级为纯抽取（无图谱扩展）
            extraction = await nlp.extract(payload.text)
            result = {
                "triples": extraction.get("triples", []),
                "product_ids": [],
                "related_terms": extraction.get("keywords", []),
            }
    except SmallModelServiceError as exc:
        raise _service_error(exc, "NLP-KG 小模型服务") from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("KG 查询失败")
        raise HTTPException(status_code=500, detail="知识图谱查询失败，请稍后重试") from exc

    product_ids = [int(pid) for pid in result.get("product_ids", [])]
    product_map = _get_product_map(db, product_ids)
    products = [product_map[pid] for pid in product_ids if pid in product_map]
    triples = [triple for triple in result.get("triples", []) if isinstance(triple, dict)]
    related_terms = [str(term) for term in result.get("related_terms", []) if term]
    return KGQueryResponse(triples=triples, products=products, related_terms=related_terms)


@router.get("/kg/graph", response_model=KGGraphOut, summary="知识图谱快照")
async def kg_graph(
    product_id: int | None = Query(default=None, ge=1, description="聚焦某个商品的一跳子图"),
    limit: int = Query(default=60, ge=1, le=300, description="最多返回节点数"),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> KGGraphOut:
    try:
        await run_in_threadpool(factory.ensure_graph, db)
    except SmallModelServiceError as exc:
        raise _service_error(exc, "NLP-KG 小模型服务") from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("构建知识图谱失败")
        raise HTTPException(status_code=500, detail="知识图谱构建失败，请稍后重试") from exc

    snapshot = factory.current_graph()
    nodes = snapshot["nodes"]
    edges = snapshot["edges"]

    if product_id is not None:
        center = _PRODUCT_NODE.format(product_id=product_id)
        if not any(node["id"] == center for node in nodes):
            return KGGraphOut(
                nodes=[], edges=[], metric="chebyshev", meta=snapshot.get("meta", {})
            )
        keep = {center}
        for edge in edges:
            if center in (edge["source"], edge["target"]):
                keep.add(edge["source"])
                keep.add(edge["target"])
        nodes = [node for node in nodes if node["id"] in keep]
        edges = [
            edge
            for edge in edges
            if edge["source"] in keep and edge["target"] in keep
        ]
    else:
        # 商品节点优先保留，保证有限节点数下图谱仍能看到 similar_to / pairs_with
        nodes = sorted(nodes, key=lambda node: 0 if node["type"] == "product" else 1)[:limit]
        keep = {node["id"] for node in nodes}
        edges = [edge for edge in edges if edge["source"] in keep and edge["target"] in keep]
        edges = sorted(
            edges,
            key=lambda edge: (
                0
                if edge["source"].startswith("product:") and edge["target"].startswith("product:")
                else 1
            ),
        )

    limited_edges = edges[: max(limit * 4, 1)]
    meta = snapshot.get("meta", {})
    return KGGraphOut(
        nodes=[KGNode(**node) for node in nodes],
        edges=[KGEdge(**edge) for edge in limited_edges],
        metric=str(meta.get("metric", "chebyshev")),
        meta=meta,
    )
