# -*- coding: utf-8 -*-
"""翻译后端层。

  baidu.py        百度翻译开放平台（大模型文本翻译 + 通用翻译）
  openai_compat.py OpenAI 兼容接口（硅基流动 / LM Studio / 任意自定义平台共用）
"""

from translator.backends import baidu, openai_compat


def is_openai_compat(backend):
    """GUI 中判定某后端是否为 OpenAI 兼容。

    硅基流动、LM Studio 本地、自定义·... 平台均为 OpenAI 兼容（同一 chat_completion 链路）。
    """
    return backend == "硅基流动" or backend == "LM Studio 本地" or backend.startswith("自定义·")


def chat_for(backend):
    """返回 OpenAI 兼容后端统一使用的 chat_completion 函数。"""
    return openai_compat.chat_completion


__all__ = ["baidu", "openai_compat", "is_openai_compat", "chat_for"]