# -*- coding: utf-8 -*-
"""词级对照工具：分词、词对齐、字符偏移与 Tk 索引互转。

供双向编辑器与主界面悬停「词对照高亮」复用。
"""

import re

# 中文连续字块 / 英文单词（含连字符、撇号、小数点）
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+(?:['-.][A-Za-z0-9]+)*")


def word_tokens(text):
    """把文本切成词/词组的 (start, end, word)。中文按连续字块，英文按单词。"""
    return [(m.start(), m.end(), m.group()) for m in _TOKEN_RE.finditer(text)]


def _norm(t):
    t = t.lower()
    if re.fullmatch(r"\d+(?:[.,]\d+)*", t):
        return "‹NUM›"
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", t)


def align_tokens(src, dst):
    """词对齐：锚点（完全匹配/数字）+ 分段线性插值，返回 {src_idx: [dst_idx]}。"""
    n, m = len(src), len(dst)
    mapping = {}
    if n == 0 or m == 0:
        return mapping
    anchors = []
    used = set()
    for i, t in enumerate(src):
        nt = _norm(t)
        for j, u in enumerate(dst):
            if j in used:
                continue
            if nt and _norm(u) == nt:
                anchors.append((i, j))
                used.add(j)
                break
    segs = [(-1, -1)] + anchors + [(n, m)]
    for k in range(len(segs) - 1):
        (ia, ja), (ib, jb) = segs[k], segs[k + 1]
        di, dj = ib - ia, jb - ja
        for i in range(ia + 1, ib):
            if di > 0:
                jj = ja + int(round((i - ia) * dj / di))
            else:
                jj = ja
            jj = max(-1, min(jb - 1 if jb > ja else jb, jj))
            if 0 <= jj < m:
                mapping.setdefault(i, []).append(jj)
    for i, j in anchors:
        mapping.setdefault(i, []).append(j)
    return mapping


def char_to_index(text, offset):
    """字符线性偏移 → Tk 文本索引 "行.列"。"""
    line = text[:offset].count("\n") + 1
    last = text.rfind("\n", 0, offset)
    col = offset - (last + 1)
    return "%d.%d" % (line, col)


def index_to_char(text, tk_index):
    """Tk 文本索引 "行.列" → 字符线性偏移。"""
    try:
        line, col = tk_index.split(".")
        line, col = int(line), int(col)
    except (ValueError, TypeError):
        return None
    lines = text.split("\n")
    return sum(len(l) + 1 for l in lines[:line - 1]) + col


def token_at(toks, char):
    """返回包含字符偏移 char 的 token 序号，未命中返回 None。"""
    if char is None:
        return None
    for k, (s, e, _) in enumerate(toks):
        if s <= char < e:
            return k
    return None