# -*- coding: utf-8 -*-
"""通用 HTTP 传输层：POST JSON / GET，供各 OpenAI 兼容后端复用。

说明：本工具仅调用翻译/AI API（非 TLS 拦截型抓站），故使用标准库 urllib。
"""

import json
import urllib.request
import urllib.error


def post_json(url, payload, headers, timeout=180):
    """POST JSON，返回 (状态码, 响应文本)。网络/超时返回 (-1, 错误信息)。"""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # 网络/超时等
        return -1, str(e)


def get_json(url, headers, timeout=30):
    """GET JSON 列表端点，返回 (ok, data 或 error文本)。"""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return False, "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:200])
    except Exception as e:
        return False, str(e)