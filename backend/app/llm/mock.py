"""确定性 Mock 大模型：无 Key 时驱动完整五智能体链路。

所有评分与话术均由 ``image sha256 + 商品 id + 智能体 id`` 派生，
同一张图片、同一份商品库下结果稳定可复现；五个智能体使用不同公式，
并附带 100–300ms 的异步延迟，方便前端观察 SSE 节奏。
"""
from __future__ import annotations

import asyncio
import hashlib
import random
from typing import Any

from ..agents.base import (
    AgentOpinion,
    AgentScore,
    DiscussionContext,
    Revision,
    as_text,
    clamp_score,
)
from ..agents.personas import Persona, agent_name, peer_ids
from ..schemas import VisionAnalysis

# ---------------------------------------------------------------- 词表

_CATEGORY_POOL = ["外套", "上装", "连衣裙", "下装"]
_COLOR_POOL = [
    "墨黑",
    "月白",
    "雾灰",
    "香槟金",
    "苔藓绿",
    "沙丘蓝",
    "绛红",
    "驼色",
    "青瓷",
    "奶咖",
]
_STYLE_POOL = ["极简", "通勤", "法式", "街头", "复古", "文艺", "新中式", "休闲", "晚宴", "廓形"]
_MATERIAL_POOL = ["真丝", "羊毛", "针织", "纯棉", "缎面", "羊绒"]
_OCCASION_POOL = ["通勤", "约会", "晚宴", "周末漫步", "校园日常"]
_BODY_POOL = [
    "肩颈线条清晰，适合利落领口与收腰版型",
    "身形修长，适合高腰线与纵向廓形",
    "骨架偏小，适合有结构感的短款外套",
    "肤色偏暖，香槟金与驼色会更衬气色",
    "比例匀称，A 字与直筒版型都能驾驭",
]
_NOTE_OCCASIONS = ("通勤", "约会", "晚宴", "休闲", "校园", "度假", "运动")

_TREND_TAGS = {
    "通勤",
    "廓形",
    "叠穿",
    "极简",
    "法式",
    "街头",
    "复古",
    "新中式",
    "休闲",
    "当季",
}
_TEXTURE_TAGS = {
    "真丝",
    "缎面",
    "针织",
    "提花",
    "百褶",
    "牛仔",
    "皮革",
    "金属感",
    "羊绒",
    "羊毛",
}
_GOOD_FABRICS = ("棉", "真丝", "羊绒", "羊毛", "莫代尔", "醋酸")
_HARSH_FABRICS = ("聚酯", "腈纶", "仿羊皮", "锦纶")

_COLOR_FAMILY: dict[str, str] = {
    "墨黑": "neutral-dark",
    "砚石黑": "neutral-dark",
    "夜幕黑": "neutral-dark",
    "月白": "neutral-light",
    "初雪白": "neutral-light",
    "燕麦": "neutral-light",
    "燕麦白": "neutral-light",
    "奶咖": "neutral-light",
    "米白": "neutral-light",
    "雾灰": "neutral-mid",
    "山岚灰": "neutral-mid",
    "流云灰": "neutral-mid",
    "做旧灰": "neutral-mid",
    "香槟金": "warm-gold",
    "琥珀": "warm-gold",
    "琥珀金": "warm-gold",
    "香槟": "warm-gold",
    "驼色": "warm-gold",
    "苔藓绿": "green",
    "苔绿": "green",
    "青瓷": "green",
    "沙丘蓝": "blue",
    "雾霾蓝": "blue",
    "星夜蓝": "blue",
    "黛青": "blue",
    "绛红": "red",
    "酒红": "red",
    "烟粉": "pink",
    "透明": "neutral-light",
}

_NEUTRAL_FAMILIES = {"neutral-dark", "neutral-light", "neutral-mid"}

_PEER_FOCUS = {
    "fashion": "art",
    "art": "aesthetics",
    "aesthetics": "fashion",
    "price": "fashion",
    "comfort": "aesthetics",
}


# ---------------------------------------------------------------- 工具

def _as_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _family(color: str) -> str:
    return _COLOR_FAMILY.get(color, "unknown")


def _color_affinity(a: str, b: str) -> float:
    fa, fb = _family(a), _family(b)
    if fa == "unknown" or fb == "unknown":
        return 0.6
    if fa == fb:
        return 1.0
    if fa in _NEUTRAL_FAMILIES or fb in _NEUTRAL_FAMILIES:
        return 0.86
    pair = frozenset((fa, fb))
    if pair in (frozenset(("warm-gold", "green")), frozenset(("warm-gold", "red")),
                frozenset(("blue", "warm-gold")), frozenset(("pink", "warm-gold"))):
        return 0.8
    if pair in (frozenset(("green", "blue")), frozenset(("red", "pink")),
                frozenset(("blue", "red"))):
        return 0.66
    return 0.45


def _color_harmony(product_colors: list[str], vision_colors: list[str]) -> float:
    if not product_colors or not vision_colors:
        return 0.55
    total = 0.0
    for color in product_colors:
        total += max(_color_affinity(color, target) for target in vision_colors)
    return min(1.0, total / len(product_colors))


def _style_hits(product: Any, vision: VisionAnalysis) -> list[str]:
    tags = set(_as_list(getattr(product, "style_tags", [])))
    wanted = set(vision.style) | {vision.category}
    hits = sorted(tags & wanted)
    return hits


def _occasion_hit(product: Any, vision: VisionAnalysis) -> bool:
    occasion = as_text(getattr(product, "occasion", ""), 60)
    if not occasion or not vision.occasion:
        return False
    for token in (vision.occasion, *vision.occasion.split("/")):
        token = token.strip()
        if token and token in occasion:
            return True
    return False


def _top_product(candidates: list[Any], score_map: dict[int, float]) -> Any:
    best_id = max(score_map, key=lambda pid: score_map[pid])
    for item in candidates:
        if int(getattr(item, "id")) == best_id:
            return item
    return candidates[0]


class MockLLM:
    """实现与 Qwen 适配层相同的 round1/round2/vision 接口。"""

    mode = "mock"

    def __init__(self, image_bytes: bytes, salt: str = "") -> None:
        self.image_hash = hashlib.sha256(image_bytes or b"").hexdigest()
        self.salt = salt

    # ------------------------------------------------------------ 基础
    def _rng(self, *parts: Any) -> random.Random:
        material = "|".join([self.image_hash, self.salt, *[str(part) for part in parts]])
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return random.Random(int(digest[:16], 16))

    async def _delay(self, *parts: Any) -> None:
        rng = self._rng("delay", *parts)
        await asyncio.sleep(rng.uniform(0.1, 0.3))

    # ------------------------------------------------------------ 视觉
    def vision_analysis(self, note: str = "") -> VisionAnalysis:
        rng = self._rng("vision")
        category = rng.choice(_CATEGORY_POOL)
        colors = rng.sample(_COLOR_POOL, k=rng.choice([2, 2, 3]))
        styles = rng.sample(_STYLE_POOL, k=rng.choice([2, 2, 3]))
        materials = rng.sample(_MATERIAL_POOL, k=rng.choice([1, 2]))
        occasion = rng.choice(_OCCASION_POOL)
        if note:
            for token in _NOTE_OCCASIONS:
                if token in note:
                    occasion = token
                    break
        body = rng.choice(_BODY_POOL)
        summary = (
            f"照片中的造型偏{occasion}的{styles[0]}气质，主色是{'、'.join(colors)}，"
            f"材质看起来像{materials[0]}。建议以{category}为锚点延展整套搭配。"
        )
        if note:
            summary += f" 你提到「{as_text(note, 40)}」，我会在选款时优先考虑。"
        return VisionAnalysis(
            category=category,
            colors=colors,
            style=styles,
            material=materials,
            occasion=occasion,
            body_hints=body,
            summary=summary,
            confidence=round(rng.uniform(0.62, 0.86), 2),
        )

    # ------------------------------------------------------------ 评分公式
    def score_product(
        self,
        agent_id: str,
        product: Any,
        vision: VisionAnalysis,
        budget: float | None = None,
        note: str = "",
    ) -> tuple[float, str]:
        if agent_id == "fashion":
            return self._score_fashion(product, vision)
        if agent_id == "art":
            return self._score_art(product, vision)
        if agent_id == "aesthetics":
            return self._score_aesthetics(product, vision)
        if agent_id == "price":
            return self._score_price(product, vision, budget)
        if agent_id == "comfort":
            return self._score_comfort(product, vision)
        raise KeyError(agent_id)

    def _score_fashion(self, product: Any, vision: VisionAnalysis) -> tuple[float, str]:
        rng = self._rng("score", "fashion", getattr(product, "id", 0))
        noise = rng.uniform(-0.5, 0.5)
        hits = _style_hits(product, vision)
        tags = set(_as_list(getattr(product, "style_tags", [])))
        trend_hits = len(tags & _TREND_TAGS)
        score = 4.3 + min(2.8, len(hits) * 0.95) + min(1.4, trend_hits * 0.45)
        if _occasion_hit(product, vision):
            score += 0.9
        if as_text(getattr(product, "category", "")) == vision.category:
            score += 0.55
        score = clamp_score(score + noise)
        hit_text = "、".join(hits[:2]) or "基础廓形"
        reason = (
            f"「{as_text(getattr(product, 'name', ''), 20)}」的{hit_text}与照片的"
            f"{vision.style[0] if vision.style else '克制'}气质同频，"
            f"{vision.occasion or '日常'}场景完成度不错。"
        )
        return score, reason

    def _score_art(self, product: Any, vision: VisionAnalysis) -> tuple[float, str]:
        rng = self._rng("score", "art", getattr(product, "id", 0))
        noise = rng.uniform(-0.55, 0.55)
        harmony = _color_harmony(_as_list(getattr(product, "colors", [])), vision.colors)
        tags = set(_as_list(getattr(product, "style_tags", [])))
        texture_hits = len(tags & _TEXTURE_TAGS)
        score = clamp_score(3.8 + harmony * 3.7 + min(1.4, texture_hits * 0.5) + noise * 0.8)
        fabric = as_text(getattr(product, "fabric", ""), 24) or "面料"
        reason = (
            f"色盘与照片的{'、'.join(vision.colors[:2]) or '低饱和色'}形成约 {harmony * 100:.0f}% 的和谐度，"
            f"{fabric}的肌理让画面更有层次。"
        )
        return score, reason

    def _score_aesthetics(self, product: Any, vision: VisionAnalysis) -> tuple[float, str]:
        rng = self._rng("score", "aesthetics", getattr(product, "id", 0))
        noise = rng.uniform(-0.45, 0.45)
        colors = _as_list(getattr(product, "colors", []))
        neutral = any(_family(color) in _NEUTRAL_FAMILIES for color in colors)
        rating = _num(getattr(product, "rating", 4.7), 4.7)
        featured = bool(getattr(product, "featured", False))
        fit = as_text(getattr(product, "fit", ""), 24)
        proportion = 0.55 if any(word in fit for word in ("高腰", "短款", "收腰", "直筒", "A 字")) else 0.0
        score = clamp_score(
            4.4 + (0.5 if neutral else 0) + (rating - 4.5) * 1.1 + (0.35 if featured else 0) + proportion + noise
        )
        reason = (
            f"{fit or '利落'}版型对比例友好，{'、'.join(colors[:2]) or '低饱和色'}的配色克制，"
            f"整体有留白的高级感。"
        )
        return score, reason

    def _score_price(
        self, product: Any, vision: VisionAnalysis, budget: float | None
    ) -> tuple[float, str]:
        rng = self._rng("score", "price", getattr(product, "id", 0))
        noise = rng.uniform(-0.4, 0.4)
        price = _num(getattr(product, "price", 0), 0)
        original = _num(getattr(product, "original_price", 0) or 0, 0)
        discount = max(0.0, original - price) / original if original > price else 0.0
        if budget and budget > 0:
            ratio = price / budget
            if ratio <= 1:
                base = 7.7 + (1 - ratio) * 1.4
            else:
                base = max(2.2, 8.0 - (ratio - 1) * 5.5)
            budget_text = f"售价 {price:.0f} 元，占 {budget:.0f} 元预算的 {ratio * 100:.0f}%"
        else:
            if price <= 359:
                base = 8.1
            elif price <= 599:
                base = 7.8
            elif price <= 899:
                base = 7.4
            elif price <= 1299:
                base = 6.9
            else:
                base = 6.3
            budget_text = f"售价 {price:.0f} 元，处于同类的中高价格带"
        score = clamp_score(base + min(1.0, discount * 2.8) + (_num(getattr(product, "rating", 4.7), 4.7) - 4.5) * 0.4 + noise)
        discount_text = f"，较原价优惠 {discount * 100:.0f}%" if discount > 0.01 else ""
        reason = f"{budget_text}{discount_text}，按穿着频次折算性价比合理。"
        return score, reason

    def _score_comfort(self, product: Any, vision: VisionAnalysis) -> tuple[float, str]:
        rng = self._rng("score", "comfort", getattr(product, "id", 0))
        noise = rng.uniform(-0.4, 0.4)
        comfort = getattr(product, "comfort", {}) or {}
        if not isinstance(comfort, dict):
            comfort = {}
        breath = _num(comfort.get("breathability"), 6)
        soft = _num(comfort.get("softness"), 6)
        stretch = _num(comfort.get("stretch"), 4)
        warmth = _num(comfort.get("warmth"), 5)
        fabric = as_text(getattr(product, "fabric", ""), 40)
        care = as_text(comfort.get("care", ""), 30)
        score = 3.6 + (breath + soft + stretch) / 30 * 4.0 + warmth * 0.06
        if any(word in fabric for word in _GOOD_FABRICS):
            score += 0.65
        if any(word in fabric for word in _HARSH_FABRICS):
            score -= 0.7
        if "专业干洗" in care:
            score -= 0.65
        elif "干洗" in care:
            score -= 0.3
        score = clamp_score(score + noise)
        care_text = f"需要{care}" if care else "日常好打理"
        reason = (
            f"{fabric or '面料'}触感柔和，透气 {breath:.0f}/10、柔软 {soft:.0f}/10，"
            f"{care_text}，久穿负担小。"
        )
        return score, reason

    # ------------------------------------------------------------ 第一轮
    async def round1(self, persona: Persona, ctx: DiscussionContext) -> AgentOpinion:
        await self._delay(persona.id, "round1")
        scores: list[AgentScore] = []
        for product in ctx.candidates:
            value, reason = self.score_product(
                persona.id, product, ctx.vision, ctx.budget, ctx.note
            )
            scores.append(AgentScore(int(getattr(product, "id")), value, reason))
        scores.sort(key=lambda item: item.product_id)

        ranked = sorted(scores, key=lambda item: item.score, reverse=True)
        top = self._find_product(ctx.candidates, ranked[0].product_id) if ranked else None
        peer = _PEER_FOCUS.get(persona.id, peer_ids(persona.id)[0])
        peer_name = agent_name(peer)
        top_name = as_text(getattr(top, "name", ""), 24) if top else "候选单品"
        templates = {
            "fashion": (
                f"我先把廓形与场合定调：「{top_name}」最接近照片的"
                f"{ctx.vision.occasion or '日常'}气质。{peer_name}，帮我看看色彩呼应是否成立？"
            ),
            "art": (
                f"从色彩关系看，「{top_name}」的色盘与照片主色最默契。"
                f"{peer_name}，你觉得整体视觉重量平衡吗？"
            ),
            "aesthetics": (
                f"整体比例上我倾向「{top_name}」，{as_text(getattr(top, 'fit', ''), 16) or '利落版型'}"
                f"能把身形拉得干净。{peer_name}，版型与场合是否匹配？"
            ),
            "price": (
                f"我先看预算：按当前预算，「{top_name}」的价格带最合理。"
                f"{peer_name}，如果预算还能再分配，你会把预算留给哪一件？"
            ),
            "comfort": (
                f"从穿着体验看，「{top_name}」的{as_text(getattr(top, 'fabric', ''), 18) or '面料'}"
                f"最亲肤。{peer_name}，这套长时间穿会不会显重？"
            ),
        }
        content = templates.get(persona.id, f"我完成了{persona.focus}评分。")
        advice = f"如果只选一件，我会把「{top_name}」放进购物袋。"
        return AgentOpinion(
            agent=persona.id,
            round=1,
            scores=scores,
            advice=advice,
            message_to_peers=content,
            recipients=[peer],
            message_type="opinion",
            role="opinion",
        )

    # ------------------------------------------------------------ 第二轮
    async def round2(
        self,
        persona: Persona,
        ctx: DiscussionContext,
        own: AgentOpinion,
        peer_digest: str,
        peer_scores: dict[str, dict[int, float]],
    ) -> tuple[AgentOpinion, list[Revision]]:
        await self._delay(persona.id, "round2")
        own_map = own.score_map()
        by_id = ctx.product_by_id
        reason_map = {item.product_id: item.reason for item in own.scores}
        pairs_by_product: dict[int, list[tuple[str, float]]] = {}
        for pid, old in own_map.items():
            pairs = [
                (agent_id, scores[pid])
                for agent_id, scores in peer_scores.items()
                if agent_id != persona.id and pid in scores
            ]
            if pairs:
                pairs_by_product[pid] = pairs

        gaps: list[tuple[float, int, float, list[tuple[str, float]]]] = []
        for pid, old in own_map.items():
            pairs = pairs_by_product.get(pid)
            if not pairs:
                continue
            average = sum(value for _, value in pairs) / len(pairs)
            gaps.append((abs(average - old), pid, average, pairs))
        gaps.sort(key=lambda item: item[0], reverse=True)

        revisions: list[Revision] = []
        updated = dict(own_map)
        revision_reasons: dict[int, str] = {}
        for _, pid, average, pairs in gaps[:2]:
            product = by_id.get(pid)
            if product is None:
                continue
            old = own_map[pid]
            delta = max(-1.5, min(1.5, (average - old) * 0.55))
            if abs(delta) < 0.2:
                delta = 0.3 if average >= old else -0.3
            new = clamp_score(old + delta)
            if abs(new - old) < 0.1:
                new = clamp_score(old + (0.4 if average >= old else -0.4))
            if abs(new - old) < 0.1:
                continue
            to_agent = max(pairs, key=lambda item: item[1])[0]
            direction = "上调" if new > old else "下调"
            reason = (
                f"参照{agent_name(to_agent)}对「{as_text(getattr(product, 'name', ''), 18)}」的"
                f"{max(value for _, value in pairs):.1f}分，我重新权衡{persona.focus}后{direction}了判断。"
            )
            revisions.append(
                Revision(
                    agent=persona.id,
                    product_id=pid,
                    old_score=old,
                    new_score=new,
                    reason=reason,
                    to_agent=to_agent,
                )
            )
            updated[pid] = new
            revision_reasons[pid] = reason

        if not revisions and updated:
            # 演示契约：Mock 模式必须出现至少一次真实修订。
            pid = min(updated)
            old = updated[pid]
            direction = 1 if old < 9.8 else -1
            new = clamp_score(old + 0.3 * direction)
            if new == old:
                new = clamp_score(old - 0.3)
            if new != old:
                candidates_peer = pairs_by_product.get(pid) or []
                to_agent = (
                    max(candidates_peer, key=lambda item: item[1])[0]
                    if candidates_peer
                    else peer_ids(persona.id)[0]
                )
                product = by_id.get(pid)
                reason = (
                    f"为了让圆桌结论更聚焦，我参考{agent_name(to_agent)}的整体判断，"
                    f"对「{as_text(getattr(product, 'name', ''), 18)}」做了小幅修订。"
                )
                revisions.append(
                    Revision(
                        agent=persona.id,
                        product_id=pid,
                        old_score=old,
                        new_score=new,
                        reason=reason,
                        to_agent=to_agent,
                    )
                )
                updated[pid] = new
                revision_reasons[pid] = reason

        scores = [
            AgentScore(pid, updated[pid], revision_reasons.get(pid, reason_map.get(pid, "维持原判。")))
            for pid in sorted(updated)
        ]
        top = _top_product(ctx.candidates, updated) if updated else ctx.candidates[0]
        top_name = as_text(getattr(top, "name", ""), 24) if top is not None else "候选单品"
        recipients = [item.to_agent for item in revisions][:2]
        if not recipients:
            recipients = list(own.recipients[:1]) or [peer_ids(persona.id)[0]]
        if revisions:
            first = revisions[0]
            peer_name = agent_name(first.to_agent)
            product = by_id.get(first.product_id)
            content = (
                f"回应{peer_name}：{first.reason} 我已把「{as_text(getattr(product, 'name', ''), 18)}」"
                f"从 {first.old_score:.1f} 调整到 {first.new_score:.1f} 分。"
                f"整组看，「{top_name}」仍是我想推荐的核心。"
            )
            message_type = "revision"
        else:
            peer_name = agent_name(recipients[0])
            content = (
                f"我保留原判，并认同{peer_name}对整体平衡的关注；"
                f"「{top_name}」依旧是我心里的第一顺位。"
            )
            message_type = "critique"
        advice = f"综合同伴意见后，「{top_name}」与照片气质最契合。"
        opinion = AgentOpinion(
            agent=persona.id,
            round=2,
            scores=scores,
            advice=advice,
            message_to_peers=content,
            recipients=recipients,
            message_type=message_type,
            role="critique",
        )
        return opinion, revisions

    # ------------------------------------------------------------ 辅助
    @staticmethod
    def _find_product(candidates: list[Any], product_id: int) -> Any | None:
        for item in candidates:
            if int(getattr(item, "id")) == int(product_id):
                return item
        return None


__all__ = ["MockLLM"]
