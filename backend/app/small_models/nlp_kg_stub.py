"""NLP / 知识图谱小模型 Stub（REPLACEABLE BASELINE）。

纯规则 + 中文词典，不依赖任何远程服务：

* 从中文文本抽取品类 / 颜色 / 材质 / 风格 / 场景 / 尺码；
* 消费视觉 embedding，用切比雪夫距离给每个商品连 Top-3 ``similar_to`` 边；
* 生成“商品 → 品类/颜色/材质/风格/场景”属性边；
* 补“上装 ↔ 下装”``pairs_with`` 搭配边，供整套推荐使用；
* 支持查询扩展、邻域扩展、三元组与邻居查询。

接入自训练模型见 docs/small-model-interface.md。
"""
from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

import numpy as np

from ..config import settings
from .base import NLPKGModel
from .metrics import chebyshev_distance, chebyshev_similarity
from .text_embedding import get_text_embedder, product_text

logger = logging.getLogger("yijian.small_models.nlp_kg")

# ------------------------------------------------------------------ 中文词典
CATEGORY_TERMS: "OrderedDict[str, str]" = OrderedDict(
    [
        ("风衣", "外套"),
        ("大衣", "外套"),
        ("夹克", "外套"),
        ("羽绒服", "外套"),
        ("西装外套", "外套"),
        ("外套", "外套"),
        ("衬衫", "上装"),
        ("针织衫", "上装"),
        ("毛衣", "上装"),
        ("卫衣", "上装"),
        ("开衫", "上装"),
        ("T恤", "上装"),
        ("吊带", "上装"),
        ("上装", "上装"),
        ("连衣裙", "连衣裙"),
        ("旗袍", "连衣裙"),
        ("长裙", "连衣裙"),
        ("包臀裙", "连衣裙"),
        ("裙装", "连衣裙"),
        ("百褶裙", "下装"),
        ("半裙", "下装"),
        ("牛仔裤", "下装"),
        ("阔腿裤", "下装"),
        ("直筒裤", "下装"),
        ("西裤", "下装"),
        ("裤装", "下装"),
        ("下装", "下装"),
        ("方巾", "配饰"),
        ("丝巾", "配饰"),
        ("耳饰", "配饰"),
        ("项链", "配饰"),
        ("手拿包", "配饰"),
        ("包袋", "配饰"),
        ("配饰", "配饰"),
    ]
)

COLOR_TERMS: list[str] = [
    "雾霾蓝", "初雪白", "香槟金", "曜石黑", "夜幕黑", "砚石黑", "山岚灰",
    "流云灰", "沙丘蓝", "做旧灰", "苔藓绿", "星夜蓝", "琥珀金", "燕麦白",
    "雾灰", "燕麦", "驼色", "月白", "黛青", "烟粉", "苔绿", "奶咖", "酒红",
    "绛红", "青瓷", "米白", "香槟", "琥珀", "墨黑", "透明", "黑", "白", "红",
    "蓝", "灰", "金", "绿", "粉", "紫", "棕", "米", "银", "青",
]

MATERIAL_TERMS: list[str] = [
    "精纺羊毛", "美利奴羊毛", "桑蚕丝", "精梳棉", "新疆长绒棉", "醋酸纤维",
    "头层牛皮", "黄铜镀金", "羊绒", "真丝", "羊毛", "丹宁", "牛仔", "醋酸",
    "缎面", "提花", "针织", "皮革", "牛皮", "麂皮", "聚酯纤维", "聚酯", "粘胶",
    "氨纶", "锦纶", "腈纶", "树脂", "黄铜", "纯棉", "棉",
]

STYLE_TERMS: list[str] = [
    "新中式", "高级感", "极简", "法式", "街头", "复古", "文艺", "通勤",
    "经典", "休闲", "高端", "优雅", "性感", "温柔", "甜酷", "减龄", "百搭",
    "廓形", "垂坠", "叠穿", "轻盈", "金属感", "书卷气", "松弛", "利落", "克制",
]

OCCASION_TERMS: list[str] = [
    "夜间出行", "城市漫步", "文化场合", "正式场合", "商务", "通勤", "约会",
    "晚宴", "休闲", "校园", "婚礼", "宴会", "咖啡馆", "周末", "送礼", "日常",
    "聚会", "派对", "度假", "旅行",
]

SIZE_PATTERN = re.compile(r"(?<![A-Za-z])(XXL|XL|XS|S|M|L)(?![A-Za-z])")

QUERY_EXPANSIONS: dict[str, list[str]] = {
    "风衣": ["外套", "通勤", "秋冬", "廓形"],
    "大衣": ["外套", "羊毛", "羊绒", "秋冬", "通勤"],
    "夹克": ["外套", "街头", "春秋"],
    "衬衫": ["上装", "真丝", "通勤", "法式"],
    "针织": ["上装", "羊毛", "叠穿", "秋冬"],
    "卫衣": ["上装", "休闲", "校园", "纯棉"],
    "裙": ["连衣裙", "下装", "约会", "温柔"],
    "裙装": ["连衣裙", "下装", "约会", "温柔"],
    "裤": ["下装", "通勤", "休闲"],
    "牛仔": ["下装", "休闲", "复古", "丹宁"],
    "配饰": ["方巾", "耳饰", "包袋", "点睛"],
    "上班": ["通勤", "商务", "极简"],
    "工作": ["通勤", "商务", "正式场合"],
    "面试": ["通勤", "商务", "正式场合", "克制"],
    "约会": ["温柔", "性感", "约会", "晚宴"],
    "晚装": ["晚宴", "缎面", "性感", "配饰"],
    "聚会": ["派对", "晚宴", "街头"],
    "婚礼": ["宴会", "新中式", "真丝", "优雅"],
    "显瘦": ["高腰", "垂坠", "廓形", "下装"],
    "显白": ["绛红", "酒红", "月白"],
    "保暖": ["羊毛", "羊绒", "针织", "秋冬"],
    "夏天": ["真丝", "四季", "轻盈"],
    "冬天": ["羊绒", "羊毛", "大衣", "秋冬"],
}

_MATERIAL_FROM_FABRIC = MATERIAL_TERMS
_CATEGORY_NORMALIZE = {"裙装": "连衣裙", "裤装": "下装"}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item) for item in value)
    return str(value)


def _field(product: Any, key: str, default: Any = "") -> Any:
    """同时兼容 ORM 对象与 dict。"""
    if isinstance(product, dict):
        return product.get(key, default)
    return getattr(product, key, default)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _match_terms(text: str, terms: list[str]) -> list[str]:
    """按词典匹配，长词优先；返回保持词典顺序的命中去重列表。"""
    if not text:
        return []
    lowered = text.lower()
    hits: list[str] = []
    for term in sorted(terms, key=len, reverse=True):
        if term.lower() in lowered:
            hits.append(term)
    # 恢复词典原始顺序，保证确定性
    return _dedupe([term for term in terms if term in hits])


def _match_categories(text: str) -> list[str]:
    if not text:
        return []
    matched: list[str] = []
    for term, category in CATEGORY_TERMS.items():
        if term in text:
            matched.append(category)
    return _dedupe(matched)


def _match_sizes(text: str) -> list[str]:
    if not text:
        return []
    sizes = [match.group(1) for match in SIZE_PATTERN.finditer(text.upper())]
    if "均码" in text:
        sizes.append("均码")
    return _dedupe(sizes)


def extract_attributes(text: str) -> dict[str, list[str]]:
    """纯函数版属性抽取，便于大模型层或测试复用。"""
    text = text or ""
    return {
        "category": _match_categories(text),
        "colors": _match_terms(text, COLOR_TERMS),
        "materials": _match_terms(text, MATERIAL_TERMS),
        "styles": _match_terms(text, STYLE_TERMS),
        "occasions": _match_terms(text, OCCASION_TERMS),
        "sizes": _match_sizes(text),
    }


class NLPKGStub(NLPKGModel):
    """规则 + 词典的 NLP-KG 基线；同时托管内存知识图谱。"""

    name = "yijian-nlp-kg-stub"
    version = "stub-v1"
    backend = "stub"
    similar_top_k = 3
    similar_distance_threshold = 0.65

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self._products: dict[int, dict[str, Any]] = {}
        self._embeddings: dict[int, list[float]] = {}
        self._neighbors: dict[int, list[dict[str, Any]]] = {}
        self.meta: dict[str, Any] = {"product_count": 0, "node_count": 0, "edge_count": 0}
        self.last_error: str | None = None

    # ------------------------------------------------------------------ 抽取
    async def extract(self, text: str) -> dict[str, Any]:
        return self.extract_sync(text)

    def extract_sync(self, text: str) -> dict[str, Any]:
        attributes = extract_attributes(text)
        keywords = _dedupe(
            attributes["category"]
            + attributes["colors"]
            + attributes["materials"]
            + attributes["styles"]
            + attributes["occasions"]
            + attributes["sizes"]
        )
        triples: list[dict[str, str]] = []
        for category in attributes["category"]:
            triples.append({"subject": "查询", "relation": "品类", "object": category})
        for color in attributes["colors"]:
            triples.append({"subject": "查询", "relation": "颜色", "object": color})
        for material in attributes["materials"]:
            triples.append({"subject": "查询", "relation": "材质", "object": material})
        for style in attributes["styles"]:
            triples.append({"subject": "查询", "relation": "风格", "object": style})
        for occasion in attributes["occasions"]:
            triples.append({"subject": "查询", "relation": "场景", "object": occasion})
        for size in attributes["sizes"]:
            triples.append({"subject": "查询", "relation": "尺码", "object": size})
        return {"attributes": attributes, "keywords": keywords, "triples": triples}

    def expand_terms(self, text: str, extraction: dict[str, Any] | None = None) -> list[str]:
        """查询扩展：词典命中 + 同义/场景扩展 + 品类归一。"""
        extraction = extraction or self.extract_sync(text)
        attributes = extraction.get("attributes", {})
        base_terms: list[str] = list(extraction.get("keywords", []))
        if not base_terms and text:
            base_terms = [token for token in re.split(r"[\s，,。.;；]+", text) if token]
        expanded: list[str] = list(base_terms)
        lowered = (text or "").lower()
        for key, values in QUERY_EXPANSIONS.items():
            if key in lowered:
                expanded.extend(values)
        for category in attributes.get("category", []):
            normalized = _CATEGORY_NORMALIZE.get(category, category)
            expanded.append(normalized)
            if normalized == "外套":
                expanded.append("上装")
            if normalized == "连衣裙":
                expanded.extend(["上装", "下装"])
        if "上装" in attributes.get("category", []):
            expanded.append("下装")
        if "下装" in attributes.get("category", []):
            expanded.append("上装")
        return _dedupe([term for term in expanded if term])[:16]

    # ------------------------------------------------------------------ 排序
    async def rank(
        self,
        query_embedding: Sequence[float],
        candidates: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        return self.rank_sync(query_embedding, candidates, top_k)

    def rank_sync(
        self,
        query_embedding: Sequence[float],
        candidates: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for candidate in candidates:
            embedding = candidate.get("embedding") or candidate.get("vector")
            if not embedding or not query_embedding:
                continue
            try:
                distance = chebyshev_distance(query_embedding, embedding)
            except ValueError:
                continue
            matches.append(
                {
                    "product_id": int(candidate.get("product_id")),
                    "distance": round(distance, 6),
                    "similarity": round(chebyshev_similarity(query_embedding, embedding), 6),
                }
            )
        matches.sort(key=lambda item: (item["distance"], item["product_id"]))
        return matches[: max(0, int(top_k))]

    # ------------------------------------------------------------------ 建图
    async def build_graph(
        self,
        products: list[Any],
        embeddings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.build_graph_sync(products, embeddings)

    def build_graph_sync(
        self,
        products: list[Any],
        embeddings: list[dict[str, Any]] | dict[int, list[float]],
    ) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        product_index: dict[int, dict[str, Any]] = {}
        embedding_index = self._normalise_embeddings(embeddings)

        edge_keys: set[tuple[str, str, str]] = set()

        def add_edge(
            source: str,
            target: str,
            relation: str,
            weight: float = 0.0,
            meta: dict[str, Any] | None = None,
        ) -> None:
            key = (source, target, relation)
            if key in edge_keys or source not in nodes or target not in nodes:
                return
            edge_keys.add(key)
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "weight": round(float(weight), 6),
                    "meta": dict(meta or {}),
                }
            )

        def add_attribute_node(kind: str, name: str) -> str:
            node_id = f"{kind}:{name}"
            if node_id not in nodes:
                nodes[node_id] = {
                    "id": node_id,
                    "label": name,
                    "type": kind,
                    "meta": {"kind": kind},
                }
            return node_id

        # 1) 商品 + 属性
        for product in products or []:
            try:
                product_id = int(_field(product, "id"))
            except (TypeError, ValueError):
                continue
            name = _as_text(_field(product, "name")) or f"商品 {product_id}"
            category = _as_text(_field(product, "category"))
            colors = [str(item) for item in (_field(product, "colors", []) or [])]
            sizes = [str(item) for item in (_field(product, "sizes", []) or [])]
            style_tags = [str(item) for item in (_field(product, "style_tags", []) or [])]
            fabric = _as_text(_field(product, "fabric"))
            occasion = _as_text(_field(product, "occasion"))
            season = _as_text(_field(product, "season"))

            materials = _match_terms(fabric, _MATERIAL_FROM_FABRIC)
            styles = _dedupe(style_tags + _match_terms(_as_text(_field(product, "description")), STYLE_TERMS))
            occasions = _match_terms(occasion, OCCASION_TERMS)
            if not occasions and occasion:
                occasions = _dedupe([part.strip() for part in occasion.split("/") if part.strip()])

            product_index[product_id] = {
                "id": product_id,
                "name": name,
                "sku": _as_text(_field(product, "sku")),
                "category": category,
                "price": float(_field(product, "price", 0) or 0),
                "image": _as_text(_field(product, "image")),
                "subtitle": _as_text(_field(product, "subtitle")),
                "colors": colors,
                "materials": materials,
                "styles": styles,
                "occasions": occasions,
                "sizes": sizes,
                "season": season,
            }

            node_id = f"product:{product_id}"
            nodes[node_id] = {
                "id": node_id,
                "label": name,
                "type": "product",
                "meta": {
                    "product_id": product_id,
                    "category": category,
                    "price": product_index[product_id]["price"],
                    "image": product_index[product_id]["image"],
                },
            }
            if category:
                add_edge(node_id, add_attribute_node("category", category), "belongs_to", 1.0)
            for color in colors:
                add_edge(node_id, add_attribute_node("color", color), "has_color", 1.0)
            for material in materials:
                add_edge(node_id, add_attribute_node("material", material), "has_material", 1.0)
            for style in styles:
                add_edge(node_id, add_attribute_node("style", style), "has_style", 1.0)
            for occ in occasions:
                add_edge(node_id, add_attribute_node("occasion", occ), "has_occasion", 0.8)
            for size in sizes:
                add_edge(node_id, add_attribute_node("size", size), "has_size", 0.3)

        # 2) 视觉 Top-3 切比雪夫近邻 → similar_to
        product_ids = sorted(product_index)
        for product_id in product_ids:
            embedding = embedding_index.get(product_id)
            if not embedding:
                continue
            scored: list[tuple[float, int]] = []
            for other_id in product_ids:
                if other_id == product_id:
                    continue
                other_embedding = embedding_index.get(other_id)
                if not other_embedding:
                    continue
                try:
                    distance = chebyshev_distance(embedding, other_embedding)
                except ValueError:
                    continue
                scored.append((distance, other_id))
            scored.sort(key=lambda item: (item[0], item[1]))
            for _distance, other_id in scored[: self.similar_top_k]:
                source, target = sorted((product_id, other_id))
                similarity = chebyshev_similarity(
                    embedding_index[source], embedding_index[target]
                )
                add_edge(
                    f"product:{source}",
                    f"product:{target}",
                    "similar_to",
                    similarity,
                    meta={"method": "visual-chebyshev", "metric": "visual"},
                )

        # 2b) 中文文本语义近邻 → semantic_similar（BGE-small-zh-v1.5）
        semantic_added = 0
        text_info: dict[str, Any] = {
            "enabled": bool(settings.nlp_embedding_enabled),
            "status": "disabled" if not settings.nlp_embedding_enabled else "pending",
        }
        if settings.nlp_embedding_enabled:
            try:
                embedder = get_text_embedder()
                text_info = embedder.info()
                pids = sorted(product_index)
                texts = [product_text(product_index[pid]) for pid in pids]
                vectors = embedder.embed(texts)
                if len(vectors) == len(pids):
                    similarities = vectors @ vectors.T
                    np.fill_diagonal(similarities, -1.0)
                    top_k = max(1, int(settings.nlp_semantic_top_k))
                    threshold = float(settings.nlp_semantic_threshold)
                    for index, pid in enumerate(pids):
                        for neighbor_index in np.argsort(-similarities[index])[:top_k]:
                            other_id = pids[int(neighbor_index)]
                            similarity = float(similarities[index, int(neighbor_index)])
                            if similarity < threshold:
                                continue
                            source, target = sorted((pid, other_id))
                            before = len(edges)
                            add_edge(
                                f"product:{source}",
                                f"product:{target}",
                                "semantic_similar",
                                similarity,
                                meta={
                                    "method": "text-embedding",
                                    "model": embedder.name,
                                    "similarity": round(similarity, 6),
                                },
                            )
                            if len(edges) > before:
                                semantic_added += 1
                    text_info = {
                        **embedder.info(),
                        "status": "ready",
                        "semantic_edges": semantic_added,
                        "top_k": top_k,
                        "threshold": threshold,
                    }
                else:
                    text_info = {
                        **text_info,
                        "status": "dimension-mismatch",
                        "semantic_edges": 0,
                    }
            except Exception as exc:  # noqa: BLE001 - graph still works without it
                logger.warning("文本语义边构建失败：%s", exc)
                text_info = {
                    "enabled": True,
                    "status": "error",
                    "last_error": str(exc),
                    "semantic_edges": 0,
                }

        # 3) 上装 ↔ 下装搭配边（整套推荐用）
        tops = [pid for pid, item in product_index.items() if item["category"] == "上装"]
        bottoms = [pid for pid, item in product_index.items() if item["category"] == "下装"]
        for top_id in sorted(tops):
            for bottom_id in sorted(bottoms):
                top = product_index[top_id]
                bottom = product_index[bottom_id]
                overlap = len(set(top["styles"]) & set(bottom["styles"]))
                color_overlap = len(set(top["colors"]) & set(bottom["colors"]))
                weight = min(0.9, 0.5 + 0.1 * overlap + 0.05 * color_overlap)
                add_edge(
                    f"product:{top_id}",
                    f"product:{bottom_id}",
                    "pairs_with",
                    weight,
                    meta={"method": "style-compatibility"},
                )

        # 4) 邻接索引
        neighbors: dict[int, list[dict[str, Any]]] = {pid: [] for pid in product_ids}
        relation_order = {"similar_to": 0, "pairs_with": 1, "belongs_to": 2, "has_color": 3,
                          "has_material": 4, "has_style": 5, "has_occasion": 6, "has_size": 7}
        for edge in edges:
            source_id = edge["source"]
            target_id = edge["target"]
            if not source_id.startswith("product:") and target_id.startswith("product:"):
                source_id, target_id = target_id, source_id
            if not source_id.startswith("product:"):
                continue
            pid = int(source_id.split(":", 1)[1])
            target = nodes[target_id]
            neighbors.setdefault(pid, []).append(
                {
                    "id": target_id,
                    "label": target["label"],
                    "type": target["type"],
                    "relation": edge["relation"],
                    "weight": edge["weight"],
                }
            )
        for pid, items in neighbors.items():
            items.sort(key=lambda item: (relation_order.get(item["relation"], 99), -item["weight"], item["id"]))

        meta = {
            "product_count": len(product_index),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "similar_top_k": self.similar_top_k,
            "semantic_edges": semantic_added,
            "text_embedding": text_info,
            "metric": "chebyshev",
            "semantic_metric": "cosine",
        }
        with self._lock:
            self.nodes = nodes
            self.edges = edges
            self._products = product_index
            self._embeddings = embedding_index
            self._neighbors = neighbors
            self.meta = meta
        return {"nodes": list(nodes.values()), "edges": edges, "meta": meta}

    @staticmethod
    def _normalise_embeddings(
        embeddings: list[dict[str, Any]] | dict[int, list[float]],
    ) -> dict[int, list[float]]:
        result: dict[int, list[float]] = {}
        if not embeddings:
            return result
        if isinstance(embeddings, dict):
            for key, value in embeddings.items():
                try:
                    result[int(key)] = [float(item) for item in value]
                except (TypeError, ValueError):
                    continue
            return result
        for row in embeddings:
            if not isinstance(row, dict):
                continue
            vector = row.get("embedding") or row.get("vector")
            try:
                product_id = int(row.get("product_id"))
            except (TypeError, ValueError):
                continue
            if not vector:
                continue
            try:
                result[product_id] = [float(item) for item in vector]
            except (TypeError, ValueError):
                continue
        return result

    # ------------------------------------------------------------------ 查询
    async def neighbors(self, product_id: int, limit: int = 6) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._neighbors.get(int(product_id), []))
        return items[: max(0, int(limit))]

    async def query(self, text: str, top_k: int = 6) -> dict[str, Any]:
        """查询扩展 + 图谱邻域扩展，返回三元组/商品 id/扩展词。"""
        extraction = await self.extract(text)
        expanded = self.expand_terms(text, extraction)
        attributes = extraction["attributes"]
        with self._lock:
            product_index = dict(self._products)
            neighbors = {pid: list(items) for pid, items in self._neighbors.items()}

        scores: dict[int, float] = {pid: 0.0 for pid in product_index}
        reasons: dict[int, list[str]] = {pid: [] for pid in product_index}
        attr_sets = {
            "category": set(attributes.get("category", [])),
            "colors": set(attributes.get("colors", [])),
            "materials": set(attributes.get("materials", [])),
            "styles": set(attributes.get("styles", [])),
            "occasions": set(attributes.get("occasions", [])),
            "sizes": set(attributes.get("sizes", [])),
        }
        expanded_set = set(expanded)

        for pid, product in product_index.items():
            score = 0.0
            hits: list[str] = []
            if product["category"] and product["category"] in attr_sets["category"]:
                score += 3.0
                hits.append(f"品类：{product['category']}")
            for color in product["colors"]:
                if color in attr_sets["colors"]:
                    score += 1.5
                    hits.append(f"颜色：{color}")
            for material in product["materials"]:
                if material in attr_sets["materials"]:
                    score += 1.2
                    hits.append(f"材质：{material}")
            for style in product["styles"]:
                if style in attr_sets["styles"]:
                    score += 1.0
                    hits.append(f"风格：{style}")
                elif style in expanded_set:
                    score += 0.3
                    hits.append(f"相关风格：{style}")
            for occ in product["occasions"]:
                if occ in attr_sets["occasions"]:
                    score += 1.0
                    hits.append(f"场景：{occ}")
            for size in product["sizes"]:
                if size in attr_sets["sizes"]:
                    score += 0.5
                    hits.append(f"尺码：{size}")
            haystack = f"{product['name']} {product['subtitle']} {product['category']}"
            for term in expanded_set:
                if term and len(term) >= 2 and term in haystack:
                    score += 0.6
                    hits.append(f"关键词：{term}")
            scores[pid] = score
            reasons[pid] = _dedupe(hits)

        # 邻域扩展：打分商品通过 similar_to / pairs_with 把分数传给邻居
        direct_hits = [pid for pid, score in scores.items() if score > 0]
        for pid in direct_hits:
            for neighbor in neighbors.get(pid, []):
                if not neighbor["id"].startswith("product:"):
                    continue
                neighbor_id = int(neighbor["id"].split(":", 1)[1])
                if neighbor["relation"] == "similar_to":
                    scores[neighbor_id] = scores.get(neighbor_id, 0.0) + 0.8 * neighbor["weight"]
                elif neighbor["relation"] == "pairs_with":
                    scores[neighbor_id] = scores.get(neighbor_id, 0.0) + 0.6 * neighbor["weight"]

        ranked = sorted(
            (pid for pid in scores if scores[pid] > 0),
            key=lambda pid: (-scores[pid], pid),
        )[: max(0, int(top_k))]

        triples: list[dict[str, Any]] = list(extraction["triples"])
        for pid in ranked[: min(3, len(ranked))]:
            product = product_index[pid]
            triples.append({"subject": product["name"], "relation": "属于品类", "object": product["category"]})
            for color in product["colors"][:2]:
                triples.append({"subject": product["name"], "relation": "颜色", "object": color})
            for style in product["styles"][:2]:
                triples.append({"subject": product["name"], "relation": "风格", "object": style})
            if product["occasions"]:
                triples.append({"subject": product["name"], "relation": "场景", "object": product["occasions"][0]})
            triples.append(
                {"subject": product["name"], "relation": "匹配分", "object": round(scores[pid], 3)}
            )

        return {
            "triples": triples,
            "product_ids": ranked,
            "scores": {str(pid): round(scores[pid], 3) for pid in ranked},
            "related_terms": expanded,
            "attributes": attributes,
        }

    # ------------------------------------------------------------------ 其他
    def chebyshev(self, a: Sequence[float], b: Sequence[float]) -> float:
        return chebyshev_distance(a, b)

    def info(self) -> dict[str, Any]:
        with self._lock:
            meta = dict(self.meta)
            nodes = len(self.nodes)
            edges = len(self.edges)
            similar_edges = sum(1 for edge in self.edges if edge["relation"] == "similar_to")
            pair_edges = sum(1 for edge in self.edges if edge["relation"] == "pairs_with")
            semantic_edges = sum(
                1 for edge in self.edges if edge["relation"] == "semantic_similar"
            )
        return {
            "name": self.name,
            "version": self.version,
            "backend": self.backend,
            "healthy": True,
            "replaceable_baseline": True,
            "metric": "chebyshev",
            "semantic_metric": "cosine",
            "text_embedding": meta.get("text_embedding") or get_text_embedder().info(),
            "dictionary": {
                "category_terms": len(CATEGORY_TERMS),
                "color_terms": len(COLOR_TERMS),
                "material_terms": len(MATERIAL_TERMS),
                "style_terms": len(STYLE_TERMS),
                "occasion_terms": len(OCCASION_TERMS),
            },
            "graph": {
                **meta,
                "nodes": nodes,
                "edges": edges,
                "similar_to_edges": similar_edges,
                "pairs_with_edges": pair_edges,
                "semantic_similar_edges": semantic_edges,
            },
        }


def build_graph_sync(
    nlp_model: NLPKGStub,
    products: list[Any],
    embeddings: list[dict[str, Any]] | dict[int, list[float]],
) -> dict[str, Any]:
    """同步建图辅助函数（warm_up 在线程池中调用）。"""
    return nlp_model.build_graph_sync(products, embeddings)


__all__ = [
    "NLPKGStub",
    "extract_attributes",
    "build_graph_sync",
    "CATEGORY_TERMS",
    "COLOR_TERMS",
    "MATERIAL_TERMS",
    "STYLE_TERMS",
    "OCCASION_TERMS",
]
