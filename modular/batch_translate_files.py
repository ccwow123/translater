# -*- coding: utf-8 -*-
"""批量翻译脚本：把一个或多个文本文件（.md / .txt / .json）逐文件翻译成对应译文文件。

使用自定义 OpenAI 兼容后端，保留 Markdown 排版。每个源文件在输出目录生成同级译文文件：
  <源文件名>-<目标语言>翻译<扩展名>   例：article.md -> article-中文翻译.md

用法（在本目录 modular/ 下执行）：
  # 翻译单个文件 / 多个文件
  python batch_translate_files.py --input a.md b.md --base-url URL --api-key KEY --model m

  # 翻译整个文件夹（含子目录）
  python batch_translate_files.py --input ./articles --base-url URL --api-key KEY --model m

  # 翻译到指定输出目录 / 指定源/目标语言 / 跳过已存在的译文
  python batch_translate_files.py --input ./articles --output-dir ./out --to zh --skip-existing

凭据优先级：--api-key > 环境变量 CUSTOM_OPENAI_API_KEY。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.constants import LANG_NAMES, LANG_CODE, build_system_prompt
from src.core.preserve import preserve_translate
from src.backends import openai_compat

TEXT_EXTS = (".md", ".txt", ".json", ".markdown", ".text")


def collect_files(paths):
    """把传入的路径展开为文件列表：文件直接加入，目录递归收集文本文件。"""
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                for n in sorted(names):
                    if n.lower().endswith(TEXT_EXTS):
                        files.append(os.path.join(root, n))
        elif os.path.isfile(p):
            files.append(p)
        else:
            print("[警告] 路径不存在，已跳过: %s" % p)
    return files


def default_output_path(src_path, lang_name, output_dir=None):
    """生成译文输出路径：<原名>-<目标语言>翻译<后缀>，可放到指定输出目录。"""
    stem, ext = os.path.splitext(os.path.basename(src_path))
    fname = "%s-%s翻译%s" % (stem, lang_name, ext)
    if output_dir:
        return os.path.join(output_dir, fname)
    return os.path.join(os.path.dirname(src_path), fname)


def make_translate_fn(params, to_lang_name):
    """构造单段翻译函数 tf(文本)->译文，失败抛异常。"""
    sys_prompt = build_system_prompt(params["from_name"], to_lang_name)

    def tf(text):
        ok, raw = openai_compat.chat_completion(
            params["base_url"], params["api_key"], params["model"],
            sys_prompt, text, max_tokens=params["max_tokens"])
        if not ok:
            raise RuntimeError(raw)
        from src.constants import strip_fences
        return strip_fences(raw)
    return tf


def build_arg_parser():
    ap = argparse.ArgumentParser(description="使用自定义 OpenAI 兼容后端批量翻译多个文件")
    ap.add_argument("--input", nargs="+", required=True,
                    help="待翻译的文件或文件夹（多个；文件夹会递归收集 .md/.txt/.json）")
    ap.add_argument("--base-url", default="https://api.openai.com/v1", help="OpenAI 兼容接口地址")
    ap.add_argument("--api-key", default="", help="API Key；缺省读环境变量 CUSTOM_OPENAI_API_KEY")
    ap.add_argument("--model", default="", help="模型名")
    ap.add_argument("--from", dest="from_lang", default="日文", help="源语言(中文显示名或代码)")
    ap.add_argument("--to", dest="to_lang", default="中文", help="目标语言(中文显示名或代码)")
    ap.add_argument("--output-dir", default="", help="译文输出目录；缺省与源文件同目录")
    ap.add_argument("--max-tokens", type=int, default=8192, help="单次请求最大输出 token 数")
    ap.add_argument("--skip-existing", action="store_true",
                    help="若译文文件已存在则跳过该文件")
    return ap


def resolve_lang(value):
    """把语言显示名或代码转成 (代码, 中文名)。"""
    value = value.strip()
    if value in LANG_CODE:            # 中文显示名
        code = LANG_CODE[value]
        return code, LANG_NAMES.get(code, value)
    if value.lower() in LANG_NAMES:   # 语言代码 zh/en/jp...
        key = value.lower()
        return key, LANG_NAMES.get(key, value)
    return value, value               # 无法识别则原样


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    api_key = args.api_key or os.environ.get("CUSTOM_OPENAI_API_KEY", "").strip()
    if not api_key:
        print("[错误] 未提供 API Key：请用 --api-key 传入，或设置环境变量 CUSTOM_OPENAI_API_KEY。",
              file=sys.stderr)
        return 1
    if not args.model:
        print("[错误] 未指定模型：请用 --model 传入模型名。", file=sys.stderr)
        return 1
    if args.output_dir and not os.path.isdir(args.output_dir):
        try:
            os.makedirs(args.output_dir, exist_ok=True)
        except Exception as e:
            print("[错误] 无法创建输出目录 %s: %s" % (args.output_dir, e), file=sys.stderr)
            return 1

    from_code, from_name = resolve_lang(args.from_lang)
    to_code, to_name = resolve_lang(args.to_lang)
    params = {
        "base_url": args.base_url.strip(), "api_key": api_key,
        "model": args.model.strip(), "max_tokens": args.max_tokens,
        "from_name": from_name,
    }

    files = collect_files(args.input)
    if not files:
        print("[错误] 未找到任何可翻译的文本文件（支持 %s）" % ", ".join(TEXT_EXTS),
              file=sys.stderr)
        return 1

    print("后端: %s | 模型: %s | 语言: %s→%s"
          % (params["base_url"], params["model"], from_name, to_name))
    print("待处理文件: %d 个" % len(files))

    tf = make_translate_fn(params, to_name)
    done, skipped, failed = 0, 0, 0
    for i, src in enumerate(files, 1):
        dst_path = default_output_path(src, to_name, args.output_dir.strip())
        if args.skip_existing and os.path.exists(dst_path):
            print("[%d/%d] 跳过(已存在): %s" % (i, len(files), os.path.basename(src)))
            skipped += 1
            continue
        try:
            with open(src, encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError:
            try:
                with open(src, encoding="utf-8-sig") as f:
                    text = f.read()
            except Exception as e:
                print("[%d/%d] 失败(读取): %s | %s" % (i, len(files), os.path.basename(src), e))
                failed += 1
                continue
        except Exception as e:
            print("[%d/%d] 失败(读取): %s | %s" % (i, len(files), os.path.basename(src), e))
            failed += 1
            continue

        try:
            dst = preserve_translate(text, tf)
        except Exception as e:
            print("[%d/%d] 失败(翻译): %s | %s" % (i, len(files), os.path.basename(src), e))
            failed += 1
            continue

        try:
            with open(dst_path, "w", encoding="utf-8") as f:
                f.write(dst)
            print("[%d/%d] 完成: %s -> %s" % (i, len(files), os.path.basename(src),
                                              os.path.basename(dst_path)))
            done += 1
        except Exception as e:
            print("[%d/%d] 失败(写入): %s | %s" % (i, len(files), os.path.basename(src), e))
            failed += 1

    print("\n汇总: 成功 %d | 跳过 %d | 失败 %d" % (done, skipped, failed))
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())