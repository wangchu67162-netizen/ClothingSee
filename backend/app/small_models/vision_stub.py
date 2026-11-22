"""视觉小模型 Stub（REPLACEABLE BASELINE，可被自训练模型替换）。

不训练任何模型，只用 Pillow + NumPy 提取可解释的确定性图像特征：

    1. RGB 直方图       32 bins × 3 通道 = 96 维
    2. HSV 直方图       32 bins × 3 通道 = 96 维
    3. 梯度方向直方图    32 bins        = 32 维
    4. 分块颜色矩        2×2 块 × 3 通道 × (均值, 标准差) = 24 维
    5. 全局统计          明度/饱和度/边缘密度/色彩丰富度/长宽比 =  8 维
                                                        合计 256 维

所有图片先 EXIF 转正并缩放到 64×64，末段整体做 L2 归一化；同一字节输入
必然得到同一向量（确定性），便于比对与缓存。接入真实模型见
docs/small-model-interface.md。
"""
from __future__ import annotations

import asyncio
import io
import math
from typing import Any

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .base import VisionModel
from .metrics import chebyshev_distance, chebyshev_similarity

TARGET_SIZE = 64
HIST_BINS = 32
FEATURE_DIM = HIST_BINS * 3 + HIST_BINS * 3 + HIST_BINS + 2 * 2 * 3 * 2 + 8  # = 256


class VisionStub(VisionModel):
    """确定性视觉 embedding 基线，256 维、L2 归一化。"""

    name = "yijian-vision-stub"
    version = "stub-v1"
    dim = FEATURE_DIM
    backend = "stub"

    def __init__(self) -> None:
        self.last_error: str | None = None

    # ------------------------------------------------------------------ 公共 API
    async def embed(self, image: bytes) -> list[float]:
        return await asyncio.to_thread(self._embed_sync, image)

    async def embed_many(self, images: list[bytes]) -> list[list[float]]:
        if not images:
            return []
        return await asyncio.to_thread(lambda: [self._embed_sync(item) for item in images])

    def info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "dim": self.dim,
            "backend": self.backend,
            "healthy": True,
            "replaceable_baseline": True,
            "description": "Pillow 64×64 RGB/HSV 直方图 + 梯度方向 + 分块颜色矩，L2 归一化",
            "features": {
                "rgb_hist": HIST_BINS * 3,
                "hsv_hist": HIST_BINS * 3,
                "gradient_orientation": HIST_BINS,
                "block_color_moments": 2 * 2 * 3 * 2,
                "global_stats": 8,
            },
        }

    # ------------------------------------------------------------- 实现细节
    @staticmethod
    def _load(image: bytes) -> Image.Image:
        if not image:
            raise ValueError("图片数据为空，请重新选择图片")
        try:
            img = Image.open(io.BytesIO(image))
            img.load()
            img = ImageOps.exif_transpose(img)
            return img.convert("RGB").resize((TARGET_SIZE, TARGET_SIZE), Image.Resampling.LANCZOS)
        except UnidentifiedImageError as exc:
            raise ValueError("无法识别该图片，请上传 JPG/PNG/WEBP 格式的图片") from exc
        except (OSError, ValueError) as exc:
            raise ValueError("图片已损坏或格式不受支持，请换一张图片") from exc

    def _embed_sync(self, image: bytes) -> list[float]:
        img = self._load(image)
        rgb = np.asarray(img, dtype=np.float32) / 255.0
        hsv_img = img.convert("HSV")
        hsv = np.asarray(hsv_img, dtype=np.float32) / 255.0
        gray = np.asarray(img.convert("L"), dtype=np.float32) / 255.0

        features: list[np.ndarray] = []

        # 1) RGB 直方图：每个通道独立归一化
        for channel in range(3):
            hist, _ = np.histogram(rgb[:, :, channel], bins=HIST_BINS, range=(0.0, 1.0))
            features.append(hist.astype(np.float32) / max(float(hist.sum()), 1.0))

        # 2) HSV 直方图（PIL 的 H/S/V 都落在 0..255，这里统一除以 255）
        for channel in range(3):
            hist, _ = np.histogram(hsv[:, :, channel], bins=HIST_BINS, range=(0.0, 1.0))
            features.append(hist.astype(np.float32) / max(float(hist.sum()), 1.0))

        # 3) 梯度方向直方图（方向取 0..π，按梯度模长加权）
        grad_y, grad_x = np.gradient(gray)
        magnitude = np.hypot(grad_x, grad_y)
        orientation = np.mod(np.arctan2(grad_y, grad_x), math.pi)
        orient_hist, _ = np.histogram(
            orientation, bins=HIST_BINS, range=(0.0, math.pi), weights=magnitude
        )
        total_weight = float(orient_hist.sum())
        if total_weight <= 1e-8:
            # 纯色图没有梯度：用均匀分布占位，保持确定性
            orient_hist = np.ones(HIST_BINS, dtype=np.float64) / HIST_BINS
        else:
            orient_hist = orient_hist.astype(np.float32) / total_weight
        features.append(orient_hist.astype(np.float32))

        # 4) 2×2 分块颜色矩：每块每通道的均值与标准差
        block = TARGET_SIZE // 2
        for by in range(2):
            for bx in range(2):
                patch = rgb[by * block : (by + 1) * block, bx * block : (bx + 1) * block, :]
                mean = patch.mean(axis=(0, 1))
                std = patch.std(axis=(0, 1))
                features.append(mean.astype(np.float32))
                features.append(std.astype(np.float32))

        # 5) 全局统计：明度、饱和度、边缘密度、色彩丰富度、长宽比
        brightness = gray
        saturation = hsv[:, :, 1]
        red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        rg = red - green
        yb = 0.5 * (red + green) - blue
        colorfulness = np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean())
        edge_density = float((magnitude > 0.08).mean())
        aspect = 1.0  # 已缩放为正方形；保留维度以便替换模型使用真实长宽比
        extras = np.array(
            [
                float(brightness.mean()),
                float(brightness.std()),
                float(saturation.mean()),
                float(saturation.std()),
                edge_density,
                float(colorfulness),
                float(np.hypot(rg.mean(), yb.mean())),
                aspect,
            ],
            dtype=np.float32,
        )
        features.append(extras)

        vector = np.concatenate(features).astype(np.float32)
        if vector.shape[0] != FEATURE_DIM:  # pragma: no cover - 防御性断言
            raise RuntimeError(f"视觉特征维度异常：{vector.shape[0]}，预期 {FEATURE_DIM}")
        vector = self._l2_normalize(vector)
        return [float(value) for value in vector]

    @staticmethod
    def _l2_normalize(vector: np.ndarray) -> np.ndarray:
        norm = float(np.linalg.norm(vector))
        if not math.isfinite(norm) or norm <= 1e-12:
            vector = np.zeros_like(vector)
            vector[0] = 1.0
            return vector
        return vector / norm

    # 便于业务侧复用同一套度量
    @staticmethod
    def distance(a: list[float], b: list[float]) -> float:
        return chebyshev_distance(a, b)

    @staticmethod
    def similarity(a: list[float], b: list[float]) -> float:
        return chebyshev_similarity(a, b)
