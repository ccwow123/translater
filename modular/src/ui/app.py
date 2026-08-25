# -*- coding: utf-8 -*-
"""多后端文本翻译工具 —— 主窗口（Tkinter 可视化界面）。

整合四个翻译后端：
  1. 百度翻译文本翻译
  2. 硅基流动 API
  3. LM Studio 本地模型
  4. 自定义 OpenAI 格式（任意 OpenAI 兼容接口，可保存配置与模型列表）

后端参数、连接测试、模型获取、断点续传、配置加密等逻辑已按层拆出，
本文件仅负责界面编排，翻译能力来自 src.backends / src.core。
"""

import hashlib
import json
import logging
import os
import platform
import queue
import re
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk, filedialog, messagebox

# 日志：写入 translater/log/translate_YYYYMMDD_HHMMSS.log
_LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "log"))
os.makedirs(_LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(_LOG_DIR, "translate_%s.log" % datetime.now().strftime("%Y%m%d_%H%M%S"))


def _cleanup_old_logs(log_dir, keep=20):
    """只保留最近 keep 个日志文件，防止堆积。"""
    try:
        files = sorted(
            (os.path.join(log_dir, f) for f in os.listdir(log_dir)
             if f.startswith("translate_") and f.endswith(".log")),
            key=os.path.getmtime, reverse=True)
        for f in files[keep:]:
            try:
                os.remove(f)
            except OSError:
                pass
    except OSError:
        pass


_cleanup_old_logs(_LOG_DIR)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s/%(threadName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
log = logging.getLogger("translate")
try:
    _console = logging.StreamHandler()
    _console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    log.addHandler(_console)
except Exception:
    pass

from src.constants import (BG, FG, MUTED, ACCENT, ACCENT_DARK, ACCENT_LIGHT,
                                  BORDER, HEADER_BG, STATUS_BG, LANG_NAMES, LANG_OPTIONS,
                                  LANG_CODE, BASE_BACKENDS, CUSTOM_PREFIX, CONFIG_PATH,
                                  LLM_BACKENDS, API_BACKENDS, GROUP_LLM, GROUP_API,
                                  LLM_SYSTEM, build_system_prompt, strip_fences)
from src.ui.theme import StyleKit
from src.ui.editor import BidirectionalEditor
from src.backends.baidu import translate_one, ENDPOINTS as BAIDU_ENDPOINTS
from src.backends import openai_compat
from src.backends.tencent import translate_one as tencent_translate_one
from src.backends.tencent import DEFAULT_REGION as TENCENT_REGION
from src.backends.alicloud import translate_one as alicloud_translate_one
from src.backends.caiyun import translate_one as caiyun_translate_one
from src.core.preserve import preserve_translate, segment_counts
from src.ui import wordalign as wa
import src.utils.secure as secure_store


USAGE_TEXT = """《多功能翻译工具》使用说明
==============================

【一、功能简介】
一款多功能翻译工具，支持自定义的翻译后端，可实时翻译、批量翻译、
编辑译文与反翻译并保存。

  · 翻译后端：百度翻译、硅基流动、LM Studio 本地、
              腾讯云机器翻译、阿里云机器翻译、彩云小译，
              以及自定义 OpenAI 兼容接口（可自由添加与重命名）。
  · 核心能力：单文件翻译、批量翻译、断点续传、Markdown 排版保留、
              翻译报告、拖拽加载、双向编辑与反翻译。


【二、基本翻译（单文件）】
1. 点击「从文件加载」选择要翻译的文件（或将文件直接拖拽到窗口）。
2. 按需选择：翻译后端、源语言 / 目标语言，并填写后端参数
   （API Key、接口地址、模型、系统提示词等）。
3. 点击「翻译」（结果仅显示在输出区）或「翻译并导出」
   （按“原文件名-目标语言翻译.原扩展名”保存到原目录）。
4. 需要人工调整时，点「双向编辑」对照原文与译文修改，再「保存到文件」。

【三、反翻译】
在「双向编辑」界面可对译文执行反向翻译（译文→原文），
用于核对 AI 是否忠实还原内容、验证翻译质量。


【四、批量翻译】
1. 点击「批量翻译」，选择输入方式：
   ① 选择文件夹：读取其中全部文本文件（.md / .txt / .json 等）。
   ② 读取文件列表：选一个 .txt，按行填写文件地址，# 开头的行会被忽略。
2. 选好后文件进入待处理列表，点击「翻译并导出」才会真正开始翻译。
3. 翻译时会弹出「批量文件队列」窗口，实时查看每个文件状态，并提供：
    · 暂停 / 继续：临时挂起队列，随时恢复。
    · 停止：中断剩余文件，已完成的文件会保留。
4. 结束自动生成翻译报告到桌面，并提示成功 / 结构异常 / 失败数量。


【五、小贴士】
  · 批量每个文件失败会自动重试 3 次；单文件支持「取消」并可断点续传。
  · 翻译会保留 Markdown 排版（代码块 / 表格 / 标题 / 列表），
    并校验原文与译文段落数，异常时提醒。
  · 批量中途停止后，已处理文件会保留，可从报告查看完整清单。
  · 全部配置自动保存，API Key 采用 Windows 加密存储。
"""


def _desktop_path():
    """获取 Windows 桌面绝对路径（优先注册表，回退用户主目录）。"""
    try:
        if hasattr(getattr(__import__("ctypes"), "windll", None), "shell32"):
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0000, None, 0, buf) == 0:
                if buf.value:
                    return buf.value
    except Exception:
        pass
    try:
        p = os.path.join(os.path.expanduser("~"), "Desktop")
        if os.path.isdir(p):
            return p
    except Exception:
        pass
    return None


class TranslationCancelled(Exception):
    """用户点击取消时抛出，用于中止翻译。"""
    pass


class TranslateApp:
    def __init__(self, root):
        self.root = root
        root.title("多后端文本翻译工具")
        root.geometry("1000x900")
        root.minsize(840, 680)

        self.q = queue.Queue()
        self.busy = False
        self.cancel_requested = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._pending_batch = []
        self.batch_win = None
        self.batch_tree = None
        self.batch_pause_btn = None
        self.batch_stop_btn = None
        self.batch_status_var = None
        self.loaded_path = None

        self.backend_var = tk.StringVar(value=BASE_BACKENDS[0])
        self._last_backend = BASE_BACKENDS[0]
        self.from_var = tk.StringVar(value="日文")
        self.to_var = tk.StringVar(value="中文")
        self.max_tokens_var = tk.StringVar(value="8192")

        # 百度
        self.baidu_appid = tk.StringVar(value=os.environ.get("BAIDU_TRANS_APPID", ""))
        self.baidu_appkey = tk.StringVar(value=os.environ.get("BAIDU_TRANS_APPKEY", ""))
        self.baidu_mode = tk.StringVar(value="llm")
        self.baidu_auth = tk.StringVar(value="sign")
        # 硅基流动
        self.sf_key = tk.StringVar(value=os.environ.get("SILICONFLOW_API_KEY", ""))
        self.sf_base = tk.StringVar(value="https://api.siliconflow.cn/v1")
        self.sf_model = tk.StringVar(value="Qwen/Qwen3-8B")
        # LM Studio
        self.lm_base = tk.StringVar(value="http://localhost:1234/v1")
        self.lm_model = tk.StringVar(value="qwen2.5-7b-instruct")
        # 腾讯云机器翻译 TMT
        self.tc_secret_id = tk.StringVar(value=os.environ.get("TENCENTCLOUD_SECRET_ID", ""))
        self.tc_secret_key = tk.StringVar(value=os.environ.get("TENCENTCLOUD_SECRET_KEY", ""))
        self.tc_region = tk.StringVar(value=TENCENT_REGION)
        # 阿里云机器翻译 alimt
        self.ali_access_key_id = tk.StringVar(value=os.environ.get("ALICLOUD_ACCESS_KEY_ID", ""))
        self.ali_access_key_secret = tk.StringVar(value=os.environ.get("ALICLOUD_ACCESS_KEY_SECRET", ""))
        # 彩云小译
        self.caiyun_token = tk.StringVar(value=os.environ.get("CAIYUN_TOKEN", ""))
        # 自定义 OpenAI 格式（多个命名平台）
        self.custom_base = tk.StringVar(value="")
        self.custom_key = tk.StringVar(value="")
        self.custom_model = tk.StringVar(value="")
        self.custom_platforms = []   # [{"name","base_url","api_key","model"}, ...]
        self.custom_models = {}      # name -> [模型列表]
        self._current_custom = None  # 当前选中的自定义平台 dict

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self._load_config()
        self._refresh_backends()
        self._show_backend(self.backend_var.get())
        self._sync_baidu_auth()
        root.after(100, self._poll)
        log.info("===== 应用启动 =====")
        log.info("Python %s | 平台: %s | 架构: %s",
                 platform.python_version(), platform.platform(), platform.machine())
        try:
            log.info("Tk %s | Tcl %s", root.tk.call("info", "patchlevel"),
                     root.tk.call("info", "tclversion"))
        except Exception:
            pass
        log.info("工作目录: %s", os.getcwd())
        log.info("配置路径: %s", CONFIG_PATH)
        log.info("日志路径: %s", LOG_PATH)

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        kit = StyleKit(self.root)
        pad = {"padx": 12, "pady": 6}

        # 顶栏
        header = tk.Frame(self.root, bg=HEADER_BG, height=58)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="多后端文本翻译工具", bg=HEADER_BG, fg="#ffffff",
                 font=("Microsoft YaHei UI", 15, "bold")).pack(side="left", padx=16)
        tk.Label(header, text="LLM：硅基流动 · LM Studio · 自定义  ｜  专用翻译：百度 · 腾讯云 · 阿里云 · 彩云小译",
                 bg=HEADER_BG, fg="#b9c6e8", font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(6, 0))
        ttk.Button(header, text="使用说明", command=self._open_usage,
                   style="Accent.TButton").pack(side="right", padx=16, pady=13)

        # 顶部控制行
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="翻译后端:").pack(side="left")
        self.backend_cb = ttk.Combobox(top, textvariable=self.backend_var,
                                       values=self._all_backends(), state="readonly", width=16)
        self.backend_cb.pack(side="left", padx=4)
        self.backend_cb.bind("<<ComboboxSelected>>", self._on_backend_selected)
        ttk.Label(top, text="源语言:").pack(side="left", padx=(14, 2))
        ttk.Combobox(top, textvariable=self.from_var, values=LANG_OPTIONS,
                     state="readonly", width=6).pack(side="left")
        ttk.Label(top, text="目标语言:").pack(side="left", padx=(8, 2))
        ttk.Combobox(top, textvariable=self.to_var, values=LANG_OPTIONS,
                     state="readonly", width=6).pack(side="left")
        ttk.Label(top, text="最大输出token:").pack(side="left", padx=(14, 2))
        ttk.Entry(top, textvariable=self.max_tokens_var, width=8).pack(side="left")
        ttk.Button(top, text="清除配置", command=self._clear_config).pack(side="right")
        ttk.Button(top, text="保存配置", command=self._save_config).pack(side="right", padx=(0, 8))
        ttk.Button(top, text="管理自定义平台", command=self._manage_custom).pack(side="right", padx=(0, 8))

        # 后端参数 + 系统提示词 横向并排（1:1 宽度均分）
        config_row = ttk.Frame(self.root)
        config_row.pack(fill="x", **pad)
        config_row.columnconfigure(0, weight=1)
        config_row.columnconfigure(1, weight=1)

        self.cfg_frame = ttk.LabelFrame(config_row, text="后端参数")
        self.cfg_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        self.baidu_frame = ttk.Frame(self.cfg_frame)
        ttk.Label(self.baidu_frame, text="APPID:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.baidu_frame, textvariable=self.baidu_appid, width=44).grid(row=0, column=1, padx=6, pady=4)
        ttk.Label(self.baidu_frame, text="密钥/API Key:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.baidu_frame, textvariable=self.baidu_appkey, width=44, show="*").grid(row=1, column=1, padx=6, pady=4)
        ttk.Label(self.baidu_frame, text="接口:").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        self.baidu_mode_cb = ttk.Combobox(self.baidu_frame, textvariable=self.baidu_mode,
                                          values=("llm", "general"), state="readonly", width=12)
        self.baidu_mode_cb.grid(row=2, column=1, sticky="w", padx=6, pady=4)
        self.baidu_mode_cb.bind("<<ComboboxSelected>>", lambda e: self._sync_baidu_auth())
        ttk.Label(self.baidu_frame, text="llm=大模型文本翻译(自动用API Key鉴权)，general=通用翻译(签名鉴权)").grid(
            row=3, column=0, columnspan=3, sticky="w", padx=6, pady=2)

        self.sf_frame = ttk.Frame(self.cfg_frame)
        ttk.Label(self.sf_frame, text="API Key:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.sf_frame, textvariable=self.sf_key, width=44, show="*").grid(row=0, column=1, padx=6, pady=4)
        ttk.Label(self.sf_frame, text="接口地址:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.sf_frame, textvariable=self.sf_base, width=44).grid(row=1, column=1, padx=6, pady=4)
        ttk.Label(self.sf_frame, text="模型:").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        self.sf_model_cb = ttk.Combobox(self.sf_frame, textvariable=self.sf_model, width=41)
        self.sf_model_cb.grid(row=2, column=1, sticky="w", padx=6, pady=4)
        ttk.Button(self.sf_frame, text="测试连接", command=self._test_connection).grid(
            row=3, column=1, sticky="w", padx=6, pady=4)

        self.lm_frame = ttk.Frame(self.cfg_frame)
        ttk.Label(self.lm_frame, text="接口地址:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.lm_frame, textvariable=self.lm_base, width=44).grid(row=0, column=1, padx=6, pady=4)
        ttk.Label(self.lm_frame, text="模型:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        self.lm_model_cb = ttk.Combobox(self.lm_frame, textvariable=self.lm_model, width=41)
        self.lm_model_cb.grid(row=1, column=1, sticky="w", padx=6, pady=4)
        ttk.Button(self.lm_frame, text="测试连接", command=self._test_connection).grid(
            row=2, column=1, sticky="w", padx=6, pady=4)

        # 腾讯云机器翻译
        self.tc_frame = ttk.Frame(self.cfg_frame)
        ttk.Label(self.tc_frame, text="SecretId:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.tc_frame, textvariable=self.tc_secret_id, width=44).grid(row=0, column=1, padx=6, pady=4)
        ttk.Label(self.tc_frame, text="SecretKey:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.tc_frame, textvariable=self.tc_secret_key, width=44, show="*").grid(row=1, column=1, padx=6, pady=4)
        ttk.Label(self.tc_frame, text="地域:").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.tc_frame, textvariable=self.tc_region, width=20).grid(row=2, column=1, sticky="w", padx=6, pady=4)
        ttk.Button(self.tc_frame, text="测试连接", command=self._test_connection).grid(
            row=3, column=1, sticky="w", padx=6, pady=4)

        # 阿里云机器翻译
        self.ali_frame = ttk.Frame(self.cfg_frame)
        ttk.Label(self.ali_frame, text="AccessKey ID:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.ali_frame, textvariable=self.ali_access_key_id, width=44).grid(row=0, column=1, padx=6, pady=4)
        ttk.Label(self.ali_frame, text="AccessKey Secret:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.ali_frame, textvariable=self.ali_access_key_secret, width=44, show="*").grid(row=1, column=1, padx=6, pady=4)
        ttk.Button(self.ali_frame, text="测试连接", command=self._test_connection).grid(
            row=2, column=1, sticky="w", padx=6, pady=4)

        # 彩云小译
        self.caiyun_frame = ttk.Frame(self.cfg_frame)
        ttk.Label(self.caiyun_frame, text="访问令牌 Token:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.caiyun_frame, textvariable=self.caiyun_token, width=44, show="*").grid(row=0, column=1, padx=6, pady=4)
        ttk.Button(self.caiyun_frame, text="测试连接", command=self._test_connection).grid(
            row=1, column=1, sticky="w", padx=6, pady=4)

        self.custom_frame = ttk.Frame(self.cfg_frame)
        ttk.Label(self.custom_frame, text="API Key:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.custom_frame, textvariable=self.custom_key, width=44, show="*").grid(row=0, column=1, padx=6, pady=4)
        ttk.Label(self.custom_frame, text="接口地址:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(self.custom_frame, textvariable=self.custom_base, width=44).grid(row=1, column=1, padx=6, pady=4)
        ttk.Label(self.custom_frame, text="模型:").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        self.custom_model_cb = ttk.Combobox(self.custom_frame, textvariable=self.custom_model, width=41)
        self.custom_model_cb.grid(row=2, column=1, sticky="w", padx=6, pady=4)
        ttk.Button(self.custom_frame, text="测试连接", command=self._test_connection).grid(
            row=3, column=1, sticky="w", padx=6, pady=4)

        # 系统提示词（LLM 后端生效）——放置在后端参数栏右侧（1:1 宽度）
        sys_frame = ttk.LabelFrame(config_row, text="系统提示词（翻译角色设定，LLM 后端生效）")
        sys_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.sys_text = tk.Text(sys_frame, wrap="word", height=3, font=("Microsoft YaHei UI", 9))
        kit.style_text(self.sys_text, font=("Microsoft YaHei UI", 9))
        self.sys_text.pack(fill="both", expand=True, padx=6, pady=6)
        ttk.Button(sys_frame, text="恢复默认", command=self._reset_system_prompt).pack(anchor="e", padx=6, pady=(0, 6))

        # 中间自适应区：输入 / 按钮 / 输出 按比例伸缩
        mid = ttk.Frame(self.root)
        mid.pack(fill="both", expand=True, **pad)
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=4)   # 输入区
        mid.rowconfigure(1, weight=0)   # 按钮行（固定高度）
        mid.rowconfigure(2, weight=5)   # 输出区

        in_frame = ttk.LabelFrame(mid, text="输入文本")
        in_frame.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        self.in_text = tk.Text(in_frame, wrap="word", height=9, font=("Microsoft YaHei UI", 10))
        kit.style_text(self.in_text)
        self._link_tag("in")
        self.in_text.pack(fill="both", expand=True, padx=6, pady=6)

        btn_frame = ttk.Frame(mid)
        btn_frame.grid(row=1, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(btn_frame, text="从文件加载", command=self._load_file).pack(side="left")
        ttk.Button(btn_frame, text="批量翻译", command=self._batch_translate).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="双向编辑", command=self._open_editor).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="清空输入", command=lambda: self.in_text.delete("1.0", "end")).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="翻译并导出", style="Accent.TButton",
                   command=lambda: self._start_translate(export=True)).pack(side="right", padx=8)
        self.cancel_btn = ttk.Button(btn_frame, text="取消", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="right", padx=8)
        ttk.Button(btn_frame, text="翻译", style="Accent.TButton",
                   command=self._start_translate).pack(side="right")

        out_frame = ttk.LabelFrame(mid, text="输出译文")
        out_frame.grid(row=2, column=0, sticky="nsew", padx=2, pady=2)
        self.out_text = tk.Text(out_frame, wrap="word", height=9, font=("Microsoft YaHei UI", 10))
        kit.style_text(self.out_text)
        self._link_tag("out")
        self.out_text.pack(fill="both", expand=True, padx=6, pady=6)
        ttk.Button(out_frame, text="保存到文件", command=self._save_file).pack(anchor="e", padx=6, pady=6)

        # 状态栏
        status = tk.Frame(self.root, bg=STATUS_BG, height=34)
        status.pack(fill="x")
        status.pack_propagate(False)
        self.status_bar = status
        self.status_var = tk.StringVar(value="就绪")
        tk.Label(status, textvariable=self.status_var, bg=STATUS_BG, fg=FG,
                 font=("Microsoft YaHei UI", 10, "bold"), anchor="w").pack(side="left", padx=12, pady=6)
        self.progress_wrap = tk.Frame(status, bg=STATUS_BG)
        pstyle = ttk.Style(self.root)
        try:
            pstyle.theme_use("clam")
        except Exception:
            pass
        pstyle.configure("Green.Horizontal.TProgressbar", troughcolor="#ececec",
                         background="#2ecc71", bordercolor="#2ecc71",
                         lightcolor="#a8e6cf", darkcolor="#1e8449")
        self.progress_bar = ttk.Progressbar(self.progress_wrap, style="Green.Horizontal.TProgressbar",
                                            mode="indeterminate", maximum=100)
        self.progress_bar.pack(side="left", fill="x", expand=True, pady=8)

        
        self._enable_drag_drop()
        log.info("应用启动，日志路径: %s", LOG_PATH)

    def _all_backends(self):
        custom = [CUSTOM_PREFIX + p["name"] for p in self.custom_platforms]
        out = [GROUP_LLM] + list(LLM_BACKENDS)
        if custom:
            out += custom
        return out + [GROUP_API] + list(API_BACKENDS)

    def _is_group_title(self, name):
        return name in (GROUP_LLM, GROUP_API)

    def _first_valid_backend(self, vals=None):
        for v in (vals or self._all_backends()):
            if not self._is_group_title(v):
                return v
        return ""

    def _on_backend_selected(self, event=None):
        """选择后端：分组标题不可选，选中时回退到上一次有效后端。"""
        cur = self.backend_var.get()
        if self._is_group_title(cur):
            self.backend_var.set(self._last_backend or self._first_valid_backend())
            return
        self._last_backend = cur
        self._show_backend(cur)

    def _find_custom(self, backend):
        if not backend.startswith(CUSTOM_PREFIX):
            return None
        name = backend[len(CUSTOM_PREFIX):]
        for p in self.custom_platforms:
            if p["name"] == name:
                return p
        return None

    def _refresh_backends(self):
        vals = self._all_backends()
        self.backend_cb["values"] = vals
        cur = self.backend_var.get()
        if self._is_group_title(cur) or cur not in vals:
            self.backend_var.set(self._first_valid_backend(vals))
            self._show_backend(self.backend_var.get())

    def _sync_custom_from_frame(self):
        """把自定义参数区的当前值写回选中的平台（内存中）。"""
        if self._current_custom is not None:
            self._current_custom["base_url"] = self.custom_base.get().strip()
            self._current_custom["api_key"] = self.custom_key.get().strip()
            self._current_custom["model"] = self.custom_model.get().strip()

    def _load_custom_to_frame(self, platform):
        self.custom_base.set(platform.get("base_url", ""))
        self.custom_key.set(platform.get("api_key", ""))
        self.custom_model.set(platform.get("model", ""))
        self.custom_model_cb["values"] = self.custom_models.get(platform["name"], [])

    def _show_backend(self, backend):
        self._sync_custom_from_frame()
        for f in (self.baidu_frame, self.sf_frame, self.lm_frame,
                  self.tc_frame, self.ali_frame, self.caiyun_frame,
                  self.custom_frame):
            f.pack_forget()
        if backend == "百度翻译":
            frame = self.baidu_frame
        elif backend == "硅基流动":
            frame = self.sf_frame
        elif backend == "LM Studio 本地":
            frame = self.lm_frame
        elif backend == "腾讯云机器翻译":
            frame = self.tc_frame
        elif backend == "阿里云机器翻译":
            frame = self.ali_frame
        elif backend == "彩云小译":
            frame = self.caiyun_frame
        else:
            frame = self.custom_frame
            self._current_custom = self._find_custom(backend)
            if self._current_custom:
                self._load_custom_to_frame(self._current_custom)
            else:
                self._current_custom = None
        frame.pack(fill="x", padx=4, pady=4)
        log.info("后端切换: %s", backend)

    def _sync_baidu_auth(self):
        self.baidu_auth.set("apikey" if self.baidu_mode.get() == "llm" else "sign")

    # ------------------------------------------------------------ 系统提示词
    def _get_system_prompt(self):
        return self.sys_text.get("1.0", "end-1c").strip()

    def _reset_system_prompt(self):
        self.sys_text.delete("1.0", "end")
        self.sys_text.insert("1.0", LLM_SYSTEM)

    # ------------------------------------------------------------ 连接测试与模型获取
    def _backend_creds(self):
        """返回当前 LLM 后端的 (base_url, api_key, key_label)。"""
        backend = self.backend_var.get()
        if backend == "硅基流动":
            return self.sf_base.get().strip(), self.sf_key.get().strip(), "硅基流动 API Key"
        if backend == "LM Studio 本地":
            return self.lm_base.get().strip(), "lm-studio", None
        return self.custom_base.get().strip(), self.custom_key.get().strip(), "该自定义 OpenAI 平台的 API Key"

    def _test_connection(self):
        if self.busy:
            return
        backend = self.backend_var.get()
        if backend in ("腾讯云机器翻译", "阿里云机器翻译", "彩云小译"):
            self.busy = True
            self.status_var.set("测试连接中…（%s）" % backend)
            log.info("测试连接: backend=%s", backend)
            threading.Thread(target=self._test_special_worker,
                             args=(backend,), daemon=True).start()
            return
        base_url, api_key, key_label = self._backend_creds()
        if key_label and not api_key:
            messagebox.showwarning("缺少凭据", "请先填写%s" % key_label)
            return
        if not base_url:
            messagebox.showwarning("缺少参数", "请先填写接口地址")
            return
        self.busy = True
        self.status_var.set("测试连接中…（%s）" % backend)
        log.info("测试连接: backend=%s, base_url=%s", backend, base_url)
        threading.Thread(target=self._test_conn_worker,
                         args=(backend, base_url, api_key), daemon=True).start()

    def _test_conn_worker(self, backend, base_url, api_key):
        t0 = time.time()
        try:
            ok, msg = openai_compat.test_connection(base_url, api_key)
            if backend != "百度翻译":
                try:
                    mok, models = openai_compat.list_models(base_url, api_key)
                    if mok and models:
                        self.q.put(("models_result", (backend, True, models)))
                        log.info("获取模型成功: backend=%s, 模型数=%d", backend, len(models))
                    else:
                        log.warning("获取模型失败: backend=%s, msg=%s", backend, mok)
                except Exception as e:
                    log.warning("获取模型异常: backend=%s, err=%s", backend, e)
            log.info("测试连接%s: backend=%s, base_url=%s, 耗时=%.1fs, msg=%s",
                     "成功" if ok else "失败", backend, base_url, time.time() - t0, msg)
            self.q.put(("conn_result", (ok, msg)))
        except Exception as e:
            log.error("测试连接异常: backend=%s, err=%s, 耗时=%.1fs",
                      backend, e, time.time() - t0, exc_info=True)
            self.q.put(("conn_result", (False, str(e))))

    def _test_special_worker(self, backend):
        """对专用翻译 API（腾讯云/阿里云/彩云）做一次性真实翻译测试。"""
        try:
            ok = False
            msg = ""
            if backend == "腾讯云机器翻译":
                sid = self.tc_secret_id.get().strip()
                skey = self.tc_secret_key.get().strip()
                if not sid or not skey:
                    msg = "请先填写腾讯云 SecretId 与 SecretKey"
                else:
                    dst, err = tencent_translate_one(
                        sid, skey, "hello world", "en", "zh",
                        self.tc_region.get().strip() or TENCENT_REGION)
                    ok, msg = (err is None, "连接成功：%s" % dst if err is None else err)
            elif backend == "阿里云机器翻译":
                ak = self.ali_access_key_id.get().strip()
                sk = self.ali_access_key_secret.get().strip()
                if not ak or not sk:
                    msg = "请先填写阿里云 AccessKey ID 与 AccessKey Secret"
                else:
                    dst, err = alicloud_translate_one(ak, sk, "hello world", "en", "zh")
                    ok, msg = (err is None, "连接成功：%s" % dst if err is None else err)
            elif backend == "彩云小译":
                tk = self.caiyun_token.get().strip()
                if not tk:
                    msg = "请先填写彩云小译访问令牌 Token"
                else:
                    dst, err = caiyun_translate_one(tk, "hello world", "en", "zh")
                    ok, msg = (err is None, "连接成功：%s" % dst if err is None else err)
            self.q.put(("conn_result", (ok, msg)))
        except Exception as e:
            log.error("专用接口测试异常: backend=%s, err=%s", backend, e, exc_info=True)
            self.q.put(("conn_result", (False, str(e))))

    def _fetch_models(self):
        if self.busy:
            return
        backend = self.backend_var.get()
        base_url, api_key, key_label = self._backend_creds()
        if key_label and not api_key:
            messagebox.showwarning("缺少凭据", "请先填写%s" % key_label)
            return
        if not base_url:
            messagebox.showwarning("缺少参数", "请先填写接口地址")
            return
        self.busy = True
        self.status_var.set("获取模型列表中…（%s）" % backend)
        threading.Thread(target=self._fetch_models_worker,
                         args=(backend, base_url, api_key), daemon=True).start()

    def _fetch_models_worker(self, backend, base_url, api_key):
        try:
            ok, models = openai_compat.list_models(base_url, api_key)
            if not ok:
                self.q.put(("models_result", (backend, False, models)))
                return
            self.q.put(("models_result", (backend, True, models)))
        except Exception as e:
            self.q.put(("models_result", (backend, False, str(e))))

    def _set_models(self, backend, models):
        if backend.startswith(CUSTOM_PREFIX):
            name = backend[len(CUSTOM_PREFIX):]
            self.custom_models[name] = models
            cb = self.custom_model_cb
        else:
            cb = {"硅基流动": self.sf_model_cb, "LM Studio 本地": self.lm_model_cb}[backend]
        cb["values"] = models
        if models and not cb.get().strip():
            cb.set(models[0])
        self._persist_models()

    # ------------------------------------------------------------ 配置保存
    def _collect_model_list(self, cb):
        """收集某后端模型下拉框的列表，并把当前手输的模型并入其中。"""
        vals = list(cb["values"])
        cur = cb.get().strip()
        if cur and cur not in vals:
            vals.append(cur)
        return vals

    def _collect_config(self):
        self._sync_custom_from_frame()
        if self._current_custom is not None:
            self.custom_models[self._current_custom["name"]] = \
                self._collect_model_list(self.custom_model_cb)
        return {
            "backend": self.backend_var.get(),
            "from": self.from_var.get(),
            "to": self.to_var.get(),
            "max_tokens": self.max_tokens_var.get(),
            "system": self._get_system_prompt(),
            "baidu": {
                "appid": self.baidu_appid.get(),
                "appkey_enc": self._enc_secret(self.baidu_appkey.get()),
                "mode": self.baidu_mode.get(),
            },
            "siliconflow": {
                "api_key_enc": self._enc_secret(self.sf_key.get()),
                "base_url": self.sf_base.get(),
                "model": self.sf_model.get(),
            },
            "lmstudio": {
                "base_url": self.lm_base.get(),
                "model": self.lm_model.get(),
            },
            "tencent": {
                "secret_id": self.tc_secret_id.get(),
                "secret_key_enc": self._enc_secret(self.tc_secret_key.get()),
                "region": self.tc_region.get(),
            },
            "alicloud": {
                "access_key_id": self.ali_access_key_id.get(),
                "access_key_secret_enc": self._enc_secret(self.ali_access_key_secret.get()),
            },
            "caiyun": {
                "token_enc": self._enc_secret(self.caiyun_token.get()),
            },
            "custom_platforms": [
                {"name": p["name"],
                 "base_url": p.get("base_url", ""),
                 "api_key_enc": self._enc_secret(p.get("api_key", "")),
                 "model": p.get("model", "")}
                for p in self.custom_platforms
            ],
            "custom_models": self.custom_models,
            "models": {
                "siliconflow": self._collect_model_list(self.sf_model_cb),
                "lmstudio": self._collect_model_list(self.lm_model_cb),
            },
        }

    def _persist_models(self):
        """把各后端模型列表静默写入配置（获取模型后自动保存）。"""
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._collect_config(), f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._collect_config(), f, ensure_ascii=False, indent=1)
            self.status_var.set("配置已保存（API Key 已加密）: %s" % CONFIG_PATH)
            log.info("配置已保存: %s", CONFIG_PATH)
        except Exception as e:
            log.error("配置保存失败: %s", e, exc_info=True)
            messagebox.showerror("保存失败", str(e))

    def _load_config(self):
        if not os.path.exists(CONFIG_PATH):
            log.info("配置不存在，使用默认设置")
            return
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            log.warning("配置读取失败: %s", e)
            return
        log.info("配置已加载: %s (from=%s, to=%s, backend=%s, 自定义平台=%d)",
                 CONFIG_PATH, cfg.get("from"), cfg.get("to"),
                 cfg.get("backend"), len(cfg.get("custom_platforms") or []))
        if cfg.get("from"):
            self.from_var.set(LANG_NAMES.get(cfg["from"], cfg["from"]))
        if cfg.get("to"):
            self.to_var.set(LANG_NAMES.get(cfg["to"], cfg["to"]))
        if cfg.get("max_tokens"):
            self.max_tokens_var.set(cfg["max_tokens"])
        if cfg.get("system"):
            self.sys_text.delete("1.0", "end")
            self.sys_text.insert("1.0", cfg["system"])
        b = cfg.get("baidu", {})
        if b.get("appid"):
            self.baidu_appid.set(b["appid"])
        key = self._dec_secret(b.get("appkey_enc")) or b.get("appkey", "")
        if key:
            self.baidu_appkey.set(key)
        if b.get("mode"):
            self.baidu_mode.set(b["mode"])
        sf = cfg.get("siliconflow", {})
        key = self._dec_secret(sf.get("api_key_enc")) or sf.get("api_key", "")
        if key:
            self.sf_key.set(key)
        if sf.get("base_url"):
            self.sf_base.set(sf["base_url"])
        if sf.get("model"):
            self.sf_model.set(sf["model"])
        lm = cfg.get("lmstudio", {})
        if lm.get("base_url"):
            self.lm_base.set(lm["base_url"])
        if lm.get("model"):
            self.lm_model.set(lm["model"])
        tc = cfg.get("tencent", {})
        if tc.get("secret_id"):
            self.tc_secret_id.set(tc["secret_id"])
        tc_key = self._dec_secret(tc.get("secret_key_enc")) or tc.get("secret_key", "")
        if tc_key:
            self.tc_secret_key.set(tc_key)
        if tc.get("region"):
            self.tc_region.set(tc["region"])
        ali = cfg.get("alicloud", {})
        if ali.get("access_key_id"):
            self.ali_access_key_id.set(ali["access_key_id"])
        ali_secret = self._dec_secret(ali.get("access_key_secret_enc")) or ali.get("access_key_secret", "")
        if ali_secret:
            self.ali_access_key_secret.set(ali_secret)
        cy = cfg.get("caiyun", {})
        cy_token = self._dec_secret(cy.get("token_enc")) or cy.get("token", "")
        if cy_token:
            self.caiyun_token.set(cy_token)
        cps = cfg.get("custom_platforms")
        if cps:
            self.custom_platforms = [
                {"name": p.get("name", "自定义"),
                 "base_url": p.get("base_url", ""),
                 "api_key": self._dec_secret(p.get("api_key_enc")) or p.get("api_key", ""),
                 "model": p.get("model", "")}
                for p in cps
            ]
        else:
            # 兼容旧版单一自定义后端
            cu = cfg.get("custom", {})
            if cu.get("base_url") or cu.get("api_key") or cu.get("api_key_enc") or cu.get("model"):
                self.custom_platforms = [{
                    "name": "自定义",
                    "base_url": cu.get("base_url", ""),
                    "api_key": self._dec_secret(cu.get("api_key_enc")) or cu.get("api_key", ""),
                    "model": cu.get("model", ""),
                }]
            else:
                self.custom_platforms = [{
                    "name": "默认",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "",
                    "model": "gpt-4o-mini",
                }]
        self.custom_models = cfg.get("custom_models", {}) or {}
        b = cfg.get("backend")
        if b == "百度大模型":
            b = "百度翻译"
        if b and not self._is_group_title(b):
            self.backend_var.set(b)
            self._last_backend = b
        models = cfg.get("models", {})
        if models.get("siliconflow"):
            self.sf_model_cb["values"] = models["siliconflow"]
        if models.get("lmstudio"):
            self.lm_model_cb["values"] = models["lmstudio"]
        if cfg.get("geometry"):
            try:
                m = re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", cfg["geometry"])
                if m:
                    w, h, x, y = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
                    if 0 <= x < sw - 40 and 0 <= y < sh - 40:
                        self.root.geometry(cfg["geometry"])
            except Exception:
                pass

    def _save_geometry(self):
        try:
            cfg = {}
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    cfg = json.load(f)
            cfg["geometry"] = self.root.geometry()
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _on_close(self):
        log.info("===== 应用退出 =====")
        self._save_geometry()
        self.root.destroy()

    def _clear_config(self):
        if os.path.exists(CONFIG_PATH):
            os.remove(CONFIG_PATH)
        self.status_var.set("已清除保存的配置")

    def _manage_custom(self):
        """管理自定义 OpenAI 平台：新增 / 重命名 / 编辑 / 删除（美化版）。"""
        dlg = tk.Toplevel(self.root)
        dlg.title("管理自定义 OpenAI 平台")
        dlg.geometry("740x520")
        dlg.minsize(660, 460)
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.grab_set()

        # 顶部标题条
        header = tk.Frame(dlg, bg=HEADER_BG, height=58)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="管理自定义 OpenAI 平台", bg=HEADER_BG, fg="#ffffff",
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side="left", padx=16)
        tk.Label(header, text="支持任意 OpenAI 兼容接口，可自由添加与重命名",
                 bg=HEADER_BG, fg="#b9c6e8", font=("Microsoft YaHei UI", 9)
                 ).pack(side="right", padx=16)

        body = tk.Frame(dlg, bg=BG)

        # 底部操作按钮（独立底部条，固定显示，确保四个按钮都在）
        ops = tk.Frame(dlg, bg=BG)
        ops.pack(side="bottom", fill="x", padx=16, pady=(0, 12))
        ops.grid_columnconfigure(0, weight=1)
        tk.Button(ops, text="关闭", command=dlg.destroy, bg="#e6e8ee", fg=FG,
                  activebackground="#d8dce4", relief="flat", padx=18, pady=6,
                  font=("Microsoft YaHei UI", 9)).grid(row=0, column=1, padx=4)
        tk.Button(ops, text="删除平台", command=lambda: self._del_platform(dlg),
                  bg="#fdeceb", fg="#c0392b", activebackground="#fad8d5", relief="flat",
                  padx=14, pady=6, font=("Microsoft YaHei UI", 9)).grid(row=0, column=2, padx=4)
        tk.Button(ops, text="保存修改", command=lambda: self._save_platform(dlg),
                  bg=ACCENT, fg="#ffffff", activebackground=ACCENT_DARK, relief="flat",
                  padx=18, pady=6, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=3, padx=4)
        tk.Button(ops, text="＋ 新增平台", command=lambda: self._new_platform(dlg),
                  bg="#eef2fb", fg=ACCENT, activebackground="#e0e8f8", relief="flat",
                  padx=14, pady=6, font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=4, padx=4)

        body.pack(fill="both", expand=True, padx=16, pady=12)

        # ---------- 左侧平台列表 ----------
        left_card = tk.Frame(body, bg="#ffffff", highlightthickness=1,
                             highlightbackground=BORDER)
        left_card.pack(side="left", fill="y", padx=(0, 12))
        tk.Label(left_card, text="已添加的平台", bg="#ffffff", fg=ACCENT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        tk.Label(left_card, text=f"共 {len(self.custom_platforms)} 个平台，点击左侧名称可编辑",
                 bg="#ffffff", fg="#9a9a9a", font=("Microsoft YaHei UI", 8)
                 ).pack(anchor="w", padx=12)
        lf = tk.Frame(left_card, bg="#ffffff")
        lf.pack(fill="both", expand=True, padx=8, pady=8)
        lb = tk.Listbox(lf, width=22, height=13, font=("Microsoft YaHei UI", 10),
                        bg="#f6f8fb", fg=FG, relief="flat",
                        selectbackground=ACCENT, selectforeground="white",
                        highlightthickness=1, highlightbackground=BORDER)
        sbb = ttk.Scrollbar(lf, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sbb.set)
        lb.pack(side="left", fill="both", expand=True)
        sbb.pack(side="right", fill="y")

        # ---------- 右侧编辑表单 ----------
        right_card = tk.Frame(body, bg="#ffffff", highlightthickness=1,
                              highlightbackground=BORDER)
        right_card.pack(side="left", fill="both", expand=True)
        tk.Label(right_card, text="平台信息", bg="#ffffff", fg=ACCENT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(right_card, text="新增平台会自动填入 OpenAI 官方模板，仅需填写平台名称",
                 bg="#ffffff", fg="#9a9a9a", font=("Microsoft YaHei UI", 8)
                 ).pack(anchor="w", padx=14)
        form = tk.Frame(right_card, bg="#ffffff")
        form.pack(fill="both", expand=True, padx=14, pady=12)

        def made_row(text, var, show=None):
            r = tk.Frame(form, bg="#ffffff")
            r.pack(fill="x", pady=3)
            tk.Label(r, text=text, bg="#ffffff", fg=FG, width=12,
                     anchor="e", font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 8))
            tk.Entry(r, textvariable=var, font=("Consolas", 10), show=show,
                     relief="solid", bd=1, highlightthickness=1,
                     highlightbackground=BORDER, highlightcolor=ACCENT,
                     insertbackground=ACCENT, bg="#fbfbfd", fg=FG
                     ).pack(side="left", fill="x", expand=True, ipady=3)

        name_var = tk.StringVar()
        base_var = tk.StringVar(value="https://api.openai.com/v1")
        key_var = tk.StringVar()
        model_var = tk.StringVar(value="gpt-4o-mini")
        made_row("平台名称", name_var)
        made_row("接口地址", base_var)
        made_row("API Key", key_var, show="*")
        made_row("默认模型", model_var)

        dlg.formvars = {"name": name_var, "base": base_var,
                        "key": key_var, "model": model_var}
        dlg.formlistbox = lb
        self._custom_editing = -1

        tk.Label(right_card, text="提示：接口地址需兼容 OpenAI API，例如 https://api.deepseek.com/v1",
                 bg="#ffffff", fg="#b0b0b0", font=("Microsoft YaHei UI", 8)
                 ).pack(anchor="w", padx=14, pady=(0, 10))

        self._refresh_custom_list(dlg)

    # ---- 自定义平台管理辅助（美化对话框使用） ----
    def _refresh_custom_list(self, dlg):
        """刷新左侧平台列表并绑定选择事件。"""
        lb = getattr(dlg, "formlistbox", None)
        vars_ = getattr(dlg, "formvars", None)
        if not lb or not vars_:
            return
        editing = self._custom_editing
        lb.delete(0, "end")
        for p in self.custom_platforms:
            lb.insert("end", p["name"])
        if lb.curselection():
            editing = lb.curselection()[0]
        if editing is not None and 0 <= editing < len(self.custom_platforms):
            lb.selection_set(editing)
            lb.see(editing)
            self._load_custom_item(editing, lb)
        elif self.custom_platforms:
            lb.selection_set(0)
            self._load_custom_item(0, lb)
        lb.bind("<<ListboxSelect>>", lambda e: self._load_custom_item(
            lb.curselection()[0] if lb.curselection() else None, lb))

    def _load_custom_item(self, idx, lb):
        """把指定平台加载到表单。"""
        if idx is None or not (0 <= idx < len(self.custom_platforms)):
            return
        p = self.custom_platforms[idx]
        self._custom_editing = idx
        vars_ = lb.winfo_toplevel().formvars
        vars_["name"].set(p.get("name", ""))
        vars_["base"].set(p.get("base_url", ""))
        vars_["key"].set(p.get("api_key", ""))
        vars_["model"].set(p.get("model", ""))

    def _new_platform(self, dlg):
        """清空表单并填入 OpenAI 官方模板，聚焦平台名称。"""
        vars_ = getattr(dlg, "formvars", None)
        lb = getattr(dlg, "formlistbox", None)
        if not vars_:
            return
        self._custom_editing = -1
        vars_["name"].set("")
        vars_["base"].set("https://api.openai.com/v1")
        vars_["key"].set("")
        vars_["model"].set("gpt-4o-mini")
        if lb:
            lb.selection_clear(0, "end")
        self.status_var.set("新增平台：已填入 OpenAI 官方模板，请填写平台名称后保存")

    def _collect_form_vars(self, dlg):
        return getattr(dlg, "formvars", {})

    def _find_listbox(self, dlg):
        lb = getattr(dlg, "formlistbox", None)
        if lb:
            return lb

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Listbox):
                    return c
                r = walk(c)
                if r:
                    return r
            return None
        return walk(dlg)

    def _save_platform(self, dlg):
        vars_ = self._collect_form_vars(dlg)
        if not vars_:
            return
        name = vars_["name"].get().strip()
        if not name:
            messagebox.showwarning("提示", "请填写平台名称", parent=dlg)
            return
        lb = self._find_listbox(dlg)
        sel = lb.curselection()
        if sel:
            p = self.custom_platforms[sel[0]]
            old = p["name"]
            if name != old and any(q["name"] == name for q in self.custom_platforms):
                messagebox.showwarning("提示", "平台名称已存在", parent=dlg)
                return
            if name != old and old in self.custom_models:
                self.custom_models[name] = self.custom_models.pop(old)
            p.update(name=name, base_url=vars_["base"].get().strip(),
                     api_key=vars_["key"].get().strip(), model=vars_["model"].get().strip())
            self.status_var.set("已保存平台: %s" % name)
        else:
            if any(q["name"] == name for q in self.custom_platforms):
                messagebox.showwarning("提示", "平台名称已存在", parent=dlg)
                return
            self.custom_platforms.append({
                "name": name,
                "base_url": vars_["base"].get().strip(),
                "api_key": vars_["key"].get().strip(),
                "model": vars_["model"].get().strip(),
            })
            self._custom_editing = len(self.custom_platforms) - 1
            self.status_var.set("已添加自定义平台: %s" % name)
        self._persist_models()
        self._refresh_backends()
        self._refresh_custom_list(dlg)

    def _del_platform(self, dlg):
        lb = self._find_listbox(dlg)
        sel = lb.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先在列表中选择要删除的平台", parent=dlg)
            return
        p = self.custom_platforms[sel[0]]
        if not messagebox.askyesno("确认删除", "删除自定义平台「%s」？" % p["name"], parent=dlg):
            return
        self.custom_platforms.pop(sel[0])
        self.custom_models.pop(p["name"], None)
        self._custom_editing = -1
        self._persist_models()
        self._refresh_backends()
        self.status_var.set("已删除平台: %s" % p["name"])
        self._refresh_custom_list(dlg)

    def _reload_custom_dialog(self, dlg):
        """轻量刷新：仅重灌列表、保留选择。"""
        self._refresh_custom_list(dlg)

    # ------------------------------------------------------------ 文件载入/保存
    def _load_file(self):
        path = filedialog.askopenfilename(
            title="选择待翻译文件",
            filetypes=[("文本文件", "*.md *.txt *.json"), ("所有文件", "*.*")])
        if not path:
            return
        self._load_file_from_path(path)

    def _load_file_from_path(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(path, encoding="utf-8-sig") as f:
                    content = f.read()
            except Exception as e:
                log.error("读取文件失败: %s | %s", path, e)
                messagebox.showerror("读取失败", str(e))
                return
        except Exception as e:
            log.error("读取文件失败: %s | %s", path, e)
            messagebox.showerror("读取失败", str(e))
            return
        self.in_text.delete("1.0", "end")
        self.in_text.insert("1.0", content)
        self.loaded_path = path
        log.info("已加载文件: %s (%d字符)", path, len(content))
        self.status_var.set("已加载: %s" % os.path.basename(path))

    def _open_editor(self):
        BidirectionalEditor(self.root, self)

    def _open_usage(self):
        """弹出「使用说明」窗口（可滚动大窗口）。"""
        win = tk.Toplevel(self.root)
        win.title("使用说明 - 多功能翻译工具")
        win.configure(bg=BG)
        win.geometry("680x620")
        win.minsize(520, 400)
        try:
            win.transient(self.root)
        except Exception:
            pass

        text = tk.Text(win, wrap="word", bg="#fbfbfb", fg="#303030",
                       font=("Microsoft YaHei UI", 10), padx=14, pady=14,
                       insertbackground="white", relief="flat")
        sb = ttk.Scrollbar(win, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        ttk.Button(win, text="知道了", command=win.destroy).pack(anchor="e", pady=8)
        text.configure(state="normal")
        text.insert("1.0", USAGE_TEXT)
        text.configure(state="disabled")

    # ------------------------------------------------------------ 批量翻译
    def _batch_translate(self):
        if self.busy:
            return
        self._ask_batch_source()

    def _ask_batch_source(self):
        """批量翻译前先让用户选择输入方式：文件夹 或 文件列表txt。"""
        dlg = tk.Toplevel(self.root)
        dlg.title("批量翻译 - 选择输入方式")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        try:
            dlg.geometry("+%d+%d" % (self.root.winfo_rootx() + 120,
                                     self.root.winfo_rooty() + 120))
        except Exception:
            pass
        tk.Label(dlg, text="请选择批量翻译的输入方式：",
                 font=("Microsoft YaHei UI", 10)).pack(padx=28, pady=(18, 8))
        bf = ttk.Frame(dlg)
        bf.pack(padx=28, pady=8)
        ttk.Button(bf, text="① 选择文件夹（读取其中全部文件）", width=30,
                   command=lambda: self._batch_source_folder(dlg)).pack(fill="x", pady=4)
        ttk.Button(bf, text="② 读取文件列表（.txt，内含文件地址）", width=30,
                   command=lambda: self._batch_source_list(dlg)).pack(fill="x", pady=4)
        ttk.Button(bf, text="取消", width=30, command=dlg.destroy).pack(fill="x", pady=(12, 4))

    def _batch_source_folder(self, dlg):
        dlg.destroy()
        folder = filedialog.askdirectory(title="选择待翻译文件夹")
        if not folder:
            return
        exts = {".md", ".txt", ".json", ".markdown", ".text"}
        files = []
        for root, _dirs, names in os.walk(folder):
            for n in sorted(names):
                if os.path.splitext(n)[1].lower() in exts:
                    files.append(os.path.join(root, n))
        self._queue_batch(files)

    def _batch_source_list(self, dlg):
        dlg.destroy()
        path = filedialog.askopenfilename(
            title="选择含文件地址的列表文件(.txt)",
            filetypes=[("文本文件", "*.txt *.lst"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except UnicodeDecodeError:
            try:
                with open(path, encoding="utf-8-sig") as f:
                    lines = f.read().splitlines()
            except Exception as e:
                messagebox.showerror("读取失败", str(e))
                return
        except Exception as e:
            messagebox.showerror("读取失败", str(e))
            return
        files, missing = [], []
        for ln in lines:
            p = ln.strip()
            if not p or p.startswith("#"):
                continue
            if os.path.isfile(p):
                files.append(p)
            else:
                missing.append(p)
        self._queue_batch(files)
        if missing:
            preview = "\n".join(missing[:20])
            extra = "……" if len(missing) > 20 else ""
            messagebox.showwarning("文件列表", "%d 个路径不存在，已忽略：\n%s%s"
                                   % (len(missing), preview, extra))

    def _queue_batch(self, files):
        """收集待翻译文件，等待用户点击「翻译并导出」后一起执行。"""
        if not files:
            if not self._pending_batch:
                messagebox.showinfo("批量翻译", "没有找到可翻译的文件。")
            return
        self._pending_batch[:] = files
        self.status_var.set("已添加 %d 个待翻译文件，点击「翻译并导出」开始批量翻译" % len(files))
        log.info("批量翻译待处理列表就绪: %d 个文件", len(files))

    def _run_batch(self, files):
        if not files:
            messagebox.showinfo("提示", "未找到任何待翻译文件")
            return
        backend, params = self._collect_params()
        if backend == "百度翻译" and (not params["appid"] or not params["appkey"]):
            messagebox.showwarning("缺少凭据", "请填写百度翻译 APPID 和 密钥/API Key")
            return
        if backend == "硅基流动" and not params["api_key"]:
            messagebox.showwarning("缺少凭据", "请填写硅基流动 API Key")
            return
        if backend == "腾讯云机器翻译" and (not params["secret_id"] or not params["secret_key"]):
            messagebox.showwarning("缺少凭据", "请填写腾讯云机器翻译的 SecretId 与 SecretKey")
            return
        if backend == "阿里云机器翻译" and (not params["access_key_id"] or not params["access_key_secret"]):
            messagebox.showwarning("缺少凭据", "请填写阿里云机器翻译的 AccessKey ID 与 AccessKey Secret")
            return
        if backend == "彩云小译" and not params["token"]:
            messagebox.showwarning("缺少凭据", "请填写彩云小译访问令牌 Token")
            return
        if backend.startswith(CUSTOM_PREFIX) and not params["api_key"]:
            messagebox.showwarning("缺少凭据", "请填写该自定义 OpenAI 平台的 API Key")
            return
        lang = self.to_var.get().strip() or "中文"
        self.busy = True
        self.cancel_requested = False
        self._pause_event.set()
        win = self._get_batch_window()
        self.batch_pause_btn.config(state="normal", text="暂停")
        self.batch_stop_btn.config(state="normal")
        self.status_var.set("批量翻译 %d 个文件…（%s）" % (len(files), backend))
        log.info("批量翻译开始: %d 个文件, backend=%s, lang=%s, model=%s",
                 len(files), backend, lang, params.get("model", ""))
        self._start_progress()
        self._init_batch_queue(files)
        threading.Thread(target=self._batch_worker,
                         args=(files, backend, params, lang), daemon=True).start()

    def _get_batch_window(self):
        """创建（或复用）批量翻译队列的独立弹出窗口。"""
        if self.batch_win is not None and self.batch_win.winfo_exists():
            return self.batch_win
        win = tk.Toplevel(self.root)
        win.title("批量文件队列")
        win.configure(bg=BG)
        win.geometry("680x460")
        win.minsize(500, 320)
        try:
            win.transient(self.root)
        except Exception:
            pass
        top = ttk.LabelFrame(win, text="待翻译 / 已完成文件")
        top.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        inner = ttk.Frame(top)
        inner.pack(fill="both", expand=True, padx=6, pady=6)
        tree = ttk.Treeview(inner, columns=("status",), show="tree headings",
                            selectmode="none", height=10)
        tree.heading("#0", text="文件")
        tree.heading("status", text="状态")
        tree.column("#0", width=470, anchor="w")
        tree.column("status", width=110, anchor="center")
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(inner, orient="vertical", command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)
        tree.tag_configure("pending", foreground="#7f8c8d")
        tree.tag_configure("running", foreground="#2980b9")
        tree.tag_configure("done", foreground="#27ae60")
        tree.tag_configure("warn", foreground="#d68910")
        tree.tag_configure("failed", foreground="#c0392b")

        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=10, pady=6)
        self.batch_status_var = tk.StringVar(value="就绪")
        tk.Label(bar, textvariable=self.batch_status_var, bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left", padx=4)
        pause = ttk.Button(bar, text="暂停", command=self._toggle_pause, state="disabled")
        pause.pack(side="right", padx=4)
        stop = ttk.Button(bar, text="停止", command=self._cancel, state="disabled")
        stop.pack(side="right", padx=4)

        win.protocol("WM_DELETE_WINDOW", self._close_batch_window)
        self.batch_win = win
        self.batch_tree = tree
        self.batch_pause_btn = pause
        self.batch_stop_btn = stop
        return win

    def _close_batch_window(self):
        """关闭批量窗口：翻译进行中不允许关闭，结束后可直接关闭。"""
        if self.busy:
            self.batch_status_var.set("翻译进行中，无法关闭；可先停止")
            return
        self.batch_win.destroy()
        self.batch_win = None

    def _init_batch_queue(self, files):
        """初始化批量文件队列窗口，全部标记为待处理并显示。"""
        win = self._get_batch_window()
        try:
            win.deiconify()
            win.lift()
        except Exception:
            pass
        if self.batch_status_var is not None:
            self.batch_status_var.set("开始翻译 %d 个文件…" % len(files))
        for it in self.batch_tree.get_children():
            self.batch_tree.delete(it)
        self.batch_tree["height"] = min(10, len(files)) if files else 4
        for src in files:
            self.batch_tree.insert("", "end", iid=src, text=os.path.basename(src),
                                   values=("待处理",), tags=("pending",))

    def _update_batch_item(self, src, status):
        """更新某个文件的队列状态。status ∈ pending/running/done/warn/failed。"""
        labels = {"pending": "待处理", "running": "正在处理",
                  "done": "已完成", "warn": "结构异常", "failed": "失败"}
        tags = {"pending": "pending", "running": "running",
                "done": "done", "warn": "warn", "failed": "failed"}
        if src not in self.batch_tree.get_children():
            self.batch_tree.insert("", "end", iid=src, text=os.path.basename(src),
                                   values=(labels[status],), tags=(tags[status],))
        else:
            self.batch_tree.item(src, values=(labels[status],), tags=(tags[status],))

    def _write_batch_report(self, files, done, failed, warns, stopped, total,
                            backend, params, lang, elapsed):
        """批量翻译结束后，把统计与明细报告写入桌面。"""
        desktop = _desktop_path()
        if not desktop:
            log.warning("找不到桌面目录，跳过批量报告生成")
            return
        stamp = time.strftime("%Y%m%d_%H%M%S")
        L = ["批量翻译报告", "=" * 44]
        L.append("时间     : %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
        L.append("翻译后端 : %s" % backend)
        L.append("目标语言 : %s" % lang)
        L.append("模型     : %s" % params.get("model", ""))
        L.append("文件总数 : %d" % total)
        L.append("成功     : %d" % len(done))
        L.append("结构异常 : %d" % len(warns))
        L.append("失败     : %d" % len(failed))
        L.append("未处理   : %d" % (total - len(done) - len(failed)))
        L.append("总耗时   : %.1f 秒" % elapsed)
        L.append("")
        L.append("成功文件"); L.append("-" * 44)
        L.extend(done if done else ["（无）"])
        L.append("")
        L.append("结构异常"); L.append("-" * 44)
        L.extend(warns if warns else ["（无）"])
        L.append("")
        L.append("失败"); L.append("-" * 44)
        L.extend(failed if failed else ["（无）"])
        path = os.path.join(desktop, "翻译报告_%s.txt" % stamp)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(L))
            log.info("批量翻译报告已写入: %s", path)
        except Exception as e:
            log.error("批量报告写入失败: %s | %s", path, e)

    def _batch_worker(self, files, backend, params, lang):
        t0 = time.time()
        try:
            tf = self._with_retry(self._make_translate_fn(backend, params))
            done, failed, warns = [], [], []
            total = len(files)
            for i, src in enumerate(files, 1):
                if self.cancel_requested:
                    break
                if not self._wait_if_paused():
                    break
                t_file = time.time()
                self.q.put(("batch_file", (src, "running")))
                try:
                    try:
                        with open(src, encoding="utf-8") as f:
                            text = f.read()
                    except UnicodeDecodeError:
                        with open(src, encoding="utf-8-sig") as f:
                            text = f.read()
                except Exception as e:
                    log.error("批量读取失败: %s | %s", src, e)
                    failed.append("%s：读取失败：%s" % (os.path.basename(src), e))
                    self.q.put(("batch_file", (src, "failed")))
                    self.q.put(("batch_progress", (i, total)))
                    continue
                try:
                    dst = preserve_translate(text, tf)
                except Exception as e:
                    log.error("批量翻译失败: %s | %s", src, e)
                    failed.append("%s：翻译失败：%s" % (os.path.basename(src), e))
                    self.q.put(("batch_file", (src, "failed")))
                    self.q.put(("batch_progress", (i, total)))
                    continue
                try:
                    stem, ext = os.path.splitext(os.path.basename(src))
                    out = os.path.join(os.path.dirname(src), "%s-%s翻译%s" % (stem, lang, ext))
                    with open(out, "w", encoding="utf-8") as f:
                        f.write(dst)
                    done.append(out)
                    sn, dn = segment_counts(text, dst)
                    if sn != dn:
                        warns.append("%s：段落结构异常（原文 %d 段 / 译文 %d 段）"
                                     % (os.path.basename(src), sn, dn))
                        self.q.put(("batch_file", (src, "warn")))
                    else:
                        self.q.put(("batch_file", (src, "done")))
                except Exception as e:
                    log.error("批量写入失败: %s | %s", out, e)
                    failed.append("%s：写入失败：%s" % (os.path.basename(src), e))
                    self.q.put(("batch_file", (src, "failed")))
                self.q.put(("batch_progress", (i, total)))
                if self.cancel_requested:
                    break
                log.info("批量文件完成: %s → %s, 耗时=%.1fs",
                         os.path.basename(src), os.path.basename(out),
                         time.time() - t_file)
            log.info("批量翻译结束: 成功=%d, 结构异常=%d, 失败=%d, 停止=%s, 总耗时=%.1fs",
                     len(done), len(warns), len(failed), bool(self.cancel_requested),
                     time.time() - t0)
            self._write_batch_report(files, done, failed, warns, bool(self.cancel_requested),
                                     total, backend, params, lang, time.time() - t0)
            self.q.put(("batch_done", (done, failed, bool(self.cancel_requested), total, warns)))
        except Exception as e:
            log.error("批量翻译异常: %s", e, exc_info=True)
            self.q.put(("batch_error", str(e)))

    def _default_export_path(self):
        """按「原文件名-xx翻译.原扩展名」生成导出路径（与原文件同目录、同格式）。"""
        if not self.loaded_path:
            return None
        d = os.path.dirname(self.loaded_path)
        stem, ext = os.path.splitext(os.path.basename(self.loaded_path))
        lang = self.to_var.get().strip() or "中文"
        return os.path.join(d, "%s-%s翻译%s" % (stem, lang, ext))

    # ---------------------------------------------------- 主界面悬停词对照
    def _link_tag(self, side):
        """给某一侧文本框配置悬停对照 tag 与事件绑定。"""
        w = self.in_text if side == "in" else self.out_text
        w.tag_config("mlink", background="#C9DFFF")
        w.bind("<Enter>", self._main_hover)
        w.bind("<Motion>", self._main_hover)
        w.bind("<Leave>", self._main_leave)

    def _link_refresh(self):
        if not getattr(self, "_LINK_CACHE", None):
            self._LINK_CACHE = {"in_txt": None, "out_txt": None, "in_toks": [],
                                "out_toks": [], "aligned": {}, "rev": {}}
        it = self.in_text.get("1.0", "end-1c")
        ot = self.out_text.get("1.0", "end-1c")
        if it == self._LINK_CACHE["in_txt"] and ot == self._LINK_CACHE["out_txt"]:
            return
        ins = wa.word_tokens(it)
        outs = wa.word_tokens(ot)
        aligned = wa.align_tokens([t[2] for t in ins], [u[2] for u in outs])
        rev = {}
        for i, js in aligned.items():
            for j in js:
                rev.setdefault(j, []).append(i)
        self._LINK_CACHE.update(in_txt=it, out_txt=ot, in_toks=ins,
                                out_toks=outs, aligned=aligned, rev=rev)

    def _main_hover(self, event):
        self._link_refresh()
        self.in_text.tag_remove("mlink", "1.0", "end")
        self.out_text.tag_remove("mlink", "1.0", "end")
        w = event.widget
        if w is self.in_text:
            text, toks, oth, oth_txt, oth_toks, mp = (
                self._LINK_CACHE["in_txt"], self._LINK_CACHE["in_toks"],
                self.out_text, self._LINK_CACHE["out_txt"], self._LINK_CACHE["out_toks"],
                self._LINK_CACHE["aligned"])
        elif w is self.out_text:
            text, toks, oth, oth_txt, oth_toks, mp = (
                self._LINK_CACHE["out_txt"], self._LINK_CACHE["out_toks"],
                self.in_text, self._LINK_CACHE["in_txt"], self._LINK_CACHE["in_toks"],
                self._LINK_CACHE["rev"])
        else:
            return
        try:
            tk_idx = w.index("@%d,%d" % (event.x, event.y))
        except Exception:
            return
        char = wa.index_to_char(text, tk_idx)
        tid = wa.token_at(toks, char)
        if tid is None:
            return
        st, en, _ = toks[tid]
        w.tag_add("mlink", wa.char_to_index(text, st), wa.char_to_index(text, en))
        for j in mp.get(tid, []):
            if j >= len(oth_toks):
                continue
            s2, e2, _ = oth_toks[j]
            oth.tag_add("mlink", wa.char_to_index(oth_txt, s2), wa.char_to_index(oth_txt, e2))

    def _main_leave(self, event):
        self.in_text.tag_remove("mlink", "1.0", "end")
        self.out_text.tag_remove("mlink", "1.0", "end")

    def _save_file(self):
        content = self.out_text.get("1.0", "end-1c")
        if not content.strip():
            messagebox.showinfo("提示", "译文为空，无需保存")
            return
        default = self._default_export_path()
        path = filedialog.asksaveasfilename(
            title="保存译文",
            initialdir=os.path.dirname(default) if default else None,
            initialfile=os.path.basename(default) if default else None,
            defaultextension=os.path.splitext(default)[1] if default else ".md",
            filetypes=[("Markdown", "*.md"), ("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        log.info("译文已保存: %s (%d字符)", path, len(content))
        self.status_var.set("已保存: %s" % os.path.basename(path))

    # ------------------------------------------------------------ 翻译
    def _cancel(self):
        if self.busy:
            self.cancel_requested = True
            self._pause_event.set()
            self.status_var.set("正在取消…")

    def _toggle_pause(self):
        """批量翻译暂停 / 继续切换（仅在文件边界真正挂起）。"""
        if self._pause_event.is_set():
            self._pause_event.clear()
            self.batch_pause_btn.config(text="继续")
            self.status_var.set("批量翻译已暂停")
            if self.batch_status_var is not None:
                self.batch_status_var.set("已暂停，点击「继续」恢复")
            log.info("批量翻译已暂停")
        else:
            self._pause_event.set()
            self.batch_pause_btn.config(text="暂停")
            self.status_var.set("批量翻译继续中…")
            if self.batch_status_var is not None:
                self.batch_status_var.set("继续翻译中…")
            log.info("批量翻译已继续")

    def _wait_if_paused(self):
        """批量 worker 在文件边界阻塞等待恢复；返回 False 表示已被取消，应中止。"""
        while not self._pause_event.is_set():
            if self.cancel_requested:
                return False
            time.sleep(0.1)
        return True

    def _with_retry(self, tf, retries=3, delay=2.0):
        """给翻译函数加失败重试（带固定退避间隔）。"""
        def wrapped(t):
            last = None
            for attempt in range(retries):
                try:
                    return tf(t)
                except Exception as e:
                    last = e
                    if attempt < retries - 1:
                        time.sleep(delay)
            raise last
        return wrapped

    def _load_progress(self, path, text_hash):
        """读取断点进度文件；文本哈希一致才复用缓存。"""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("text_hash") == text_hash:
                return data.get("cache", {})
        except Exception:
            pass
        return {}

    def _save_progress(self, path, text_hash, cache):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"text_hash": text_hash, "cache": cache},
                          f, ensure_ascii=False)
        except Exception:
            pass

    def _enc_secret(self, value):
        """加密敏感字段；加密失败返回空串（调用方回退明文）。"""
        if not value:
            return ""
        try:
            return secure_store.encrypt_text(value)
        except Exception:
            return ""

    def _dec_secret(self, enc):
        if not enc:
            return ""
        try:
            return secure_store.decrypt_text(enc) or ""
        except Exception:
            return ""

    def _collect_params(self):
        backend = self.backend_var.get()
        from_code = LANG_CODE.get(self.from_var.get().strip(), "jp")
        to_code = LANG_CODE.get(self.to_var.get().strip(), "zh")
        params = {"from": from_code, "to": to_code,
                  "max_tokens": int(self.max_tokens_var.get() or 8192)}
        if backend == "百度翻译":
            params.update({
                "appid": self.baidu_appid.get().strip(),
                "appkey": self.baidu_appkey.get().strip(),
                "auth": self.baidu_auth.get(),
                "endpoint": BAIDU_ENDPOINTS[self.baidu_mode.get()],
            })
        elif backend == "硅基流动":
            params.update({
                "base_url": self.sf_base.get().strip(),
                "api_key": self.sf_key.get().strip(),
                "model": self.sf_model.get().strip(),
                "system": self._get_system_prompt(),
            })
        elif backend == "LM Studio 本地":
            params.update({
                "base_url": self.lm_base.get().strip(),
                "api_key": "lm-studio",
                "model": self.lm_model.get().strip(),
                "system": self._get_system_prompt(),
            })
        elif backend == "腾讯云机器翻译":
            params.update({
                "secret_id": self.tc_secret_id.get().strip(),
                "secret_key": self.tc_secret_key.get().strip(),
                "region": self.tc_region.get().strip() or TENCENT_REGION,
            })
        elif backend == "阿里云机器翻译":
            params.update({
                "access_key_id": self.ali_access_key_id.get().strip(),
                "access_key_secret": self.ali_access_key_secret.get().strip(),
            })
        elif backend == "彩云小译":
            params.update({
                "token": self.caiyun_token.get().strip(),
            })
        else:  # 自定义 OpenAI 格式
            params.update({
                "base_url": self.custom_base.get().strip(),
                "api_key": self.custom_key.get().strip(),
                "model": self.custom_model.get().strip(),
                "system": self._get_system_prompt(),
            })
        return backend, params

    def _start_translate(self, export=False):
        if self.busy:
            return
        if self._pending_batch:
            files = self._pending_batch
            self._pending_batch = []
            self._run_batch(files)
            return
        text = self.in_text.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showinfo("提示", "请输入待翻译文本")
            return
        backend, params = self._collect_params()
        if backend == "百度翻译" and (not params["appid"] or not params["appkey"]):
            messagebox.showwarning("缺少凭据", "请填写百度翻译 APPID 和 密钥/API Key（两种鉴权方式均需 APPID）")
            return
        if backend == "硅基流动" and not params["api_key"]:
            messagebox.showwarning("缺少凭据", "请填写硅基流动 API Key")
            return
        if backend == "腾讯云机器翻译" and (not params["secret_id"] or not params["secret_key"]):
            messagebox.showwarning("缺少凭据", "请填写腾讯云机器翻译的 SecretId 与 SecretKey")
            return
        if backend == "阿里云机器翻译" and (not params["access_key_id"] or not params["access_key_secret"]):
            messagebox.showwarning("缺少凭据", "请填写阿里云机器翻译的 AccessKey ID 与 AccessKey Secret")
            return
        if backend == "彩云小译" and not params["token"]:
            messagebox.showwarning("缺少凭据", "请填写彩云小译访问令牌 Token")
            return
        if backend.startswith(CUSTOM_PREFIX) and not params["api_key"]:
            messagebox.showwarning("缺少凭据", "请填写该自定义 OpenAI 平台的 API Key")
            return
        export_path = None
        if export:
            export_path = self._default_export_path()
            if not export_path:
                messagebox.showinfo("提示", "请先通过「从文件加载」选择要翻译的文件")
                return
        self.busy = True
        self.cancel_requested = False
        self.cancel_btn.config(state="normal")
        self.status_var.set("翻译中…（%s）" % backend)
        model = params.get("model", "")
        log.info("开始翻译: backend=%s, from=%s, to=%s, model=%s, 文本长度=%d字符, 保留排版=是",
                 backend, params.get("from"), params.get("to"), model, len(text))
        self._start_progress()
        threading.Thread(target=self._worker, args=(backend, params, text, export_path), daemon=True).start()

    def _make_translate_fn(self, backend=None, params=None):
        """根据当前后端配置构造翻译函数 tf(文本) -> 译文，失败抛异常。"""
        if backend is None or params is None:
            backend, params = self._collect_params()
        if backend == "百度翻译":
            def tf(t):
                dst, err = translate_one(params["appid"], params["appkey"], t,
                                         params["from"], params["to"], params["endpoint"],
                                         auth=params["auth"])
                if err:
                    raise RuntimeError(err)
                return dst
        elif backend == "腾讯云机器翻译":
            def tf(t):
                dst, err = tencent_translate_one(
                    params["secret_id"], params["secret_key"], t,
                    params["from"], params["to"], params["region"])
                if err:
                    raise RuntimeError(err)
                return dst
        elif backend == "阿里云机器翻译":
            def tf(t):
                dst, err = alicloud_translate_one(
                    params["access_key_id"], params["access_key_secret"], t,
                    params["from"], params["to"])
                if err:
                    raise RuntimeError(err)
                return dst
        elif backend == "彩云小译":
            def tf(t):
                dst, err = caiyun_translate_one(params["token"], t,
                                                params["from"], params["to"])
                if err:
                    raise RuntimeError(err)
                return dst
        else:
            sys_prompt = params.get("system", LLM_SYSTEM)

            def tf(t):
                ok, raw = openai_compat.chat_completion(
                    params["base_url"], params["api_key"], params["model"],
                    sys_prompt, t, max_tokens=params["max_tokens"])
                if not ok:
                    raise RuntimeError(raw)
                return strip_fences(raw)
        return self._with_retry(tf)

    def _make_reverse_translate_fn(self, backend=None, params=None):
        """构造反向翻译函数（译文→原文，交换源/目标语言）。"""
        if backend is None or params is None:
            backend, params = self._collect_params()
        rfrom, rto = params["to"], params["from"]
        if backend == "百度翻译":
            def tf(t):
                dst, err = translate_one(params["appid"], params["appkey"], t,
                                         rfrom, rto, params["endpoint"], auth=params["auth"])
                if err:
                    raise RuntimeError(err)
                return dst
        elif backend == "腾讯云机器翻译":
            def tf(t):
                dst, err = tencent_translate_one(params["secret_id"],
                                                 params["secret_key"], t,
                                                 rfrom, rto, params["region"])
                if err:
                    raise RuntimeError(err)
                return dst
        elif backend == "阿里云机器翻译":
            def tf(t):
                dst, err = alicloud_translate_one(params["access_key_id"],
                                                  params["access_key_secret"], t,
                                                  rfrom, rto)
                if err:
                    raise RuntimeError(err)
                return dst
        elif backend == "彩云小译":
            def tf(t):
                dst, err = caiyun_translate_one(params["token"], t, rfrom, rto)
                if err:
                    raise RuntimeError(err)
                return dst
        else:
            sys_prompt = build_system_prompt(LANG_NAMES.get(rfrom, rfrom),
                                             LANG_NAMES.get(rto, rto))

            def tf(t):
                ok, raw = openai_compat.chat_completion(
                    params["base_url"], params["api_key"], params["model"],
                    sys_prompt, t, max_tokens=params["max_tokens"])
                if not ok:
                    raise RuntimeError(raw)
                return strip_fences(raw)
        return self._with_retry(tf)

    def _worker(self, backend, params, text, export_path=None):
        t0 = time.time()
        cache = None
        text_hash = ""
        progress_path = None
        if export_path:
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            progress_path = export_path + ".progress.json"
            cache = self._load_progress(progress_path, text_hash)
        try:
            tf = self._make_translate_fn(backend, params)

            def progress_cb(done, total):
                if self.cancel_requested:
                    raise TranslationCancelled()
                if progress_path:
                    self._save_progress(progress_path, text_hash, cache)
                self.q.put(("progress", (done, total)))

            dst = preserve_translate(text, tf, progress_cb, cache)
            if export_path:
                with open(export_path, "w", encoding="utf-8") as f:
                    f.write(dst)
                if progress_path and os.path.exists(progress_path):
                    os.remove(progress_path)
                self.q.put(("done_export", (dst, export_path)))
            else:
                self.q.put(("done", dst))
            sn, dn = segment_counts(text, dst)
            self.q.put(("format_check", (sn, dn)))
            log.info("翻译完成: backend=%s, 原文=%d字符, 译文=%d字符, 耗时=%.1fs, 导出=%s",
                     backend, len(text), len(dst), time.time() - t0,
                     export_path or "否")
        except TranslationCancelled:
            self.q.put(("cancelled", None))
            log.info("翻译被取消: backend=%s, 耗时=%.1fs", backend, time.time() - t0)
        except Exception as e:
            log.error("翻译失败: backend=%s, err=%s, 耗时=%.1fs",
                      backend, e, time.time() - t0, exc_info=True)
            self.q.put(("error", str(e)))

    def _start_progress(self):
        """翻译开始时立即显示（绿色滚动动画，表示实时进行中）。"""
        self.progress_bar.configure(mode="indeterminate")
        self.progress_wrap.pack(side="right", fill="x", expand=True, padx=(8, 12), pady=6)
        try:
            self.progress_bar.start(25)
        except Exception:
            pass

    def _show_progress(self, maximum, value):
        if self.progress_bar.cget("mode") == "indeterminate":
            self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate", maximum=maximum, value=value)
        self.progress_wrap.pack(side="right", fill="x", expand=True, padx=(8, 12), pady=6)

    def _hide_progress(self):
        try:
            self.progress_bar.stop()
        except Exception:
            pass
        self.progress_wrap.pack_forget()

    # ------------------------------------------------------------ 拖拽文件
    def _enable_drag_drop(self):
        """启用拖拽文件加载。优先使用 tkinterdnd2（若已安装），否则静默跳过。"""
        try:
            if hasattr(self.root, "drop_target_register"):
                self.root.drop_target_register("DND_Files")
                self.root.dnd_bind("<<Drop>>", self._on_drop)
                log.info("拖拽支持已启用 (tkinterdnd2)")
            else:
                log.info("拖拽支持未启用: 未检测到 tkinterdnd2")
        except Exception as e:
            log.warning("拖拽支持不可用: %s", e)

    def _on_drop(self, event):
        try:
            files = self.root.tk.splitlist(event.data)
            if files:
                path = files[0]
                log.info("拖拽文件: %s", path)
                self._load_file_from_path(path)
        except Exception as e:
            log.error("拖拽处理失败: %s", e, exc_info=True)

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "progress":
                    done, total = payload
                    self.status_var.set("翻译中… %d/%d" % (done, total))
                    self._show_progress(total, done)
                    continue
                if kind == "batch_progress":
                    cur, batch_total = payload
                    self.status_var.set("批量翻译中… %d/%d" % (cur, batch_total))
                    if self.batch_status_var is not None:
                        self.batch_status_var.set("翻译中 %d/%d" % (cur, batch_total))
                    self._show_progress(batch_total, cur)
                    continue
                if kind == "batch_file":
                    src, status = payload
                    self._update_batch_item(src, status)
                    continue
                if kind == "done":
                    self.out_text.delete("1.0", "end")
                    self.out_text.insert("1.0", payload)
                    self.status_var.set("翻译完成")
                elif kind == "done_export":
                    dst, path = payload
                    self.out_text.delete("1.0", "end")
                    self.out_text.insert("1.0", dst)
                    self.status_var.set("翻译完成，已导出: %s" % path)
                elif kind == "format_check":
                    sn, dn = payload
                    if sn != dn:
                        self.status_var.set("翻译完成（结构校验：原文 %d 段 / 译文 %d 段）"
                                            % (sn, dn))
                        messagebox.showwarning(
                            "结构校验提示",
                            "译文段落数与原文不一致（原文 %d 段 / 译文 %d 段）。\n\n"
                            "AI 可能合并或拆分了部分段落，请检查译文结构是否完整、"
                            "是否存在内容丢失。" % (sn, dn))
                    else:
                        self.status_var.set("翻译完成（结构校验通过）")
                elif kind == "cancelled":
                    self.status_var.set("已取消（进度已保存，可再次翻译续传）")
                elif kind == "error":
                    self.status_var.set("翻译失败")
                    messagebox.showerror("翻译失败", payload)
                elif kind == "conn_result":
                    ok, msg = payload
                    self.status_var.set("连接测试: %s" % ("成功" if ok else "失败"))
                    if ok:
                        messagebox.showinfo("连接测试", msg)
                    else:
                        messagebox.showerror("连接测试失败", msg)
                elif kind == "models_result":
                    backend, ok, models = payload
                    if ok:
                        self._set_models(backend, models)
                        self.status_var.set("获取到 %d 个模型" % len(models))
                    else:
                        self.status_var.set("获取模型失败")
                        messagebox.showerror("获取模型失败", models)
                elif kind == "batch_done":
                    done, failed, stopped, total, warns = payload
                    self.out_text.delete("1.0", "end")
                    lines = ["已生成：%s" % os.path.basename(p) for p in done]
                    lines += ["结构异常：%s" % w for w in warns]
                    lines += ["失败：%s" % m for m in failed]
                    if stopped:
                        remaining = total - len(done) - len(failed)
                        lines.append("已停止：剩余 %d 个文件未处理" % remaining)
                    self.out_text.insert("1.0", "\n".join(lines) or "（无输出）")
                    if stopped:
                        self.status_var.set("批量翻译已停止（成功 %d，结构异常 %d，"
                                            "失败 %d，未处理 %d）"
                                            % (len(done), len(warns), len(failed),
                                               total - len(done) - len(failed)))
                        msg = ["已翻译 %d 个文件：" % len(done)]
                        msg += done if done else ["（无）"]
                        if warns:
                            msg.append("-" * 30)
                            msg += ["结构异常 %d 个：" % len(warns)]
                            msg += warns
                        if failed:
                            msg.append("-" * 30)
                            msg += ["失败 %d 个：" % len(failed)]
                            msg += failed
                        remaining = total - len(done) - len(failed)
                        if remaining:
                            msg.append("-" * 30)
                            msg.append("另有 %d 个文件未处理。" % remaining)
                        messagebox.showinfo("批量翻译已停止", "\n".join(msg))
                    else:
                        self.status_var.set("批量翻译完成：成功 %d，结构异常 %d，失败 %d"
                                            % (len(done), len(warns), len(failed)))
                        alerts = []
                        if warns:
                            alerts.append("结构异常 %d 个：\n%s"
                                          % (len(warns), "\n".join(warns)))
                        if failed:
                            alerts.append("失败 %d 个：\n%s"
                                          % (len(failed), "\n".join(failed)))
                        if alerts:
                            messagebox.showwarning(
                                "批量翻译",
                                "成功 %d 个。\n\n%s" % (len(done), "\n\n".join(alerts)))
                        else:
                            messagebox.showinfo("批量翻译", "全部 %d 个文件翻译完成。"
                                                % len(done))
                elif kind == "batch_error":
                    self.status_var.set("批量翻译失败")
                    messagebox.showerror("批量翻译失败", payload)
                self.busy = False
                self.cancel_btn.config(state="disabled")
                if self.batch_status_var is not None:
                    self.batch_status_var.set("批量翻译结束")
                if self.batch_pause_btn is not None:
                    self.batch_pause_btn.config(state="disabled", text="暂停")
                    self.batch_stop_btn.config(state="disabled")
                self._pause_event.set()
                self._hide_progress()
        except queue.Empty:
            pass
        self.root.after(100, self._poll)