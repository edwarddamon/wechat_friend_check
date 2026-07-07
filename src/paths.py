# -*- coding: utf-8 -*-
"""统一路径定义。

打包后用 exe 同目录，源码运行用项目根目录（src 的父目录）。
所有模块从这里导入路径，避免散落的 Path(__file__).parent。
"""

import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    # PyInstaller 打包后：exe 同目录
    BASE_DIR = Path(sys.executable).parent
else:
    # 源码运行：src/ 的父目录就是项目根
    BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

# 数据文件
FRIENDS_FILE = DATA_DIR / "friends.txt"
LEDGER_FILE = OUTPUT_DIR / "checked_ledger.csv"


def ensure_dirs():
    """确保运行时目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
