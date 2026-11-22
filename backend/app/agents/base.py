"""与具体大模型无关的五智能体数据结构。

智能体之间只交换这些轻量结构；LLM 适配层负责把模型输出转换为它们，
聚合器只依赖 ``AgentOpinion`` / ``Revision``，不感知 Qwen 或 Mock。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..schemas import VisionAnalysis


def clamp_score(value: Any, default: float = 5.0) -> float:
    """把任意输入收敛到 0-10 之间的一位小数评分。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return round(min(10.0, max(0.0, number)), 1)


def as_text(value: Any, limit: int = 240) -> str:
    """安全截断为中文可读文本。"""
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def as_str_list(value: Any, limit: int = 6) -> list[str]:
    """把模型返回的字符串/数组统一成去重字符串列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in value:
        text = as_text(item, 60)
        if text and text not in result:
            result.append(text)
    return result[:limit]


@dataclass(slots=True)
class AgentScore:
    product_id: int
    score: float
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": int(self.product_id),
            "score": clamp_score(self.score),
            "reason": self.reason,
        }


@dataclass(slots=True)
class AgentOpinion:
    """某一轮中单个智能体的完整观点。"""

    agent: str
    round: int
    scores: list[AgentScore] = field(default_factory=list)
    advice: str = ""
    message_to_peers: str = ""
    recipients: list[str] = field(default_factory=list)
    message_type: str = "opinion"
    role: str = "opinion"

    def score_map(self) -> dict[int, float]:
        return {int(item.product_id): clamp_score(item.score) for item in self.scores}

    def ordered_scores(self) -> list[AgentScore]:
        return sorted(self.scores, key=lambda item: int(item.product_id))

    def to_payload(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "round": self.round,
            "scores": [item.to_dict() for item in self.ordered_scores()],
            "advice": self.advice,
            "message_to_peers": self.message_to_peers,
            "recipients": list(self.recipients),
            "message_type": self.message_type,
        }


@dataclass(slots=True)
class Revision:
    """Round 2 中一次可追溯的分数修订。"""

    agent: str
    product_id: int
    old_score: float
    new_score: float
    reason: str
    to_agent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "product_id": int(self.product_id),
            "old_score": clamp_score(self.old_score),
            "new_score": clamp_score(self.new_score),
            "reason": self.reason,
            "to_agent": self.to_agent,
        }


@dataclass(slots=True)
class DiscussionContext:
    """一次圆桌评议共享的上下文（照片解析 + 候选商品 + 用户约束）。"""

    vision: VisionAnalysis
    candidates: list[Any] = field(default_factory=list)
    budget: float | None = None
    note: str = ""

    @property
    def candidate_ids(self) -> set[int]:
        return {int(getattr(item, "id")) for item in self.candidates}

    @property
    def product_by_id(self) -> dict[int, Any]:
        return {int(getattr(item, "id")): item for item in self.candidates}
