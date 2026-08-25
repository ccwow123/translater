"""智能解析 GUI 启动器应使用的 pythonw 路径。

优先顺序：
1. launcher.ini 中显式配置的路径（每行一个，支持 纯路径 / key=path / "path"）
2. 已知的 torchg 环境
3. 自动扫描 Miniconda envs 下所有环境
4. 当前解释器（仅当其自带 tkinterdnd2 时）

仅输出一行可用的 pythonw 绝对路径；无可用环境时退出码非 0。
"""
import importlib.util
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, 'launcher.ini')
CONDA = r'e:\Files\manga-translator-ui\Miniconda3'


def read_configured():
    candidates = []
    if not os.path.exists(CONFIG):
        return candidates
    with open(CONFIG, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                line = line.split('=', 1)[1]
            line = line.strip().strip('"').strip("'")
            if line:
                candidates.append(line)
    return candidates


def candidate_envs():
    candidates = []
    envs = os.path.join(CONDA, 'envs')
    if os.path.isdir(envs):
        for name in sorted(os.listdir(envs)):
            p = os.path.join(envs, name, 'pythonw.exe')
            if os.path.isfile(p):
                candidates.append(p)
    return candidates


def has_tkdnd(entry):
    if entry.lower().endswith('pythonw.exe'):
        probe = entry[:-len('pythonw.exe')] + 'python.exe'
        if not os.path.isfile(probe):
            probe = entry
    else:
        probe = entry
    code = ("import importlib.util, sys;"
            "sys.exit(0 if importlib.util.find_spec('tkinterdnd2') else 1)")
    try:
        r = subprocess.run([probe, '-c', code], capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def main():
    for c in read_configured() + [os.path.join(CONDA, 'envs', 'torchg', 'pythonw.exe')] + candidate_envs():
        if os.path.isfile(c) and has_tkdnd(c):
            print(c)
            return 0
    try:
        if importlib.util.find_spec('tkinterdnd2'):
            print(sys.executable)
            return 0
    except Exception:
        pass
    return 1


if __name__ == '__main__':
    sys.exit(main())