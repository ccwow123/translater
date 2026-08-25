# -*- coding: utf-8 -*-
"""保持排版的块级翻译：保留 Markdown 结构符号，只翻译文字内容。

用法：
    from translator.core.preserve import preserve_translate
    dst = preserve_translate(text, translate_fn)   # translate_fn(文本) -> 译文
"""

import re


def split_blocks(text):
    """把文本按行拆成块，返回 [(type, content), ...]。

    type: code / blank / hr / heading / quote / list / table / text
    heading/quote/list 的 content 为 (前缀, 正文)。
    """
    lines = text.split("\n")
    blocks = []
    i = 0
    in_code = False
    code_buf = []
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if in_code:
                code_buf.append(line)
                blocks.append(("code", "\n".join(code_buf)))
                code_buf = []
                in_code = False
            else:
                in_code = True
                code_buf = [line]
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue
        if not stripped:
            blocks.append(("blank", ""))
            i += 1
            continue
        if re.match(r"^(\s*)(-{3,}|\*{3,}|_{3,})\s*$", line):
            blocks.append(("hr", line))
            i += 1
            continue
        m = re.match(r"^(\s*#{1,6}\s+)(.*)$", line)
        if m:
            blocks.append(("heading", (m.group(1), m.group(2))))
            i += 1
            continue
        m = re.match(r"^(\s*>\s?)(.*)$", line)
        if m:
            blocks.append(("quote", (m.group(1), m.group(2))))
            i += 1
            continue
        m = re.match(r"^(\s*(?:[-*+]|\d+[.)])\s+)(.*)$", line)
        if m:
            blocks.append(("list", (m.group(1), m.group(2))))
            i += 1
            continue
        if line.lstrip().startswith("|") and line.count("|") >= 2:
            blocks.append(("table", line))
            i += 1
            continue
        blocks.append(("text", line))
        i += 1
    if in_code and code_buf:
        blocks.append(("code", "\n".join(code_buf)))
    return blocks


def merge_paragraphs(blocks):
    """把连续的 text 块合并成段落（保持段落上下文），其余块原样保留。"""
    merged = []
    buf = []
    for btype, content in blocks:
        if btype == "text":
            buf.append(content)
        else:
            if buf:
                merged.append(("text", "\n".join(buf)))
                buf = []
            merged.append((btype, content))
    if buf:
        merged.append(("text", "\n".join(buf)))
    return merged


def _translate_table_row(line, translate_fn):
    cells = line.split("|")
    out = []
    for cell in cells:
        if not cell.strip():
            out.append(cell)
        elif set(cell.strip()) <= set("-: "):
            out.append(cell)
        else:
            out.append(translate_fn(cell))
    return "|".join(out)


def translate_blocks(blocks, translate_fn, progress_cb=None, cache=None):
    """逐块翻译。progress_cb(done, total) 每块翻译前回调一次（可抛异常中止）；
    cache 为 {块索引: 译文} 字典，命中则跳过该块（用于断点续传）。"""
    out = []
    total = len(blocks)
    for i, (btype, content) in enumerate(blocks):
        if progress_cb:
            progress_cb(i, total)
        if cache is not None and str(i) in cache:
            out.append(cache[str(i)])
            continue
        if btype == "code":
            translated = content
        elif btype == "blank":
            translated = ""
        elif btype == "hr":
            translated = content
        elif btype == "heading":
            prefix, text = content
            translated = prefix + translate_fn(text)
        elif btype == "quote":
            prefix, text = content
            translated = prefix + translate_fn(text)
        elif btype == "list":
            prefix, text = content
            translated = prefix + translate_fn(text)
        elif btype == "table":
            translated = _translate_table_row(content, translate_fn)
        elif btype == "text":
            translated = translate_fn(content)
        out.append(translated)
        if cache is not None:
            cache[str(i)] = translated
    if progress_cb:
        progress_cb(total, total)
    return "\n".join(out)


def preserve_translate(text, translate_fn, progress_cb=None, cache=None):
    """保持排版的翻译入口。translate_fn(文本) -> 译文。"""
    blocks = split_blocks(text)
    blocks = merge_paragraphs(blocks)
    return translate_blocks(blocks, translate_fn, progress_cb, cache)


def segment_counts(src, dst):
    """分别统计原文 / 译文在保持排版后的可见结构块数量。

    用于校验 AI 是否吞段或合并段：连续 text 段落被 merge，其余标记块
    （代码 / 标题 / 引用 / 列表 / 表格 / 分隔线）各计一个独立块，空行不计。
    """
    def count(text):
        blocks = merge_paragraphs(split_blocks(text))
        return sum(1 for btype, _ in blocks if btype != "blank")
    return count(src), count(dst)