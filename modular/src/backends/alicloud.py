# -*- coding: utf-8 -*-
"""阿里云机器翻译 alimt 后端（通用文本翻译 TranslateGeneral 接口）。

使用阿里云 RPC 签名机制（HMAC-SHA1），凭据为云账号 API 密钥对：
  - AccessKey ID
  - AccessKey Secret
需要先在阿里云开通「机器翻译」，并在「AccessKey 管理」创建密钥。
免费额度：新用户每月 100 万字符。
"""

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

ENDPOINT = "https://mt.aliyuncs.com"
ACTION = "TranslateGeneral"
VERSION = "2018-10-12"
# 单次请求字符上限（保守，官方无严格限制但过长易失败）
MAX_Q_CHARS = 3000

# 项目内语言代码 -> 阿里云语言代码
_LANG = {"zh": "zh", "en": "en", "jp": "ja", "ko": "ko",
         "fr": "fr", "de": "de", "ru": "ru"}


def _map_lang(code):
    return _LANG.get(code, code or "en")


def _pct_encode(s):
    """阿里云 RPC 签名专用百分号编码。"""
    s = urllib.parse.quote(str(s), safe="")
    s = s.replace("+", "%20").replace("*", "%2A").replace("%7E", "~")
    return s


def _build_sign_string(access_key_secret, params):
    """按 key 字典序拼装授权串并计算签名。"""
    items = sorted(params.items())
    canon = "&".join("%s=%s" % (_pct_encode(k), _pct_encode(v))
                     for k, v in items)
    string_to_sign = ("POST&%2F&" + _pct_encode(canon))
    digest = hmac.new(access_key_secret.encode("utf-8"),
                      string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _do_translate(access_key_id, access_key_secret, text, from_lang, to_lang,
                  timeout):
    now = datetime.utcnow()
    params = {
        "Action": ACTION,
        "AccessKeyId": access_key_id,
        "Format": "JSON",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": str(uuid.uuid4()),
        "SignatureVersion": "1.0",
        "Timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": VERSION,
        # 业务参数
        "FormatType": "text",
        "Scene": "general",
        "SourceLanguage": from_lang,
        "TargetLanguage": to_lang,
        "SourceText": text,
    }
    params["Signature"] = _build_sign_string(access_key_secret, params)
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                 headers={"Content-Type":
                                          "application/x-www-form-urlencoded"})
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
    code = data.get("Code")
    if code not in (None, "200", 200):
        return None, "Code=%s Message=%s" % (code, data.get("Message"))
    translated = data.get("Translated") or (data.get("Data") or {}).get("Translated")
    if translated is None:
        return None, "无法识别的响应: %s" % raw[:300]
    return translated, None


def translate_one(access_key_id, access_key_secret, text, from_lang, to_lang,
                  timeout=30, max_q_chars=MAX_Q_CHARS):
    """翻译一段文本，返回 (译文, 错误信息)。译文为空字符串表示原文为空。"""
    text = text if isinstance(text, str) else str(text)
    if not text.strip():
        return "", None
    from_lang = _map_lang(from_lang)
    to_lang = _map_lang(to_lang)
    if len(text) > max_q_chars:
        parts = []
        for i in range(0, len(text), max_q_chars):
            dst, err = translate_one(access_key_id, access_key_secret,
                                     text[i:i + max_q_chars],
                                     from_lang, to_lang, timeout, max_q_chars)
            if err:
                return None, err
            parts.append(dst or "")
        return "".join(parts), None
    return _do_translate(access_key_id, access_key_secret, text,
                         from_lang, to_lang, timeout)