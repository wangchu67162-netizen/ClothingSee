"""T2 commerce tests: catalog search, cart semantics and order checkout.

Each test runs against an isolated temporary SQLite database seeded through
``seed_if_empty``; no network, no API key and no T3 small-model code required.
"""
from __future__ import annotations

import base64
import re
import sys
import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Embedding, Order, OrderItem, Product, User
from app.security import create_access_token, hash_password, verify_password
from app.seed import DEMO_ORDER_NO, seed_if_empty

# 1x1 transparent PNG: only used as request bytes (the vision model is faked here).
PNG_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

SHIPPING = {
    "name": "测试收货人",
    "phone": "13800000000",
    "address": "上海市测试路 1 号",
}


# ------------------------------------------------------------------ fixtures
@pytest.fixture()
def db_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 't2-test.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    with factory() as db:
        seed_if_empty(db)
    yield factory
    engine.dispose()


@pytest.fixture()
def client(db_factory):
    def override_get_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def demo_headers(db_factory):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.username == "demo"))
        assert user is not None
        token = create_access_token(user.id, user.username)
    return {"Authorization": f"Bearer {token}"}


def product_id_by_sku(db_factory, sku: str) -> int:
    with db_factory() as db:
        product = db.scalar(select(Product).where(Product.sku == sku))
        assert product is not None, sku
        return int(product.id)


def add_item(client, headers, product_id: int, quantity: int = 1, size: str = "M", color: str = ""):
    response = client.post(
        "/api/cart",
        json={"product_id": product_id, "quantity": quantity, "size": size, "color": color},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ seed
def test_seed_populates_catalog_demo_user_and_history(db_factory):
    with db_factory() as db:
        products = db.scalars(select(Product)).all()
        assert len(products) == 16
        assert {product.category for product in products} == {
            "外套",
            "上装",
            "连衣裙",
            "下装",
            "配饰",
        }

        trench = next(product for product in products if product.sku == "ys-ow-001")
        assert trench.search_text
        for token in ("暮色长风衣", "精纺羊毛", "通勤"):
            assert token in trench.search_text
        assert len(trench.gallery) == 3
        assert trench.comfort["warmth"] == 8
        assert trench.featured is True

        demo = db.scalar(select(User).where(User.username == "demo"))
        assert demo is not None
        assert demo.nickname == "云裳体验官"
        assert verify_password("demo123", demo.password_hash)

        order = db.scalar(select(Order).where(Order.order_no == DEMO_ORDER_NO))
        assert order is not None
        assert order.user_id == demo.id
        assert order.status == "paid"
        assert order.source == "platform"
        assert order.total == pytest.approx(699.0 + 599.0)
        assert {item.name for item in order.items} == {"云缎真丝衬衫", "流云阔腿裤"}

    # Second call must not duplicate anything.
    with db_factory() as db:
        before = (
            db.scalar(select(func.count(Product.id))),
            db.scalar(select(func.count(User.id))),
            db.scalar(select(func.count(Order.id))),
            db.scalar(select(func.count(OrderItem.id))),
        )
        seed_if_empty(db)
        after = (
            db.scalar(select(func.count(Product.id))),
            db.scalar(select(func.count(User.id))),
            db.scalar(select(func.count(Order.id))),
            db.scalar(select(func.count(OrderItem.id))),
        )
        assert before == after == (16, 1, 1, 2)


# ------------------------------------------------------------------ catalog
def test_product_listing_pagination_and_fields(client):
    response = client.get("/api/products")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 16
    assert (data["page"], data["page_size"], data["pages"]) == (1, 12, 2)
    assert len(data["items"]) == 12
    first = data["items"][0]
    for field in (
        "id",
        "sku",
        "name",
        "subtitle",
        "category",
        "price",
        "original_price",
        "description",
        "fabric",
        "fit",
        "style_tags",
        "colors",
        "sizes",
        "image",
        "gallery",
        "stock",
        "rating",
        "sales",
        "occasion",
        "season",
        "comfort",
        "featured",
    ):
        assert field in first

    page_two = client.get("/api/products", params={"page": 2, "page_size": 12}).json()
    assert len(page_two["items"]) == 4
    assert page_two["total"] == 16

    page_five = client.get("/api/products", params={"page": 2, "page_size": 5}).json()
    assert len(page_five["items"]) == 5
    assert page_five["pages"] == 4


def test_product_keyword_and_category_search(client):
    silk = client.get("/api/products", params={"q": "真丝"}).json()
    assert silk["total"] == 4
    for item in silk["items"]:
        haystack = (
            item["name"]
            + item["subtitle"]
            + item["description"]
            + "".join(item["style_tags"])
        )
        assert "真丝" in haystack

    silk_accessory = client.get(
        "/api/products", params={"q": "真丝", "category": "配饰"}
    ).json()
    assert silk_accessory["total"] == 2
    assert {item["sku"] for item in silk_accessory["items"]} == {
        "ys-ac-001",
        "ys-ac-002",
    }

    windbreaker = client.get("/api/products", params={"q": "风衣"}).json()
    assert windbreaker["total"] == 1
    assert windbreaker["items"][0]["sku"] == "ys-ow-001"

    nothing = client.get("/api/products", params={"q": "不存在的关键词"}).json()
    assert nothing["total"] == 0

    # LIKE wildcards must be escaped rather than matching everything.
    wildcard = client.get("/api/products", params={"q": "_"}).json()
    assert wildcard["total"] == 0


def test_product_sorting_and_featured(client):
    price_asc = client.get("/api/products", params={"sort": "price_asc"}).json()
    assert price_asc["items"][0]["sku"] == "ys-ac-002"
    prices = [item["price"] for item in price_asc["items"]]
    assert prices == sorted(prices)

    price_desc = client.get("/api/products", params={"sort": "price_desc"}).json()
    assert price_desc["items"][0]["sku"] == "ys-ow-003"

    sales = client.get("/api/products", params={"sort": "sales"}).json()
    assert sales["items"][0]["sku"] == "ys-bt-002"

    featured = client.get("/api/products", params={"featured": "true"}).json()
    assert featured["total"] == 5
    assert all(item["featured"] is True for item in featured["items"])

    bad_sort = client.get("/api/products", params={"sort": "unknown"})
    assert bad_sort.status_code == 400
    assert "排序" in bad_sort.json()["detail"]


def test_categories_registered_before_product_detail(client):
    response = client.get("/api/products/categories")
    assert response.status_code == 200
    data = response.json()
    assert [item["name"] for item in data] == ["外套", "上装", "连衣裙", "下装", "配饰"]
    assert [item["count"] for item in data] == [3, 4, 3, 3, 3]
    assert sum(item["count"] for item in data) == 16


def test_product_detail_and_404(client, db_factory):
    product_id = product_id_by_sku(db_factory, "ys-dr-003")
    response = client.get(f"/api/products/{product_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "青瓷新中式裙"
    assert data["featured"] is True

    missing = client.get("/api/products/999999")
    assert missing.status_code == 404
    assert "商品不存在" in missing.json()["detail"]


# ------------------------------------------------------------------ image search
def test_image_search_without_model_returns_chinese_503(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "app.small_models.factory", None)
    response = client.post(
        "/api/products/search-by-image",
        files={"file": ("query.png", PNG_PIXEL, "image/png")},
    )
    assert response.status_code == 503
    assert "图片" in response.json()["detail"]


def test_image_search_ranks_embeddings_with_chebyshev(client, db_factory, monkeypatch):
    sku_vectors = {
        "ys-tp-001": [0.5] * 8,
        "ys-dr-001": [0.55] * 8,
        "ys-bt-001": [0.95] * 8,
    }
    with db_factory() as db:
        for sku, vector in sku_vectors.items():
            product = db.scalar(select(Product).where(Product.sku == sku))
            assert product is not None
            db.merge(
                Embedding(
                    product_id=product.id,
                    vector=vector,
                    dim=8,
                    model_version="test-vision",
                )
            )
        db.commit()

    class FakeVision:
        name = "test-vision"
        version = "0.1"
        dim = 8

        def info(self):
            return {"name": self.name, "dim": self.dim}

        async def embed(self, image: bytes):
            return [0.5] * 8

    fake_factory = types.ModuleType("app.small_models.factory")
    fake_factory.get_vision_model = lambda: FakeVision()
    monkeypatch.setitem(sys.modules, "app.small_models.factory", fake_factory)

    response = client.post(
        "/api/products/search-by-image",
        data={"top_k": "2"},
        files={"file": ("query.png", PNG_PIXEL, "image/png")},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["distance_metric"] == "chebyshev"
    assert data["backend"] == "test-vision"
    assert [item["sku"] for item in data["items"]] == ["ys-tp-001", "ys-dr-001"]
    assert data["items"][0]["similarity"] >= data["items"][1]["similarity"]
    assert data["items"][0]["similarity"] == pytest.approx(1.0)


# ------------------------------------------------------------------ cart
def test_cart_requires_login(client):
    response = client.get("/api/cart")
    assert response.status_code == 401
    assert "登录" in response.json()["detail"]


def test_cart_add_merge_update_delete(client, db_factory, demo_headers):
    product_id = product_id_by_sku(db_factory, "ys-tp-001")

    cart = add_item(client, demo_headers, product_id, quantity=1, size="M", color="月白")
    assert cart["total_quantity"] == 1
    assert cart["total_amount"] == pytest.approx(699.0)
    item = cart["items"][0]
    assert item["product"]["id"] == product_id
    assert item["line_total"] == pytest.approx(699.0)
    assert (item["size"], item["color"]) == ("M", "月白")

    merged = add_item(client, demo_headers, product_id, quantity=2, size="M", color="月白")
    assert len(merged["items"]) == 1
    assert merged["items"][0]["quantity"] == 3
    assert merged["total_quantity"] == 3
    assert merged["total_amount"] == pytest.approx(699.0 * 3)

    other_variant = add_item(client, demo_headers, product_id, quantity=1, size="L", color="月白")
    assert len(other_variant["items"]) == 2
    assert other_variant["total_quantity"] == 4

    first_item_id = merged["items"][0]["id"]
    second_item_id = next(
        item["id"] for item in other_variant["items"] if item["id"] != first_item_id
    )

    updated = client.patch(
        f"/api/cart/{first_item_id}", json={"quantity": 2}, headers=demo_headers
    )
    assert updated.status_code == 200
    assert updated.json()["total_quantity"] == 3
    assert updated.json()["total_amount"] == pytest.approx(699.0 * 3)

    removed = client.patch(
        f"/api/cart/{first_item_id}", json={"quantity": 0}, headers=demo_headers
    )
    assert removed.status_code == 200
    assert [item["id"] for item in removed.json()["items"]] == [second_item_id]

    deleted = client.delete(f"/api/cart/{second_item_id}", headers=demo_headers)
    assert deleted.status_code == 200
    assert deleted.json() == {"items": [], "total_quantity": 0, "total_amount": 0}

    add_item(client, demo_headers, product_id, quantity=1, size="M", color="月白")
    cleared = client.delete("/api/cart", headers=demo_headers)
    assert cleared.status_code == 200
    assert cleared.json()["items"] == []


def test_cart_validation_errors(client, db_factory, demo_headers):
    missing = client.post(
        "/api/cart",
        json={"product_id": 999999, "quantity": 1, "size": "", "color": ""},
        headers=demo_headers,
    )
    assert missing.status_code == 404
    assert "商品不存在" in missing.json()["detail"]

    product_id = product_id_by_sku(db_factory, "ys-dr-003")
    bad_size = client.post(
        "/api/cart",
        json={"product_id": product_id, "quantity": 1, "size": "XXXL", "color": "青瓷"},
        headers=demo_headers,
    )
    assert bad_size.status_code == 400
    assert "尺码" in bad_size.json()["detail"]

    # ys-ow-003 stock is 12; CartAddRequest allows up to 20.
    scarce_id = product_id_by_sku(db_factory, "ys-ow-003")
    stock_error = client.post(
        "/api/cart",
        json={"product_id": scarce_id, "quantity": 20, "size": "M", "color": "山岚灰"},
        headers=demo_headers,
    )
    assert stock_error.status_code == 400
    assert "库存" in stock_error.json()["detail"]


# ------------------------------------------------------------------ orders
def test_orders_require_login(client):
    assert client.get("/api/orders").status_code == 401
    assert (
        client.post("/api/orders", json={"shipping": SHIPPING, "note": ""}).status_code
        == 401
    )


def test_checkout_recomputes_total_and_clears_cart(client, db_factory, demo_headers):
    shirt_id = product_id_by_sku(db_factory, "ys-tp-001")  # 699
    pants_id = product_id_by_sku(db_factory, "ys-bt-001")  # 599
    add_item(client, demo_headers, shirt_id, quantity=2, size="M", color="月白")
    add_item(client, demo_headers, pants_id, quantity=1, size="M", color="流云灰")

    response = client.post(
        "/api/orders",
        json={"shipping": SHIPPING, "note": "请尽快发货"},
        headers=demo_headers,
    )
    assert response.status_code == 200, response.text
    order = response.json()
    assert re.fullmatch(r"YJ\d{18}", order["order_no"])
    assert order["status"] == "paid"
    assert order["source"] == "platform"
    assert order["total"] == pytest.approx(699.0 * 2 + 599.0)
    assert order["shipping_name"] == SHIPPING["name"]
    assert order["note"] == "请尽快发货"
    assert len(order["items"]) == 2
    assert {item["name"] for item in order["items"]} == {"云缎真丝衬衫", "流云阔腿裤"}
    assert {item["quantity"] for item in order["items"]} == {1, 2}

    cart = client.get("/api/cart", headers=demo_headers).json()
    assert cart["items"] == []
    assert cart["total_quantity"] == 0
    assert cart["total_amount"] == 0

    detail = client.get(f"/api/orders/{order['id']}", headers=demo_headers)
    assert detail.status_code == 200
    assert detail.json()["order_no"] == order["order_no"]

    orders = client.get("/api/orders", headers=demo_headers).json()
    assert orders[0]["id"] == order["id"]  # newest first
    assert any(
        item["order_no"] == DEMO_ORDER_NO and item["source"] == "platform"
        for item in orders
    )

    cancelled = client.post(f"/api/orders/{order['id']}/cancel", headers=demo_headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    again = client.post(f"/api/orders/{order['id']}/cancel", headers=demo_headers)
    assert again.status_code == 400
    assert "已取消" in again.json()["detail"]


def test_checkout_empty_cart_is_rejected(client, demo_headers):
    response = client.post(
        "/api/orders",
        json={"shipping": SHIPPING, "note": ""},
        headers=demo_headers,
    )
    assert response.status_code == 400
    assert "购物车" in response.json()["detail"]


def test_checkout_selected_items_keeps_rest_of_cart(client, db_factory, demo_headers):
    shirt_id = product_id_by_sku(db_factory, "ys-tp-001")  # 699
    dress_id = product_id_by_sku(db_factory, "ys-dr-001")  # 899
    add_item(client, demo_headers, shirt_id, quantity=1, size="M", color="月白")
    cart = add_item(client, demo_headers, dress_id, quantity=1, size="M", color="墨黑")
    item_ids = {item["product"]["id"]: item["id"] for item in cart["items"]}

    response = client.post(
        "/api/orders",
        json={"shipping": SHIPPING, "item_ids": [item_ids[shirt_id]]},
        headers=demo_headers,
    )
    assert response.status_code == 200, response.text
    order = response.json()
    assert len(order["items"]) == 1
    assert order["items"][0]["product_id"] == shirt_id
    assert order["total"] == pytest.approx(699.0)

    remaining = client.get("/api/cart", headers=demo_headers).json()
    assert len(remaining["items"]) == 1
    assert remaining["items"][0]["product"]["id"] == dress_id

    unknown = client.post(
        "/api/orders",
        json={"shipping": SHIPPING, "item_ids": [999999]},
        headers=demo_headers,
    )
    assert unknown.status_code == 400
    assert "购物车" in unknown.json()["detail"]


def test_orders_are_private_per_user(client, db_factory):
    with db_factory() as db:
        other = User(
            username="other",
            password_hash=hash_password("other123"),
            nickname="其他用户",
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        token = create_access_token(other.id, other.username)
        demo_order = db.scalar(select(Order).where(Order.order_no == DEMO_ORDER_NO))
        assert demo_order is not None
        demo_order_id = demo_order.id

    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/orders", headers=headers).json() == []
    assert client.get(f"/api/orders/{demo_order_id}", headers=headers).status_code == 404
    assert (
        client.post(f"/api/orders/{demo_order_id}/cancel", headers=headers).status_code
        == 404
    )
