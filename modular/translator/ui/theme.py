# -*- coding: utf-8 -*-
"""界面主题与样式：配色来自 translator.constants，在此统一封装 ttk 样式与文本控件外观。

原主窗口与双向编辑器各自重复定义，此处抽为 StyleKit 复用。
"""

from tkinter import ttk

from translator.constants import (BG, FG, ACCENT, ACCENT_DARK, ACCENT_LIGHT,
                                  BORDER, HEADER_BG, MUTED)


class StyleKit:
    """统一管理 root 容器与 ttk 控件样式。"""

    def __init__(self, root):
        self.root = root
        self.root.configure(bg=BG)
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", background=BG, foreground=FG,
                        font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                        relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=BG, foreground=ACCENT,
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TButton", font=("Microsoft YaHei UI", 10),
                        padding=(10, 5))
        style.map("TButton",
                  background=[("active", ACCENT_LIGHT)],
                  bordercolor=[("active", ACCENT)])
        style.configure("Accent.TButton", background=ACCENT, foreground="white",
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton",
                  background=[("active", ACCENT_DARK), ("disabled", "#a9b7d6")],
                  foreground=[("disabled", "#eef2fb")])
        style.configure("TCombobox", fieldbackground="white", background="white",
                        arrowcolor=ACCENT, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER)
        style.map("TCombobox", fieldbackground=[("readonly", "white")])
        style.configure("TEntry", fieldbackground="white", bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER)
        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.map("TCheckbutton", background=[("active", BG)])

    def style_text(self, widget, padx=8, pady=8, font=("Microsoft YaHei UI", 10)):
        """给 tk.Text 统一外观。"""
        widget.configure(bg="white", fg=FG, insertbackground=ACCENT, relief="flat",
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT, padx=padx, pady=pady, font=font)


__all__ = ["StyleKit", "HEADER_BG", "MUTED"]