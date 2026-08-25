# -*- coding: utf-8 -*-
"""命令行批量翻译：baidu / siliconflow / lmstudio 三个子命令。

将原 translate_baidu.py / translate_siliconflow.py / translate_lmstudio.py
三个脚本的入口逻辑统一于此，复用 src.core.batch 的批处理流水线，
OpenAI 兼容链路（硅基/LM/自定义）共享同一实现。

用法：
  python run_cli.py baidu      --input 路径 --output 路径 [--auth apikey]
  python run_cli.py siliconflow --input 路径 [--glossary 对照表]
  python run_cli.py lmstudio   --model qwen2.5-7b-instruct [--list-models]
"""

import argparse
import os
import sys

from src.backends import baidu, openai_compat
from src.core import batch as runner
from src.core import glossary

DEFAULT_INPUT = "04_源数据/technique_文章清单.json"
DEFAULT_GLOSSARY = "03_提取稿件/technique_文章标题清单_中文.md"


def add_common_args(p, default_sleep):
    p.add_argument("--input", default=DEFAULT_INPUT,
                   help="输入文件：含 title 的 JSON 数组，或每行一条的纯文本")
    p.add_argument("--output", default="", help="输出文件；缺省为 <input同名>_xx译文.json")
    p.add_argument("--json-key", default="title", help="输入 JSON 数组中代表原文的字段名")
    p.add_argument("--start", type=int, default=0, help="从第几条开始(0-based)")
    p.add_argument("--limit", type=int, default=0, help="最多翻译条数；0=全部")
    p.add_argument("--sleep", type=float, default=default_sleep, help="每条/每批之间休眠秒数")
    p.add_argument("--max-retries", type=int, default=3, help="失败重试次数")


# ------------------------------------------------------------------ 百度
def _baidu_credential(args):
    appid = (args.appid or os.environ.get("BAIDU_TRANS_APPID", "")).strip()
    appkey = (args.appkey or os.environ.get("BAIDU_TRANS_APPKEY", "")).strip()
    if not appid or not appkey:
        sys.exit("未提供凭据：请设置环境变量 BAIDU_TRANS_APPID / BAIDU_TRANS_APPKEY，"
                 "或用 --appid / --appkey 传入（两种鉴权方式均需 APPID）。")
    return appid, appkey


def cmd_baidu(args):
    ap = argparse.ArgumentParser(description="调用百度翻译 API 进行日→中翻译",
                                 prog="run_cli.py baidu")
    add_common_args(ap, default_sleep=baidu.DEFAULT_SLEEP)
    ap.add_argument("--mode", choices=tuple(baidu.ENDPOINTS), default=baidu.DEFAULT_MODE,
                    help="翻译接口：llm=大模型文本翻译(默认)，general=通用文本翻译")
    ap.add_argument("--auth", choices=("sign", "apikey"), default="sign",
                    help="鉴权方式：sign=签名鉴权(appid+密钥)，apikey=API Key 鉴权(Bearer)")
    ap.add_argument("--appid", default="", help="百度翻译 APPID；缺省读环境变量 BAIDU_TRANS_APPID")
    ap.add_argument("--appkey", default="", help="百度翻译密钥；缺省读环境变量 BAIDU_TRANS_APPKEY")
    ap.add_argument("--from", dest="from_lang", default=baidu.DEFAULT_FROM, help="源语言代码(默认 jp)")
    ap.add_argument("--to", default=baidu.DEFAULT_TO, help="目标语言代码(默认 zh)")
    ap.add_argument("--max-q-chars", type=int, default=baidu.MAX_Q_CHARS, help="单次请求 q 最大字符数")
    ap.add_argument("--test", action="store_true", help="单条自检：翻译输入第一行并打印原始响应")
    args = ap.parse_args(args)

    appid, appkey = _baidu_credential(args)
    endpoint = baidu.ENDPOINTS[args.mode]
    print("接口: %s\n%s" % (args.mode, endpoint), flush=True)

    entries, json_key = runner.load_entries(args.input, args.json_key)
    entries = runner.slice_entries(entries, args.start, args.limit)

    if args.test:
        it = entries[0]
        src = it.get(json_key) or it.get("_text")
        print("自检原文: %s" % src, flush=True)
        dst, err = baidu.translate_one(appid, appkey, src, args.from_lang, args.to,
                                       endpoint, auth=args.auth)
        if err:
            sys.exit("自检失败: %s" % err)
        print("自检译文: %s" % dst, flush=True)
        return

    out_path = runner.resolve_output_path(args.input, args.output, "百度译文")
    done = runner.load_done(out_path)
    pending = runner.build_pending(entries, json_key, done)
    print("待翻译条数: %d | 命中断点缓存: %d" % (len(pending), len(done)), flush=True)

    def translate(src):
        return baidu.translate_one(appid, appkey, src, args.from_lang, args.to, endpoint,
                                   max_q_chars=args.max_q_chars, auth=args.auth)

    runner.run_single(pending, done, out_path, translate,
                      retries=args.max_retries, sleep=args.sleep)


# ------------------------------------------------------------------ OpenAI 兼容（硅基 / LM / 自定义）
def _openai_credential(args, env_var, default_key=""):
    api_key = args.api_key or os.environ.get(env_var, "") or default_key
    if not api_key:
        sys.exit("未提供 API Key：请设置环境变量 %s 或用 --api-key 传入。" % env_var)
    return api_key


def cmd_siliconflow(args):
    ap = argparse.ArgumentParser(description="调用硅基流动 API 进行日→中翻译",
                                 prog="run_cli.py siliconflow")
    add_common_args(ap, default_sleep=0.0)
    ap.add_argument("--base-url", default=openai_compat.DEFAULT_BASE_URL, help="硅基流动 API 地址")
    ap.add_argument("--api-key", default="", help="API 密钥；缺省读环境变量 SILICONFLOW_API_KEY")
    ap.add_argument("--model", default="", help="模型名；缺省用 %s" % openai_compat.DEFAULT_MODEL)
    ap.add_argument("--glossary", default=DEFAULT_GLOSSARY,
                    help="已人工翻译对照表(md)路径；不需要可传空字符串")
    ap.add_argument("--chunk-size", type=int, default=10, help="每次请求翻译的条数")
    ap.add_argument("--max-tokens", type=int, default=4096, help="单次请求最大输出 token 数")
    ap.add_argument("--list-models", action="store_true", help="仅列出可用模型后退出")
    args = ap.parse_args(args)

    api_key = _openai_credential(args, "SILICONFLOW_API_KEY")

    if args.list_models:
        models = openai_compat.get_models(args.base_url, api_key)
        print("硅基流动可用模型：")
        for m in models:
            print("  " + m)
        return

    model = args.model or openai_compat.DEFAULT_MODEL
    print("使用模型: %s" % model, flush=True)
    _run_llm_batch(args, api_key, model, "硅基译文")


def cmd_lmstudio(args):
    ap = argparse.ArgumentParser(description="调用 LM Studio 本地模型进行日→中翻译",
                                 prog="run_cli.py lmstudio")
    add_common_args(ap, default_sleep=0.0)
    ap.add_argument("--base-url", default="http://localhost:1234/v1", help="LM Studio API 地址")
    ap.add_argument("--api-key", default="lm-studio", help="API 密钥(本地任意值即可)")
    ap.add_argument("--model", default="", help="模型名；缺省时尝试取 /models 第一个")
    ap.add_argument("--glossary", default=DEFAULT_GLOSSARY,
                    help="已人工翻译对照表(md)路径；不需要可传空字符串")
    ap.add_argument("--chunk-size", type=int, default=10, help="每次请求翻译的条数")
    ap.add_argument("--max-tokens", type=int, default=4096, help="单次请求最大输出 token 数")
    ap.add_argument("--list-models", action="store_true", help="仅列出本地已加载模型后退出")
    args = ap.parse_args(args)

    api_key = args.api_key or "lm-studio"

    if args.list_models:
        models = openai_compat.get_models(args.base_url, api_key)
        print("已加载模型：")
        for m in models:
            print("  " + m)
        return

    model = args.model
    if not model:
        models = openai_compat.get_models(args.base_url, api_key)
        candidates = [m for m in models if not m.startswith("<")]
        if not candidates:
            sys.exit("未指定 --model 且无法从本地 API 获取模型列表，请显式传入 --model 或用 --list-models 查看。")
        model = candidates[0]
        print("自动选择模型: %s" % model, flush=True)
    _run_llm_batch(args, api_key, model, "本地译文")


def _run_llm_batch(args, api_key, model, suffix):
    entries, json_key = runner.load_entries(args.input, args.json_key)
    entries = runner.slice_entries(entries, args.start, args.limit)
    out_path = runner.resolve_output_path(args.input, args.output, suffix)
    done = runner.load_done(out_path)
    pending = runner.build_pending(entries, json_key, done)
    gl = glossary.load_glossary(args.glossary) if args.glossary else []
    print("待翻译条数: %d | 命中断点缓存: %d | 术语映射: %d"
          % (len(pending), len(done), len(gl)), flush=True)

    cfg = {
        "base_url": args.base_url, "api_key": api_key, "model": model,
        "glossary": gl, "json_key": json_key,
        "chunk_size": args.chunk_size, "sleep": args.sleep,
        "max_tokens": args.max_tokens,
    }

    def tbatch(items):
        return openai_compat.translate_batch(cfg, items)

    runner.run_batch(pending, done, out_path, tbatch,
                     chunk_size=args.chunk_size, sleep=args.sleep,
                     retries=args.max_retries)


def main(argv=None):
    ap = argparse.ArgumentParser(description="多后端批量翻译命令行工具")
    sub = ap.add_subparsers(dest="backend", required=True)
    sub.add_parser("baidu", help="百度翻译开放平台")
    sub.add_parser("siliconflow", help="硅基流动 API")
    sub.add_parser("lmstudio", help="LM Studio 本地模型")

    argv = list(argv) if argv is not None else sys.argv[1:]
    backend = argv[0] if argv else ""
    rest = argv[1:]
    if backend == "baidu":
        cmd_baidu(rest)
    elif backend == "siliconflow":
        cmd_siliconflow(rest)
    elif backend == "lmstudio":
        cmd_lmstudio(rest)
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()