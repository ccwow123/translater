# -*- coding: utf-8 -*-
"""启动图形界面入口。

用法（在本目录 modular/ 下执行）：python run_gui.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from tkinter import ttk

from translator.ui.app import TranslateApp


def main():
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except ImportError:
        root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    TranslateApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()