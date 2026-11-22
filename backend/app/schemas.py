"""Pydantic schemas shared by routers, services and the frontend contract."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


# ---------------------------------------------------------------- auth
class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str = ""
    created_at: datetime | None = None


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=6, max_length=64)
    nickname: str = Field(default="", max_length=32)


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=6, max_length=64)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


# ---------------------------------------------------------------- catalog
class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    subtitle: str = ""
    category: str
    price: float
    original_price: float | None = None
    description: str = ""
    fabric: str = ""
    fit: str = ""
    style_tags: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    sizes: list[str] = Field(default_factory=list)
    image: str = ""
    gallery: list[str] = Field(default_factory=list)
    stock: int = 0
    rating: float = 0
    sales: int = 0
    occasion: str = ""
    season: str = ""
    comfort: dict[str, Any] = Field(default_factory=dict)
    featured: bool = False
    similarity: float | None = None


class ProductListOut(BaseModel):
    items: list[ProductOut]
    total: int
    page: int = 1
    page_size: int = 12
    pages: int = 1


class CategoryOut(BaseModel):
    name: str
    count: int


class ImageSearchOut(BaseModel):
    items: list[ProductOut]
    distance_metric: str = "chebyshev"
    backend: str = "stub"
    vision: dict[str, Any] | None = None


# ---------------------------------------------------------------- cart / orders
class CartAddRequest(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=20)
    size: str = ""
    color: str = ""


class CartUpdateRequest(BaseModel):
    quantity: int = Field(ge=0, le=20)


class CartItemOut(BaseModel):
    id: int
    product: ProductOut
    quantity: int
    size: str = ""
    color: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def line_total(self) -> float:
        return round(self.product.price * self.quantity, 2)


class CartOut(BaseModel):
    items: list[CartItemOut] = Field(default_factory=list)
    total_quantity: int = 0
    total_amount: float = 0

    @classmethod
    def from_items(cls, items: list[CartItemOut]) -> "CartOut":
        return cls(
            items=items,
            total_quantity=sum(item.quantity for item in items),
            total_amount=round(sum(item.line_total for item in items), 2),
        )


class ShippingInfo(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    phone: str = Field(min_length=5, max_length=24)
    address: str = Field(min_length=3, max_length=256)


class OrderCreateRequest(BaseModel):
    shipping: ShippingInfo
    note: str = Field(default="", max_length=256)
    item_ids: list[int] | None = None  # None = checkout the whole cart


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int | None = None
    name: str
    image: str = ""
    price: float
    quantity: int
    size: str = ""
    color: str = ""


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    status: str
    source: str
    total: float
    shipping_name: str = ""
    shipping_phone: str = ""
    shipping_address: str = ""
    note: str = ""
    external_ref: str | None = None
    agent_session_id: str | None = None
    created_at: datetime
    items: list[OrderItemOut] = Field(default_factory=list)


# ---------------------------------------------------------------- small models
class VisionEmbedResponse(BaseModel):
    embedding: list[float]
    dim: int
    model_version: str
    backend: str


class SimilarMatch(BaseModel):
    product: ProductOut
    distance: float
    similarity: float


class VisionSimilarResponse(BaseModel):
    query_embedding: list[float]
    matches: list[SimilarMatch]
    backend: str
    model_version: str
    elapsed_ms: int = 0


class ChebyshevRequest(BaseModel):
    a: list[float]
    b: list[float]


class ChebyshevResponse(BaseModel):
    distance: float
    similarity: float
    formula: str = "chebyshev: max_i |a_i - b_i|"


class KGQueryRequest(BaseModel):
    text: str = Field(min_length=1, max_length=512)
    top_k: int = Field(default=6, ge=1, le=20)


class KGQueryResponse(BaseModel):
    triples: list[dict[str, Any]] = Field(default_factory=list)
    products: list[ProductOut] = Field(default_factory=list)
    related_terms: list[str] = Field(default_factory=list)


class KGNode(BaseModel):
    id: str
    label: str
    type: str
    meta: dict[str, Any] = Field(default_factory=dict)


class KGEdge(BaseModel):
    source: str
    target: str
    relation: str
    weight: float = 0.0
    meta: dict[str, Any] = Field(default_factory=dict)


class KGGraphOut(BaseModel):
    nodes: list[KGNode] = Field(default_factory=list)
    edges: list[KGEdge] = Field(default_factory=list)
    metric: str = "chebyshev"
    meta: dict[str, Any] = Field(default_factory=dict)


class SmallModelsStatus(BaseModel):
    mode: str
    vision: dict[str, Any]
    nlp_kg: dict[str, Any]


# ---------------------------------------------------------------- agents
AgentName = Literal["fashion", "art", "aesthetics", "price", "comfort"]


class VisionAnalysis(BaseModel):
    category: str = ""
    colors: list[str] = Field(default_factory=list)
    style: list[str] = Field(default_factory=list)
    material: list[str] = Field(default_factory=list)
    occasion: str = ""
    body_hints: str = ""
    summary: str = ""
    confidence: float = 0.7


class AgentScore(BaseModel):
    product_id: int
    score: float = Field(ge=0, le=10)
    reason: str = ""


class AgentOpinion(BaseModel):
    agent: str
    round: int
    scores: list[AgentScore] = Field(default_factory=list)
    advice: str = ""
    message_to_peers: str = ""


class RecommendationProduct(BaseModel):
    product: ProductOut
    score: float
    reasons: list[str] = Field(default_factory=list)
    agent_scores: dict[str, float] = Field(default_factory=dict)


class RecommendationFinal(BaseModel):
    session_id: str
    mode: str = "mock"
    vision: VisionAnalysis
    candidates: list[ProductOut] = Field(default_factory=list)
    recommendations: list[RecommendationProduct] = Field(default_factory=list)
    outfit: list[ProductOut] = Field(default_factory=list)
    outfit_total: float = 0
    advice: str = ""
    kg: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: int = 0


class AgentSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    status: str
    mode: str = "mock"
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime | None = None


class AgentMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    seq: int = 0
    agent: str
    agent_name: str = ""
    round: int = 0
    role: str = "opinion"
    message_type: str = "opinion"
    recipients: list[str] = Field(default_factory=list)
    content: str = ""
    scores: list[dict[str, Any]] = Field(default_factory=list)
    payload: dict[str, Any] | None = None
    created_at: datetime


# ---------------------------------------------------------------- assistant
class AssistantChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=512)
    session_id: str | None = None


class AssistantIntent(BaseModel):
    intent: Literal["recommend", "order", "chat", "unknown"] = "unknown"
    query: str = ""
    size: str = ""
    color: str = ""
    confidence: float = 0.0


class BrowseStep(BaseModel):
    index: int
    action: str
    status: Literal["running", "done", "failed"] = "done"
    screenshot: str | None = None
    detail: str = ""


class AssistantProductCard(BaseModel):
    product: ProductOut
    platform_url: str
    mall_url: str = ""


class MetaOut(BaseModel):
    app_name: str
    version: str
    mode: Literal["qwen", "mock"]
    llm_mode: str
    small_model_mode: str
    demo_username: str = "demo"
    demo_password: str = "demo123"
    features: dict[str, bool] = Field(default_factory=dict)
