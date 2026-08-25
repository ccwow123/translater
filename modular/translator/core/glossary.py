# -*- coding: utf-8 -*-
"""术语表：从已人工翻译的对照表 md 提炼 原文→译文 映射，并构造 few-shot 用户提示词。"""

import os
import re


def load_glossary(glossary_path, limit=8):
    """从已人工翻译的对照表 md 中提炼 {日文原文: 中文译文}。

    兼容两种排版：
      1) 翻译对照表：| 序号 | id | 日文原标题 | 中文翻译 | 原链接 |
      2) 纯映射行：`日文原文` → `中文译文`
    """
    if not glossary_path or not os.path.exists(glossary_path):
        return []
    pairs = []
    for line in open(glossary_path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line or line.startswith("|") is False and "→" not in line:
            continue
        # 表格行
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            # 跳过表头/分隔行
            if len(cells) < 4:
                continue
            if any(c in ("序号", "日文原标题", "id", "---") for c in cells):
                continue
            cells = [c for c in cells if c and c not in ("---",)]
            if len(cells) >= 2:
                src, tgt = cells[-2], cells[-1]
                if src and tgt and src != tgt:
                    pairs.append((src, tgt))
        else:
            m = re.match(r"^(.*?)\s*[→>]\s*(.*)$", line)
            if m:
                s, t = m.group(1).strip(), m.group(2).strip()
                if s and t:
                    pairs.append((s, t))
    return pairs[:limit]


SYSTEM_PROMPT = (
    "你是一名专业的日文→中文翻译，产出供成人向性教育/科普类文章研究的译文。要求：\n"
    "1. 忠实原文，术语规范，说明性语气，保持科普基调；不要自创色情化表述、不要添油加醋。\n"
    "2. 当给出术语对照时，必须严格使用既定译法（如体位名、中イキ→阴道高潮 等），不允许改词。\n"
    "3. 只输出 JSON，不要任何多余解释、开头语或结尾语。"
)


def build_user_prompt(glossary_pairs, items, json_key="title"):
    """构造一次翻译请求的用户内容：few-shot 术语示例 + 待翻译清单。"""
    lines = []
    if glossary_pairs:
        lines.append("以下为已确定的术语对照，翻译时必须采用这些译法：")
        for src, tgt in glossary_pairs:
            lines.append("  %s → %s" % (src, tgt))
        lines.append("")
    lines.append("请将下列条目逐条翻译为中文，返回一个 JSON 数组，数组元素为 "
                 "{\"%s_trans\": \"译文\", ...} 之外仅含 {\"%s\": 原文} 与 {\"trans\": 译文}，"
                 "顺序与输入一致。" % (json_key, json_key))
    lines.append("输入条目：")
    for it in items:
        src = it.get(json_key) or it.get("name") or it.get("text") or it.get("content") or str(it)
        lines.append("- " + src)
    return "\n".join(lines)