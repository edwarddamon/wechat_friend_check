# -*- coding: utf-8 -*-
"""
PyInstaller 打包脚本
====================
把项目打包成单个 exe，客户双击即可运行（无需装 Python）。

  python build_exe.py            # 打包（~60-90MB）

要求：
  pip install pyinstaller

输出：
  dist/微信好友状态检测.exe
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent
APP_NAME = "微信好友状态检测"
ENTRY = "main.py"                  # GUI 入口
DIST = BASE_DIR / "dist"
BUILD = BASE_DIR / "build"
SPEC = BASE_DIR / f"{APP_NAME}.spec"


def run(cmd):
    print(f"\n>>> {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=BASE_DIR)


def ensure_pyinstaller():
    try:
        import PyInstaller
        print(f"PyInstaller {PyInstaller.__version__} 已安装")
    except ImportError:
        print("未检测到 PyInstaller，正在安装: pip install pyinstaller")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def clean():
    for d in (DIST, BUILD):
        if d.exists():
            print(f"清理 {d}")
            shutil.rmtree(d, ignore_errors=True)
    if SPEC.exists():
        SPEC.unlink()


def hidden_imports():
    return [
        "--hidden-import", "wxauto4",
        "--hidden-import", "wxauto4.wx",
        "--hidden-import", "wxauto4.ui.main",
        "--hidden-import", "wxauto4.ui.component",
        "--hidden-import", "wxauto4.ui.sessionbox",
        "--hidden-import", "wxauto4.ui.navigationbox",
        "--hidden-import", "wxauto4.ui.chatbox",
        "--hidden-import", "wxauto4.uia.uiautomation",
        "--hidden-import", "wxauto4.utils",
        "--hidden-import", "uiautomation",
        "--hidden-import", "win32gui",
        "--hidden-import", "win32con",
        "--hidden-import", "win32process",
        "--hidden-import", "win32api",
        "--hidden-import", "pythoncom",
        # src 包
        "--hidden-import", "src",
        "--hidden-import", "src.gui",
        "--hidden-import", "src.wx_check",
        "--hidden-import", "src.auto_scrape",
        "--hidden-import", "src.show_wechat",
        "--hidden-import", "src.ledger",
        "--hidden-import", "src.paths",
    ]


def build():
    print("\n=== 打包中 ===")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", APP_NAME,
        "--noconfirm",
        "--clean",
    ] + hidden_imports() + [
        "--collect-all", "wxauto4",
        ENTRY,
    ]
    run(cmd)
    show_result()


def show_result():
    print("\n" + "=" * 60)
    exe = DIST / f"{APP_NAME}.exe"
    if exe.exists():
        size_mb = exe.stat().st_size / 1024 / 1024
        print(f"✅ 打包成功!")
        print(f"   输出: {exe}")
        print(f"   大小: {size_mb:.1f} MB")
        print(f"   双击即可运行（首次启动较慢，需解压到临时目录）")
    else:
        print(f"❌ 打包失败，请检查上方日志")
        sys.exit(1)
    print("=" * 60)
    print("\n分发说明：")
    print(f"  把 {exe.name} 单独发给客户即可")
    print("  客户首次运行时，会在 exe 同目录生成:")
    print("    data/friends.txt    - 好友名单（GUI 自动抓取或手动导入）")
    print("    output/             - 检测结果 + 账本")
    print("\n  客户需自备: 微信 4.1.8.107 + 主窗口可见")


def main():
    ensure_pyinstaller()
    clean()
    build()


if __name__ == "__main__":
    main()
