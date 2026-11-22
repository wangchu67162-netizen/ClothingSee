"""Shopping cart: per-user variant-aware cart with merge-on-add semantics."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import CartItem, Product, User
from ..schemas import CartAddRequest, CartItemOut, CartOut, CartUpdateRequest, ProductOut

router = APIRouter(prefix="/cart", tags=["购物车"])

MAX_QUANTITY = 20


def _get_product_or_404(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    return product


def _normalize_variant(product: Product, size: str, color: str) -> tuple[str, str]:
    size = (size or "").strip()[:16]
    color = (color or "").strip()[:32]
    if size and product.sizes and size not in product.sizes:
        raise HTTPException(status_code=400, detail="所选尺码不存在，请重新选择")
    if color and product.colors and color not in product.colors:
        raise HTTPException(status_code=400, detail="所选颜色不存在，请重新选择")
    return size, color


def _cart_out(db: Session, user_id: int) -> CartOut:
    items = db.scalars(
        select(CartItem)
        .where(CartItem.user_id == user_id)
        .order_by(CartItem.created_at.asc(), CartItem.id.asc())
    ).unique().all()
    return CartOut.from_items(
        [
            CartItemOut(
                id=item.id,
                product=ProductOut.model_validate(item.product),
                quantity=item.quantity,
                size=item.size,
                color=item.color,
            )
            for item in items
        ]
    )


def _get_cart_item_or_404(db: Session, user_id: int, item_id: int) -> CartItem:
    item = db.scalar(
        select(CartItem).where(CartItem.id == item_id, CartItem.user_id == user_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="购物车商品不存在")
    return item


@router.get("", response_model=CartOut)
def get_cart(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CartOut:
    return _cart_out(db, current_user.id)


@router.post("", response_model=CartOut)
def add_to_cart(
    payload: CartAddRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CartOut:
    product = _get_product_or_404(db, payload.product_id)
    size, color = _normalize_variant(product, payload.size, payload.color)

    existing = db.scalar(
        select(CartItem).where(
            CartItem.user_id == current_user.id,
            CartItem.product_id == product.id,
            CartItem.size == size,
            CartItem.color == color,
        )
    )
    quantity = payload.quantity + (existing.quantity if existing is not None else 0)

    if product.stock <= 0:
        raise HTTPException(status_code=400, detail=f"「{product.name}」暂时缺货")
    if quantity > MAX_QUANTITY:
        raise HTTPException(status_code=400, detail=f"同一商品最多购买 {MAX_QUANTITY} 件")
    if quantity > product.stock:
        raise HTTPException(
            status_code=400,
            detail=f"库存不足，「{product.name}」仅剩 {product.stock} 件",
        )

    if existing is None:
        db.add(
            CartItem(
                user_id=current_user.id,
                product_id=product.id,
                quantity=payload.quantity,
                size=size,
                color=color,
            )
        )
    else:
        existing.quantity = quantity
    db.commit()
    return _cart_out(db, current_user.id)


@router.patch("/{item_id}", response_model=CartOut)
def update_cart_item(
    item_id: int,
    payload: CartUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CartOut:
    item = _get_cart_item_or_404(db, current_user.id, item_id)
    if payload.quantity == 0:
        db.delete(item)
        db.commit()
        return _cart_out(db, current_user.id)

    product = item.product
    if product is not None and payload.quantity > product.stock:
        raise HTTPException(
            status_code=400,
            detail=f"库存不足，「{product.name}」仅剩 {product.stock} 件",
        )
    item.quantity = payload.quantity
    db.commit()
    return _cart_out(db, current_user.id)


@router.delete("/{item_id}", response_model=CartOut)
def delete_cart_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CartOut:
    item = _get_cart_item_or_404(db, current_user.id, item_id)
    db.delete(item)
    db.commit()
    return _cart_out(db, current_user.id)


@router.delete("", response_model=CartOut)
def clear_cart(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CartOut:
    db.execute(delete(CartItem).where(CartItem.user_id == current_user.id))
    db.commit()
    return CartOut.from_items([])
