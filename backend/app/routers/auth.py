"""认证路由：注册、登录、当前用户与登出。

密码使用 ``app.security`` 的 scrypt 哈希；令牌为无状态 JWT（HS256）。
所有业务错误均返回中文 ``detail``，便于前端直接展示。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import AuthResponse, LoginRequest, RegisterRequest, UserPublic
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["认证"])

USERNAME_MIN_LEN = 2
USERNAME_MAX_LEN = 32
NICKNAME_MAX_LEN = 32

_DUPLICATE_USERNAME_DETAIL = "该用户名已被注册"
_BAD_CREDENTIALS_DETAIL = "用户名或密码错误"


def _normalize_username(raw: str) -> str:
    """去除首尾空白并做长度校验。

    Pydantic 的 ``min_length``/``max_length`` 发生在去空白之前，
    因此这里需要按去空白后的结果再校验一次（例如 ``"  a  "``）。
    """
    username = raw.strip()
    if not (USERNAME_MIN_LEN <= len(username) <= USERNAME_MAX_LEN):
        raise HTTPException(
            status_code=422,
            detail=(
                f"用户名长度需为 {USERNAME_MIN_LEN}-{USERNAME_MAX_LEN} 个字符"
                "（忽略首尾空白）"
            ),
        )
    return username


def _auth_response(user: User) -> AuthResponse:
    """签发 JWT 并组装登录/注册统一响应。"""
    token = create_access_token(user.id, user.username)
    return AuthResponse(
        access_token=token,
        token_type="bearer",
        user=UserPublic.model_validate(user),
    )


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    """注册新用户：去空白、长度校验、用户名查重、scrypt 哈希、昵称默认用户名。"""
    username = _normalize_username(payload.username)

    # 密码不做 strip：空白也是密码的一部分；长度 6-64 已由 RegisterRequest 约束。
    nickname = payload.nickname.strip()
    if len(nickname) > NICKNAME_MAX_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"昵称不能超过 {NICKNAME_MAX_LEN} 个字符",
        )
    if not nickname:
        nickname = username

    existing = db.scalar(select(User).where(User.username == username))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_DUPLICATE_USERNAME_DETAIL,
        )

    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        nickname=nickname,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # 并发注册同名用户时由唯一索引兜底。
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_DUPLICATE_USERNAME_DETAIL,
        ) from None
    db.refresh(user)
    return _auth_response(user)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    """校验用户名与密码，成功签发 JWT；任何失败统一返回 401 中文提示。"""
    username = payload.username.strip()
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BAD_CREDENTIALS_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _auth_response(user)


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    """返回当前登录用户信息。"""
    return UserPublic.model_validate(current_user)


@router.post("/logout", dependencies=[Depends(get_current_user)])
def logout() -> dict[str, bool]:
    """登出：JWT 无状态，服务端不保存会话也不做黑名单。

    该接口要求携带有效 token，用于前端统一调用并确认登录态；
    返回 ``{"ok": true}`` 表示服务端已受理，真正的登出由客户端删除本地 token 完成。
    """
    return {"ok": True}
