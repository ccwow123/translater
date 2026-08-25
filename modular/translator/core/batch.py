# -*- coding: utf-8 -*-
"""批处理流水线通用件：输入解析、断点缓存、进度与重试循环。

原 baidu / siliconflow / lmstudio 三个脚本各自重复实现，这里抽出共享部分。
"""

import json
import os
import sys

from translator.core.llm_json import pick_key


def load_entries(input_path, json_key="title"):
    """读取输入文件为条目列表。

    支持两种输入：
      - JSON 数组（取含原文字段的 dict）
      - 纯文本行（每行一条，作为 {"_text": 行}）
    返回 (entries, effective_json_key)。
    """
    raw_text = ""
    if os.path.exists(input_path):
        with open(input_path, encoding="utf-8") as f:
            raw_text = f.read().strip()
    entries = []
    if raw_text.startswith("["):
        try:
            data = json.loads(raw_text)
            for it in data:
                if isinstance(it, dict) and pick_key(it):
                    entries.append(it)
        except Exception as e:
            sys.exit("输入 JSON 解析失败: %s" % e)
        if not entries:
            sys.exit("输入 JSON 中未找到含原文的条目标题字段(%s)" % json_key)
    elif raw_text:
        entries = [{"_text": line} for line in raw_text.splitlines() if line.strip()]
        json_key = "_text"
    else:
        sys.exit("输入文件为空或不存在: %s" % input_path)
    return entries, json_key


def slice_entries(entries, start, limit):
    """按 --start / --limit 截取条目范围。"""
    if start:
        entries = entries[start:]
    if limit:
        entries = entries[:limit]
    return entries


def resolve_output_path(input_path, output_arg, suffix):
    """求出输出路径；缺省为 <input同名>_<suffix>.json。"""
    if output_arg:
        return output_arg
    base = os.path.splitext(input_path)[0]
    return base + "_%s.json" % suffix


def load_done(out_path):
    """读取断点续传缓存；不存在或损坏返回空 dict。"""
    done = {}
    if os.path.exists(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                done = json.load(f)
        except Exception:
            done = {}
    return done


def flush_done(out_path, done):
    """把缓存写回输出文件。"""
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(done, f, ensure_ascii=False, indent=1)


def build_pending(entries, json_key, done):
    """返回待翻译条目 [(index, item, src)]，已命中断点缓存的跳过。"""
    pending = []
    for idx, it in enumerate(entries):
        src = it.get(json_key) or it.get("_text")
        if src in done:
            continue
        pending.append((idx, it, src))
    return pending


def run_single(pending, done, out_path, translate, retries=3, sleep=0.35):
    """逐条翻译主循环（百度链路）。translate(src) -> (dst, err)。"""
    fail_count = 0
    for i, (idx, it, src) in enumerate(pending):
        dst, err = translate(src)
        if err is None:
            done[src] = dst or ""
            print("[%d/%d] %s -> %s" % (i + 1, len(pending), src, done[src]), flush=True)
            flush_done(out_path, done)
            fail_count = 0
        else:
            fail_count += 1
            print("[%d/%d] 失败: %s" % (i + 1, len(pending), err), flush=True)
            if fail_count >= retries:
                print("连续失败 %d 次，停止。可稍后重跑继续（断点已保存）。" % fail_count,
                      file=sys.stderr)
                break
        if sleep:
            import time
            time.sleep(sleep)
    print("\n完成，结果已保存: %s" % out_path, flush=True)


def run_batch(pending, done, out_path, translate_batch, chunk_size=10,
              sleep=0.0, retries=3):
    """分批翻译主循环（OpenAI 兼容链路）。translate_batch(items) -> (ok, payload)。"""
    fail_count = 0
    i = 0
    while i < len(pending):
        batch = pending[i:i + chunk_size]
        items = [it for _, it, _ in batch]
        ok, res = translate_batch(items)
        if ok:
            for j, (idx, it, src) in enumerate(batch):
                done[src] = res[j] if isinstance(res, dict) else None
            for j, (idx, it, src) in enumerate(batch):
                print("[%d/%d] %s -> %s" % (i + 1, len(pending), src, done.get(src)), flush=True)
            flush_done(out_path, done)
            i += chunk_size
            fail_count = 0
        else:
            fail_count += 1
            msg = res if isinstance(res, str) else "未知错误"
            print("批次 %d 失败: %s" % (i // chunk_size + 1, msg), flush=True)
            if fail_count >= retries:
                print("连续失败 %d 次，停止。可稍后重跑继续（断点已保存）。" % fail_count,
                      file=sys.stderr)
                break
            if sleep:
                import time
                time.sleep(2)
        if sleep:
            import time
            time.sleep(sleep)
    print("\n完成，结果已保存: %s" % out_path, flush=True)