"""五智能体荐衣路由：SSE 主链路 + 会话回看。

``POST /api/recommend/image`` 直接返回 ``text/event-stream``；
事件名与字段严格遵循 ``docs/CONTRACTS.md`` 3.6 节。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..agents.personas import agent_name
from ..database import get_db
from ..deps import get_current_user
from ..models import AgentMessage, AgentSession, User
from ..schemas import AgentMessageOut, AgentSessionOut
from ..services.recommendation import (
    InvalidImageError,
    sniff_image,
    stream_stylist,
)

logger = logging.getLogger("yijian.routers.recommend")

router = APIRouter(prefix="/recommend", tags=["五智能体荐衣"])

_HEARTBEAT_SECONDS = 15.0
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _parse_budget(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="预算格式不正确，请输入数字") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise HTTPException(status_code=400, detail="预算格式不正确，请输入数字")
    if value <= 0:
        return None
    if value > 10_000_000:
        raise HTTPException(status_code=400, detail="预算数值过大")
    return round(value, 2)


def _format_event(event: str, data: dict[str, Any], event_id: int) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n"


async def _sse_wrapper(source: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    """把业务事件包成 SSE，并在 15s 空档发送注释心跳。"""
    queue: asyncio.Queue[Any] = asyncio.Queue()
    sentinel = object()

    async def produce() -> None:
        try:
            async for item in source:
                await queue.put(item)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - 业务层已兜底，这里防最后一道
            logger.exception("推荐 SSE 生产协程异常")
            await queue.put(
                {
                    "event": "error",
                    "data": {
                        "code": "stream_failed",
                        "message": "推荐流式输出中断，请稍后重试",
                    },
                }
            )
        finally:
            await queue.put(sentinel)

    task = asyncio.create_task(produce())
    event_id = 0
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if item is sentinel:
                break
            event_id += 1
            yield _format_event(
                str(item.get("event") or "message"),
                item.get("data") if isinstance(item.get("data"), dict) else {},
                event_id,
            )
    except asyncio.CancelledError:
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
        raise
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await task


@router.post("/image")
async def recommend_image(
    file: UploadFile = File(...),
    budget: str | None = Form(default=None),
    note: str = Form(default=""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """上传图片，直接以 SSE 返回五智能体两轮评议全过程。"""
    image_bytes = await file.read()
    try:
        image_format = sniff_image(image_bytes)
    except InvalidImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    budget_value = _parse_budget(budget)
    generator = stream_stylist(
        db,
        user,
        image_bytes,
        image_format=image_format,
        content_type=file.content_type or "",
        budget=budget_value,
        note=(note or "").strip()[:200],
    )
    return StreamingResponse(
        _sse_wrapper(generator),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


def _message_out(message: AgentMessage) -> dict[str, Any]:
    payload = AgentMessageOut.model_validate(message).model_dump(mode="json")
    payload["agent_name"] = agent_name(message.agent)
    return payload


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    session = db.get(AgentSession, session_id)
    if (
        session is None
        or session.kind != "stylist"
        or session.user_id != user.id
    ):
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    messages = (
        db.query(AgentMessage)
        .filter(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.seq.asc(), AgentMessage.id.asc())
        .all()
    )
    return {
        "session": AgentSessionOut.model_validate(session).model_dump(mode="json"),
        "messages": [_message_out(item) for item in messages],
        "result": session.result,
    }


@router.get("/history")
def get_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    sessions = (
        db.query(AgentSession)
        .filter(
            AgentSession.user_id == user.id,
            AgentSession.kind == "stylist",
        )
        .order_by(AgentSession.created_at.desc(), AgentSession.id.desc())
        .limit(50)
        .all()
    )
    return [
        AgentSessionOut.model_validate(item).model_dump(mode="json")
        for item in sessions
    ]
