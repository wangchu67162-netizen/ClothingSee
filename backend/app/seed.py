"""Idempotent demo data seeding: catalog, demo account and one historical order.

Called once from ``app.main`` lifespan (``seed_if_empty``) and safe to call
repeatedly: every entity is looked up by its natural key (SKU / username /
fixed order number) before being inserted.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .catalog_data import DEMO_ORDER_SKUS, DEMO_USER, PRODUCTS
from .models import Order, OrderItem, Product, User
from .security import hash_password

logger = logging.getLogger("yijian.seed")

# Fixed order number keeps seeding idempotent. Format: YJ + yyyyMMddHHmmss + 4 digits.
DEMO_ORDER_NO = "YJ202401010900000001"
DEMO_ORDER_CREATED_AT = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
DEMO_ORDER_SHIPPING = {
    "name": "云裳体验官",
    "phone": "13800000000",
    "address": "上海市徐汇区云裳路 1 号 衣见大厦",
}
DEMO_ORDER_NOTE = "课程演示历史订单（模拟支付）"


def build_search_text(data: dict) -> str:
    """Concatenate name / subtitle / description / style tags / fabric for keyword search."""
    parts = [
        str(data.get("name") or ""),
        str(data.get("subtitle") or ""),
        str(data.get("description") or ""),
        " ".join(str(tag) for tag in (data.get("style_tags") or [])),
        str(data.get("fabric") or ""),
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())[:1024]


def _ensure_products(db: Session) -> dict[str, Product]:
    existing = {product.sku: product for product in db.scalars(select(Product)).all()}
    for data in PRODUCTS:
        sku = data["sku"]
        if sku in existing:
            continue
        # All catalog keys map 1:1 to Product columns; search_text is derived.
        product = Product(**data, search_text=build_search_text(data))
        db.add(product)
        db.flush()
        existing[sku] = product
    return existing


def _ensure_demo_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.username == DEMO_USER["username"]))
    if user is None:
        user = User(
            username=DEMO_USER["username"],
            password_hash=hash_password(DEMO_USER["password"]),
            nickname=DEMO_USER["nickname"],
        )
        db.add(user)
        db.flush()
    return user


def _pick_size(product: Product) -> str:
    sizes = list(product.sizes or [])
    if "M" in sizes:
        return "M"
    return sizes[0] if sizes else ""


def _pick_color(product: Product) -> str:
    colors = list(product.colors or [])
    return colors[0] if colors else ""


def _ensure_demo_order(db: Session, user: User, products: dict[str, Product]) -> None:
    exists = db.scalar(select(Order.id).where(Order.order_no == DEMO_ORDER_NO))
    if exists is not None:
        return

    items: list[OrderItem] = []
    total = 0.0
    for sku in DEMO_ORDER_SKUS:
        product = products.get(sku)
        if product is None:  # pragma: no cover - catalog is canonical
            logger.warning("演示订单跳过不存在的 SKU: %s", sku)
            continue
        items.append(
            OrderItem(
                product_id=product.id,
                name=product.name,
                image=product.image,
                price=float(product.price),
                quantity=1,
                size=_pick_size(product),
                color=_pick_color(product),
            )
        )
        total += float(product.price)

    if not items:  # pragma: no cover - catalog is canonical
        return

    db.add(
        Order(
            order_no=DEMO_ORDER_NO,
            user_id=user.id,
            status="paid",
            source="platform",
            total=round(total, 2),
            shipping_name=DEMO_ORDER_SHIPPING["name"],
            shipping_phone=DEMO_ORDER_SHIPPING["phone"],
            shipping_address=DEMO_ORDER_SHIPPING["address"],
            note=DEMO_ORDER_NOTE,
            created_at=DEMO_ORDER_CREATED_AT,
            items=items,
        )
    )
    db.flush()


def seed_if_empty(db: Session) -> None:
    """Create catalog products, the demo user and a historical paid order if missing."""
    try:
        products = _ensure_products(db)
        user = _ensure_demo_user(db)
        _ensure_demo_order(db, user, products)
        db.commit()
    except Exception:  # pragma: no cover - surfaced to caller/logs
        db.rollback()
        logger.exception("种子数据写入失败")
        raise
