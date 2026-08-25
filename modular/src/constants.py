# -*- coding: utf-8 -*-
"""全部共享常量与纯函数：配色、语言表、提示词、代码围栏清理等。

供 ui/ 与 cli/ 共用，消除原脚本中各界面重复定义配色的冗余。
"""

import os

# 界面配色
BG = "#f4f6fb"            # 窗口背景
FG = "#2d3436"            # 主文字
MUTED = "#7f8c9b"         # 次要文字
ACCENT = "#2f6fed"        # 主色（蓝）
ACCENT_DARK = "#2456c4"   # 主色深（悬停）
ACCENT_LIGHT = "#eaf0fe"  # 主色浅（选中/悬停背景）
BORDER = "#d5dbe8"        # 边框
HEADER_BG = "#1f2d3d"     # 顶栏深色
STATUS_BG = "#eef1f7"     # 状态栏背景

# 目标语言代码 → 中文名（用于导出文件名，如 article-中文翻译.md）
LANG_NAMES = {"zh": "中文", "en": "英文", "ja": "日文", "jp": "日文",
              "ko": "韩文", "fr": "法文", "de": "德文", "ru": "俄文"}

# 源/目标语言下拉框（中文显示）→ 语言代码
LANG_OPTIONS = ["中文", "英文", "日文", "韩文", "法文", "德文", "俄文"]
LANG_CODE = {"中文": "zh", "英文": "en", "日文": "jp", "韩文": "ko",
             "法文": "fr", "德文": "de", "俄文": "ru"}

# 内置后端与自定义前缀
# LLM 对话模型组（对话补全接口）
LLM_BACKENDS = ["硅基流动", "LM Studio 本地"]
# 专用翻译 API 组（云厂商文本翻译接口）
API_BACKENDS = ["百度翻译", "腾讯云机器翻译", "阿里云机器翻译", "彩云小译"]
BASE_BACKENDS = LLM_BACKENDS + API_BACKENDS
CUSTOM_PREFIX = "自定义·"
# 后端下拉分组标题（仅作提示，不可选中）
GROUP_LLM = "── LLM 对话模型 ──"
GROUP_API = "── 专用翻译 API ──"

# 本地配置文件（存于用户主目录，避免混入项目目录）
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".translate_gui_config.json")


def build_system_prompt(src_name, dst_name):
    """构造翻译角色设定提示词。"""
    return (
        "你是一名专业的%s→%s翻译。请将用户提供的文本完整翻译为%s：\n"
        "1. 忠实原文，保持段落结构、换行和标点。\n"
        "2. 保留原文中的 Markdown 排版标记（如 **加粗**、*斜体*、[链接文字](url)、行内代码 `code`），"
        "只翻译其中的文字内容，不要改动这些标记。\n"
        "3. 术语规范，说明性语气，保持科普基调。\n"
        "4. 只输出译文本身，不要任何解释、开头语或结尾语。"
    ) % (src_name, dst_name, dst_name)


LLM_SYSTEM = build_system_prompt("日文", "中文")


def strip_fences(text):
    """去掉 LLM 输出可能包裹的 ``` 代码围栏。"""
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t