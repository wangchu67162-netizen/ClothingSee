"""Single shopping assistant API (Bearer): SSE chat + session history."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import AgentSession, User
from ..schemas import AssistantChatRequest, ProductOut
from ..services import assistant as assistant_service

router = APIRouter(prefix="/assistant", tags=["购物智能体"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@router.post("/chat", summary="购物助理对话（SSE，需登录）")
async def chat(
    payload: AssistantChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    products_orm = assistant_service.search_products(db, payload.message, limit=6)
    products = [ProductOut.model_validate(product) for product in products_orm]
    intent = assistant_service.detect_intent(payload.message, products_orm)
    session = assistant_service.prepare_session(
        db, user, payload.session_id, payload.message, intent
    )
    assistant_service.add_user_message(db, session.id, payload.message, intent)

    base_url = str(request.base_url).rstrip("/")
    generator = assistant_service.stream_assistant(
        session_id=session.id,
        user_id=user.id,
        user_name=user.nickname or user.username,
        message=payload.message,
        intent=intent,
        products=products,
        base_url=base_url,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream; charset=utf-8",
        headers=SSE_HEADERS,
    )


@router.get("/history", summary="购物助理会话历史")
def history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": assistant_service.session_history(db, user.id)}


@router.get("/sessions/{session_id}", summary="购物助理会话详情与步骤")
def session_detail(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session = db.get(AgentSession, session_id)
    if session is None or session.kind != "assistant" or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return assistant_service.session_detail(db, session)
