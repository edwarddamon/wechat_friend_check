# -*- coding: utf-8 -*-
"""
好友名单抓取（OCR 滚动通讯录）
==============================
微信 4.x 自渲染读不到控件，用"滚动通讯录 + 截图 + OCR"提取联系人名字。
依赖 calibrate.py 里校准的 contacts_tab 和 contacts_list_region。

流程：
  1. 点通讯录标签
  2. 点列表顶部聚焦
  3. 循环：截图列表区域 → OCR → 收集名字 → PageDown 滚动
  4. 连续 3 次没新名字就停
  5. 去重 → friends.txt

注意：OCR 抓名字会有少量噪声/漏字，跑完后请人工扫一眼 friends.txt，
删掉明显不是人名的行（单字母、系统项等），再跑 check.py。
"""

import json
import time
from pathlib import Path

import pyautogui

from ocr_utils import init_ocr, ocr_image

COORDS_FILE = Path(__file__).parent / "coords.json"
OUT_FILE = Path(__file__).parent / "friends.txt"

SKIP_NAMES = {
    "新的朋友", "群聊", "标签", "公众号", "企业微信联系人", "通讯录",
    "文件传输助手", "腾讯新闻", "微信团队", "微信支付", "weixin",
}

SCROLL_PAUSE = 1.2          # 每次滚动后等界面渲染秒数
MAX_ROUNDS = 400            # 最多滚动轮数，防死循环
STABLE_STOP = 3             # 连续 N 轮无新名字则停


def load_coords():
    if not COORDS_FILE.exists():
        raise SystemExit(f"没找到 {COORDS_FILE}，请先运行 python calibrate.py")
    return json.loads(COORDS_FILE.read_text(encoding="utf-8"))


def click(p):
    pyautogui.click(p["x"], p["y"])
    time.sleep(0.6)


def screenshot_region(region):
    left = region["left"]
    top = region["top"]
    width = region["right"] - region["left"]
    height = region["bottom"] - region["top"]
    return pyautogui.screenshot(region=(left, top, width, height))


def clean_name(line):
    """从 OCR 一行文本里提取可能是人名的部分。"""
    s = line.strip()
    if not s:
        return ""
    # 去掉常见噪声字符
    for ch in " \t\r\n·、,，:：()（）":
        s = s.replace(ch, "")
    # 过滤：单字符、纯字母索引、纯数字、含明显非人名关键词
    if len(s) < 2:
        return ""
    if s.isdigit():
        return ""
    # 单字母索引行（A/B/C...）
    if len(s) == 1 and s.isascii():
        return ""
    return s


def main():
    print("=" * 60)
    print("好友名单抓取  |  OCR 滚动通讯录")
    print("=" * 60)

    coords = load_coords()
    for k in ("contacts_tab", "contacts_list_region"):
        if k not in coords:
            raise SystemExit(f"coords.json 缺少 {k}，请先运行 python calibrate.py 校准")

    print("\n[1/3] 初始化 OCR...")
    init_ocr()

    print("[2/3] 切换到通讯录并滚到顶部...")
    click(coords["contacts_tab"])
    time.sleep(1.5)
    region = coords["contacts_list_region"]
    # 点列表顶部聚焦
    pyautogui.click(region["left"] + 30, region["top"] + 30)
    time.sleep(0.8)
    # 滚到顶（Home 键，部分版本支持；不支持就多按几次 PgUp）
    for _ in range(10):
        pyautogui.press("pgup")
        time.sleep(0.15)
    time.sleep(1)

    print(f"[3/3] 开始滚动抓取（最多 {MAX_ROUNDS} 轮，连续 {STABLE_STOP} 轮无新名字则停）...")
    seen = set()
    names = []
    last_count = 0
    stable = 0

    for rnd in range(1, MAX_ROUNDS + 1):
        img = screenshot_region(region)
        text = ocr_image(img)
        new_this_round = 0
        for line in text.splitlines():
            nm = clean_name(line)
            if nm and nm not in SKIP_NAMES and nm not in seen:
                seen.add(nm)
                names.append(nm)
                new_this_round += 1

        print(f"  轮 {rnd}: 本轮新增 {new_this_round:3d}，累计 {len(names)}")

        if len(names) == last_count:
            stable += 1
            if stable >= STABLE_STOP:
                print(f"  连续 {STABLE_STOP} 轮无新名字，停止。")
                break
        else:
            stable = 0
        last_count = len(names)

        # 滚动：PageDown
        pyautogui.press("pagedown")
        time.sleep(SCROLL_PAUSE)

    OUT_FILE.write_text("\n".join(names), encoding="utf-8")
    print(f"\n完成！共 {len(names)} 个名字写入 {OUT_FILE}")
    print("\n⚠️ 请人工扫一眼 friends.txt：")
    print("   - 删掉明显不是人名的行（OCR 误识别）")
    print("   - 删掉群名/公众号名等不是好友的项")
    print("   - 确认后跑 python check.py 开始检测")


if __name__ == "__main__":
    main()
