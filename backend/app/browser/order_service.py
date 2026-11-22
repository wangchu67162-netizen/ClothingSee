"""Create a platform order from the demo mall checkout.

This helper is shared by two callers so both real and mock browser engines
write exactly the same records:

* ``routers/demo_mall.py`` — the public checkout API used by the real browser
* ``browser/mock_driver.py`` — the deterministic test engine

Design notes
------------
* The browser never sends a price; the server recomputes it from the product
  row (``price * quantity``).
* ``external_ref`` stores the order number and is unique, so a repeated submit
  of the same ``BrowseTask`` token is idempotent: the original order is
  returned instead of creating a duplicate.
* A valid :class:`BrowseTask` whose session belongs to a logged-in user is
  required, which is why an anonymous visitor cannot "place an agent order".
"""
from __future__ import annotations

import logging
import random
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import AgentSession, BrowseTask, Order, OrderItem, Product

logger = logging.getLogger("yijian.mall")

MAX_QUANTITY = 10


class MallOrderError(Exception):
    """Domain error carrying an HTTP-ish status and a Chinese user message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def generate_order_no() -> str:
    """``YJ{YYYYMMDDHHMMSS}{4 random digits}`` (contract format)."""
    return "YJ{}".format(datetime.now().strftime("%Y%m%d%H%M%S")) + f"{random.randint(0, 9999):04d}"


def _unique_order_no(db: Session) -> str:
    for _ in range(10):
        candidate = generate_order_no()
        exists = db.query(Order.id).filter(Order.order_no == candidate).first()
        if not exists:
            return candidate
    raise MallOrderError("订单号生成失败，请稍后重试", 500)


def _validate_customer(customer: dict[str, str]) -> dict[str, str]:
    data = {key: str((customer or {}).get(key, "")).strip() for key in ("name", "phone", "address")}
    if not data["name"]:
        raise MallOrderError("请填写收货人姓名")
    if len(data["name"]) > 32:
        raise MallOrderError("收货人姓名过长")
    if len(data["phone"]) < 5 or len(data["phone"]) > 24:
        raise MallOrderError("请填写有效的手机号")
    if len(data["address"]) < 3 or len(data["address"]) > 256:
        raise MallOrderError("请填写完整的收货地址")
    return data


def _existing_order(db: Session, order_no: str | None) -> Order | None:
    if not order_no:
        return None
    return db.query(Order).filter(Order.external_ref == order_no).one_or_none()


def create_agent_order(
    db: Session,
    *,
    task: BrowseTask | None,
    product: Product | None,
    size: str,
    color: str,
    quantity: int,
    customer: dict[str, str],
) -> tuple[Order, bool]:
    """Create (or idempotently return) the platform order for a browse task.

    Returns ``(order, created)`` where ``created`` is False when an earlier
    submit already produced this order.
    """

    if task is None:
        raise MallOrderError("任务令牌无效或已过期，请重新发起下单", 404)
    if task.status == "failed":
        raise MallOrderError("该浏览任务已失败，无法重复下单", 409)

    # A completed task replays its original order (token-based idempotency).
    if task.order_no:
        existing = _existing_order(db, task.order_no)
        if existing is not None:
            return existing, False
        # Order row missing (e.g. database reset): fall through and recreate it
        # with the same task token; external_ref uniqueness still protects us.

    session = db.get(AgentSession, task.session_id)
    if session is None:
        raise MallOrderError("任务对应的会话不存在，请重新发起下单", 404)
    if session.user_id is None:
        raise MallOrderError("请先登录后再由购物助理下单", 403)

    if product is None:
        raise MallOrderError("商品不存在或已下架", 404)
    if product.stock <= 0:
        raise MallOrderError("该商品已售罄", 409)

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise MallOrderError("购买数量无效") from None
    if quantity < 1 or quantity > MAX_QUANTITY:
        raise MallOrderError(f"购买数量需在 1–{MAX_QUANTITY} 件之间")

    sizes = [str(item) for item in (product.sizes or [])]
    colors = [str(item) for item in (product.colors or [])]
    size = (size or "").strip()
    color = (color or "").strip()
    if sizes:
        if not size:
            size = sizes[0]
        elif size not in sizes:
            raise MallOrderError(f"尺码「{size}」不可用，请选择：{'、'.join(sizes)}")
    if colors:
        if not color:
            color = colors[0]
        elif color not in colors:
            raise MallOrderError(f"颜色「{color}」不可用，请选择：{'、'.join(colors)}")

    if quantity > product.stock:
        raise MallOrderError(f"库存不足，仅剩 {product.stock} 件", 409)

    shipping = _validate_customer(customer)

    order_no = _unique_order_no(db)
    total = round(float(product.price) * quantity, 2)

    order = Order(
        order_no=order_no,
        user_id=session.user_id,
        status="paid",  # demo mall payment is simulated and always succeeds
        source="agent",
        total=total,
        shipping_name=shipping["name"],
        shipping_phone=shipping["phone"],
        shipping_address=shipping["address"],
        note="云裳商城 · 购物助理浏览器下单（模拟支付）",
        external_ref=order_no,
        agent_session_id=session.id,
    )
    order.items.append(
        OrderItem(
            product_id=product.id,
            name=product.name,
            image=product.image or "",
            price=float(product.price),
            quantity=quantity,
            size=size,
            color=color,
        )
    )

    product.stock = max(0, int(product.stock or 0) - quantity)
    product.sales = int(product.sales or 0) + quantity
    task.status = "done"
    task.order_no = order_no
    task.error = None

    db.add(order)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent duplicate submit: the other transaction won the race.
        db.rollback()
        fresh = db.get(BrowseTask, task.id)
        existing = _existing_order(db, fresh.order_no if fresh else None)
        if existing is not None:
            return existing, False
        raise MallOrderError("订单提交冲突，请重试", 409) from None

    db.refresh(order)
    return order, True
