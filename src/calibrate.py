# -*- coding: utf-8 -*-
"""
坐标校准工具（点击录制版）
==========================
为 scrape_friends.py 校准通讯录相关坐标。

两种调用方式：
  1. CLI:   python -m src.calibrate
  2. 模块:  from .calibrate import Calibrator, run_calibrate
            run_calibrate(log=print, on_step=callback, on_done=callback)

需要校准的 2 项：
  1. contacts_tab       左侧导航栏「通讯录」图标（单点）
  2. contacts_list_region 通讯录页右侧联系人列表（框选）

紧急中断：鼠标甩到左上角 (0,0) 触发 pyautogui FailSafe。
"""

import json
import time

import pyautogui
from pynput import mouse

from .paths import COORDS_FILE, ensure_dirs

pyautogui.FAILSAFE = True

STEPS = [
    ("contacts_tab", "point", "1/2 通讯录标签 —— 点左侧导航栏「通讯录」图标"),
    ("contacts_list_region", "region", "2/2 联系人列表区域 —— 在通讯录页框选右侧联系人列表（点左上角+右下角）"),
]


class Calibrator:
    """点击捕获器：启动 pynput 监听，等用户点击，返回坐标。

    阻塞式调用，应在子线程跑（避免阻塞 GUI 主线程）。
    """

    def __init__(self, log=print):
        self._listener = None
        self._click_pos = None
        self.log = log

    def _on_click(self, x, y, button, pressed):
        if pressed and button == mouse.Button.left:
            self._click_pos = (int(x), int(y))

    def capture_point(self, prompt):
        self.log(f"    请在微信里点击: {prompt}")
        self._click_pos = None
        self._listener = mouse.Listener(on_click=self._on_click)
        self._listener.daemon = True
        self._listener.start()
        try:
            while self._click_pos is None:
                time.sleep(0.05)
            pos = self._click_pos
            self.log(f"    已记录: {pos}")
            return pos
        except pyautogui.FailSafeException:
            self.log("    [放弃] 鼠标触发左上角 FailSafe")
            return None
        finally:
            if self._listener is not None:
                self._listener.stop()
                self._listener = None

    def capture_region(self, prompt):
        self.log(f"    框选区域: {prompt}")
        tl = self.capture_point("点击区域【左上角】")
        if tl is None:
            return None
        br = self.capture_point("点击区域【右下角】")
        if br is None:
            return None
        region = {
            "left": min(tl[0], br[0]),
            "top": min(tl[1], br[1]),
            "right": max(tl[0], br[0]),
            "bottom": max(tl[1], br[1]),
        }
        self.log(f"    区域: {region}")
        return region


def load_coords():
    if COORDS_FILE.exists():
        try:
            return json.loads(COORDS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_coords(coords):
    ensure_dirs()
    COORDS_FILE.write_text(json.dumps(coords, ensure_ascii=False, indent=2), encoding="utf-8")
    return COORDS_FILE


def run_calibrate(log=print, on_step=None, on_done=None, only_keys=None):
    """跑校准流程。阻塞调用，应在子线程跑。"""
    log("=" * 60)
    log("坐标校准（点击录制版）")
    log("=" * 60)
    log("方式：按提示在微信里直接点击目标，脚本自动记录点击坐标。")
    log("前提：微信已登录、窗口在左上角。")

    cal = Calibrator(log=log)
    coords = load_coords()
    if coords:
        log(f"\n发现已有 coords.json，将在其基础上更新。")

    for key, kind, prompt in STEPS:
        if only_keys and key not in only_keys:
            continue
        log("\n" + "-" * 60)
        if on_step:
            on_step(key, kind, prompt)
        if kind == "point":
            val = cal.capture_point(prompt)
            if val is not None:
                coords[key] = {"x": val[0], "y": val[1]}
        else:
            val = cal.capture_region(prompt)
            if val is not None:
                coords[key] = val
        save_coords(coords)
        log(f"    已保存到 {COORDS_FILE}")
        if on_step:
            on_step(key, kind, prompt, value=coords.get(key))

    log("\n" + "=" * 60)
    log("校准完成！")
    log("=" * 60)
    if on_done:
        on_done(coords)
    return coords


def main():
    """CLI 入口：交互式校准，已有值可选择保留/重校/跳过。"""
    existing = load_coords()
    if existing:
        print(f"发现已有 coords.json: {existing}\n")

    cal = Calibrator()
    coords = dict(existing)
    for key, kind, prompt in STEPS:
        print("\n" + "-" * 60)
        if key in existing:
            print(f"已有值: {existing[key]}")
            choice = input("选择 [回车=保留 / r=重校 / s=跳过]: ").strip().lower()
            if choice == "" or choice == "s":
                continue
        if kind == "point":
            val = cal.capture_point(prompt)
            if val is not None:
                coords[key] = {"x": val[0], "y": val[1]}
        else:
            val = cal.capture_region(prompt)
            if val is not None:
                coords[key] = val
        save_coords(coords)
        print(f"    已保存到 {COORDS_FILE}")

    print("\n校准完成！下一步: python -m src.scrape_friends")


if __name__ == "__main__":
    main()
