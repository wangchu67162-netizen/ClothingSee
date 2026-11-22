"""HTTP 小模型适配器：把用户自训练的远程模型接入本项目（重点交付）。

协议见 docs/CONTRACTS.md 4.3 与 docs/small-model-interface.md：

    POST {VISION_SERVICE_URL}/embed
      {"images_base64": [...], "normalize": true}
      -> {"embeddings": [[...]], "dim": 256, "model_version": "..."}

    POST {NLP_KG_SERVICE_URL}/rank
      {"query_embedding": [...], "text": "...", "candidates": [...], "top_k": 8}
      -> {"matches": [{"product_id": 1, "distance": 0.12, "similarity": 0.89}], "extracted": {...}}

    POST {NLP_KG_SERVICE_URL}/extract
      {"text": "..."} -> {"attributes": {...}, "keywords": [...], "triples": [...]}

异常策略：默认 ``SMALL_MODEL_FALLBACK_TO_STUB=true``，请求失败（超时/连接失败/
HTTP 非 2xx/响应不合法）时记录 warning 并自动降级到本地 Stub；设为 false 时抛出
``SmallModelServiceError``，由路由转成中文 502/503 提示。
"""
from __future__ import annotations

import base64
import logging
import os
import uuid
from functools import lru_cache
from typing import Any

import httpx

from ..config import BACKEND_DIR, settings
from .base import NLPKGModel, VisionModel
from .nlp_kg_stub import NLPKGStub
from .vision_stub import VisionStub

logger = logging.getLogger("yijian.small_models")

_FALSE_VALUES = {"0", "false", "no", "off", ""}


class SmallModelServiceError(RuntimeError):
    """远程小模型服务不可用；路由层会把它转成中文 502 提示。"""


@lru_cache(maxsize=1)
def _dotenv_values() -> dict[str, str]:
    """读取 backend/.env（config.py 不会把自定义变量放进 os.environ）。"""
    try:
        from dotenv import dotenv_values

        values = dotenv_values(BACKEND_DIR / ".env")
        return {key: str(value) for key, value in values.items() if key and value is not None}
    except Exception:  # pragma: no cover - dotenv 缺失时忽略
        return {}


def env_value(name: str, default: str = "") -> str:
    """环境变量优先，其次 backend/.env。"""
    value = os.environ.get(name)
    if value is not None and value != "":
        return value
    dotenv_value = _dotenv_values().get(name)
    if dotenv_value is not None:
        return dotenv_value
    return default


def env_flag(name: str, default: bool = True) -> bool:
    raw = env_value(name, "true" if default else "false")
    return raw.strip().lower() not in _FALSE_VALUES


def _service_url(explicit: str | None, setting_value: str, env_name: str) -> str:
    value = explicit if explicit is not None else (setting_value or env_value(env_name, ""))
    return value.strip().rstrip("/")


def _timeout(explicit: float | None) -> float:
    if explicit is not None:
        return float(explicit)
    try:
        return float(env_value("SMALL_MODEL_TIMEOUT", str(settings.small_model_timeout)))
    except ValueError:
        return float(settings.small_model_timeout)


def _token(explicit: str | None) -> str:
    if explicit is not None:
        return explicit.strip()
    return env_value("SMALL_MODEL_TOKEN", getattr(settings, "small_model_token", "")).strip()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


class _HttpBase:
    """共享的 JSON POST 逻辑（超时、Bearer、错误封装）。"""

    service_url: str
    timeout: float
    token: str
    fallback_to_stub: bool
    last_error: str | None = None
    degraded: bool = False

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.service_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=_headers(self.token))
        except httpx.TimeoutException as exc:
            raise SmallModelServiceError(f"小模型服务请求超时（>{self.timeout:g} 秒）：{url}") from exc
        except httpx.HTTPError as exc:
            raise SmallModelServiceError(f"小模型服务连接失败：{url}（{type(exc).__name__}）") from exc
        if response.status_code >= 400:
            raise SmallModelServiceError(
                f"小模型服务返回错误 HTTP {response.status_code}：{url}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise SmallModelServiceError(f"小模型服务返回的不是合法 JSON：{url}") from exc
        if not isinstance(data, dict):
            raise SmallModelServiceError(f"小模型服务返回结构不合法：{url}")
        return data

    def _mark_success(self) -> None:
        self.degraded = False
        self.last_error = None

    def _mark_failure(self, exc: Exception) -> None:
        self.last_error = str(exc)
        self.degraded = True
        logger.warning("小模型远程调用失败：%s", exc)


class HttpVisionModel(_HttpBase, VisionModel):
    """远程视觉模型适配器；失败可降级到 ``VisionStub``。"""

    name = "yijian-vision-http"
    backend = "http"
    version = "remote-unknown"

    def __init__(
        self,
        service_url: str | None = None,
        *,
        timeout: float | None = None,
        token: str | None = None,
        fallback_to_stub: bool | None = None,
        stub: VisionStub | None = None,
    ) -> None:
        self.service_url = _service_url(service_url, settings.vision_service_url, "VISION_SERVICE_URL")
        self.timeout = _timeout(timeout)
        self.token = _token(token)
        self.fallback_to_stub = (
            env_flag("SMALL_MODEL_FALLBACK_TO_STUB", True)
            if fallback_to_stub is None
            else bool(fallback_to_stub)
        )
        self._stub = stub or VisionStub()
        self.dim = self._stub.dim
        # 启动随机后缀：HTTP 模式每次启动都强制重新校验/补算 embedding，
        # 以便感知远程模型版本或维度变化（文档「维度变化」一节有说明）。
        self.version = f"remote-{uuid.uuid4().hex[:8]}"

    async def embed(self, image: bytes) -> list[float]:
        embeddings = await self.embed_many([image])
        return embeddings[0]

    async def embed_many(self, images: list[bytes]) -> list[list[float]]:
        if not images:
            return []
        if not self.service_url:
            exc = SmallModelServiceError("未配置 VISION_SERVICE_URL，无法调用远程视觉模型")
            if not self.fallback_to_stub:
                raise exc
            self._mark_failure(exc)
            return await self._stub.embed_many(images)
        payload = {
            "images_base64": [base64.b64encode(image).decode("ascii") for image in images],
            "normalize": True,
        }
        try:
            data = await self._post_json("/embed", payload)
            raw_embeddings = data.get("embeddings")
            if not isinstance(raw_embeddings, list) or len(raw_embeddings) != len(images):
                raise SmallModelServiceError("远程视觉模型返回的 embeddings 数量与输入不一致")
            vectors: list[list[float]] = []
            for raw in raw_embeddings:
                if not isinstance(raw, list) or not raw:
                    raise SmallModelServiceError("远程视觉模型返回了空的 embedding")
                vector = [float(value) for value in raw]
                vectors.append(vector)
            dim = int(data.get("dim") or len(vectors[0]))
            if dim != len(vectors[0]):
                raise SmallModelServiceError(
                    f"远程视觉模型维度声明不一致：dim={dim}，实际={len(vectors[0])}"
                )
            self.dim = dim
            # 远程未声明 model_version 时保留本次启动的随机后缀，避免跨进程误用旧缓存
            self.version = str(data.get("model_version") or self.version)
            self._mark_success()
            return vectors
        except (SmallModelServiceError, TypeError, ValueError) as exc:
            wrapped = exc if isinstance(exc, SmallModelServiceError) else SmallModelServiceError(
                f"远程视觉模型响应解析失败：{exc}"
            )
            if not self.fallback_to_stub:
                raise wrapped
            self._mark_failure(wrapped)
            return await self._stub.embed_many(images)

    def info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "dim": self.dim,
            "backend": self.backend,
            "healthy": not self.degraded and bool(self.service_url),
            "service_url": self.service_url,
            "timeout": self.timeout,
            "fallback_to_stub": self.fallback_to_stub,
            "degraded": self.degraded,
            "last_error": self.last_error,
            "replaceable_baseline": False,
        }


class HttpNLPKGModel(_HttpBase, NLPKGModel):
    """远程 NLP-KG 适配器。

    ``extract`` / ``rank`` 走 HTTP；``build_graph`` / ``neighbors`` / ``chebyshev``
    属于本地图运算（HTTP 契约未定义），委托给内置 ``NLPKGStub``，不额外发请求。
    """

    name = "yijian-nlp-kg-http"
    backend = "http"
    version = "remote-unknown"

    def __init__(
        self,
        service_url: str | None = None,
        *,
        timeout: float | None = None,
        token: str | None = None,
        fallback_to_stub: bool | None = None,
        stub: NLPKGStub | None = None,
    ) -> None:
        self.service_url = _service_url(service_url, settings.nlp_kg_service_url, "NLP_KG_SERVICE_URL")
        self.timeout = _timeout(timeout)
        self.token = _token(token)
        self.fallback_to_stub = (
            env_flag("SMALL_MODEL_FALLBACK_TO_STUB", True)
            if fallback_to_stub is None
            else bool(fallback_to_stub)
        )
        self._stub = stub or NLPKGStub()

    async def extract(self, text: str) -> dict[str, Any]:
        if not self.service_url:
            return await self._degrade_extract(text, "未配置 NLP_KG_SERVICE_URL")
        try:
            data = await self._post_json("/extract", {"text": text})
            attributes = data.get("attributes") or {}
            if not isinstance(attributes, dict):
                raise SmallModelServiceError("远程 NLP 模型返回的 attributes 不是对象")
            keywords = [str(item) for item in (data.get("keywords") or [])]
            triples = [item for item in (data.get("triples") or []) if isinstance(item, dict)]
            self._mark_success()
            return {
                "attributes": {
                    "category": _as_str_list(attributes.get("category") or attributes.get("categories")),
                    "colors": _as_str_list(attributes.get("colors")),
                    "materials": _as_str_list(attributes.get("materials")),
                    "styles": _as_str_list(attributes.get("styles")),
                    "occasions": _as_str_list(attributes.get("occasions")),
                    "sizes": _as_str_list(attributes.get("sizes")),
                },
                "keywords": keywords,
                "triples": triples,
            }
        except (SmallModelServiceError, TypeError, ValueError) as exc:
            return await self._degrade_extract(text, str(exc))

    async def _degrade_extract(self, text: str, message: str) -> dict[str, Any]:
        exc = SmallModelServiceError(f"NLP-KG 远程抽取失败：{message}")
        if not self.fallback_to_stub:
            raise exc
        self._mark_failure(exc)
        return await self._stub.extract(text)

    async def rank(
        self,
        query_embedding: list[float] | tuple[float, ...],
        candidates: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        if not self.service_url:
            return await self._degrade_rank(query_embedding, candidates, top_k, "未配置 NLP_KG_SERVICE_URL")
        payload = {
            "query_embedding": list(query_embedding),
            "text": "",
            "candidates": candidates,
            "top_k": int(top_k),
        }
        try:
            data = await self._post_json("/rank", payload)
            raw_matches = data.get("matches")
            if not isinstance(raw_matches, list):
                raise SmallModelServiceError("远程 NLP 模型返回的 matches 不是数组")
            matches: list[dict[str, Any]] = []
            for item in raw_matches:
                if not isinstance(item, dict):
                    continue
                distance = float(item.get("distance"))
                similarity = item.get("similarity")
                matches.append(
                    {
                        "product_id": int(item.get("product_id")),
                        "distance": round(distance, 6),
                        "similarity": round(
                            float(similarity) if similarity is not None else 1.0 / (1.0 + distance),
                            6,
                        ),
                    }
                )
            matches.sort(key=lambda match: (match["distance"], match["product_id"]))
            self._mark_success()
            return matches[: max(0, int(top_k))]
        except (SmallModelServiceError, TypeError, ValueError) as exc:
            return await self._degrade_rank(query_embedding, candidates, top_k, str(exc))

    async def _degrade_rank(
        self,
        query_embedding: list[float] | tuple[float, ...],
        candidates: list[dict[str, Any]],
        top_k: int,
        message: str,
    ) -> list[dict[str, Any]]:
        exc = SmallModelServiceError(f"NLP-KG 远程排序失败：{message}")
        if not self.fallback_to_stub:
            raise exc
        self._mark_failure(exc)
        return await self._stub.rank(query_embedding, candidates, top_k)

    async def neighbors(self, product_id: int, limit: int = 6) -> list[dict[str, Any]]:
        return await self._stub.neighbors(product_id, limit)

    async def build_graph(
        self,
        products: list[Any],
        embeddings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self._stub.build_graph(products, embeddings)

    async def query(self, text: str, top_k: int = 6) -> dict[str, Any]:
        """先用远程抽取，再用本地图谱做查询扩展（保持 HTTP 契约最小）。"""
        extraction = await self.extract(text)
        expanded = self._stub.expand_terms(text, extraction)
        with self._stub._lock:  # noqa: SLF001 - 同一适配器内部共享
            product_index = dict(self._stub._products)
            neighbors = {pid: list(items) for pid, items in self._stub._neighbors.items()}
        scores: dict[int, float] = {}
        attributes = extraction.get("attributes", {})
        attr_categories = set(attributes.get("category", []))
        attr_colors = set(attributes.get("colors", []))
        attr_styles = set(attributes.get("styles", []))
        for pid, product in product_index.items():
            score = 0.0
            if product["category"] in attr_categories:
                score += 3.0
            score += 1.5 * len(set(product["colors"]) & attr_colors)
            score += 1.0 * len(set(product["styles"]) & attr_styles)
            for term in expanded:
                if term and len(term) >= 2 and term in f"{product['name']} {product['subtitle']}":
                    score += 0.6
            if score > 0:
                scores[pid] = score
        for pid in list(scores):
            for neighbor in neighbors.get(pid, []):
                if neighbor["relation"] == "similar_to" and neighbor["id"].startswith("product:"):
                    neighbor_id = int(neighbor["id"].split(":", 1)[1])
                    scores[neighbor_id] = scores.get(neighbor_id, 0.0) + 0.8 * neighbor["weight"]
        ranked = sorted(scores, key=lambda pid: (-scores[pid], pid))[: max(0, int(top_k))]
        triples = list(extraction.get("triples", []))
        for pid in ranked[:3]:
            product = product_index[pid]
            triples.append({"subject": product["name"], "relation": "属于品类", "object": product["category"]})
        return {
            "triples": triples,
            "product_ids": ranked,
            "scores": {str(pid): round(scores[pid], 3) for pid in ranked},
            "related_terms": expanded,
            "attributes": attributes,
        }

    def chebyshev(self, a: list[float], b: list[float]) -> float:
        return self._stub.chebyshev(a, b)

    def info(self) -> dict[str, Any]:
        stub_info = self._stub.info()
        return {
            "name": self.name,
            "version": self.version,
            "backend": self.backend,
            "healthy": not self.degraded and bool(self.service_url),
            "service_url": self.service_url,
            "timeout": self.timeout,
            "fallback_to_stub": self.fallback_to_stub,
            "degraded": self.degraded,
            "last_error": self.last_error,
            "metric": "chebyshev",
            "graph": stub_info.get("graph", {}),
            "replaceable_baseline": False,
        }


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        return [str(value)]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return []


__all__ = [
    "SmallModelServiceError",
    "HttpVisionModel",
    "HttpNLPKGModel",
    "env_value",
    "env_flag",
]
