# -*- coding: utf-8 -*-
"""文件读写工具：带重试的原子 JSON 写入，规避 Windows 文件占用。"""

import json
import os
import time


def write_json_atomic(path, data, retries=3, delay=0.2):
    """原子写入 JSON：先写同目录临时文件再 os.replace 替换，失败自动重试。

    直接 open(path, "w") 在 Windows 下可能因杀毒/索引等进程短暂占用而报
    PermissionError；先写临时文件再原子替换，即使目标被占用也不会损坏原文件。
    """
    tmp = path + ".tmp"
    for attempt in range(retries + 1):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
            return
        except OSError:
            if attempt >= retries:
                raise
            time.sleep(delay)
