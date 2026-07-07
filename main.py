# -*- coding: utf-8 -*-
"""
微信好友状态检测  |  GUI 客户端入口
====================================
双击运行或 python main.py 启动 GUI 客户端。

CLI 用法（在项目根目录）：
    python -m src.show_wechat --test     # 测 wxauto4
    python -m src.calibrate              # 校准坐标
    python -m src.scrape_friends         # 抓好友名单
    python -m src.wx_check               # 跑检测
    python -m src.ledger [stats|show|clear]  # 账本管理
    python build_exe.py [--full]         # 打包成 exe
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path，让 `from src.xxx import` 能工作
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.gui import main

if __name__ == "__main__":
    main()
