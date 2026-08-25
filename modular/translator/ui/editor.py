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

from translator.constants import (BG, FG, MUTED, ACCENT, ACCENT_DARK, ACCENT_LIGHT,
                                  BORDER, HEADER_BG, STATUS_BG, LANG_NAMES)
from translator.core.preserve import preserve_translate
from translator.ui.theme import StyleKit


class BidirectionalEditor(tk.Toplevel):
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
            ("翻译", self._retranslate_all, "Accent.TButton"),
            ("反向翻译", self._reverse_all, "Accent.TButton"),
            ("保存/导出", self._export, None),
            ("关闭", self.destroy, None),
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
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
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

    # ------------------------------------------------------------ 数据
    def _split_paragraphs(self, text):
        return [p.strip("\n") for p in re.split(r"\n\s*\n", text) if p.strip()]

    def _load_file(self):
        path = filedialog.askopenfilename(
            title="选择待翻译文件",
            filetypes=[("文本文件", "*.md *.txt *.json"), ("所有文件", "*.*")])
        if not path:
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
        self.segments = [{"src": p, "dst": ""} for p in self._split_paragraphs(content)]
        self._rebuild()
        self.status_var.set("已加载 %d 段: %s" % (len(self.segments), os.path.basename(path)))

    def _guess_translation_path(self, src_path):
        d = os.path.dirname(src_path)
        stem, ext = os.path.splitext(os.path.basename(src_path))
        lang = LANG_NAMES.get(self.app.to_var.get().strip().lower(),
                              self.app.to_var.get().strip())
        return os.path.join(d, "%s-%s翻译%s" % (stem, lang, ext))

    def _auto_load(self):
        """打开时直接加载主窗口已载入的原文，并自动配对同目录的译文文件。"""
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
            self.segments = [{"src": p, "dst": ""} for p in self._split_paragraphs(content)]
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
        src_paras = self._split_paragraphs(src_content)
        dst_paras = self._split_paragraphs(dst_content)
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
        src_text = tk.Text(card, wrap="word", height=4, font=("Microsoft YaHei UI", 10))
        dst_text = tk.Text(card, wrap="word", height=4, font=("Microsoft YaHei UI", 10))
        StyleKit(self).style_text(src_text)
        StyleKit(self).style_text(dst_text)
        src_text.grid(row=2, column=0, sticky="nsew", padx=2)
        dst_text.grid(row=2, column=2, sticky="nsew", padx=2)

        mid = ttk.Frame(card)
        mid.grid(row=2, column=1, sticky="ns")
        ttk.Button(mid, text="→ 翻译本段", command=lambda s=seg: self._retranslate(s)).pack(pady=2)
        ttk.Button(mid, text="← 反向翻译本段", command=lambda s=seg: self._reverse_translate(s)).pack(pady=2)

        src_text.insert("1.0", seg["src"])
        dst_text.insert("1.0", seg["dst"])

        self.cards.append({"frame": card, "src_text": src_text, "dst_text": dst_text})

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
                elif kind == "src_done":
                    index, src = payload
                    if 0 <= index < len(self.cards):
                        self.cards[index]["src_text"].delete("1.0", "end")
                        self.cards[index]["src_text"].insert("1.0", src)
                        self.segments[index]["src"] = src
                    self.status_var.set("反向翻译完成")
                elif kind == "seg_error":
                    index, err = payload
                    self.status_var.set("翻译失败")
                    messagebox.showerror("翻译失败", "段 %d：%s" % (index + 1, err))
                elif kind == "src_error":
                    index, err = payload
                    self.status_var.set("反向翻译失败")
                    messagebox.showerror("反向翻译失败", "段 %d：%s" % (index + 1, err))
                elif kind == "error":
                    self.status_var.set("翻译失败")
                    messagebox.showerror("翻译失败", payload)
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
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self.status_var.set("已保存/导出: %s" % os.path.basename(path))