"""Database models. These are a shared contract: coordinate before changing fields."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    nickname: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    subtitle: Mapped[str] = mapped_column(String(256), default="")
    category: Mapped[str] = mapped_column(String(32), index=True)
    price: Mapped[float] = mapped_column(Float)
    original_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    fabric: Mapped[str] = mapped_column(String(128), default="")
    fit: Mapped[str] = mapped_column(String(64), default="")
    style_tags: Mapped[list] = mapped_column(JSON, default=list)
    colors: Mapped[list] = mapped_column(JSON, default=list)
    sizes: Mapped[list] = mapped_column(JSON, default=list)
    image: Mapped[str] = mapped_column(String(512), default="")
    gallery: Mapped[list] = mapped_column(JSON, default=list)
    stock: Mapped[int] = mapped_column(Integer, default=100)
    rating: Mapped[float] = mapped_column(Float, default=4.8)
    sales: Mapped[int] = mapped_column(Integer, default=0)
    search_text: Mapped[str] = mapped_column(String(1024), default="")
    occasion: Mapped[str] = mapped_column(String(128), default="")
    season: Mapped[str] = mapped_column(String(64), default="")
    comfort: Mapped[dict] = mapped_column(JSON, default=dict)
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Embedding(Base):
    __tablename__ = "embeddings"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    vector: Mapped[list] = mapped_column(JSON)
    dim: Mapped[int] = mapped_column(Integer, default=0)
    model_version: Mapped[str] = mapped_column(String(64), default="stub-v0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("user_id", "product_id", "size", "color", name="uq_cart_variant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    size: Mapped[str] = mapped_column(String(16), default="")
    color: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product] = relationship(lazy="joined")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="paid")
    source: Mapped[str] = mapped_column(String(20), default="platform")  # platform | agent
    total: Mapped[float] = mapped_column(Float, default=0)
    shipping_name: Mapped[str] = mapped_column(String(64), default="")
    shipping_phone: Mapped[str] = mapped_column(String(32), default="")
    shipping_address: Mapped[str] = mapped_column(String(512), default="")
    note: Mapped[str] = mapped_column(String(512), default="")
    external_ref: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    agent_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128))
    image: Mapped[str] = mapped_column(String(512), default="")
    price: Mapped[float] = mapped_column(Float, default=0)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    size: Mapped[str] = mapped_column(String(16), default="")
    color: Mapped[str] = mapped_column(String(32), default="")

    order: Mapped[Order] = relationship(back_populates="items")


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid4().hex)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="stylist")  # stylist | assistant
    input_image: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | failed
    mode: Mapped[str] = mapped_column(String(20), default="mock")
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    agent: Mapped[str] = mapped_column(String(32), default="moderator")
    round: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String(32), default="opinion")  # opinion | critique | summary | tool
    message_type: Mapped[str] = mapped_column(String(32), default="opinion")
    recipients: Mapped[list] = mapped_column(JSON, default=list)
    content: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scores: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BrowseTask(Base):
    __tablename__ = "browse_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    task_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    steps: Mapped[list] = mapped_column(JSON, default=list)
    order_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
