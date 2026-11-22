"""五智能体消息总线：单调递增事件序号、广播、观点摘要。

总线只负责“谁在第几轮对谁说了什么”，不负责持久化与 SSE；
编排器把它产出的 :class:`BusRecord` 交给业务层落库并推送。
"""
from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .base import clamp_score
from .personas import AGENT_IDS, agent_name

logger = logging.getLogger("yijian.agents.bus")

Listener = Callable[["BusRecord"], Awaitable[None] | None]


@dataclass(slots=True)
class BusRecord:
    """一条已广播的智能体消息。``seq`` 在单个会话内从 1 单调递增。"""

    seq: int
    round: int
    agent: str
    content: str
    message_type: str = "opinion"
    role: str = "opinion"
    recipients: list[str] = field(default_factory=list)
    scores: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "round": self.round,
            "agent": self.agent,
            "content": self.content,
            "message_type": self.message_type,
            "role": self.role,
            "recipients": list(self.recipients),
            "scores": list(self.scores),
            "payload": self.payload,
        }


class MessageBus:
    """会话级消息总线。"""

    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id
        self._seq = 0
        self.records: list[BusRecord] = []
        self._listeners: list[Listener] = []

    @property
    def seq(self) -> int:
        return self._seq

    def subscribe(self, listener: Listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def broadcast(
        self,
        *,
        round: int,
        agent: str,
        content: str,
        message_type: str = "opinion",
        role: str = "opinion",
        recipients: list[str] | None = None,
        scores: list[dict[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> BusRecord:
        """分配下一个序号并广播给监听者。"""
        self._seq += 1
        record = BusRecord(
            seq=self._seq,
            round=int(round),
            agent=str(agent),
            content=content or "",
            message_type=message_type,
            role=role,
            recipients=[str(item) for item in (recipients or []) if item],
            scores=list(scores or []),
            payload=payload,
        )
        self.records.append(record)
        for listener in list(self._listeners):
            try:
                result = listener(record)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # pragma: no cover - 监听者不应影响主流程
                logger.exception("消息总线监听者执行失败")
        return record

    def records_for_round(self, round_no: int) -> list[BusRecord]:
        return [item for item in self.records if item.round == int(round_no)]

    def round_scores(self, round_no: int) -> dict[str, dict[int, float]]:
        """汇总某一轮各智能体的评分：``{agent: {product_id: score}}``。"""
        result: dict[str, dict[int, float]] = {}
        for record in self.records_for_round(round_no):
            if record.agent not in AGENT_IDS:
                continue
            bucket = result.setdefault(record.agent, {})
            for item in record.scores:
                try:
                    product_id = int(item.get("product_id"))
                    bucket[product_id] = clamp_score(item.get("score"))
                except (TypeError, ValueError, AttributeError):
                    continue
        return result

    def round1_digest(self, limit: int = 90) -> str:
        """生成给 Round 2 的同伴观点摘要（中文，含具名智能体）。"""
        parts: list[str] = []
        for record in self.records_for_round(1):
            if record.agent not in AGENT_IDS:
                continue
            ranked = sorted(
                record.scores,
                key=lambda item: float(item.get("score") or 0),
                reverse=True,
            )[:2]
            chips = "、".join(
                f"#{int(item.get('product_id'))} {clamp_score(item.get('score')):.1f}分"
                for item in ranked
                if item.get("product_id") is not None
            )
            summary = (record.content or "").replace("\n", " ").strip()
            if len(summary) > limit:
                summary = summary[: limit - 1].rstrip() + "…"
            parts.append(f"{agent_name(record.agent)}（{chips}）：{summary}")
        return "\n".join(parts)
