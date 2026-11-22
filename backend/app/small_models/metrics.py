"""相似度度量：切比雪夫距离 / 相似度。

公式（与 docs/CONTRACTS.md、docs/small-model-interface.md 保持一致）：

    chebyshev_distance(a, b) = max_i |a_i - b_i|
    chebyshev_similarity(a, b) = 1 / (1 + chebyshev_distance(a, b))

要求两个向量非空且等长，否则抛出 ``ValueError``（中文提示）。
"""
from __future__ import annotations

from collections.abc import Sequence

Number = int | float

# 浮点比较容差：避免 0.1+0.2 之类的表示误差影响测试与前端展示
_EPS = 1e-12


def _validate(a: Sequence[Number], b: Sequence[Number]) -> None:
    if a is None or b is None:
        raise ValueError("向量不能为空：请提供两个非空数字数组")
    if len(a) == 0 or len(b) == 0:
        raise ValueError("向量不能为空：请提供两个非空数字数组")
    if len(a) != len(b):
        raise ValueError(f"向量维度不一致：a 为 {len(a)} 维，b 为 {len(b)} 维")


def chebyshev_distance(a: Sequence[Number], b: Sequence[Number]) -> float:
    """切比雪夫距离 = max_i |a_i - b_i|。"""
    _validate(a, b)
    distance = 0.0
    for x, y in zip(a, b):
        delta = abs(float(x) - float(y))
        if delta > distance:
            distance = delta
    return float(distance)


def chebyshev_similarity(a: Sequence[Number], b: Sequence[Number]) -> float:
    """切比雪夫相似度 = 1 / (1 + distance)，落在 (0, 1]。"""
    distance = chebyshev_distance(a, b)
    if distance <= _EPS:
        return 1.0
    return float(1.0 / (1.0 + distance))
