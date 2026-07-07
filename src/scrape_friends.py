# -*- coding: utf-8 -*-
"""
好友名单抓取（OCR 滚动通讯录）
==============================
微信 4.x 自渲染读不到控件，用"滚动通讯录 + 截图 + OCR"提取联系人名字。
依赖 calibrate.py 里校准的 contacts_tab 和 contacts_list_region。

两种调用方式：
  1. CLI:   python -m src.scrape_friends
  2. 模块:  from .scrape_friends import run_scrape
            run_scrape(log=print, progress=None, stop_event=None)

注意：OCR 抓名字会有少量噪声/漏字，跑完后请人工扫一眼 friends.txt。
"""

import json
import time

import pyautogui

from .ocr_utils import init_ocr, ocr_image
from .paths import COORDS_FILE, FRIENDS_FILE


SKIP_NAMES = {
    "新的朋友", "群聊", "标签", "公众号", "企业微信联系人", "通讯录",
    "文件传输助手", "腾讯新闻", "微信团队", "微信支付", "weixin",
}

DEFAULTS = {
    "SCROLL_PAUSE": 1.2,
    "MAX_ROUNDS": 400,
    "STABLE_STOP": 3,
}


def load_coords(log=print):
    if not COORDS_FILE.exists():
        log(f"[错误] 没找到 {COORDS_FILE}，请先校准坐标")
        return None
    c = json.loads(COORDS_FILE.read_text(encoding="utf-8"))
    miss = [k for k in ("contacts_tab", "contacts_list_region") if k not in c]
    if miss:
        log(f"[错误] coords.json 缺少: {miss}，请重跑校准")
        return None
    return c


def _click(p, log=print):
    pyautogui.click(p["x"], p["y"])
    time.sleep(0.6)


def _screenshot_region(region):
    left = region["left"]
    top = region["top"]
    width = region["right"] - region["left"]
    height = region["bottom"] - region["top"]
    return pyautogui.screenshot(region=(left, top, width, height))


def _clean_name(line):
    s = line.strip()
    if not s:
        return ""
    for ch in " \t\r\n·、,，:：()（）":
        s = s.replace(ch, "")
    if len(s) < 2:
        return ""
    if s.isdigit():
        return ""
    if len(s) == 1 and s.isascii():
        return ""
    return s


def run_scrape(params=None, log=print, progress=None, stop_event=None):
    """抓好友名单主流程。供 GUI 或 CLI 调用。"""
    cfg = dict(DEFAULTS)
    if params:
        cfg.update(params)

    log("=" * 60)
    log("好友名单抓取  |  OCR 滚动通讯录")
    log("=" * 60)

    coords = load_coords(log=log)
    if coords is None:
        return None

    log("\n[1/3] 初始化 OCR...")
    try:
        init_ocr()
    except SystemExit as e:
        log(f"[错误] OCR 初始化失败: {e}")
        return None

    log("[2/3] 切换到通讯录并滚到顶部...")
    _click(coords["contacts_tab"], log=log)
    time.sleep(1.5)
    region = coords["contacts_list_region"]
    pyautogui.click(region["left"] + 30, region["top"] + 30)
    time.sleep(0.8)
    for _ in range(10):
        pyautogui.press("pgup")
        time.sleep(0.15)
    time.sleep(1)

    log(f"[3/3] 开始滚动抓取（最多 {cfg['MAX_ROUNDS']} 轮，连续 {cfg['STABLE_STOP']} 轮无新名字则停）...")
    seen = set()
    names = []
    last_count = 0
    stable = 0

    def _stopped():
        return stop_event is not None and stop_event.is_set()

    for rnd in range(1, cfg["MAX_ROUNDS"] + 1):
        if _stopped():
            log(f"\n[中断] 用户请求停止，第 {rnd} 轮")
            break
        img = _screenshot_region(region)
        text = ocr_image(img)
        new_this_round = 0
        for line in text.splitlines():
            nm = _clean_name(line)
            if nm and nm not in SKIP_NAMES and nm not in seen:
                seen.add(nm)
                names.append(nm)
                new_this_round += 1

        log(f"  轮 {rnd}: 本轮新增 {new_this_round:3d}，累计 {len(names)}")
        if progress:
            progress(rnd, len(names))

        if len(names) == last_count:
            stable += 1
            if stable >= cfg["STABLE_STOP"]:
                log(f"  连续 {cfg['STABLE_STOP']} 轮无新名字，停止。")
                break
        else:
            stable = 0
        last_count = len(names)

        pyautogui.press("pagedown")
        time.sleep(cfg["SCROLL_PAUSE"])

    FRIENDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    FRIENDS_FILE.write_text("\n".join(names), encoding="utf-8")
    log(f"\n完成！共 {len(names)} 个名字写入 {FRIENDS_FILE}")
    log("\n⚠️ 请人工扫一眼 friends.txt：")
    log("   - 删掉明显不是人名的行（OCR 误识别）")
    log("   - 删掉群名/公众号名等不是好友的项")
    log("   - 确认后跑 wx_check.py 开始检测")
    return names


def main():
    run_scrape(DEFAULTS)


if __name__ == "__main__":
    main()
