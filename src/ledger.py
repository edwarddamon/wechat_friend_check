# -*- coding: utf-8 -*-
"""已检测账本：共享读写 + CLI 查看/清空。

作为模块用：
    from .ledger import LEDGER_FILE, LEDGER_FIELDS, load_ledger, append_to_ledger
        LEDGER_FILE       Path 对象，output/checked_ledger.csv
        LEDGER_FIELDS     字段列表
        load_ledger()     -> dict[who -> status]   跨会话去重用
        append_to_ledger(rows, session_ts) -> int  追加新增/更新的条数

作为 CLI 用：
    python -m src.ledger              统计
    python -m src.ledger show         看全部明细
    python -m src.ledger clear        清空账本
"""

import csv
import sys
from collections import Counter

from .paths import LEDGER_FILE, OUTPUT_DIR, ensure_dirs

LEDGER_FIELDS = ["who", "status", "check_time", "session_ts"]


def load_ledger():
    """返回 dict[who -> status]，用于跨会话去重。"""
    if not LEDGER_FILE.exists():
        return {}
    d = {}
    try:
        with open(LEDGER_FILE, "r", encoding="utf-8-sig", newline="") as fp:
            for row in csv.DictReader(fp):
                d[row["who"]] = row.get("status", "")
    except Exception as e:
        print(f"[警告] 读账本失败: {e}")
    return d


def append_to_ledger(rows, session_ts):
    """把本次结果追加到账本。已存在且状态相同的跳过。返回新增/更新条数。"""
    ensure_dirs()
    exists = LEDGER_FILE.exists()
    existing = load_ledger() if exists else {}
    new = []
    for r in rows:
        if r["who"] in existing and existing[r["who"]] == r["status"]:
            continue
        new.append({k: r.get(k, "") for k in LEDGER_FIELDS})
    if not new:
        return 0
    with open(LEDGER_FILE, "a", encoding="utf-8-sig", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=LEDGER_FIELDS)
        if not exists:
            w.writeheader()
        for r in new:
            w.writerow(r)
    return len(new)


def _load_all():
    """读全部明细（CLI 用）。"""
    if not LEDGER_FILE.exists():
        return []
    with open(LEDGER_FILE, "r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "clear":
        if LEDGER_FILE.exists():
            LEDGER_FILE.unlink()
            print(f"已清空账本: {LEDGER_FILE}\n下次跑检测会全部重测。")
        else:
            print("账本不存在。")
        return

    rows = _load_all()
    if not rows:
        print(f"账本为空或不存在: {LEDGER_FILE}")
        print("还没检测过。运行 python -m src.wx_check 开始。")
        return

    if cmd == "show":
        print(f"全部已测记录 ({len(rows)}) - {LEDGER_FILE}:\n")
        for r in rows:
            print(f"  {r.get('who',''):20s} | {r.get('status',''):10s} | {r.get('check_time','')}")
        return

    c = Counter(r.get("status", "") for r in rows)
    print(f"已检测账本: {LEDGER_FILE}")
    print(f"总计: {len(rows)} 个\n按状态：")
    for s, n in c.most_common():
        print(f"    {s or '(空)':12s} {n}")
    print(f"\n最近: {rows[-1].get('check_time','')}")
    print("\n命令: show=看明细  clear=清空重测")


if __name__ == "__main__":
    main()
