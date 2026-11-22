"""两轮五智能体评议编排。

Round 1：五智能体并行独立评分，完成一个广播一个（SSE 可实时观看）。
Round 2：主持人摘要第一轮观点，五智能体看到彼此评分后交叉讨论，
最多修订 2 个分数，并向具名同伴发言。

编排器只依赖“智能体后端”接口；Qwen 失败时逐智能体降级到 Mock，
并返回结构化 warning，业务层负责推送与落库。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol

from .base import AgentOpinion, AgentScore, DiscussionContext, Revision
from .bus import BusRecord, MessageBus
from .personas import AGENT_IDS, PERSONAS, Persona, agent_name, peer_ids

logger = logging.getLogger("yijian.agents.orchestrator")


class AgentBackend(Protocol):
    mode: str

    async def round1(self, persona: Persona, ctx: DiscussionContext) -> AgentOpinion: ...

    async def round2(
        self,
        persona: Persona,
        ctx: DiscussionContext,
        own: AgentOpinion,
        peer_digest: str,
        peer_scores: dict[str, dict[int, float]],
    ) -> tuple[AgentOpinion, list[Revision]]: ...


def _fill_missing_scores(opinion: AgentOpinion, fallback: AgentOpinion) -> AgentOpinion:
    """Qwen 漏评个别商品时，用 Mock 评分补齐，保证聚合器拿到完整矩阵。"""
    known = {item.product_id for item in opinion.scores}
    for item in fallback.scores:
        if item.product_id not in known:
            opinion.scores.append(
                AgentScore(item.product_id, item.score, "补充参考：结合同伴与商品属性。")
            )
    opinion.scores.sort(key=lambda item: item.product_id)
    return opinion


def _named_recipients(agent_id: str, recipients: list[str]) -> list[str]:
    seen: list[str] = []
    for item in recipients:
        if item in AGENT_IDS and item != agent_id and item not in seen:
            seen.append(item)
    if not seen:
        peers = peer_ids(agent_id)
        if peers:
            seen = [peers[0]]
    return seen[:2]


def _ensure_peer_mention(content: str, recipients: list[str]) -> str:
    if not recipients:
        return content
    peer_name = agent_name(recipients[0])
    if peer_name in content:
        return content
    suffix = f"（想听{peer_name}的进一步意见。）"
    if len(content) + len(suffix) > 500:
        content = content[: 500 - len(suffix)]
    return content + suffix


def _warning_for(persona: Persona, stage: str, exc: Exception) -> dict[str, Any]:
    detail = str(exc).strip()[:80]
    suffix = f"（{detail}）" if detail else ""
    return {
        "code": "qwen_fallback",
        "message": f"{persona.name}调用通义千问失败，已降级为本地 Mock 评分{suffix}",
        "stage": stage,
    }


async def _run_round1_agent(
    persona: Persona,
    backend: AgentBackend,
    fallback: AgentBackend,
    ctx: DiscussionContext,
) -> tuple[Persona, AgentOpinion, dict[str, Any] | None]:
    try:
        opinion = await backend.round1(persona, ctx)
        missing = ctx.candidate_ids - {item.product_id for item in opinion.scores}
        if missing:
            fallback_opinion = await fallback.round1(persona, ctx)
            opinion = _fill_missing_scores(opinion, fallback_opinion)
        return persona, opinion, None
    except Exception as exc:
        if getattr(backend, "mode", "") != "qwen":
            raise
        logger.warning("智能体 %s 第一轮 Qwen 调用失败：%s", persona.id, exc)
        opinion = await fallback.round1(persona, ctx)
        return persona, opinion, _warning_for(persona, "round1", exc)


async def run_round1(
    bus: MessageBus,
    backend: AgentBackend,
    fallback: AgentBackend,
    ctx: DiscussionContext,
) -> AsyncIterator[tuple[BusRecord, AgentOpinion, dict[str, Any] | None]]:
    """并行执行第一轮；按完成顺序产出广播记录。"""
    tasks = [
        asyncio.create_task(_run_round1_agent(persona, backend, fallback, ctx))
        for persona in PERSONAS
    ]
    try:
        for future in asyncio.as_completed(tasks):
            persona, opinion, warning = await future
            recipients = _named_recipients(persona.id, opinion.recipients)
            content = opinion.message_to_peers or opinion.advice or f"我完成了{persona.focus}评分。"
            record = await bus.broadcast(
                round=1,
                agent=persona.id,
                content=content,
                message_type="opinion",
                role="opinion",
                recipients=recipients,
                scores=[item.to_dict() for item in opinion.ordered_scores()],
                payload={"advice": opinion.advice, "focus": persona.focus},
            )
            yield record, opinion, warning
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()


async def _run_round2_agent(
    persona: Persona,
    backend: AgentBackend,
    fallback: AgentBackend,
    ctx: DiscussionContext,
    own: AgentOpinion,
    peer_digest: str,
    peer_scores: dict[str, dict[int, float]],
) -> tuple[Persona, AgentOpinion, list[Revision], dict[str, Any] | None]:
    try:
        opinion, revisions = await backend.round2(
            persona, ctx, own, peer_digest, peer_scores
        )
        return persona, opinion, revisions, None
    except Exception as exc:
        if getattr(backend, "mode", "") != "qwen":
            raise
        logger.warning("智能体 %s 第二轮 Qwen 调用失败：%s", persona.id, exc)
        opinion, revisions = await fallback.round2(
            persona, ctx, own, peer_digest, peer_scores
        )
        return persona, opinion, revisions, _warning_for(persona, "round2", exc)


async def run_round2(
    bus: MessageBus,
    backend: AgentBackend,
    fallback: AgentBackend,
    ctx: DiscussionContext,
    round1_opinions: dict[str, AgentOpinion],
) -> AsyncIterator[tuple[BusRecord, AgentOpinion, list[Revision], dict[str, Any] | None]]:
    """五智能体看到彼此第一轮观点后的交叉讨论与修订。"""
    peer_digest = bus.round1_digest()
    peer_scores = bus.round_scores(1)
    tasks = [
        asyncio.create_task(
            _run_round2_agent(
                persona,
                backend,
                fallback,
                ctx,
                round1_opinions[persona.id],
                peer_digest,
                peer_scores,
            )
        )
        for persona in PERSONAS
    ]
    try:
        for future in asyncio.as_completed(tasks):
            persona, opinion, revisions, warning = await future
            recipients = _named_recipients(
                persona.id,
                list(opinion.recipients) + [item.to_agent for item in revisions],
            )
            content = _ensure_peer_mention(
                opinion.message_to_peers or opinion.advice or "我完成了第二轮讨论。",
                recipients,
            )
            record = await bus.broadcast(
                round=2,
                agent=persona.id,
                content=content,
                message_type="revision" if revisions else "critique",
                role="critique",
                recipients=recipients,
                scores=[item.to_dict() for item in opinion.ordered_scores()],
                payload={
                    "advice": opinion.advice,
                    "revision_product_ids": [item.product_id for item in revisions],
                },
            )
            yield record, opinion, revisions, warning
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
