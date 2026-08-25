# -*- coding: utf-8 -*-
"""OpenAI 兼容后端：硅基流动、LM Studio 本地、自定义 OpenAI 平台共用。

三个来源均为「填 base_url + api_key + model 调 /chat/completions」的同一链路，
原 translate_siliconflow.py 与 translate_lmstudio.py 高度重复，此处统一。
不同来源仅默认参数不同，由调用方（GUI / CLI）传入即可。
"""

import json

from translator.core import http
from translator.core import llm_json
from translator.core import glossary

DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"


def list_models(base_url, api_key, timeout=30):
    """获取模型列表。返回 (ok, models 列表或错误)。"""
    url = base_url.rstrip("/") + "/models"
    ok, data = http.get_json(url, {"Authorization": "Bearer %s" % api_key}, timeout=timeout)
    if not ok:
        return False, data
    models = [m.get("id") for m in data.get("data", []) if m.get("id")]
    return True, models


def get_models(base_url, api_key, timeout=30):
    """获取模型列表（旧接口，失败返回占位列表）。"""
    ok, res = list_models(base_url, api_key, timeout=timeout)
    if ok:
        return res
    return ["<无法获取模型列表: %s>" % res]


def test_connection(base_url, api_key, timeout=30):
    """测试连接。返回 (ok, message)。"""
    ok, res = list_models(base_url, api_key, timeout=timeout)
    if ok:
        return True, "连接成功，可用模型 %d 个" % len(res)
    return False, res


def chat_completion(base_url, api_key, model, system, user, timeout=180, max_tokens=4096):
    """调用一次非流式 chat completion，返回 (ok, text 或 error)。"""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": "Bearer %s" % api_key,
        "Content-Type": "application/json",
    }
    code, body = http.post_json(url, payload, headers, timeout=timeout)
    if code != 200:
        return False, "HTTP %s: %s" % (code, body[:300])
    try:
        data = json.loads(body)
        text = data["choices"][0]["message"]["content"]
        return True, text
    except Exception as e:
        return False, "解析响应失败: %s (%s)" % (e, body[:300])


def translate_batch(cfg, entries):
    """一次请求翻译一批条目（<= chunk_size）。

    返回 (ok, payload)：
      ok=True  -> payload 为 {相对索引: 译文} 字典
      ok=False -> payload 为错误信息字符串
    """
    json_key = cfg.get("json_key", "title")
    system = glossary.SYSTEM_PROMPT
    user = glossary.build_user_prompt(cfg["glossary"], entries, json_key)
    ok, raw = chat_completion(cfg["base_url"], cfg["api_key"], cfg["model"], system, user,
                              max_tokens=cfg.get("max_tokens", 4096))
    if not ok:
        return False, "请求失败: %s" % raw
    parsed = llm_json.parse_json_reply(raw)
    if not isinstance(parsed, list):
        if isinstance(parsed, dict):  # 兜底：可能返回单对象
            parsed = [parsed]
        else:
            return False, "无法解析模型输出: %s" % raw[:300]
    result = {}
    for i, it in enumerate(entries):
        key = llm_json.pick_key(it) or json_key
        val = None
        if i < len(parsed) and isinstance(parsed[i], dict):
            p = parsed[i]
            val = (p.get("trans") or p.get("translation") or p.get("译文")
                   or p.get("中文") or p.get(json_key + "_trans"))
        if not val:
            return False, "第%d条(%s)缺失译文，解析结果: %s" % (
                i + 1, (it.get(key) or it.get("_text")),
                json.dumps(parsed, ensure_ascii=False)[:300])
        result[i] = str(val).strip()
    return True, result