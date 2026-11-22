"""大模型层：通义千问适配器、确定性 Mock 与提示词模板。"""
from .mock import MockLLM
from .qwen import QwenAgentBackend, QwenClient, QwenError, qwen_available

__all__ = [
    "MockLLM",
    "QwenAgentBackend",
    "QwenClient",
    "QwenError",
    "qwen_available",
]
