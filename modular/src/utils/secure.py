# -*- coding: utf-8 -*-
"""Windows DPAPI 加密存储：用于本地保存 API Key 等敏感信息。

使用系统 CryptProtectData/CryptUnprotectData，密文绑定当前 Windows 用户，
无需额外依赖、无需密码提示。仅支持 Windows；非 Windows 环境返回不可用。
"""

import base64
import ctypes
from ctypes import wintypes


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte))]


try:
    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _DPAPI_AVAILABLE = True
except Exception:
    _DPAPI_AVAILABLE = False


def _blob_from_bytes(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))


def _bytes_from_blob(blob):
    if not blob.pbData or blob.cbData == 0:
        return b""
    return ctypes.string_at(blob.pbData, blob.cbData)


def encrypt_text(plaintext):
    """加密字符串，返回 base64 密文；失败抛异常。"""
    if not _DPAPI_AVAILABLE:
        raise RuntimeError("DPAPI 不可用（非 Windows 环境）")
    data = plaintext.encode("utf-8")
    blob_in = _blob_from_bytes(data)
    blob_out = DATA_BLOB()
    if not _crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None,
                                     None, 0, ctypes.byref(blob_out)):
        raise ctypes.WinError()
    try:
        return base64.b64encode(_bytes_from_blob(blob_out)).decode("ascii")
    finally:
        _kernel32.LocalFree(blob_out.pbData)


def decrypt_text(b64):
    """解密 base64 密文，返回原文；失败返回 None。"""
    if not _DPAPI_AVAILABLE:
        return None
    try:
        enc = base64.b64decode(b64)
    except Exception:
        return None
    blob_in = _blob_from_bytes(enc)
    blob_out = DATA_BLOB()
    if not _crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None,
                                       None, 0, ctypes.byref(blob_out)):
        return None
    try:
        return _bytes_from_blob(blob_out).decode("utf-8")
    except Exception:
        return None
    finally:
        _kernel32.LocalFree(blob_out.pbData)