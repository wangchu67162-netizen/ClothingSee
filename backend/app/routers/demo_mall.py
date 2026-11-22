"""云裳商城 API — the built-in simulated mall used by the browser assistant.

The static pages (``/demo-mall/…``) are mounted by ``app.main``; this router
only owns the JSON API:

* ``GET  /demo-mall/api/products?q=``
* ``GET  /demo-mall/api/products/{id}``
* ``POST /demo-mall/api/orders``

Checkout requires a valid ``BrowseTask.task_token`` created by the assistant.
The price is always recomputed server-side and the resulting platform order is
marked ``source="agent"`` with ``external_ref=<order_no>``. Re-posting the same
task token is idempotent.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, or_
from sqlalchemy.orm import Session

from ..browser.order_service import MallOrderError, create_agent_order
from ..database import get_db
from ..models import BrowseTask, Product
from ..schemas import ProductOut

router = APIRouter(prefix="/demo-mall/api", tags=["云裳商城"])


class MallCustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    phone: str = Field(min_length=5, max_length=24)
    address: str = Field(min_length=3, max_length=256)


class MallOrderIn(BaseModel):
    task_token: str = Field(min_length=8, max_length=64)
    product_id: int = Field(ge=1)
    size: str = Field(default="", max_length=16)
    color: str = Field(default="", max_length=32)
    quantity: int = Field(default=1, ge=1, le=10)
    customer: MallCustomerIn


class MallOrderOut(BaseModel):
    order_no: str
    total: float
    status: str = "paid"
    idempotent: bool = False


class MallProductListOut(BaseModel):
    items: list[ProductOut]
    total: int
    query: str = ""


@router.get("/products", response_model=MallProductListOut, summary="商城商品列表/搜索")
def list_products(
    q: str = Query(default="", max_length=64),
    db: Session = Depends(get_db),
) -> MallProductListOut:
    query = db.query(Product)
    keyword = (q or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                Product.name.like(like),
                Product.subtitle.like(like),
                Product.category.like(like),
                Product.search_text.like(like),
                Product.style_tags.cast(String).like(like),
            )
        )
    products = (
        query.order_by(Product.featured.desc(), Product.sales.desc(), Product.id.asc())
        .limit(48)
        .all()
    )
    items = [ProductOut.model_validate(product) for product in products]
    return MallProductListOut(items=items, total=len(items), query=keyword)


@router.get("/products/{product_id}", response_model=ProductOut, summary="商城商品详情")
def product_detail(product_id: int, db: Session = Depends(get_db)) -> ProductOut:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在或已下架")
    return ProductOut.model_validate(product)


@router.post("/orders", response_model=MallOrderOut, summary="商城下单（需任务令牌）")
def place_order(payload: MallOrderIn, db: Session = Depends(get_db)) -> MallOrderOut:
    task = (
        db.query(BrowseTask)
        .filter(BrowseTask.task_token == payload.task_token.strip())
        .one_or_none()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="任务令牌无效或已过期，请从购物助理重新发起下单")
    product = db.get(Product, payload.product_id)
    try:
        order, created = create_agent_order(
            db,
            task=task,
            product=product,
            size=payload.size,
            color=payload.color,
            quantity=payload.quantity,
            customer=payload.customer.model_dump(),
        )
    except MallOrderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return MallOrderOut(
        order_no=order.order_no,
        total=float(order.total),
        status=order.status,
        idempotent=not created,
    )
