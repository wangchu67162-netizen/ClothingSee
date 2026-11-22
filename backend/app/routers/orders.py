"""Orders: checkout from the cart (server-side pricing), listing, detail and cancel."""
from __future__ import annotations

import logging
import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import CartItem, Order, OrderItem, User
from ..schemas import OrderCreateRequest, OrderOut

router = APIRouter(prefix="/orders", tags=["订单"])
logger = logging.getLogger("yijian.orders")


def _generate_order_no(db: Session) -> str:
    """YJ + yyyyMMddHHmmss + 4 random digits, retried on the (rare) collision."""
    for _ in range(10):
        candidate = f"YJ{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(0, 9999):04d}"
        exists = db.scalar(select(Order.id).where(Order.order_no == candidate))
        if exists is None:
            return candidate
    raise HTTPException(status_code=500, detail="订单号生成失败，请稍后重试")


def _get_user_order_or_404(db: Session, user_id: int, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if order is None or order.user_id != user_id:
        raise HTTPException(status_code=404, detail="订单不存在")
    return order


@router.post("", response_model=OrderOut)
def create_order(
    payload: OrderCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrderOut:
    statement = select(CartItem).where(CartItem.user_id == current_user.id)
    requested_ids: set[int] | None = None
    if payload.item_ids is not None:
        requested_ids = {int(item_id) for item_id in payload.item_ids}
        if not requested_ids:
            raise HTTPException(status_code=400, detail="请选择要结算的商品")
        statement = statement.where(CartItem.id.in_(requested_ids))

    cart_items = db.scalars(statement.order_by(CartItem.id.asc())).unique().all()
    if not cart_items:
        if requested_ids is None:
            raise HTTPException(status_code=400, detail="购物车是空的，请先添加商品")
        raise HTTPException(status_code=400, detail="所选商品不在购物车中，请刷新后重试")
    if requested_ids is not None and len(cart_items) != len(requested_ids):
        raise HTTPException(status_code=400, detail="部分结算商品不存在，请刷新购物车后重试")

    order_items: list[OrderItem] = []
    total = 0.0
    for cart_item in cart_items:
        product = cart_item.product
        if product is None:
            raise HTTPException(status_code=400, detail="购物车中的商品已下架，请刷新后重试")
        if cart_item.quantity > product.stock:
            raise HTTPException(
                status_code=400,
                detail=f"库存不足，「{product.name}」仅剩 {product.stock} 件",
            )
        # Prices always come from the database, never from the client.
        price = float(product.price)
        total += price * cart_item.quantity
        order_items.append(
            OrderItem(
                product_id=product.id,
                name=product.name,
                image=product.image,
                price=price,
                quantity=cart_item.quantity,
                size=cart_item.size,
                color=cart_item.color,
            )
        )

    order = Order(
        order_no=_generate_order_no(db),
        user_id=current_user.id,
        status="paid",  # simulated payment: demo project, never charged for real
        source="platform",
        total=round(total, 2),
        shipping_name=payload.shipping.name.strip(),
        shipping_phone=payload.shipping.phone.strip(),
        shipping_address=payload.shipping.address.strip(),
        note=payload.note.strip(),
        items=order_items,
    )
    db.add(order)
    for cart_item in cart_items:
        db.delete(cart_item)
    db.commit()
    logger.info("订单创建成功: %s 用户=%s 金额=%.2f", order.order_no, current_user.username, order.total)
    return OrderOut.model_validate(order)


@router.get("", response_model=list[OrderOut])
def list_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[OrderOut]:
    orders = db.scalars(
        select(Order)
        .where(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    ).unique().all()
    return [OrderOut.model_validate(order) for order in orders]


@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrderOut:
    order = _get_user_order_or_404(db, current_user.id, order_id)
    return OrderOut.model_validate(order)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrderOut:
    order = _get_user_order_or_404(db, current_user.id, order_id)
    if order.status == "cancelled":
        raise HTTPException(status_code=400, detail="订单已取消，无需重复操作")
    if order.status != "paid":
        raise HTTPException(status_code=400, detail="当前订单状态不支持取消")
    order.status = "cancelled"
    db.commit()
    return OrderOut.model_validate(order)
