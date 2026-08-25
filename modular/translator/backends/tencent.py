# -*- coding: utf-8 -*-
"""腾讯云机器翻译 TMT 后端（文本翻译 TextTranslate 接口）。

使用腾讯云 v3 签名（TC3-HMAC-SHA256），凭据为云 API 密钥对：
  - SecretId
  - SecretKey
需要先在腾讯云控制台开通「机器翻译」服务，并在「访问管理-API密钥管理」创建密钥。
免费额度：每月 500 万字符。
"""

import hashlib
import hmac
import json
import urllib.error
import urllib.request
from datetime import datetime

HOST = "tmt.tencentcloudapi.com"
ACTION = "TextTranslate"
VERSION = "2018-03-21"
# 腾讯云地域（机器翻译支持地域），默认华南广州
DEFAULT_REGION = "ap-guangzhou"
# 单次请求字符上限（官方 6000，保守取 5000）
MAX_Q_CHARS = 5000

# 项目内语言代码 -> 腾讯云语言代码
_LANG = {"zh": "zh", "en": "en", "jp": "ja", "ko": "ko",
         "fr": "fr", "de": "de", "ru": "ru"}


def _map_lang(code):
    return _LANG.get(code, code or "en")


def _hmac_sha256(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _build_authorization(secret_id, secret_key, timestamp, date, body):
    canonical_headers = (
        "content-type:application/json; charset=utf-8\n"
        "host:%s\n"
        "x-tc-action:%s\n" % (HOST, ACTION.lower()))
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(body).hexdigest()
    canonical_request = "POST\n/\n\n%s\n%s\n%s" % (
        canonical_headers, signed_headers, hashed_payload)
    credential_scope = "%s/tmt/tc3_request" % date
    hashed_canonical = hashlib.sha256(
        canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = "TC3-HMAC-SHA256\n%s\n%s\n%s" % (
        timestamp, credential_scope, hashed_canonical)
    secret_date = _hmac_sha256(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, "tmt")
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()
    return ("TC3-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s"
            % (secret_id, credential_scope, signed_headers, signature))


def _do_translate(secret_id, secret_key, text, from_lang, to_lang, region,
                  timeout):
    payload = {"SourceText": text, "Source": from_lang,
               "Target": to_lang, "ProjectId": 0}
    body = json.dumps(payload, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    now = datetime.utcnow()
    date = now.strftime("%Y-%m-%d")
    timestamp = str(int(now.timestamp()))
    req = urllib.request.Request(
        "https://" + HOST, data=body, method="POST", headers={
            "Content-Type": "application/json; charset=utf-8",
            "Host": HOST,
            "X-TC-Action": ACTION,
            "X-TC-Version": VERSION,
            "X-TC-Region": region,
            "X-TC-Timestamp": timestamp,
            "X-TC-Signature": _build_authorization(
                secret_id, secret_key, timestamp, date, body),
            "X-TC-SignedHeaders": "content-type;host;x-tc-action",
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
    resp = data.get("Response", {})
    err = resp.get("Error")
    if err:
        return None, "%s: %s" % (err.get("Code"), err.get("Message"))
    target = resp.get("TargetText")
    if target is None:
        return None, "无法识别的响应: %s" % raw[:300]
    return target, None


def translate_one(secret_id, secret_key, text, from_lang, to_lang,
                  region=DEFAULT_REGION, timeout=30,
                  max_q_chars=MAX_Q_CHARS):
    """翻译一段文本，返回 (译文, 错误信息)。译文为空字符串表示原文为空。"""
    text = text if isinstance(text, str) else str(text)
    if not text.strip():
        return "", None
    from_lang = _map_lang(from_lang)
    to_lang = _map_lang(to_lang)
    if len(text) > max_q_chars:
        parts = []
        for i in range(0, len(text), max_q_chars):
            dst, err = translate_one(secret_id, secret_key, text[i:i + max_q_chars],
                                     from_lang, to_lang, region, timeout,
                                     max_q_chars)
            if err:
                return None, err
            parts.append(dst or "")
        return "".join(parts), None
    return _do_translate(secret_id, secret_key, text, from_lang, to_lang,
                         region, timeout)