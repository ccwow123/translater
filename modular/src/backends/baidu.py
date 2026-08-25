# -*- coding: utf-8 -*-
"""百度翻译开放平台后端。

适配两种接口：
  - llm：大模型文本翻译 /ait/api/aiTextTranslate（个人开发者实名认证后送 100W 字符/月 免费额度）
  - general：通用文本翻译 /api/trans/vip/translate

鉴权两种方式（--auth 选择），两种方式均需 APPID：
  - sign   （默认）旧式签名鉴权：appid + 密钥，md5(appid+q+salt+密钥)
  - apikey         新式 API Key 鉴权：请求头 Authorization: Bearer <API Key>，请求体仍需带 appid
"""

import random
import urllib.error
import urllib.parse
import urllib.request
from hashlib import md5

import json

ENDPOINTS = {
    "llm": "https://fanyi-api.baidu.com/ait/api/aiTextTranslate",
    "general": "https://fanyi-api.baidu.com/api/trans/vip/translate",
}
DEFAULT_MODE = "llm"
DEFAULT_FROM = "jp"
DEFAULT_TO = "zh"
# 单次请求 q 上限（官方通用接口 6000 字符，保守取 4500 以兼容 UTF-8 多字节）
MAX_Q_CHARS = 4500
# 免费额度约 1 QPS
DEFAULT_SLEEP = 0.35


def make_md5(s, encoding="utf-8"):
    return md5(s.encode(encoding)).hexdigest()


def translate_one(appid, appkey, text, from_lang, to_lang, endpoint,
                  timeout=30, max_q_chars=MAX_Q_CHARS, auth="sign"):
    """翻译一段文本，返回 (译文, 错误信息)。译文为空字符串表示原文为空。

    auth="sign"  -> 旧式签名鉴权，appid/密钥 必填
    auth="apikey" -> 新式 API Key 鉴权，请求头 Authorization: Bearer <appkey>
    """
    text = text if isinstance(text, str) else str(text)
    if not text.strip():
        return "", None
    if len(text) > max_q_chars:
        # 超长分段翻译后拼接
        parts = []
        for i in range(0, len(text), max_q_chars):
            dst, err = translate_one(appid, appkey, text[i:i + max_q_chars],
                                     from_lang, to_lang, endpoint, timeout,
                                     max_q_chars, auth)
            if err:
                return None, err
            parts.append(dst or "")
        return "".join(parts), None

    headers = {}
    if auth == "apikey":
        headers["Authorization"] = "Bearer %s" % appkey
        payload = {"appid": appid, "q": text, "from": from_lang, "to": to_lang}
    else:
        salt = random.randint(32768, 65536)
        sign = make_md5(appid + text + str(salt) + appkey)
        payload = {"appid": appid, "q": text, "from": from_lang, "to": to_lang,
                   "salt": salt, "sign": sign}
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return None, "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:300])
    except Exception as e:
        return None, "网络错误: %s" % e

    try:
        data = json.loads(body)
    except Exception as e:
        return None, "响应非 JSON: %s (%s)" % (e, body[:300])

    if "error_code" in data and data.get("error_code") not in (None, "", "0"):
        code = data.get("error_code")
        msg = data.get("error_msg", "")
        if str(code) == "54001":
            return None, ("54001: %s — 签名校验失败。若账号使用新式 API Key 鉴权，"
                          "请改用 --auth apikey（APPKEY 处填 API Key）；"
                          "若用签名鉴权，请核对 APPID 与密钥是否匹配、无多余空格。" % msg)
        return None, "%s: %s" % (code, msg)
    if "trans_result" in data:
        parts = [item.get("dst", "") for item in data["trans_result"]]
        return "".join(parts), None
    # 兜底：尝试常见字段
    for key in ("data", "result", "translation"):
        val = data.get(key)
        if isinstance(val, str):
            return val, None
    return None, "无法识别的响应: %s" % body[:300]