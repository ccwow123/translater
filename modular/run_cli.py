# -*- coding: utf-8 -*-
"""启动命令行批量翻译入口。

用法（在本目录 modular/ 下执行）：
  python run_cli.py baidu --help
  python run_cli.py siliconflow --help
  python run_cli.py lmstudio --help
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from translator.cli.batch import main


if __name__ == "__main__":
    main()