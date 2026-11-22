"""通义千问（DashScope OpenAI 兼容接口）适配层。

- ``qwen3-vl-plus`` 读取图片（data URL），``qwen-plus`` 负责文本评议；
- 90s 超时；429 / 5xx / 超时自动重试 2 次；400 / 401 / 403 不重试；
- JSON 解析容错：去掉 ``` 代码围栏、截取首尾大括号；
- 任何失败都抛 :class:`QwenError`，由业务层降级 Mock 并推送 warning。
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
from typing import Any

import httpx
from PIL import Image

from ..agents.base import (
    AgentOpinion,
    AgentScore,
    DiscussionContext,
    Revision,
    as_str_list,
    as_text,
    clamp_score,
)
from ..agents.personas import AGENT_IDS, Persona, agent_name, peer_ids
from ..config import settings
from ..schemas import VisionAnalysis
from .prompts import build_round1_messages, build_round2_messages, build_vision_messages

logger = logging.getLogger("yijian.llm.qwen")

RETRY_ATTEMPTS = 3  # 首次 + 重试 2 次
RETRY_DELAYS = (1.2, 2.4)


class QwenError(RuntimeError):
    """通义千问调用失败（消息可直接面向用户）。"""


def qwen_available() -> bool:
    """显式 mock 模式或没有 Key 时一律使用 Mock。"""
    return settings.llm_mode != "mock" and bool(settings.dashscope_api_key.strip())


def _guess_mime(image_bytes: bytes) -> str:
    head = image_bytes[:12]
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"RIFF") and b"WEBP" in head:
        return "image/webp"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head.startswith(b"BM"):
        return "image/bmp"
    return "image/jpeg"


def prepare_image_data_url(image_bytes: bytes, mime: str = "") -> str:
    """把图片转为 data URL；过大时本地压缩，避免请求体超限。"""
    payload = image_bytes
    out_mime = (mime or "").strip().lower()
    if not out_mime.startswith("image/"):
        out_mime = _guess_mime(image_bytes)
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            detected = Image.MIME.get(image.format or "")
            if detected:
                out_mime = detected
            if max(image.size) > 1400 or len(image_bytes) > 2_000_000:
                converted = image.convert("RGB")
                converted.thumbnail((1400, 1400), Image.LANCZOS)
                buffer = io.BytesIO()
                converted.save(buffer, format="JPEG", quality=86)
                payload = buffer.getvalue()
                out_mime = "image/jpeg"
    except Exception:  # pragma: no cover - 无法解码时按原样发送
        logger.debug("图片预处理失败，按原始数据发送")
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{out_mime};base64,{encoded}"


def parse_json_loose(text: str | None) -> Any | None:
    """容错 JSON 解析：去围栏、截首尾大括号、去尾逗号。"""
    if not text:
        return None
    cleaned = str(text).strip().lstrip("﻿")
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S | re.I)
    if fence:
        cleaned = fence.group(1).strip()
    candidates: list[str] = [cleaned]
    first, last = cleaned.find("{"), cleaned.rfind("}")
    if first != -1 and last > first:
        candidates.append(cleaned[first : last + 1])
    first_bracket, last_bracket = cleaned.find("["), cleaned.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        candidates.append(cleaned[first_bracket : last_bracket + 1])
    for candidate in candidates:
        for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
            try:
                return json.loads(attempt)
            except (json.JSONDecodeError, TypeError):
                continue
    return None


def _extract_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise QwenError("通义千问未返回候选结果")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise QwenError("通义千问返回结构异常")
    content = message.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if isinstance(text, str):
                    parts.append(text)
        content = "".join(parts)
    if not isinstance(content, str) or not content.strip():
        raise QwenError("通义千问返回了空内容")
    return content.strip()


class QwenClient:
    """DashScope OpenAI 兼容 Chat Completions 客户端。"""

    mode = "qwen"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        text_model: str | None = None,
        vl_model: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else settings.dashscope_api_key).strip()
        self.base_url = (base_url or settings.dashscope_base_url).rstrip("/")
        self.text_model = text_model or settings.qwen_text_model
        self.vl_model = vl_model or settings.qwen_vl_model
        self.timeout = float(timeout or settings.llm_timeout)
        self._transport = transport

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    async def _post(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        if not self.api_key:
            raise QwenError("未配置 DASHSCOPE_API_KEY，无法调用通义千问")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        last_error: str = "通义千问请求失败"
        timeout = httpx.Timeout(self.timeout, connect=15.0)
        async with httpx.AsyncClient(
            timeout=timeout, transport=self._transport
        ) as client:
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    response = await client.post(self.endpoint, headers=headers, json=body)
                except httpx.TimeoutException:
                    last_error = "通义千问请求超时"
                    if attempt < RETRY_ATTEMPTS - 1:
                        await asyncio.sleep(RETRY_DELAYS[attempt])
                        continue
                    raise QwenError("通义千问响应超时，已重试 2 次仍失败") from None
                except httpx.TransportError as exc:
                    last_error = f"通义千问网络异常：{type(exc).__name__}"
                    if attempt < RETRY_ATTEMPTS - 1:
                        await asyncio.sleep(RETRY_DELAYS[attempt])
                        continue
                    raise QwenError("通义千问网络连接失败，已重试 2 次仍失败") from None

                status = response.status_code
                if status in (400, 401, 403):
                    raise QwenError(
                        f"通义千问请求被拒绝（HTTP {status}），请检查 API Key 与模型配置"
                    )
                if status == 429 or status >= 500:
                    last_error = f"通义千问限流或服务异常（HTTP {status}）"
                    if attempt < RETRY_ATTEMPTS - 1:
                        delay = RETRY_DELAYS[attempt]
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                delay = min(5.0, max(0.5, float(retry_after)))
                            except ValueError:
                                pass
                        logger.warning("%s，%.1fs 后重试（%d/%d）", last_error, delay, attempt + 1, RETRY_ATTEMPTS - 1)
                        await asyncio.sleep(delay)
                        continue
                    raise QwenError("通义千问限流或服务异常，已重试 2 次仍失败")
                if status >= 400:
                    raise QwenError(f"通义千问调用失败（HTTP {status}）")

                try:
                    payload = response.json()
                except ValueError as exc:
                    raise QwenError("通义千问返回了无法解析的响应") from exc
                return _extract_content(payload)
        raise QwenError(last_error)

    async def chat_text(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.5,
        max_tokens: int = 2200,
    ) -> str:
        return await self._post(
            messages,
            model=self.text_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.45,
        max_tokens: int = 2400,
    ) -> Any:
        content = await self.chat_text(
            messages, temperature=temperature, max_tokens=max_tokens
        )
        data = parse_json_loose(content)
        if data is None:
            raise QwenError("通义千问返回内容无法解析为 JSON")
        return data

    async def analyze_image(
        self, image_bytes: bytes, mime: str = "", note: str = ""
    ) -> VisionAnalysis:
        data_url = prepare_image_data_url(image_bytes, mime)
        messages = build_vision_messages(data_url, note)
        data = await self._post(
            messages, model=self.vl_model, temperature=0.2, max_tokens=1400
        )
        parsed = parse_json_loose(data)
        if parsed is None:
            raise QwenError("通义千问视觉解析结果不是合法 JSON")
        return vision_from_dict(parsed)


# ---------------------------------------------------------------- 解析辅助

def vision_from_dict(data: Any) -> VisionAnalysis:
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        raise QwenError("通义千问视觉解析结果格式不正确")
    for key in ("analysis", "vision", "result", "data"):
        nested = data.get(key)
        if isinstance(nested, dict):
            data = nested
            break
    vision = VisionAnalysis(
        category=as_text(data.get("category"), 24),
        colors=as_str_list(data.get("colors"), 4),
        style=as_str_list(data.get("style"), 4),
        material=as_str_list(data.get("material"), 4),
        occasion=as_text(data.get("occasion"), 40),
        body_hints=as_text(data.get("body_hints"), 80),
        summary=as_text(data.get("summary"), 260),
        confidence=min(0.99, max(0.2, _to_float(data.get("confidence"), 0.7))),
    )
    if not (vision.category or vision.colors or vision.style):
        raise QwenError("通义千问视觉解析缺少关键字段")
    return vision


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip().lstrip("#"))
    except (TypeError, ValueError):
        return None


def _clean_recipients(value: Any, agent_id: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text in AGENT_IDS and text != agent_id and text not in result:
            result.append(text)
    return result[:2]


def _score_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("scores", "ratings", "items", "opinions"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _item_product_id(item: dict[str, Any]) -> int | None:
    for key in ("product_id", "productId", "id", "product"):
        if key in item:
            return _to_int(item.get(key))
    return None


def _item_score(item: dict[str, Any]) -> float:
    for key in ("score", "rating", "value"):
        if key in item:
            return clamp_score(item.get(key))
    return 5.0


def _item_reason(item: dict[str, Any], default: str = "综合照片与商品属性给出的判断。") -> str:
    for key in ("reason", "comment", "why", "rationale"):
        text = as_text(item.get(key), 160)
        if text:
            return text
    return default


def opinion_from_data(
    data: Any,
    persona: Persona,
    round_no: int,
    valid_ids: set[int],
) -> AgentOpinion:
    scores: list[AgentScore] = []
    seen: set[int] = set()
    for item in _score_items(data):
        product_id = _item_product_id(item)
        if product_id is None or product_id not in valid_ids or product_id in seen:
            continue
        scores.append(
            AgentScore(product_id, _item_score(item), _item_reason(item))
        )
        seen.add(product_id)
    if not scores:
        raise QwenError("通义千问未返回有效评分")
    payload = data if isinstance(data, dict) else {}
    recipients = _clean_recipients(payload.get("recipients"), persona.id)
    if not recipients:
        recipients = [peer_ids(persona.id)[0]]
    message = as_text(
        payload.get("message_to_peers") or payload.get("message"), 400
    )
    advice = as_text(payload.get("advice") or payload.get("summary"), 300)
    if not message:
        message = advice or f"我从{persona.focus}的角度完成了评分。"
    scores.sort(key=lambda item: item.product_id)
    return AgentOpinion(
        agent=persona.id,
        round=round_no,
        scores=scores,
        advice=advice,
        message_to_peers=message,
        recipients=recipients,
        message_type="opinion",
        role="opinion",
    )


def _best_peer_for(
    product_id: int, peer_scores: dict[str, dict[int, float]], agent_id: str
) -> str:
    best: tuple[str, float] | None = None
    for peer, scores in peer_scores.items():
        if peer == agent_id or product_id not in scores:
            continue
        value = scores[product_id]
        if best is None or value > best[1]:
            best = (peer, value)
    if best is not None:
        return best[0]
    peers = peer_ids(agent_id)
    return peers[0] if peers else "moderator"


def round2_from_data(
    data: Any,
    persona: Persona,
    own: AgentOpinion,
    peer_scores: dict[str, dict[int, float]],
) -> tuple[AgentOpinion, list[Revision]]:
    if isinstance(data, list):
        data = {"revisions": data}
    if not isinstance(data, dict):
        raise QwenError("通义千问第二轮返回格式不正确")

    own_map = own.score_map()
    own_reason = {item.product_id: item.reason for item in own.scores}
    raw_revisions = data.get("revisions") or data.get("revised_scores") or []
    if not isinstance(raw_revisions, list):
        raw_revisions = []
    if not raw_revisions and isinstance(data.get("scores"), list):
        # 容忍模型直接返回更新后的完整评分表
        for item in data["scores"]:
            if not isinstance(item, dict):
                continue
            product_id = _item_product_id(item)
            if product_id is None or product_id not in own_map:
                continue
            if abs(_item_score(item) - own_map[product_id]) >= 0.1:
                raw_revisions.append(
                    {
                        "product_id": product_id,
                        "new_score": _item_score(item),
                        "reason": _item_reason(item, "参考同伴观点后调整。"),
                    }
                )

    revisions: list[Revision] = []
    updated = dict(own_map)
    revision_reason: dict[int, str] = {}
    for item in raw_revisions[:2]:
        if not isinstance(item, dict):
            continue
        product_id = _item_product_id(item)
        if product_id is None or product_id not in own_map:
            continue
        old = own_map[product_id]
        new = clamp_score(item.get("new_score", item.get("score", old)))
        if abs(new - old) < 0.1:
            continue
        to_agent = _clean_recipients([item.get("to_agent")], persona.id)
        to_agent_id = (
            to_agent[0] if to_agent else _best_peer_for(product_id, peer_scores, persona.id)
        )
        reason = as_text(item.get("reason"), 220) or (
            f"参考{agent_name(to_agent_id)}的观点后调整了{persona.focus}判断。"
        )
        revisions.append(
            Revision(
                agent=persona.id,
                product_id=product_id,
                old_score=old,
                new_score=new,
                reason=reason,
                to_agent=to_agent_id,
            )
        )
        updated[product_id] = new
        revision_reason[product_id] = reason

    scores = [
        AgentScore(
            product_id,
            updated[product_id],
            revision_reason.get(product_id) or own_reason.get(product_id, "维持原判。"),
        )
        for product_id in sorted(updated)
    ]

    recipients = _clean_recipients(data.get("recipients"), persona.id)
    for revision in revisions:
        if revision.to_agent not in recipients:
            recipients.append(revision.to_agent)
    recipients = recipients[:2] or [_best_peer_for(min(updated), peer_scores, persona.id)]

    message = as_text(
        data.get("message_to_peers") or data.get("message"), 420
    )
    advice = as_text(data.get("advice") or data.get("summary"), 300)
    if not message:
        if revisions:
            first = revisions[0]
            message = (
                f"回应{agent_name(first.to_agent)}：{first.reason} "
                f"我已将 #{first.product_id} 从 {first.old_score:.1f} 调整到 {first.new_score:.1f} 分。"
            )
        else:
            message = f"我保留原判，并想听听{agent_name(recipients[0])}对整体平衡的看法。"
    if revisions:
        peer_name = agent_name(revisions[0].to_agent)
        if peer_name not in message:
            message = f"{message}（想听{peer_name}的进一步意见。）"
    elif recipients:
        peer_name = agent_name(recipients[0])
        if peer_name not in message:
            message = f"{message}（想听{peer_name}的进一步意见。）"

    opinion = AgentOpinion(
        agent=persona.id,
        round=2,
        scores=scores,
        advice=advice,
        message_to_peers=message,
        recipients=recipients,
        message_type="revision" if revisions else "critique",
        role="critique",
    )
    return opinion, revisions


# ---------------------------------------------------------------- 智能体适配器

class QwenAgentBackend:
    """把 QwenClient 包装成与 MockLLM 相同的智能体接口。"""

    mode = "qwen"

    def __init__(self, client: QwenClient | None = None) -> None:
        self.client = client or QwenClient()

    async def analyze_image(
        self, image_bytes: bytes, mime: str = "", note: str = ""
    ) -> VisionAnalysis:
        return await self.client.analyze_image(image_bytes, mime, note)

    async def round1(self, persona: Persona, ctx: DiscussionContext) -> AgentOpinion:
        payload = await self.client.chat_json(
            build_round1_messages(persona, ctx),
            temperature=0.55,
            max_tokens=2400,
        )
        return opinion_from_data(payload, persona, 1, ctx.candidate_ids)

    async def round2(
        self,
        persona: Persona,
        ctx: DiscussionContext,
        own: AgentOpinion,
        peer_digest: str,
        peer_scores: dict[str, dict[int, float]],
    ) -> tuple[AgentOpinion, list[Revision]]:
        payload = await self.client.chat_json(
            build_round2_messages(persona, ctx, own, peer_digest, peer_scores),
            temperature=0.5,
            max_tokens=2400,
        )
        return round2_from_data(payload, persona, own, peer_scores)


__all__ = [
    "QwenAgentBackend",
    "QwenClient",
    "QwenError",
    "opinion_from_data",
    "parse_json_loose",
    "prepare_image_data_url",
    "qwen_available",
    "round2_from_data",
    "vision_from_dict",
]
