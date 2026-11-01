# -*- coding: utf-8 -*-
"""自由翻译器 —— 模块化版本。

包结构：
  src/constants.py  全局常量（配色/语言表/提示词）
  src/core/         核心逻辑（排版保留、术语表、HTTP、JSON、批处理）
  src/backends/     翻译后端（百度 / OpenAI 兼容）
  src/ui/           桌面界面（主窗口 / 双向编辑器）
  src/cli/          命令行批量翻译
  src/utils/        工具（安全存储）

用法（在本目录 modular/ 下执行）：
  python run_gui.py                # 启动图形界面
  python run_cli.py baidu -h       # 命令行翻译
  python run_cli.py siliconflow -h
"""

__version__ = "2.0.0"