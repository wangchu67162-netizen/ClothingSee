"""小模型适配层抽象接口（唯一契约，stub 与 HTTP 适配器共同实现）。

只定义接口，不引入训练依赖。业务代码只能通过 ``factory.py`` 获取实例，
不得直接依赖某个具体实现，方便用户后续用自训练模型替换。

契约来源：docs/CONTRACTS.md 第 4 节 / docs/small-model-interface.md。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any


class VisionModel(ABC):
    """视觉小模型：把图片编码为定长向量，并支持相似检索。"""

    name: str
    version: str
    dim: int

    @abstractmethod
    async def embed(self, image: bytes) -> list[float]:
        """把单张图片（原始字节）编码为 ``dim`` 维、L2 归一化的向量。"""

    @abstractmethod
    async def embed_many(self, images: list[bytes]) -> list[list[float]]:
        """批量编码；返回顺序必须与输入一致。"""

    @abstractmethod
    def info(self) -> dict[str, Any]:
        """返回模型元信息（name/version/dim/backend/healthy 等），供 status 接口使用。"""


class NLPKGModel(ABC):
    """NLP / 知识图谱小模型：中文属性抽取、切比雪夫排序与图谱查询。"""

    name: str
    version: str

    @abstractmethod
    async def extract(self, text: str) -> dict[str, Any]:
        """从中文文本抽取 ``{attributes, keywords, triples}``。

        attributes 建议包含 category / colors / materials / styles / occasions / sizes
        六个键（值为字符串列表）；triples 为 ``{subject, relation, object}`` 列表。
        """

    @abstractmethod
    async def rank(
        self,
        query_embedding: Sequence[float],
        candidates: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """按切比雪夫距离对候选排序。

        ``candidates`` 形如 ``[{"product_id": 1, "embedding": [...]}]``；
        返回 ``[{"product_id", "distance", "similarity"}]``，按 distance 升序。
        """

    @abstractmethod
    async def neighbors(self, product_id: int, limit: int = 6) -> list[dict[str, Any]]:
        """返回图谱中与某商品直接相连的邻居（similar_to / 搭配 / 属性节点）。"""

    @abstractmethod
    async def build_graph(
        self,
        products: list[Any],
        embeddings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """根据商品与视觉向量构建内存知识图谱，返回 ``{nodes, edges, meta}``。

        ``products`` 既可以是 ORM 对象也可以是 dict；``embeddings`` 形如
        ``[{"product_id": 1, "embedding": [...]}]``。
        """

    @abstractmethod
    def chebyshev(self, a: Sequence[float], b: Sequence[float]) -> float:
        """切比雪夫距离 ``max_i |a_i - b_i|``（等长非空，否则 ValueError）。"""

    @abstractmethod
    def info(self) -> dict[str, Any]:
        """返回模型元信息（name/version/backend/词典规模/图谱统计等）。"""
