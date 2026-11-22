"""Single shopping assistant: rule-first intent, product cards, SSE + browser.

Event flow emitted over SSE (contract §3.7):

    session → intent → assistant_message → products → browse_step… →
    order_created → done

On any failure the stream ends with a Chinese ``error`` event (plus ``done``)
and the session is persisted as ``failed``. The assistant never fabricates a
successful order: an ``order_created`` event is only emitted after the browser
success page reports an order number **and** that order exists in the platform
database for the current user.

Rules first, Qwen optional: when a DashScope key is configured the service may
ask ``qwen-plus`` to refine a chat-only intent; any error silently falls back
to the deterministic local rules (with a ``warning`` event).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from ..browser.base import BrowserUnavailable, ShopRequest, ShopResult
from ..browser.mock_driver import MockMallShopper
from ..browser.shopper import MallShopper
from ..config import settings
from ..database import SessionLocal
from ..models import AgentMessage, AgentSession, BrowseTask, Order, Product
from ..schemas import AssistantIntent, ProductOut

logger = logging.getLogger("yijian.assistant")

# --------------------------------------------------------------------- rules
_ORDER_KEYWORDS = (
    "帮我下单",
    "替我下单",
    "帮我购买",
    "帮我买",
    "替我买",
    "直接下单",
    "立即购买",
    "直接买",
    "下单",
    "购买",
    "买下",
    "结算",
    "拍下",
)

_RECOMMEND_KEYWORDS = (
    "我想买",
    "我要买",
    "想买",
    "想入手",
    "想要",
    "有没有",
    "帮我找",
    "帮我推荐",
    "推荐",
    "找一",
    "搜一",
    "看看",
    "看一下",
    "适合",
    "搭配",
    "链接",
    "多少钱",
    "价格",
    "找",
    "搜",
)

_NOISE_TOKENS = sorted(
    set(_ORDER_KEYWORDS)
    | set(_RECOMMEND_KEYWORDS)
    | {
        "请",
        "麻烦",
        "帮我",
        "替我",
        "一下",
        "一件",
        "一个",
        "一条",
        "一套",
        "一双",
        "能配",
        "可以",
        "我想",
        "我要",
        "我",
        "的",
        "吗",
        "呢",
        "吧",
        "啊",
        "呀",
        "和",
        "跟",
        "买",
        "要",
        "想",
        "码",
        "号",
    },
    key=len,
    reverse=True,
)

_SIZE_PATTERN = re.compile(
    r"(?:^|[^A-Za-z])(XS|XXL|XL|S|M|L)(?:码|号)?(?=$|[^A-Za-z])",
    re.IGNORECASE,
)

AGENT_NAMES = {"user": "你", "assistant": "衣见购物助理", "moderator": "主持人"}


# --------------------------------------------------------------- text helpers
def _extract_size(text: str) -> str:
    match = _SIZE_PATTERN.search(text or "")
    return match.group(1).upper() if match else ""


def _extract_query(text: str, product: Any | None = None) -> str:
    query = text or ""
    for token in _NOISE_TOKENS:
        if token:
            query = query.replace(token, " ")
    query = _SIZE_PATTERN.sub(" ", query)
    if product is not None:
        for color in getattr(product, "colors", None) or []:
            query = query.replace(str(color), " ")
    query = re.sub(r"[\s,，。.!！?？、；;：:·\-]+", " ", query).strip()
    return query[:64]


def search_products(db: Session, message: str, limit: int = 6) -> list[Product]:
    """Deterministic keyword search over the (small) local catalog.

    Scores product-name hits highest, then tags/categories/occasions, then
    two-character overlap. Returns only real matches — callers decide what to
    do when nothing matches (never fall back to an arbitrary product for an
    order).
    """
    text = (message or "").strip()
    if not text:
        return []
    cleaned = _extract_query(text)
    terms = [term for term in cleaned.split() if term]
    scored: list[tuple[float, Product]] = []

    products = db.query(Product).all()
    for product in products:
        name = product.name or ""
        score = 0.0
        if name and name in text:
            score += 14
        if cleaned and cleaned in name:
            score += 10
        for term in terms:
            if len(term) >= 2 and term in name:
                score += 6
            elif len(term) >= 2 and product.subtitle and term in product.subtitle:
                score += 2
        tags = list(product.style_tags or []) + [product.category, product.occasion, product.season]
        for tag in tags:
            if tag and str(tag) in text:
                score += 3
        if product.category and product.category in text:
            score += 3
        if cleaned and product.search_text and cleaned in product.search_text:
            score += 2
        grams = {
            cleaned[i : i + 2]
            for i in range(max(0, len(cleaned) - 1))
            if cleaned[i : i + 2].strip()
        }
        overlap = sum(1 for gram in grams if gram in name)
        score += min(overlap, 6) * 1.5
        if score > 0:
            scored.append((score, product))

    scored.sort(key=lambda pair: (-pair[0], 0 if pair[1].featured else 1, -(pair[1].sales or 0)))
    return [product for _, product in scored[:limit]]


def detect_intent(message: str, products: list[Any] | None = None) -> AssistantIntent:
    """Rule-based intent. Order commands win over recommendation phrasing."""
    text = (message or "").strip()
    products = products or []
    order_hit = any(keyword in text for keyword in _ORDER_KEYWORDS)
    recommend_hit = any(keyword in text for keyword in _RECOMMEND_KEYWORDS)
    size = _extract_size(text)
    first = products[0] if products else None
    color = ""
    if first is not None:
        color = next(
            (str(item) for item in (getattr(first, "colors", None) or []) if str(item) in text),
            "",
        )
    query = _extract_query(text, first)

    if order_hit:
        intent, confidence = "order", 0.92
    elif recommend_hit or products:
        intent, confidence = "recommend", 0.85
    else:
        intent, confidence = "chat", 0.55
    return AssistantIntent(intent=intent, query=query, size=size, color=color, confidence=confidence)


def build_cards(products: list[ProductOut]) -> list[dict[str, Any]]:
    return [
        {
            "product": product.model_dump(mode="json"),
            "platform_url": f"/product/{product.id}",
            "mall_url": f"/demo-mall/product.html?id={product.id}",
        }
        for product in products
    ]


def assistant_reply(
    intent: AssistantIntent,
    products: list[ProductOut],
    *,
    size: str = "",
    color: str = "",
) -> str:
    keyword = intent.query or (products[0].name if products else "这件单品")
    if intent.intent == "order":
        if not products:
            return (
                f"没有找到与「{intent.query or '这个描述'}」匹配、可下单的商品。"
                "请换个关键词，例如「帮我下单暮色长风衣，M 码」。"
            )
        product = products[0]
        chosen_size = size or intent.size or (product.sizes[0] if product.sizes else "默认尺码")
        chosen_color = color or intent.color or (product.colors[0] if product.colors else "默认颜色")
        return (
            f"收到下单任务：{product.name}（{chosen_size} / {chosen_color}）× 1。"
            "我正在打开无头浏览器进入云裳商城，依次搜索、选规格、结算并提交，每一步都会截图回传。"
        )
    if intent.intent == "recommend":
        if not products:
            return (
                f"暂时没有找到与「{intent.query or '这个描述'}」匹配的单品。"
                "可以试试「风衣」「真丝衬衫」「阔腿裤」等关键词。"
            )
        names = "、".join(product.name for product in products[:3])
        return (
            f"在衣橱里为你挑出 {len(products)} 件与「{keyword}」相关的单品：{names}。"
            "每张卡片都可以打开平台详情或云裳商城。"
        )
    return (
        "你好，我是衣见购物助理。可以帮你找带图商品链接，也可以直接打开无头浏览器替你下单。"
        "试试说：「我想买一件适合秋天的风衣」或「帮我下单暮色长风衣，M 码」。"
    )


# ------------------------------------------------------------------- session
def prepare_session(
    db: Session,
    user: Any,
    session_id: str | None,
    message: str,
    intent: AssistantIntent,
) -> AgentSession:
    """Reuse the user's existing assistant session or create a new one."""
    session: AgentSession | None = None
    if session_id:
        candidate = db.get(AgentSession, session_id)
        if candidate is not None and candidate.kind == "assistant" and candidate.user_id == user.id:
            session = candidate
    if session is None:
        session = AgentSession(
            user_id=user.id,
            kind="assistant",
            status="running",
            mode="qwen" if settings.llm_enabled else "mock",
            result={},
        )
        db.add(session)
    else:
        session.status = "running"
        session.error = None
    db.commit()
    db.refresh(session)
    return session


def _next_seq(db: Session, session_id: str) -> int:
    row = (
        db.query(AgentMessage.seq)
        .filter(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.seq.desc())
        .first()
    )
    return int(row[0] or 0) + 1 if row else 1


def add_user_message(db: Session, session_id: str, message: str, intent: AssistantIntent) -> None:
    db.add(
        AgentMessage(
            session_id=session_id,
            seq=_next_seq(db, session_id),
            agent="user",
            round=0,
            role="user",
            message_type="user",
            recipients=[],
            content=message,
            payload={"intent": intent.model_dump(mode="json")},
        )
    )
    db.commit()


def _save_assistant_message(
    session_id: str, content: str, payload: dict[str, Any]
) -> None:
    try:
        with SessionLocal() as db:
            db.add(
                AgentMessage(
                    session_id=session_id,
                    seq=_next_seq(db, session_id),
                    agent="assistant",
                    round=0,
                    role="assistant",
                    message_type="reply",
                    recipients=["user"],
                    content=content,
                    payload=payload,
                )
            )
            db.commit()
    except Exception:  # pragma: no cover - history write must not kill SSE
        logger.exception("failed to persist assistant message")


def _finish_session(
    session_id: str,
    *,
    status: str,
    error: str | None,
    result_patch: dict[str, Any],
) -> None:
    try:
        with SessionLocal() as db:
            session = db.get(AgentSession, session_id)
            if session is None:
                return
            result = dict(session.result or {})
            result.update(result_patch)
            session.result = result
            session.status = status
            session.error = (error or "")[:500] or None
            db.commit()
    except Exception:  # pragma: no cover
        logger.exception("failed to persist assistant session %s", session_id)


# --------------------------------------------------------------- browse task
def _create_browse_task(session_id: str) -> tuple[int, str]:
    task_token = uuid4().hex
    with SessionLocal() as db:
        task = BrowseTask(
            session_id=session_id,
            task_token=task_token,
            status="running",
            steps=[],
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task.id, task_token


def _persist_step(task_id: int, step: dict[str, Any]) -> None:
    try:
        with SessionLocal() as db:
            task = db.get(BrowseTask, task_id)
            if task is None:
                return
            steps = list(task.steps or [])
            steps.append(step)
            task.steps = steps
            if step.get("status") == "failed":
                task.status = "failed"
                task.error = str(step.get("detail") or "浏览器步骤失败")[:500]
            db.commit()
    except Exception:  # pragma: no cover
        logger.exception("failed to persist browse step")


def _finish_task(
    task_id: int,
    *,
    status: str,
    order_no: str | None = None,
    error: str | None = None,
) -> None:
    try:
        with SessionLocal() as db:
            task = db.get(BrowseTask, task_id)
            if task is None:
                return
            task.status = status
            if order_no:
                task.order_no = order_no
            task.error = (error or "")[:500] or None
            db.commit()
    except Exception:  # pragma: no cover
        logger.exception("failed to finish browse task %s", task_id)


def _normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    status = step.get("status") or "done"
    if status not in ("running", "done", "failed"):
        status = "done"
    try:
        index = int(step.get("index") or 0)
    except (TypeError, ValueError):
        index = 0
    screenshot = step.get("screenshot")
    return {
        "index": index,
        "action": str(step.get("action") or "浏览器操作"),
        "status": status,
        "detail": str(step.get("detail") or ""),
        "screenshot": str(screenshot) if screenshot else None,
    }


def _verify_order(order_no: str, user_id: int) -> tuple[str, float] | None:
    """Only trust the browser when the platform actually persisted the order."""
    with SessionLocal() as db:
        order = (
            db.query(Order)
            .filter(Order.external_ref == order_no, Order.user_id == user_id)
            .one_or_none()
        )
        if order is None:
            return None
        return order.order_no, float(order.total)


# -------------------------------------------------------------------- engine
def build_shopper(engine: str, *, base_url: str, session_factory: Any) -> Any:
    """Pick the browser engine. ``mock`` exists for tests only."""
    normalized = (engine or "").strip().lower()
    if normalized == "mock":
        return MockMallShopper(session_factory)
    if normalized == "browser_use":
        from ..browser.browser_use_driver import BrowserUseShopper

        return BrowserUseShopper(base_url, session_factory=session_factory)
    return MallShopper(base_url)


def _default_customer(user_name: str) -> dict[str, str]:
    name = (user_name or "").strip() or "云裳体验官"
    return {
        "name": name[:32],
        "phone": "13800000000",
        "address": "上海市黄浦区云裳路 88 号 衣见公寓 3 栋 501（演示地址）",
    }


# ---------------------------------------------------------------------- qwen
def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model output")
    return json.loads(raw[start : end + 1])


async def refine_intent_with_qwen(
    message: str, products: list[ProductOut]
) -> AssistantIntent | None:
    """Optional Qwen intent refinement; never raises, returns None on failure."""
    if not settings.llm_enabled:
        return None
    catalog = "、".join(product.name for product in products[:6]) or "无"
    system = (
        "你是「衣见」电商购物助理的意图分类器。只输出 JSON，不要多余文字，格式："
        '{"intent":"recommend|order|chat","query":"用于检索商品的中文关键词"}。'
        "order 表示用户明确要求替其下单/结算/购买；recommend 表示寻找、推荐、比价；"
        "其余为 chat。query 不要包含“帮我下单”等指令词。"
    )
    payload = {
        "model": settings.qwen_text_model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"候选商品：{catalog}\n用户消息：{message}"},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
            response = await client.post(
                settings.dashscope_base_url.rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.dashscope_api_key.strip()}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = _extract_json_object(content)
        intent = str(parsed.get("intent") or "").strip().lower()
        if intent not in ("recommend", "order", "chat"):
            return None
        return AssistantIntent(
            intent=intent,  # type: ignore[arg-type]
            query=str(parsed.get("query") or "")[:64],
            confidence=0.75,
        )
    except Exception as exc:  # no key / timeout / bad JSON → rules win
        logger.warning("Qwen intent refinement unavailable: %s", exc)
        return None


# ----------------------------------------------------------------------- SSE
def _format_event(event: str, data: dict[str, Any], event_id: int) -> str:
    body = json.dumps(data, ensure_ascii=False, default=str)
    return f"id: {event_id}\nevent: {event}\ndata: {body}\n\n"


async def stream_assistant(
    *,
    session_id: str,
    user_id: int,
    user_name: str,
    message: str,
    intent: AssistantIntent,
    products: list[ProductOut],
    base_url: str,
) -> AsyncIterator[str]:
    """Yield the assistant SSE stream while a background job does the work.

    The job keeps running (and finishing DB writes) even if the client
    disconnects, per the project contract; only the queue consumption stops.
    """
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
    job = asyncio.create_task(
        _run_assistant_job(
            queue,
            session_id=session_id,
            user_id=user_id,
            user_name=user_name,
            message=message,
            intent=intent,
            products=products,
            base_url=base_url,
        )
    )

    def _consume_task_result(task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:  # pragma: no cover
            pass
        except Exception:  # pragma: no cover
            logger.exception("assistant job crashed")

    job.add_done_callback(_consume_task_result)

    event_id = 0
    # Note: the job is intentionally never cancelled here. If the client
    # disconnects, the job still owns the browser and the final DB writes, so
    # it must be allowed to finish (contract §7).
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=15.0)
        except asyncio.TimeoutError:
            yield ": ping\n\n"
            continue
        if item is None:
            break
        event, data = item
        event_id += 1
        yield _format_event(event, data, event_id)


async def _run_assistant_job(
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None],
    *,
    session_id: str,
    user_id: int,
    user_name: str,
    message: str,
    intent: AssistantIntent,
    products: list[ProductOut],
    base_url: str,
) -> None:
    started = time.perf_counter()
    engine = (settings.browser_engine or "playwright").strip().lower()
    mode = "qwen" if settings.llm_enabled else "mock"
    final_content = ""
    outcome = {"status": "done", "error": None}
    result_patch: dict[str, Any] = {
        "message": message,
        "intent": intent.model_dump(mode="json"),
        "products": [product.model_dump(mode="json") for product in products],
        "engine": engine,
    }
    task_id: int | None = None
    failure_step_emitted = False
    step_count = 0

    async def emit(event: str, data: dict[str, Any]) -> None:
        await queue.put((event, data))

    try:
        await emit(
            "session",
            {"session_id": session_id, "kind": "assistant", "mode": mode, "engine": engine},
        )

        # Optional LLM refinement only when rules already said "chat".
        if intent.intent == "chat" and settings.llm_enabled:
            refined = await refine_intent_with_qwen(message, products)
            if refined is not None:
                intent = refined.model_copy(
                    update={"size": refined.size or intent.size, "color": refined.color or intent.color}
                )
                result_patch["intent"] = intent.model_dump(mode="json")
                if intent.intent in ("recommend", "order") and not products and intent.query:
                    with SessionLocal() as db:
                        found = search_products(db, intent.query, limit=6)
                        products = [ProductOut.model_validate(product) for product in found]
                    result_patch["products"] = [
                        product.model_dump(mode="json") for product in products
                    ]
            else:
                await emit(
                    "warning",
                    {"code": "qwen_fallback", "message": "大模型意图识别暂不可用，已使用本地规则。"},
                )

        await emit("intent", intent.model_dump(mode="json"))

        selected = products[0] if products else None
        size, color = "", ""
        variant_warnings: list[str] = []
        if selected is not None and intent.intent == "order":
            size = (intent.size or "").upper()
            if size and selected.sizes and size not in selected.sizes:
                variant_warnings.append(f"该商品没有 {size} 码，已改为 {selected.sizes[0]} 码。")
                size = ""
            if not size:
                size = selected.sizes[0] if selected.sizes else ""
            color = intent.color or ""
            if color and selected.colors and color not in selected.colors:
                variant_warnings.append(f"该商品没有「{color}」配色，已改为「{selected.colors[0]}」。")
                color = ""
            if not color:
                color = selected.colors[0] if selected.colors else ""

        final_content = assistant_reply(intent, products, size=size, color=color)
        await emit("assistant_message", {"role": "assistant", "content": final_content})

        if intent.intent in ("recommend", "order"):
            await emit("products", {"items": build_cards(products)})

        for warning_text in variant_warnings:
            await emit("warning", {"code": "variant_adjusted", "message": warning_text})

        if intent.intent == "recommend" and not products:
            await emit(
                "warning",
                {
                    "code": "no_product",
                    "message": "没有找到匹配的单品，换个关键词试试，例如「风衣」或「真丝衬衫」。",
                },
            )
            result_patch["no_product"] = True

        elif intent.intent == "order":
            if selected is None:
                await emit(
                    "warning",
                    {
                        "code": "no_product",
                        "message": "没有找到可下单的商品，请换一个关键词后重试。",
                    },
                )
                result_patch["no_product"] = True
            else:
                task_id, task_token = _create_browse_task(session_id)
                result_patch["browse_task_id"] = task_id
                result_patch["selected_product_id"] = selected.id
                result_patch["size"] = size
                result_patch["color"] = color

                customer = _default_customer(user_name)
                shopper = build_shopper(
                    engine, base_url=base_url, session_factory=SessionLocal
                )
                request = ShopRequest(
                    session_id=session_id,
                    task_token=task_token,
                    base_url=base_url,
                    product_id=selected.id,
                    product_name=selected.name,
                    query=intent.query or selected.name,
                    size=size,
                    color=color,
                    quantity=1,
                    customer=customer,
                    expected_total=round(float(selected.price), 2),
                )

                async def on_step(step: dict[str, Any]) -> None:
                    nonlocal failure_step_emitted, step_count
                    normalized = _normalize_step(step)
                    step_count += 1
                    normalized["index"] = step_count
                    if normalized["status"] == "failed":
                        failure_step_emitted = True
                    _persist_step(task_id, normalized)  # type: ignore[arg-type]
                    await emit("browse_step", normalized)

                shop_result: ShopResult = await shopper.shop(request, on_step)

                verified = _verify_order(shop_result.order_no, user_id)
                if verified is None:
                    raise BrowserUnavailable(
                        "云裳商城显示下单成功，但平台未记录对应订单，已终止流程，请联系管理员。"
                    )
                order_no, total = verified
                _finish_task(task_id, status="done", order_no=order_no)
                result_patch.update(
                    {
                        "order_no": order_no,
                        "total": total,
                        "source": "agent",
                        "browse_task_id": task_id,
                    }
                )
                await emit(
                    "order_created",
                    {
                        "order_no": order_no,
                        "source": "agent",
                        "total": total,
                        "session_id": session_id,
                    },
                )
                final_content = (
                    f"{selected.name} 已通过云裳商城下单成功，订单号 {order_no}，"
                    f"合计 ¥{total:.2f}。可在「我的订单」查看，完整截图见右侧工具轨迹。"
                )
                await emit("assistant_message", {"role": "assistant", "content": final_content})

    except BrowserUnavailable as exc:
        outcome["status"] = "failed"
        outcome["error"] = str(exc)
        logger.warning("browser unavailable for session %s: %s", session_id, exc)
        if task_id is not None:
            _finish_task(task_id, status="failed", error=str(exc))
            if not failure_step_emitted:
                step_count += 1
                failed_step = {
                    "index": step_count,
                    "action": "浏览器执行失败",
                    "status": "failed",
                    "detail": str(exc),
                    "screenshot": exc.screenshot,
                }
                _persist_step(task_id, failed_step)
                await emit("browse_step", failed_step)
        final_content = f"下单失败：{exc}"
        await emit("error", {"code": "browser_unavailable", "message": str(exc)})

    except Exception as exc:  # pragma: no cover - unexpected failures
        logger.exception("assistant job failed for session %s", session_id)
        outcome["status"] = "failed"
        outcome["error"] = f"智能助理处理失败：{exc}"
        if task_id is not None:
            _finish_task(task_id, status="failed", error="智能助理处理失败")
        final_content = "处理失败：智能助理暂时无法完成本次请求，请稍后重试。"
        await emit("error", {"code": "assistant_error", "message": final_content})

    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _finish_session(
            session_id,
            status="done" if outcome["status"] == "done" else "failed",
            error=outcome["error"],
            result_patch=result_patch,
        )
        if final_content:
            _save_assistant_message(
                session_id,
                final_content,
                {
                    "intent": result_patch.get("intent"),
                    "order_no": result_patch.get("order_no"),
                    "product_ids": [product.id for product in products],
                },
            )
        await emit(
            "done",
            {
                "session_id": session_id,
                "elapsed_ms": elapsed_ms,
                "status": outcome["status"],
            },
        )
        await queue.put(None)


# -------------------------------------------------------------------- history
def serialize_session(session: AgentSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "kind": session.kind,
        "status": session.status,
        "mode": session.mode,
        "error": session.error,
        "result": session.result or {},
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": (session.updated_at or session.created_at).isoformat()
        if (session.updated_at or session.created_at)
        else None,
    }


def _message_dict(message: AgentMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "session_id": message.session_id,
        "seq": message.seq,
        "agent": message.agent,
        "agent_name": AGENT_NAMES.get(message.agent, message.agent),
        "round": message.round,
        "role": message.role,
        "message_type": message.message_type,
        "recipients": message.recipients or [],
        "content": message.content,
        "scores": message.scores or [],
        "payload": message.payload,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _task_dict(task: BrowseTask | None) -> dict[str, Any] | None:
    if task is None:
        return None
    return {
        "id": task.id,
        "session_id": task.session_id,
        "status": task.status,
        "steps": task.steps or [],
        "order_no": task.order_no,
        "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def session_detail(db: Session, session: AgentSession) -> dict[str, Any]:
    messages = (
        db.query(AgentMessage)
        .filter(AgentMessage.session_id == session.id)
        .order_by(AgentMessage.seq.asc(), AgentMessage.id.asc())
        .all()
    )
    task = (
        db.query(BrowseTask)
        .filter(BrowseTask.session_id == session.id)
        .order_by(BrowseTask.id.desc())
        .first()
    )
    return {
        "session": serialize_session(session),
        "messages": [_message_dict(message) for message in messages],
        "browse_task": _task_dict(task),
        "result": session.result or {},
    }


def session_history(db: Session, user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    sessions = (
        db.query(AgentSession)
        .filter(AgentSession.user_id == user_id, AgentSession.kind == "assistant")
        .order_by(AgentSession.created_at.desc())
        .limit(limit)
        .all()
    )
    return [serialize_session(session) for session in sessions]
