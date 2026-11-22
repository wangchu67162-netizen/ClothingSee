"""认证路由测试（T1）：注册、重复注册、登录失败、me、登出。

使用 ``with TestClient(app)`` 触发 FastAPI lifespan（``init_db`` 建表）。
所有测试用户名统一以本次运行唯一的 ``PREFIX`` 开头，结束后统一清理，
不污染演示数据库中的其它用户。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import User

PASSWORD = "secret123"
PREFIX = f"t1_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def client():
    """模块级 TestClient；with 语句会执行 lifespan（init_db、seed 等）。"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module", autouse=True)
def _cleanup_test_users(client):
    """测试结束后删除本次运行创建的用户。"""
    yield
    with SessionLocal() as db:
        # startswith + autoescape：PREFIX 中的 "_" 不会被当成 LIKE 通配符。
        db.query(User).filter(User.username.startswith(PREFIX, autoescape=True)).delete(
            synchronize_session=False
        )
        db.commit()


def _username(suffix: str) -> str:
    return f"{PREFIX}_{suffix}"


def _register(
    client: TestClient,
    username: str,
    password: str = PASSWORD,
    nickname: str = "",
):
    return client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "nickname": nickname},
    )


def _login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- 注册


def test_register_success_and_me(client: TestClient):
    username = _username("reg")
    resp = _register(client, f"  {username}  ", nickname="   ")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == username  # 已去除首尾空白
    assert body["user"]["nickname"] == username  # 昵称留空时默认用户名
    assert isinstance(body["user"]["id"], int)

    me = client.get("/api/auth/me", headers=_auth(body["access_token"]))
    assert me.status_code == 200, me.text
    assert me.json()["username"] == username
    assert me.json()["id"] == body["user"]["id"]


def test_register_trims_nickname(client: TestClient):
    username = _username("nick")
    resp = _register(client, username, nickname="  小衣  ")
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["nickname"] == "小衣"


def test_register_password_is_hashed_in_db(client: TestClient):
    username = _username("hash")
    resp = _register(client, username)
    assert resp.status_code == 200, resp.text

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one()
        assert user.password_hash != PASSWORD
        assert user.password_hash.startswith("scrypt$")


def test_register_duplicate_username(client: TestClient):
    username = _username("dup")
    assert _register(client, username).status_code == 200

    again = _register(client, f" {username} ")
    assert again.status_code == 409
    assert "已被注册" in again.json()["detail"]


def test_register_rejects_blank_or_short_username(client: TestClient):
    blank = _register(client, "   ")
    assert blank.status_code == 422
    assert "用户名长度" in blank.json()["detail"]

    short = _register(client, "  a  ")
    assert short.status_code == 422
    assert "用户名长度" in short.json()["detail"]


def test_register_rejects_too_long_username_and_short_password(client: TestClient):
    too_long = _register(client, f"{PREFIX}_" + "x" * 40)
    assert too_long.status_code == 422

    short_pw = _register(client, _username("shortpw"), password="123")
    assert short_pw.status_code == 422


# ---------------------------------------------------------------- 登录


def test_login_success_returns_token(client: TestClient):
    username = _username("login")
    assert _register(client, username).status_code == 200

    resp = _login(client, f"  {username}  ")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == username

    me = client.get("/api/auth/me", headers=_auth(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["username"] == username


def test_login_wrong_password_returns_401_chinese(client: TestClient):
    username = _username("badpw")
    assert _register(client, username).status_code == 200

    resp = _login(client, username, password="wrong-pass")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户名或密码错误"
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_login_unknown_user_returns_401(client: TestClient):
    resp = _login(client, _username("ghost"))
    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户名或密码错误"


# ---------------------------------------------------------------- me / 登出


def test_me_requires_valid_token(client: TestClient):
    no_token = client.get("/api/auth/me")
    assert no_token.status_code == 401
    assert no_token.json()["detail"] == "请先登录"

    bad_token = client.get("/api/auth/me", headers=_auth("not-a-real-token"))
    assert bad_token.status_code == 401
    assert bad_token.json()["detail"] == "请先登录"


def test_logout_requires_login(client: TestClient):
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 401


def test_logout_returns_ok(client: TestClient):
    username = _username("logout")
    assert _register(client, username).status_code == 200
    token = _login(client, username).json()["access_token"]

    resp = client.post("/api/auth/logout", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # JWT 无状态：服务端不维护黑名单，登出后由客户端删除 token。
    # 因此同一 token 在过期前仍能通过校验，这里仅验证接口契约。
    still_ok = client.get("/api/auth/me", headers=_auth(token))
    assert still_ok.status_code == 200
