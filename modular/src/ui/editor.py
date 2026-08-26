# -*- coding: utf-8 -*-
"""双向配对编辑窗口：原文/译文逐段配对，双向可编辑，增删同步。

由主窗口「双向编辑」按钮打开，复用主窗口的翻译配置。
"""

import os
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from src.constants import (BG, FG, MUTED, ACCENT, ACCENT_DARK, ACCENT_LIGHT,
                                  BORDER, HEADER_BG, STATUS_BG, LANG_NAMES)
from src.core.preserve import preserve_translate
from src.ui.theme import StyleKit
from src.ui import wordalign as wa


class BidirectionalEditor(tk.Toplevel):
    # 常见英文缩写（末尾带点，切句时不应在点号处断开）
    _ABBR = {
        "mr", "mrs", "ms", "miss", "dr", "prof", "sr", "jr", "st",
        "vs", "etc", "inc", "ltd", "co", "corp", "no", "vol", "fig",
        "e.g", "i.e", "eg", "ie", "dept", "appx", "par", "apt", "mm",
        "cm", "km", "kg", "approx", "est", "hon", "mrs",
    }

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("双向配对编辑")
        self.geometry("1100x760")
        self.minsize(760, 520)

        self.segments = []   # [{"src": str, "dst": str}, ...]
        self.cards = []      # [{"frame":..., "src_text":..., "dst_text":...}, ...]
        self.loaded_path = None
        self.q = queue.Queue()
        self.busy = False
        self._by_sentence = True  # 默认按句子；遇到 Markdown 源会自动切回段落
        self._focus_text = None   # 最近聚焦的原文/译文文本框

        StyleKit(self)
        self._build_ui()
        self.after(100, self._poll)
        self._auto_load()

    def _style_text(self, w):
        StyleKit(self).style_text(w)

    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}
        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        self._toolbar = bar
        self._toolbar_items = [
            ("加载文件", self._load_file, None),
            ("加载原文+译文", self._load_pair_dialog, None),
            ("句子分段", self._toggle_sentence, None),
            ("翻译", self._retranslate_all, "Accent.TButton"),
            ("反向翻译", self._reverse_all, "Accent.TButton"),
            ("保存/导出", self._export, None),
        ]
        self._toolbar_btns = []
        for text, cmd, style in self._toolbar_items:
            b = ttk.Button(bar, text=text, command=cmd, style=style or "TButton")
            self._toolbar_btns.append(b)
        bar.bind("<Configure>", self._relayout_toolbar)
        self._relayout_toolbar()

        status = tk.Frame(self, bg=STATUS_BG, height=30)
        status.pack(fill="x")
        status.pack_propagate(False)
        self.status_var = tk.StringVar(value="就绪")
        tk.Label(status, textvariable=self.status_var, bg=STATUS_BG, fg=MUTED,
                 font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x", padx=10, pady=6)

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, **pad)
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._inner_win = self.canvas.create_window((0, 0), window=self.inner,
                                                    anchor="nw", width=400)
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self._inner_win,
                                                             width=e.width))
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.inner.bind("<MouseWheel>",
                        lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

    def _relayout_toolbar(self, event=None):
        """工具栏自适应：窗口变窄时自动换行，保证按钮不被截断。"""
        if getattr(self, "_relayouting", False):
            return
        self._relayouting = True
        try:
            for b in self._toolbar_btns:
                b.grid_forget()
            self._toolbar.update_idletasks()
            widths = [b.winfo_reqwidth() for b in self._toolbar_btns]
            avail = self._toolbar.winfo_width()
            if avail < 100:
                avail = sum(widths) + (len(widths) - 1) * 6 + 40
            row = col = 0
            used = 0
            gap = 6
            for i, b in enumerate(self._toolbar_btns):
                if used > 0 and used + gap + widths[i] > avail:
                    row += 1
                    col = 0
                    used = 0
                b.grid(row=row, column=col, padx=(0, gap), pady=2, sticky="w")
                col += 1
                used += widths[i] + gap
            self._toolbar.columnconfigure(0, weight=1)
        finally:
            self._relayouting = False

    def _canvas_scroll(self, event):
        """把鼠标滚轮转发到画布，实现全局滚动（并禁用文本框自身滚动）。"""
        self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _bind_global_wheel(self, widget):
        widget.bind("<MouseWheel>", self._canvas_scroll)

    def _remember_focus(self, event):
        self._focus_text = event.widget

    # ---------------------------------------------------- 词对齐（悬停对照）
    def _word_tokens(self, text):
        return wa.word_tokens(text)

    def _align_tokens(self, src, dst):
        return wa.align_tokens(src, dst)

    def _char_to_index(self, text, offset):
        return wa.char_to_index(text, offset)

    def _index_to_char(self, text, tk_index):
        return wa.index_to_char(text, tk_index)

    def _token_at(self, toks, char):
        return wa.token_at(toks, char)

    def _locate_card(self, widget):
        for card in self.cards:
            if widget is card["src_text"]:
                return card, "src"
            if widget is card["dst_text"]:
                return card, "dst"
        return None, None

    _LINK = "#9FC1FF"

    def _on_hover(self, event):
        """悬停某词 → 高亮对侧对应词，同时自身亮起作即时反馈。"""
        card, side = self._locate_card(event.widget)
        if not card:
            return
        w = event.widget
        card["src_text"].tag_remove("link", "1.0", "end")
        card["dst_text"].tag_remove("link", "1.0", "end")
        oth = card["dst_text"] if side == "src" else card["src_text"]
        cur_toks = card["src_toks"] if side == "src" else card["dst_toks"]
        oth_toks = card["dst_toks"] if side == "src" else card["src_toks"]
        cur_text = card["seg_text"]["src"] if side == "src" else card["seg_text"]["dst"]
        oth_text = card["seg_text"]["dst"] if side == "src" else card["seg_text"]["src"]
        try:
            idx = w.index("@%d,%d" % (event.x, event.y))
        except (tk.TclError, ValueError):
            return
        char = self._index_to_char(cur_text, idx)
        tid = self._token_at(cur_toks, char)
        if tid is None:
            return
        st, en, _ = cur_toks[tid]
        w.tag_add("link", self._char_to_index(cur_text, st),
                  self._char_to_index(cur_text, en))   # 自身即时反馈
        for idx2 in card["aligned"].get(tid, []) if side == "src" else card["dst_to_src"].get(tid, []):
            if idx2 >= len(oth_toks):
                continue
            s2, e2, _ = oth_toks[idx2]
            oth.tag_add("link", self._char_to_index(oth_text, s2),
                        self._char_to_index(oth_text, e2))

    def _on_leave(self, event):
        card, _ = self._locate_card(event.widget)
        if card:
            card["src_text"].tag_remove("link", "1.0", "end")
            card["dst_text"].tag_remove("link", "1.0", "end")

    # ------------------------------------------------------------ 数据
    def _split_paragraphs(self, text):
        return [p.strip("\n") for p in re.split(r"\n\s*\n", text) if p.strip()]

    def _sentence_pieces(self, text):
        """把文本切成句子。规则：

        - 中文宽标点（。？！…）无条件断句；
        - ASCII 的 .!? 仅当「后随空白 + 大写/数字/引号」才断，避免拆 3.14；
        - 缩写（Dr.、U.S. 等）结尾处不拆，与后续合并；
        - 纯标点碎片并入上一句（处理 ！？ 连用、... 等）。
        """
        s = re.sub(r"\s*\n\s*", " ", text).strip()
        if not s:
            return []
        s = re.sub(r"(?<=[。？！…])", "\x01", s)              # 中文无条件断
        s = re.sub(r"(?<=[.!?]) (?=[A-Z0-9（(【])", "\x01 ", s)  # 英文需空格+大写
        pieces = [p.strip() for p in s.split("\x01")]
        out = []
        for p in pieces:
            if not p:
                continue
            if not re.search(r"[\w\u4e00-\u9fff]", p):        # 纯标点碎片并入上句
                if out:
                    out[-1] += p
                else:
                    out.append(p)
            elif out and self._is_abbrev_tail(out[-1]):       # 上句以缩写结尾→合并
                out[-1] += " " + p
            else:
                out.append(p)
        return out

    def _is_abbrev_tail(self, piece):
        m = re.search(r"([A-Za-z][A-Za-z.\u2019']*)$", piece)
        if not m:
            return False
        token = m.group(1)
        base = token.rstrip(".")
        if base.lower() in self._ABBR:
            return True
        parts = [p for p in base.split(".") if p]
        return (len(parts) > 1 and all(p.isalpha() and len(p) <= 4 for p in parts)
                and base.isupper())

    def _chunk_text(self, text):
        """按当前分段粒度切分文本：段落 或 句子。"""
        paras = self._split_paragraphs(text)
        if not self._by_sentence:
            return paras
        out = []
        for p in paras:
            out.extend(self._sentence_pieces(p))
        return out

    def _looks_markdown(self, text):
        """轻量判断文本是否带 Markdown 结构特征。"""
        for line in text.splitlines()[:40]:
            line = line.strip()
            if (line.startswith("#") or line.startswith("```")
                    or line.startswith(">") or line.startswith("|")
                    or re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line)):
                return True
        return False

    def _set_split_mode(self, path=None, text=""):
        """根据来源智能化选择分段粒度：Markdown 按段落，普通文段按句子。"""
        if path and path.lower().endswith((".md", ".markdown", ".mdown")):
            self._by_sentence = False   # Markdown 文件 → 段落
            return
        if self._looks_markdown(text):
            self._by_sentence = False   # 内容带 Markdown 结构 → 段落
        else:
            self._by_sentence = True    # 普通文段 → 句子

    def _toggle_sentence(self):
        """在「按段落 / 按句子」分段之间切换，并基于当前内容重建。"""
        self._by_sentence = not self._by_sentence
        src_full = "\n\n".join(s["src"] for s in self.segments)
        dst_full = "\n\n".join(s["dst"] for s in self.segments)
        src_parts = self._chunk_text(src_full)
        dst_parts = self._chunk_text(dst_full)
        n = max(len(src_parts), len(dst_parts))
        self.segments = [
            {"src": src_parts[i] if i < len(src_parts) else "",
             "dst": dst_parts[i] if i < len(dst_parts) else ""}
            for i in range(n)]
        self._rebuild()
        if self._by_sentence:
            self._check_pair_consistency()
        else:
            self.status_var.set("已按段落分段，共 %d 段" % len(self.segments))

    def _check_pair_consistency(self):
        """句子分段后校验每个配对原文/译文的句数是否一致，提示可能错位的段。"""
        bad = []
        for i, seg in enumerate(self.segments, start=1):
            src = seg["src"].strip()
            dst = seg["dst"].strip()
            if not src or not dst:
                continue
            ns = self._count_sentences(src)
            nd = self._count_sentences(dst)
            if ns != nd:
                bad.append((i, ns, nd))
        if bad:
            det = "、".join("#%d(原文%d句/译文%d句)" % (i, s, d) for i, s, d in bad[:20])
            if len(bad) > 20:
                det += " …"
            self.status_var.set("已按句子分段，但 %d 段原文/译文句数不一致" % len(bad))
            messagebox.showwarning(
                "分段不一致",
                "%d 段原文与译文的句子数不一致（分段后可能错位）：\n%s\n\n"
                "建议先在各段内核对内容，词序或标点差异通常需人工对齐。"
                % (len(bad), det))
        else:
            self.status_var.set("已按句子分段，原文/译文句数一致 ✓")

    def _count_sentences(self, text):
        return len(self._sentence_pieces(text))

    def _automatch_translation(self, src_path):
        """在同目录探测与原文配对的译文文件（如 a.md ↔ a-中文翻译.md）。"""
        d = os.path.dirname(src_path) or "."
        base = os.path.splitext(os.path.basename(src_path))[0]
        ext = os.path.splitext(src_path)[1]
        try:
            files = os.listdir(d)
        except OSError:
            return None
        for f in files:
            if f == os.path.basename(src_path):
                continue
            ffull = os.path.join(d, f)
            if not os.path.isfile(ffull) or not f.lower().endswith(ext.lower()):
                continue
            fb = os.path.splitext(f)[0]
            if (fb.startswith(base) and fb != base
                    and ("翻译" in fb or "translation" in f.lower())):
                return ffull
        return None

    def _load_file(self):
        path = filedialog.askopenfilename(
            title="选择待翻译文件",
            filetypes=[("文本文件", "*.md *.txt *.json"), ("所有文件", "*.*")])
        if not path:
            return
        dst = self._automatch_translation(path)
        if dst:
            self._load_pair(path, dst)
            self.status_var.set("已加载原文+译文成组：%s ↔ %s"
                                % (os.path.basename(path), os.path.basename(dst)))
            return
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(path, encoding="utf-8-sig") as f:
                content = f.read()
        except Exception as e:
            messagebox.showerror("读取失败", str(e))
            return
        self.loaded_path = path
        self._set_split_mode(path, content)
        self.segments = [{"src": p, "dst": ""} for p in self._chunk_text(content)]
        self._rebuild()
        self.status_var.set("未找到匹配译文，已加载原文 %d 段: %s"
                            % (len(self.segments), os.path.basename(path)))

    def _guess_translation_path(self, src_path):
        d = os.path.dirname(src_path)
        stem, ext = os.path.splitext(os.path.basename(src_path))
        lang = LANG_NAMES.get(self.app.to_var.get().strip().lower(),
                              self.app.to_var.get().strip())
        return os.path.join(d, "%s-%s翻译%s" % (stem, lang, ext))

    def _auto_load(self):
        """打开时直接加载主窗口已翻译的结果或已载入的原文。

        优先取主窗口内存中的原文+译文（刚翻译完尚未落盘也能带入），
        否则自动配对原文件同目录的译文文件，最后退回仅加载原文。
        """
        inn = self.app.in_text.get("1.0", "end-1c").strip()
        out = self.app.out_text.get("1.0", "end-1c").strip()
        if out:
            self.loaded_path = self.app.loaded_path
            self._set_split_mode(self.app.loaded_path, inn)
            src_paras = self._chunk_text(inn)
            dst_paras = self._chunk_text(out)
            n = max(len(src_paras), len(dst_paras))
            self.segments = [
                {"src": src_paras[i] if i < len(src_paras) else "",
                 "dst": dst_paras[i] if i < len(dst_paras) else ""}
                for i in range(n)]
            self._rebuild()
            self.status_var.set("已载入主窗口翻译结果，共 %d 段" % len(self.segments))
            return
        src = self.app.loaded_path
        if not src:
            return
        dst = self._guess_translation_path(src)
        if os.path.exists(dst):
            self._load_pair(src, dst)
        else:
            try:
                with open(src, encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(src, encoding="utf-8-sig") as f:
                    content = f.read()
            except Exception as e:
                messagebox.showerror("读取失败", str(e))
                return
            self.loaded_path = src
            self._set_split_mode(src, content)
            self.segments = [{"src": p, "dst": ""} for p in self._chunk_text(content)]
            self._rebuild()
            self.status_var.set("已加载原文 %d 段: %s" % (len(self.segments), os.path.basename(src)))

    def _load_pair_dialog(self):
        src_path = filedialog.askopenfilename(
            title="选择原文文件",
            filetypes=[("文本文件", "*.md *.txt *.json"), ("所有文件", "*.*")])
        if not src_path:
            return
        dst_path = filedialog.askopenfilename(
            title="选择译文文件",
            filetypes=[("文本文件", "*.md *.txt *.json"), ("所有文件", "*.*")])
        if not dst_path:
            return
        self._load_pair(src_path, dst_path)

    def _load_pair(self, src_path, dst_path):
        try:
            with open(src_path, encoding="utf-8") as f:
                src_content = f.read()
            try:
                with open(dst_path, encoding="utf-8") as f:
                    dst_content = f.read()
            except UnicodeDecodeError:
                with open(dst_path, encoding="utf-8-sig") as f:
                    dst_content = f.read()
        except Exception as e:
            messagebox.showerror("读取失败", str(e))
            return
        self._set_split_mode(src_path, src_content)
        src_paras = self._chunk_text(src_content)
        dst_paras = self._chunk_text(dst_content)
        n = max(len(src_paras), len(dst_paras))
        segments = []
        for i in range(n):
            segments.append({
                "src": src_paras[i] if i < len(src_paras) else "",
                "dst": dst_paras[i] if i < len(dst_paras) else "",
            })
        self.loaded_path = src_path
        self.segments = segments
        self._rebuild()
        self.status_var.set("已加载原文+译文，共 %d 段" % len(segments))

    def _sync_from_widgets(self):
        for seg, card in zip(self.segments, self.cards):
            seg["src"] = card["src_text"].get("1.0", "end-1c")
            seg["dst"] = card["dst_text"].get("1.0", "end-1c")

    def _rebuild(self):
        for card in self.cards:
            card["frame"].destroy()
        self.cards = []
        for i, seg in enumerate(self.segments):
            self._add_card(seg, i)

    def _add_card(self, seg, index):
        card = ttk.Frame(self.inner, relief="solid", borderwidth=1, padding=6)
        card.pack(fill="x", padx=4, pady=4)
        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=0)
        card.columnconfigure(2, weight=1)

        head = ttk.Frame(card)
        head.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Label(head, text="段 %d" % (index + 1), foreground=ACCENT,
                  font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        ttk.Button(head, text="删除段", command=lambda s=seg: self._delete(s)).pack(side="right", padx=(4, 0))
        ttk.Button(head, text="插入段", command=lambda s=seg: self._insert_after(s)).pack(side="right", padx=4)

        ttk.Label(card, text="原文（可编辑）", foreground=MUTED).grid(row=1, column=0, sticky="w")
        ttk.Label(card, text="译文（可编辑）", foreground=MUTED).grid(row=1, column=2, sticky="w")
        src_text = tk.Text(card, wrap="word", height=4, width=28, font=("Microsoft YaHei UI", 10))
        dst_text = tk.Text(card, wrap="word", height=4, width=28, font=("Microsoft YaHei UI", 10))
        StyleKit(self).style_text(src_text)
        StyleKit(self).style_text(dst_text)
        self._bind_global_wheel(src_text)
        self._bind_global_wheel(dst_text)
        src_text.bind("<FocusIn>", self._remember_focus)
        dst_text.bind("<FocusIn>", self._remember_focus)
        src_text.grid(row=2, column=0, sticky="nsew", padx=2)
        dst_text.grid(row=2, column=2, sticky="nsew", padx=2)

        mid = ttk.Frame(card)
        mid.grid(row=2, column=1, sticky="ns")
        ttk.Button(mid, text="→ 翻译本段", command=lambda s=seg: self._retranslate(s)).pack(pady=2)
        ttk.Button(mid, text="← 反向翻译本段", command=lambda s=seg: self._reverse_translate(s)).pack(pady=2)

        src_text.insert("1.0", seg["src"])
        dst_text.insert("1.0", seg["dst"])

        src_toks = self._word_tokens(seg["src"])
        dst_toks = self._word_tokens(seg["dst"])
        for s, e, _ in src_toks:
            src_text.tag_add("sw", self._char_to_index(seg["src"], s),
                            self._char_to_index(seg["src"], e))
        for s, e, _ in dst_toks:
            dst_text.tag_add("dw", self._char_to_index(seg["dst"], s),
                            self._char_to_index(seg["dst"], e))
        aligned = self._align_tokens([t[2] for t in src_toks],
                                     [t[2] for t in dst_toks])
        dst_to_src = {}
        for si, djs in aligned.items():
            for dj in djs:
                dst_to_src[dj] = si
        src_text.bind("<Enter>", self._on_hover)
        dst_text.bind("<Enter>", self._on_hover)
        src_text.bind("<Motion>", self._on_hover)
        dst_text.bind("<Motion>", self._on_hover)
        src_text.bind("<Leave>", self._on_leave)
        dst_text.bind("<Leave>", self._on_leave)
        src_text.tag_config("link", background=self._LINK)
        dst_text.tag_config("link", background=self._LINK)

        self.cards.append({
            "frame": card, "src_text": src_text, "dst_text": dst_text,
            "seg_text": {"src": seg["src"], "dst": seg["dst"]},
            "src_toks": src_toks, "dst_toks": dst_toks,
            "aligned": aligned, "dst_to_src": dst_to_src,
        })

    def _find_index(self, seg):
        try:
            return self.segments.index(seg)
        except ValueError:
            return -1

    # ------------------------------------------------------------ 操作
    def _insert_after(self, seg):
        if self.busy:
            return
        i = self._find_index(seg)
        if i < 0:
            return
        self._sync_from_widgets()
        self.segments.insert(i + 1, {"src": "", "dst": ""})
        self._rebuild()
        self.status_var.set("已在段 %d 后插入空段" % (i + 1))

    def _delete(self, seg):
        if self.busy:
            return
        i = self._find_index(seg)
        if i < 0:
            return
        if not messagebox.askyesno("确认删除", "删除段 %d（原文和译文同时删除）？" % (i + 1)):
            return
        self._sync_from_widgets()
        del self.segments[i]
        self._rebuild()
        self.status_var.set("已删除段 %d" % (i + 1))

    def _retranslate(self, seg):
        if self.busy:
            return
        self._sync_from_widgets()
        if not seg["src"].strip():
            return
        self.busy = True
        self.status_var.set("翻译本段…")
        backend, params = self.app._collect_params()
        threading.Thread(target=self._worker, args=(seg, backend, params), daemon=True).start()

    def _retranslate_all(self):
        if self.busy:
            return
        self._sync_from_widgets()
        todo = [s for s in self.segments if s["src"].strip()]
        if not todo:
            messagebox.showinfo("提示", "没有可翻译的段落")
            return
        self.busy = True
        self.status_var.set("全部翻译中…（%d 段）" % len(todo))
        backend, params = self.app._collect_params()
        threading.Thread(target=self._worker_all, args=(todo, backend, params), daemon=True).start()

    def _worker(self, seg, backend, params):
        try:
            tf = self.app._make_translate_fn(backend, params)
            dst = preserve_translate(seg["src"], tf)
            self.q.put(("seg_done", (self._find_index(seg), dst)))
        except Exception as e:
            self.q.put(("seg_error", (self._find_index(seg), str(e))))
        finally:
            self.q.put(("all_done", None))

    def _worker_all(self, todo, backend, params):
        try:
            tf = self.app._make_translate_fn(backend, params)
            for seg in todo:
                try:
                    dst = preserve_translate(seg["src"], tf)
                    self.q.put(("seg_done", (self._find_index(seg), dst)))
                except Exception as e:
                    self.q.put(("seg_error", (self._find_index(seg), str(e))))
        except Exception as e:
            self.q.put(("error", str(e)))
        finally:
            self.q.put(("all_done", None))

    # ---- 反向翻译（译文 → 原文）----
    def _reverse_translate(self, seg):
        if self.busy:
            return
        self._sync_from_widgets()
        if not seg["dst"].strip():
            return
        self.busy = True
        self.status_var.set("反向翻译本段…")
        backend, params = self.app._collect_params()
        threading.Thread(target=self._worker_reverse, args=(seg, backend, params), daemon=True).start()

    def _reverse_all(self):
        if self.busy:
            return
        self._sync_from_widgets()
        todo = [s for s in self.segments if s["dst"].strip()]
        if not todo:
            messagebox.showinfo("提示", "没有可反向翻译的译文")
            return
        self.busy = True
        self.status_var.set("全部反向翻译中…（%d 段）" % len(todo))
        backend, params = self.app._collect_params()
        threading.Thread(target=self._worker_reverse_all, args=(todo, backend, params), daemon=True).start()

    def _worker_reverse(self, seg, backend, params):
        try:
            tf = self.app._make_reverse_translate_fn(backend, params)
            src = preserve_translate(seg["dst"], tf)
            self.q.put(("src_done", (self._find_index(seg), src)))
        except Exception as e:
            self.q.put(("src_error", (self._find_index(seg), str(e))))
        finally:
            self.q.put(("all_done", None))

    def _worker_reverse_all(self, todo, backend, params):
        try:
            tf = self.app._make_reverse_translate_fn(backend, params)
            for seg in todo:
                try:
                    src = preserve_translate(seg["dst"], tf)
                    self.q.put(("src_done", (self._find_index(seg), src)))
                except Exception as e:
                    self.q.put(("src_error", (self._find_index(seg), str(e))))
        except Exception as e:
            self.q.put(("error", str(e)))
        finally:
            self.q.put(("all_done", None))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "seg_done":
                    index, dst = payload
                    if 0 <= index < len(self.cards):
                        self.cards[index]["dst_text"].delete("1.0", "end")
                        self.cards[index]["dst_text"].insert("1.0", dst)
                        self.segments[index]["dst"] = dst
                    self.status_var.set("翻译完成")
                    # 段级结果，不在此复位 busy；整批由 all_done 统一复位
                    continue
                elif kind == "src_done":
                    index, src = payload
                    if 0 <= index < len(self.cards):
                        self.cards[index]["src_text"].delete("1.0", "end")
                        self.cards[index]["src_text"].insert("1.0", src)
                        self.segments[index]["src"] = src
                    self.status_var.set("反向翻译完成")
                    continue
                elif kind == "seg_error":
                    index, err = payload
                    self.status_var.set("翻译失败")
                    messagebox.showerror("翻译失败", "段 %d：%s" % (index + 1, err))
                    continue
                elif kind == "src_error":
                    index, err = payload
                    self.status_var.set("反向翻译失败")
                    messagebox.showerror("反向翻译失败", "段 %d：%s" % (index + 1, err))
                    continue
                elif kind == "error":
                    self.status_var.set("翻译失败")
                    messagebox.showerror("翻译失败", payload)
                elif kind == "all_done":
                    self.status_var.set(self.status_var.get())
                self.busy = False
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ------------------------------------------------------------ 保存/导出
    def _default_export_path(self):
        if not self.loaded_path:
            return None
        d = os.path.dirname(self.loaded_path)
        stem, ext = os.path.splitext(os.path.basename(self.loaded_path))
        lang = LANG_NAMES.get(self.app.to_var.get().strip().lower(),
                              self.app.to_var.get().strip())
        return os.path.join(d, "%s-%s翻译%s" % (stem, lang, ext))

    def _export(self):
        self._sync_from_widgets()
        content = "\n\n".join(s["dst"] for s in self.segments)
        if not content.strip():
            messagebox.showinfo("提示", "译文为空")
            return
        default = self._default_export_path()
        path = filedialog.asksaveasfilename(
            title="保存/导出译文",
            initialdir=os.path.dirname(default) if default else None,
            initialfile=os.path.basename(default) if default else None,
            defaultextension=os.path.splitext(default)[1] if default else ".md",
            filetypes=[("Markdown", "*.md"), ("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            messagebox.showerror("保存失败", "无法写入文件：%s\n%s" % (path, e))
            return
        self.status_var.set("已保存/导出: %s" % os.path.basename(path))