"""Local Chinese fashion-text embedder (BGE-small-zh-v1.5, ONNX INT8).

The knowledge graph uses this model to connect products whose Chinese
descriptions are semantically close, independently of the visual embedding.
It is deliberately dependency-light: ``onnxruntime`` + ``tokenizers`` rather
than PyTorch.  If the model files are absent the graph builder simply skips
``semantic_similar`` edges and keeps the visual/lexicon graph.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

from ..config import BACKEND_DIR, settings

logger = logging.getLogger("yijian.small_models.text_embedding")


class TextEmbeddingUnavailable(RuntimeError):
    """Model files or runtime dependencies are missing."""


class FashionTextEmbedder:
    name = "bge-small-zh-v1.5"
    backend = "onnx-int8"
    dim = 512
    version = "bge-small-zh-v1.5-int8-v1"

    def __init__(
        self,
        model_dir: str | None = None,
        model_file: str | None = None,
        max_length: int | None = None,
    ) -> None:
        raw_dir = Path(model_dir or settings.nlp_embedding_model_dir)
        self.model_dir = raw_dir if raw_dir.is_absolute() else (BACKEND_DIR / raw_dir)
        self.model_path = self.model_dir / (model_file or settings.nlp_embedding_model_file)
        self.tokenizer_path = self.model_dir / "tokenizer.json"
        self.max_length = int(max_length or settings.nlp_embedding_max_length)
        self._lock = threading.RLock()
        self._tokenizer: Any = None
        self._session: Any = None
        self._loaded = False
        self._last_error: str | None = None
        self._input_names: list[str] = []

    @property
    def available(self) -> bool:
        return bool(
            settings.nlp_embedding_enabled
            and self.model_path.is_file()
            and self.tokenizer_path.is_file()
        )

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            if not settings.nlp_embedding_enabled:
                raise TextEmbeddingUnavailable("NLP 文本嵌入模型已在配置中关闭")
            if not self.model_path.is_file():
                raise TextEmbeddingUnavailable(f"缺少模型文件：{self.model_path}")
            if not self.tokenizer_path.is_file():
                raise TextEmbeddingUnavailable(f"缺少分词器：{self.tokenizer_path}")
            try:
                import onnxruntime as ort
                from tokenizers import Tokenizer
            except Exception as exc:  # pragma: no cover - optional dependency
                raise TextEmbeddingUnavailable(
                    "未安装 onnxruntime/tokenizers，无法启用文本嵌入"
                ) from exc

            tokenizer = Tokenizer.from_file(str(self.tokenizer_path))
            tokenizer.enable_truncation(max_length=self.max_length)
            tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")

            session = ort.InferenceSession(
                str(self.model_path), providers=["CPUExecutionProvider"]
            )
            self._tokenizer = tokenizer
            self._session = session
            self._input_names = [item.name for item in session.get_inputs()]
            self._loaded = True
            self._last_error = None
            logger.info(
                "文本嵌入模型已加载：%s（%s，%d 维）",
                self.name,
                self.backend,
                self.dim,
            )

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return L2-normalized CLS embeddings with shape ``(n, 512)``."""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        self._ensure_loaded()
        cleaned = [str(text or "").strip() for text in texts]
        try:
            encodings = self._tokenizer.encode_batch(cleaned)
        except Exception as exc:
            raise TextEmbeddingUnavailable(f"文本分词失败：{exc}") from exc

        input_ids = np.asarray([item.ids for item in encodings], dtype=np.int64)
        attention_mask = np.asarray(
            [item.attention_mask for item in encodings], dtype=np.int64
        )
        feeds: dict[str, np.ndarray] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        # Some BGE exports include token_type_ids; zeros are correct for BERT.
        for name in self._input_names:
            if name not in feeds:
                feeds[name] = np.zeros_like(input_ids)

        with self._lock:
            outputs = self._session.run(None, feeds)
        if not outputs:
            raise TextEmbeddingUnavailable("文本嵌入模型没有输出")
        hidden = np.asarray(outputs[0], dtype=np.float32)
        # BGE-small-zh-v1.5 uses CLS pooling.
        vectors = hidden[:, 0, :]
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-9)
        return vectors.astype(np.float32, copy=False)

    def info(self) -> dict[str, Any]:
        status = "ready" if self.available else "missing"
        if self._loaded:
            status = "loaded"
        return {
            "name": self.name,
            "version": self.version,
            "backend": self.backend,
            "dim": self.dim,
            "max_length": self.max_length,
            "available": self.available,
            "loaded": self._loaded,
            "status": status,
            "model_path": str(self.model_path),
            "last_error": self._last_error,
        }


_embedder: FashionTextEmbedder | None = None
_embedder_lock = threading.Lock()


def get_text_embedder() -> FashionTextEmbedder:
    global _embedder
    with _embedder_lock:
        if _embedder is None:
            _embedder = FashionTextEmbedder()
        return _embedder


def reset_text_embedder() -> None:
    global _embedder
    with _embedder_lock:
        _embedder = None


def product_text(product: dict[str, Any]) -> str:
    """Flatten the Chinese product attributes into one embedding sentence."""
    fields: list[str] = []
    for key in ("name", "subtitle", "category", "description", "fabric", "fit", "occasion", "season"):
        value = product.get(key)
        if isinstance(value, str) and value.strip():
            fields.append(value.strip())
    for key in ("style_tags", "colors", "sizes"):
        value = product.get(key)
        if isinstance(value, (list, tuple)):
            fields.extend(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            fields.append(value.strip())
    # Preserve order but remove duplicates.
    seen: set[str] = set()
    unique = [item for item in fields if not (item in seen or seen.add(item))]
    return "；".join(unique)[:1200]


__all__ = [
    "FashionTextEmbedder",
    "TextEmbeddingUnavailable",
    "get_text_embedder",
    "reset_text_embedder",
    "product_text",
]
