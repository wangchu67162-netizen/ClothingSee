"""通义千问提示词：视觉解析与两轮圆桌评议。

所有提示词要求模型仅输出 JSON 对象；``llm/qwen.py`` 负责容错解析。
"""
from __future__ import annotations

import json
from typing import Any

from ..agents.base import AgentOpinion, DiscussionContext, as_text
from ..agents.personas import Persona, agent_name

VISION_SYSTEM = (
    "你是衣见 ATELIER 的视觉造型分析师，擅长从一张照片中读出品类、色彩、风格、材质、"
    "场合与身形线索。你只依据画面可见信息推断，语气专业克制，全部使用简体中文。"
)

VISION_USER_TEMPLATE = """请分析这张穿搭/商品照片，输出一个 JSON 对象（不要 Markdown、不要解释），字段如下：
{{
  "category": "最可能的主品类，只能是：外套 / 上装 / 连衣裙 / 下装 / 配饰",
  "colors": ["2-3 个主色，用中文色名，如 墨黑、月白、驼色"],
  "style": ["2-3 个风格关键词，如 极简、通勤、法式、街头、复古、新中式"],
  "material": ["1-3 个可能的材质，如 真丝、羊毛、针织、纯棉"],
  "occasion": "最适配的场合，如 通勤 / 约会 / 晚宴 / 周末漫步",
  "body_hints": "一句身形与比例线索，20 字以内",
  "summary": "两句中文总结这套造型的气质与适配方向",
  "confidence": 0.0 到 1.0 之间的数字
}}
用户补充偏好：{note}
"""

ROUND1_RULES = """
你正在参加一场五智能体圆桌评议，共两轮。第一轮独立打分，不要假设别人怎么想。
评分要求：
1. 对给出的每一件候选商品打分（0-10，一位小数），并给出 20 字以内的中文理由；
2. 理由必须结合照片解析、商品属性与你的关注点，避免空话；
3. 输出严格 JSON，不要 Markdown 代码块，不要额外文字。
"""

ROUND1_TEMPLATE = """照片解析：
{vision}

用户预算：{budget}
用户偏好/场合：{note}

候选商品：
{candidates}

请以「{agent_name}」的身份独立评分，只输出 JSON：
{{
  "scores": [{{"product_id": 1, "score": 8.2, "reason": "中文短理由"}}],
  "advice": "一句面向用户的建议",
  "message_to_peers": "一句对同伴说的话，可点名某位智能体",
  "recipients": ["同伴智能体 id，可选：fashion/art/aesthetics/price/comfort"]
}}
"""

ROUND2_RULES = """
这是第二轮交叉讨论。你已经看到其他四位智能体的第一轮观点。
要求：
1. 明确回应至少一位具名同伴（在 recipients 中写出其 id，并在 message_to_peers 中称呼其名）；
2. 可以修订自己第一轮的评分，但最多修订 2 个商品；也可以坚持原判；
3. 修订必须给出中文理由，并说明受谁的观点影响；
4. 输出严格 JSON，不要 Markdown 代码块，不要额外文字。
"""

ROUND2_TEMPLATE = """照片解析：
{vision}

用户预算：{budget}
用户偏好/场合：{note}

候选商品：
{candidates}

你在第一轮的评分：
{own_scores}

其他智能体的第一轮观点：
{peer_digest}

各智能体第一轮评分明细（JSON）：
{peer_scores}

请以「{agent_name}」的身份参与第二轮讨论，只输出 JSON：
{{
  "revisions": [{{"product_id": 1, "old_score": 7.5, "new_score": 8.2, "reason": "中文理由", "to_agent": "影响你的同伴 id"}}],
  "message_to_peers": "对具名同伴说的话",
  "recipients": ["同伴智能体 id"],
  "advice": "一句面向用户的综合建议"
}}
修订数量 0-2 个；若不修订则 revisions 为空数组。
"""


def _product_digest(product: Any) -> dict[str, Any]:
    comfort = getattr(product, "comfort", {}) or {}
    return {
        "product_id": int(getattr(product, "id", 0)),
        "name": as_text(getattr(product, "name", ""), 40),
        "category": as_text(getattr(product, "category", ""), 16),
        "price": round(float(getattr(product, "price", 0) or 0), 2),
        "original_price": (
            round(float(getattr(product, "original_price", 0) or 0), 2)
            if getattr(product, "original_price", None)
            else None
        ),
        "style_tags": list(getattr(product, "style_tags", []) or [])[:6],
        "colors": list(getattr(product, "colors", []) or [])[:4],
        "fabric": as_text(getattr(product, "fabric", ""), 40),
        "fit": as_text(getattr(product, "fit", ""), 30),
        "occasion": as_text(getattr(product, "occasion", ""), 30),
        "rating": float(getattr(product, "rating", 0) or 0),
        "sales": int(getattr(product, "sales", 0) or 0),
        "comfort": comfort if isinstance(comfort, dict) else {},
    }


def candidate_digest(candidates: list[Any]) -> str:
    """把候选商品压缩为 JSON 文本，控制提示词长度。"""
    rows = [_product_digest(item) for item in candidates]
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


def _vision_digest(ctx: DiscussionContext) -> str:
    vision = ctx.vision
    return json.dumps(vision.model_dump(), ensure_ascii=False, separators=(",", ":"))


def build_vision_messages(image_data_url: str, note: str = "") -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": VISION_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": VISION_USER_TEMPLATE.format(note=note or "无")},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]


def build_round1_messages(persona: Persona, ctx: DiscussionContext) -> list[dict[str, Any]]:
    system = persona.system_prompt + ROUND1_RULES
    user = ROUND1_TEMPLATE.format(
        vision=_vision_digest(ctx),
        budget=f"{ctx.budget:.0f} 元" if ctx.budget else "未指定",
        note=ctx.note or "无",
        candidates=candidate_digest(ctx.candidates),
        agent_name=persona.name,
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_round2_messages(
    persona: Persona,
    ctx: DiscussionContext,
    own: AgentOpinion,
    peer_digest: str,
    peer_scores: dict[str, dict[int, float]],
) -> list[dict[str, Any]]:
    system = persona.system_prompt + ROUND2_RULES
    own_payload = [
        {"product_id": item.product_id, "score": item.score, "reason": item.reason}
        for item in own.ordered_scores()
    ]
    peer_payload = {
        agent_name(agent_id): {f"#{pid}": score for pid, score in scores.items()}
        for agent_id, scores in peer_scores.items()
        if agent_id != persona.id
    }
    user = ROUND2_TEMPLATE.format(
        vision=_vision_digest(ctx),
        budget=f"{ctx.budget:.0f} 元" if ctx.budget else "未指定",
        note=ctx.note or "无",
        candidates=candidate_digest(ctx.candidates),
        own_scores=json.dumps(own_payload, ensure_ascii=False, separators=(",", ":")),
        peer_digest=peer_digest or "（暂无同伴观点）",
        peer_scores=json.dumps(peer_payload, ensure_ascii=False, separators=(",", ":")),
        agent_name=persona.name,
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
