# -*- coding: utf-8 -*-
"""LLM JSON 输出稳健解析：修复常见瑕疵，兼容 markdown 围栏与前后杂质。

原 translate_siliconflow.py / translate_lmstudio.py 中重复实现，此处统一。
"""

import json
import re


def repair_json(text):
    """修复常见 LLM JSON 输出瑕疵：重复/尾随逗号、缺引号等。"""
    # 去掉 ```json ... ``` 外层围栏
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    # 重复逗号 ,, 或 , ,  ->  ,
    text = re.sub(r",\s*,", ",", text)
    # 尾随逗号 ,} / ,]  ->  } / ]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def parse_json_reply(text):
    """从模型回复中稳健提取 JSON。兼容 markdown 代码围栏 / 前后杂质 / 常见瑕疵。"""
    text = repair_json(text.strip())
    try:
        return json.loads(text)
    except Exception:
        pass
    # 提取第一个 {...} 或 [...] 片段
    for ch_open, ch_close in (("{", "}"), ("[", "]")):
        i = text.find(ch_open)
        if i >= 0:
            j = text.rfind(ch_close)
            if j > i:
                try:
                    return json.loads(text[i:j + 1])
                except Exception:
                    continue
    return None


def pick_key(item):
    """从条目 dict 中挑选代表原文的字段名。"""
    for k in ("title", "name", "text", "content"):
        if isinstance(item, dict) and item.get(k):
            return k
    return None