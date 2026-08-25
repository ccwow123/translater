# -*- coding: utf-8 -*-
"""彩云小译后端（文本翻译 /v1/translator 接口）。

凭据为「彩云小译访问令牌」（token），放在请求头：
    X-Authorization: token <token>
需先在彩云科技开放平台注册并申请开通小译 Token。
新用户注册可得 100 万字符免费额度（有效期一个月）。
测试可用官方开放 Token：3975l6lr5pcbvidl6jl2（不保证稳定）。
"""

import json
import urllib.error
import urllib.request
import uuid

ENDPOINT = "https://api.interpreter.caiyunai.com/v1/translator"
# 单次请求字符上限（彩云无严格限制，但 preserve 按块会传入较大文本，保守分段）
MAX_Q_CHARS = 2000

# 彩云源语言代码（用于构造 trans_type）
_CAIYUN_SRC = {"zh": "zh", "zh-hant": "zh-Hant", "en": "en", "ja": "ja",
               "ko": "ko", "fr": "fr", "de": "de", "ru": "ru", "es": "es",
               "it": "it", "pt": "pt", "tr": "tr", "vi": "vi"}
# 项目内代码 -> 彩云代码
_LANG = {"zh": "zh", "en": "en", "jp": "ja", "ko": "ko",
         "fr": "fr", "de": "de", "ru": "ru"}


def _map_lang(code):
    return _LANG.get(code, code or "en")


def _do_translate(token, text, trans_type, timeout):
    payload = {
        "source": [text],
        "trans_type": trans_type,
        "request_id": "tr_" + uuid.uuid4().hex[:16],
        "detect": trans_type.startswith("auto"),
        "media": "text",
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Authorization": "token " + token,
        })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return None, "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:300])
    except Exception as e:
        return None, "网络错误: %s" % e
    try:
        data = json.loads(raw)
    except Exception as e:
        return None, "响应非 JSON: %s (%s)" % (e, raw[:300])
    if data.get("message") and data.get("rc") != 0:
        return None, "rc=%s %s" % (data.get("rc"), data.get("message"))
    target = data.get("target")
    if isinstance(target, list):
        return "".join(str(t) for t in target), None
    if isinstance(target, str):
        return target, None
    return None, "无法识别的响应: %s" % raw[:300]


def _pick_trans_type(from_lang, to_lang):
    """按目标语言选择翻译方向；目标为中文用 auto，其余尽力构造 a2b。"""
    if to_lang == "zh":
        return "auto2zh"
    # 目标非中文：仅当源语言也被彩云支持，才构造 from2to
    if from_lang in _CAIYUN_SRC:
        return "%s2%s" % (_CAIYUN_SRC[from_lang], to_lang)
    return None


def translate_one(token, text, from_lang, to_lang, timeout=30,
                  max_q_chars=MAX_Q_CHARS):
    """翻译一段文本，返回 (译文, 错误信息)。译文为空字符串表示原文为空。"""
    text = text if isinstance(text, str) else str(text)
    if not text.strip():
        return "", None
    from_lang = _map_lang(from_lang)
    to_lang = _map_lang(to_lang)
    trans_type = _pick_trans_type(from_lang, to_lang)
    if not trans_type:
        return None, ("彩云小译不支持「%s→%s」方向；"
                      "彩云主要支持翻译为中文，建议使用其他后端。" %
                      (from_lang, to_lang))
    if len(text) > max_q_chars:
        parts = []
        for i in range(0, len(text), max_q_chars):
            dst, err = translate_one(token, text[i:i + max_q_chars],
                                     from_lang, to_lang, timeout, max_q_chars)
            if err:
                return None, err
            parts.append(dst or "")
        return "".join(parts), None
    return _do_translate(token, text, trans_type, timeout)