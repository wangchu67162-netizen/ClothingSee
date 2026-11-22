"""Product catalog: listing, keyword/category filters, sorting and image search."""
from __future__ import annotations

import importlib
import inspect
import logging
import math

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ..catalog_data import CATEGORIES
from ..database import get_db
from ..models import Embedding, Product
from ..schemas import CategoryOut, ImageSearchOut, ProductListOut, ProductOut

router = APIRouter(prefix="/products", tags=["商品"])

logger = logging.getLogger("yijian.products")

SORT_OPTIONS = ("new", "sales", "price_asc", "price_desc")
SORT_ERROR = "排序方式无效，仅支持 new、sales、price_asc、price_desc"
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _keyword_condition(term: str):
    pattern = _like_pattern(term)
    return or_(
        Product.name.ilike(pattern, escape="\\"),
        Product.subtitle.ilike(pattern, escape="\\"),
        Product.description.ilike(pattern, escape="\\"),
        Product.search_text.ilike(pattern, escape="\\"),
        cast(Product.style_tags, String).ilike(pattern, escape="\\"),
    )


@router.get("", response_model=ProductListOut)
def list_products(
    q: str = Query(default="", max_length=100, description="关键词"),
    category: str = Query(default="", max_length=32, description="分类"),
    sort: str = Query(default="new", description="new | sales | price_asc | price_desc"),
    featured: bool | None = Query(default=None, description="仅看精选"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=60),
    db: Session = Depends(get_db),
) -> ProductListOut:
    if sort not in SORT_OPTIONS:
        raise HTTPException(status_code=400, detail=SORT_ERROR)

    conditions = []
    category = category.strip()
    if category:
        conditions.append(Product.category == category)

    terms = [term for term in q.replace("　", " ").split() if term][:8]
    for term in terms:
        conditions.append(_keyword_condition(term))

    if featured is not None:
        conditions.append(Product.featured.is_(featured))

    total = int(db.scalar(select(func.count(Product.id)).where(*conditions)) or 0)

    if sort == "sales":
        ordering = (Product.sales.desc(), Product.id.asc())
    elif sort == "price_asc":
        ordering = (Product.price.asc(), Product.id.asc())
    elif sort == "price_desc":
        ordering = (Product.price.desc(), Product.id.asc())
    else:  # new
        ordering = (Product.created_at.desc(), Product.id.desc())

    products = db.scalars(
        select(Product)
        .where(*conditions)
        .order_by(*ordering)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    pages = math.ceil(total / page_size) if total else 0
    return ProductListOut(
        items=[ProductOut.model_validate(product) for product in products],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


# NOTE: registered before /{product_id} so "categories" is not parsed as an id.
@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[CategoryOut]:
    rows = db.execute(
        select(Product.category, func.count(Product.id)).group_by(Product.category)
    ).all()
    counts = {str(name): int(count) for name, count in rows}
    ordered: list[CategoryOut] = []
    for name in CATEGORIES:
        if name in counts:
            ordered.append(CategoryOut(name=name, count=counts.pop(name)))
    for name in sorted(counts):
        ordered.append(CategoryOut(name=name, count=counts[name]))
    return ordered


def _load_chebyshev():
    """Import T3's Chebyshev helpers; tolerate both metrics.py and chebyshev.py names."""
    for module_name in ("app.small_models.metrics", "app.small_models.chebyshev"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        distance_fn = getattr(module, "chebyshev_distance", None)
        similarity_fn = getattr(module, "chebyshev_similarity", None)
        if callable(distance_fn) or callable(similarity_fn):
            return distance_fn, similarity_fn
    return None, None


def _local_chebyshev(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        raise ValueError("向量维度不一致")
    return max(abs(float(x) - float(y)) for x, y in zip(a, b))


async def _resolve(value):
    if inspect.isawaitable(value):
        return await value
    return value


@router.post("/search-by-image", response_model=ImageSearchOut)
async def search_by_image(
    file: UploadFile = File(..., description="查询图片"),
    top_k: int = Form(default=8, ge=1, le=20),
    db: Session = Depends(get_db),
) -> ImageSearchOut:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="请上传图片文件")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片过大，请压缩后再试")

    # T3 owns the small-model layer; import lazily so the catalog works without it.
    try:
        factory = importlib.import_module("app.small_models.factory")
        get_vision_model = getattr(factory, "get_vision_model", None)
        if not callable(get_vision_model):
            raise ImportError("get_vision_model 未实现")
    except Exception:
        logger.info("视觉小模型工厂未就绪，图片检索返回 503")
        raise HTTPException(status_code=503, detail="图片检索模型尚未就绪，请稍后重试")

    try:
        model = await _resolve(get_vision_model())
    except Exception:
        logger.exception("视觉小模型加载失败")
        raise HTTPException(status_code=503, detail="图片检索模型加载失败，请稍后重试")
    if model is None:
        raise HTTPException(status_code=503, detail="图片检索模型尚未就绪，请稍后重试")

    try:
        embedded = await _resolve(model.embed(raw))
        query_vector = [float(value) for value in embedded]
    except Exception:
        logger.exception("图片向量化失败")
        raise HTTPException(status_code=503, detail="图片解析失败，请换一张图片重试")
    if not query_vector:
        raise HTTPException(status_code=503, detail="图片解析失败，请换一张图片重试")

    rows = db.execute(select(Embedding.product_id, Embedding.vector)).all()
    if not rows:
        raise HTTPException(status_code=503, detail="商品视觉索引尚未构建完成，请稍后重试")

    distance_fn, similarity_fn = _load_chebyshev()
    scored: list[tuple[float, float, int, float]] = []
    for product_id, vector in rows:
        if not isinstance(vector, list) or not vector or len(vector) != len(query_vector):
            continue
        try:
            distance: float | None = None
            similarity: float | None = None
            if callable(distance_fn):
                distance = float(await _resolve(distance_fn(query_vector, vector)))
            if callable(similarity_fn):
                similarity = float(await _resolve(similarity_fn(query_vector, vector)))
            if distance is None:
                if similarity is not None:
                    distance = (1.0 / similarity - 1.0) if similarity > 0 else float("inf")
                else:
                    distance = _local_chebyshev(query_vector, vector)
            if similarity is None:
                similarity = 1.0 / (1.0 + max(distance, 0.0))
        except Exception:
            logger.debug("跳过无法比较的 embedding: product_id=%s", product_id)
            continue
        scored.append((distance, -similarity, int(product_id), similarity))

    if not scored:
        raise HTTPException(status_code=503, detail="商品视觉索引与当前模型不一致，请稍后重试")

    scored.sort(key=lambda row: (row[0], row[2]))
    top = scored[:top_k]
    ids = [row[2] for row in top]
    products = {
        product.id: product
        for product in db.scalars(select(Product).where(Product.id.in_(ids))).all()
    }

    items: list[ProductOut] = []
    for _distance, _neg_similarity, product_id, similarity in top:
        product = products.get(product_id)
        if product is None:
            continue
        item = ProductOut.model_validate(product)
        item.similarity = round(similarity, 6)
        items.append(item)

    if not items:
        raise HTTPException(status_code=503, detail="商品视觉索引尚未构建完成，请稍后重试")

    backend = str(
        getattr(model, "backend", None)
        or getattr(model, "name", None)
        or "stub"
    )
    vision = None
    info = getattr(model, "info", None)
    if callable(info):
        try:
            maybe_info = await _resolve(info())
            if isinstance(maybe_info, dict):
                vision = maybe_info
        except Exception:
            vision = None

    return ImageSearchOut(
        items=items,
        distance_metric="chebyshev",
        backend=backend,
        vision=vision,
    )


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)) -> ProductOut:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    return ProductOut.model_validate(product)
