# -*- coding: utf-8 -*-
"""
坐标校准工具（点击录制版）
==========================
为 scrape_friends.py 校准通讯录相关坐标。

需要校准的 2 项：
  1. 通讯录标签       左侧导航栏「通讯录」图标
  2. 联系人列表区域   通讯录页右侧联系人列表（点两个角框选）

准备：
  - 微信已登录，窗口在左上角，位置别再动
  - 运行: python calibrate.py
  - 按提示在微信里点击对应位置即可，脚本自动记录
  - 紧急中断：鼠标甩到左上角 (0,0)
"""

import json
import time
from pathlib import Path

import pyautogui
from pynput import mouse

COORDS_FILE = Path(__file__).parent / "coords.json"

pyautogui.FAILSAFE = True

_click_pos = None
_listener = None


def _on_click(x, y, button, pressed):
    global _click_pos
    if pressed and button == mouse.Button.left:
        _click_pos = (int(x), int(y))


def _start_listener():
    global _listener, _click_pos
    _click_pos = None
    _listener = mouse.Listener(on_click=_on_click)
    _listener.daemon = True
    _listener.start()


def _stop_listener():
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None


def wait_for_click(prompt):
    global _click_pos
    print(f"\n>>> {prompt}")
    print("    请在【微信窗口】里点击目标位置，脚本会自动记录你点的坐标。")
    print("    （放弃此步：鼠标甩到左上角 (0,0) 触发 FailSafe）")
    _start_listener()
    try:
        while _click_pos is None:
            time.sleep(0.05)
        pos = _click_pos
        print(f"    已记录: {pos}")
        return pos
    except pyautogui.FailSafeException:
        print("\n    [放弃] 鼠标触发左上角 FailSafe，跳过此步。")
        return None
    finally:
        _stop_listener()


def capture_point(prompt):
    pos = wait_for_click(prompt)
    if pos is None:
        return None
    return {"x": pos[0], "y": pos[1]}


def capture_region(prompt):
    """框选区域：点左上角 + 点右下角。"""
    print(f"\n>>> {prompt}")
    print("    需要框选矩形区域，点两个角。")
    tl = wait_for_click("在微信里点击区域【左上角】")
    if tl is None:
        return None
    br = wait_for_click("在微信里点击区域【右下角】")
    if br is None:
        return None
    region = {
        "left": min(tl[0], br[0]),
        "top": min(tl[1], br[1]),
        "right": max(tl[0], br[0]),
        "bottom": max(tl[1], br[1]),
    }
    print(f"    区域: {region}")
    return region


def main():
    print("=" * 60)
    print("坐标校准（点击录制版）  |  为 scrape_friends.py 校准通讯录坐标")
    print("=" * 60)
    print("方式：按提示在微信里直接点击目标，脚本自动记录点击坐标。")
    print("前提：微信已登录、窗口在左上角。")

    existing = {}
    if COORDS_FILE.exists():
        try:
            existing = json.loads(COORDS_FILE.read_text(encoding="utf-8"))
            print(f"\n发现已有 coords.json，可在此基础上更新。")
        except Exception:
            pass

    steps = [
        ("contacts_tab", "point",
         "1/2 通讯录标签 —— 点左侧导航栏「通讯录」图标（点完进通讯录页）"),
        ("contacts_list_region", "region",
         "2/2 联系人列表区域 —— 在通讯录页，框选右侧联系人列表区域（点左上角+右下角）"),
    ]

    coords = dict(existing)
    for key, kind, prompt in steps:
        print("\n" + "-" * 60)
        if key in existing:
            print(f"已有值: {existing[key]}")
            choice = input("选择 [回车=保留 / r=重校 / s=跳过]: ").strip().lower()
            if choice == "" or choice == "s":
                continue
        if kind == "point":
            val = capture_point(prompt)
        else:
            val = capture_region(prompt)
        if val is not None:
            coords[key] = val
            COORDS_FILE.write_text(json.dumps(coords, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"    已保存到 {COORDS_FILE}")
        else:
            print(f"    未记录（跳过）")

    print("\n" + "=" * 60)
    print("校准完成！配置已保存到", COORDS_FILE)
    print("=" * 60)
    print("\n下一步：")
    print("  1. 抓好友名单:  python scrape_friends.py")
    print("  2. 跑检测:      python wx_check.py")


if __name__ == "__main__":
    main()
