# -*- coding: utf-8 -*-
"""界面主题与样式：基于 ttkbootstrap 现代主题，统一封装 ttk 样式与文本控件外观。

原主窗口与双向编辑器各自重复定义，此处抽为 StyleKit 复用；皮肤切换也在此收敛。
"""

import tkinter as tk

import ttkbootstrap as tb

from src.constants import ACCENT, ACCENT_DARK, ACCENT_LIGHT, BORDER, FG


# 皮肤选择列表（浅色 / 深色分组）
LIGHT_THEMES = ["nord-light", "bootstrap-light", "catppuccin-light", "minty-light"]
DARK_THEMES = ["nord-dark", "bootstrap-dark", "catppuccin-dark", "dracula-dark",
               "tokyo-night-dark"]
ALL_THEMES = LIGHT_THEMES + DARK_THEMES


class StyleKit:
    """统一管理 root 容器与 ttk 控件样式（ttkbootstrap 主题）。"""

    FONT = ("Microsoft YaHei UI", 10)
    FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
    THEME = "nord-light"

    _style = None
    current = THEME

    def __init__(self, root):
        self.root = root
        if StyleKit._style is None:
            StyleKit._style = tb.Style(theme=StyleKit.current)
            self._setup_accent()
        self.style = StyleKit._style

    @classmethod
    def _setup_accent(cls):
        """品牌主色按钮（兼容现有 style="Accent.TButton" 调用）。"""
        cls._style.configure("Accent.TButton",
                             background=ACCENT, foreground="white",
                             font=cls.FONT_BOLD)
        cls._style.map("Accent.TButton",
                       background=[("active", ACCENT_DARK),
                                   ("disabled", ACCENT_LIGHT)],
                       foreground=[("disabled", "#eef2fb")])

    def style_text(self, widget, padx=8, pady=8, font=FONT):
        """给 tk.Text 统一外观。"""
        widget.configure(bg="white", fg=FG, insertbackground=ACCENT,
                         relief="flat", highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=ACCENT,
                         padx=padx, pady=pady, font=font)

    # ---------------------------------------------------------- 皮肤切换
    def apply_theme(self, name):
        """切换 ttkbootstrap 主题，并同步刷新全部 tk 原生控件配色。"""
        StyleKit.current = name
        self.style.theme_use(name)
        self._setup_accent()
        self.recolor(self.root)
        # 同步模块级配色，供后续新建控件使用
        import src.constants as C
        c = self.style.colors
        C.BG = c.bg
        C.FG = c.fg
        C.BORDER = c.border
        C.STATUS_BG = c.bg

    def recolor(self, widget=None):
        """遍历 widget 树，把 tk 原生控件刷成当前主题色。"""
        widget = widget or self.root
        c = self.style.colors
        dark = "dark" in self.style.theme.name
        text_bg = "#1e222a" if dark else "white"
        for w in self._walk(widget):
            if self._keep(w):
                continue
            if isinstance(w, tk.Frame):
                w.configure(bg=c.bg)
            elif isinstance(w, tk.Label):
                w.configure(bg=c.bg, fg=c.fg)
            elif isinstance(w, tk.Text):
                w.configure(bg=text_bg, fg=c.fg, insertbackground=c.primary,
                            highlightbackground=c.border, highlightcolor=c.primary)
            elif isinstance(w, tk.Canvas):
                w.configure(bg=c.bg)
            elif isinstance(w, tk.Button):
                w.configure(bg=c.bg, fg=c.fg, activebackground=c.bg,
                            activeforeground=c.fg)

    @staticmethod
    def _walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from StyleKit._walk(child)

    @staticmethod
    def _keep(widget):
        """祖先链上存在 _keep_bg 标记（如深色顶栏）则跳过换色。"""
        p = widget
        while p is not None:
            if getattr(p, "_keep_bg", False):
                return True
            p = p.master
        return False


__all__ = ["StyleKit", "LIGHT_THEMES", "DARK_THEMES", "ALL_THEMES"]
