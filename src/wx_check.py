# -*- coding: utf-8 -*-
"""
微信好友状态检测  |  wxauto4 探测消息法（免费版 API）
====================================================
用 wxauto4 免费版（UI 自动化）检测哪些好友把你删除/拉黑。

两种调用方式：
  1. CLI:   python -m src.wx_check
  2. 模块:  from .wx_check import run_check
            run_check(params_dict, log=print, progress=None, stop_event=None)

原理：
  向每个好友发送一个"近乎不可见"的零宽探测字符，读取微信返回的系统消息：
    "开启了朋友验证，你还不是他(她)朋友..."  -> 对方已删除你（deleted）
    "消息已发出，但被对方拒收了"             -> 对方已拉黑你（blocked）
    无系统消息                              -> 仍是好友（normal）
    超时/异常                               -> 待人工复核（uncertain）

环境要求：
  - Windows 10/11
  - 微信 PC 客户端 4.1.8.107（wxauto4 免费版支持上限）
  - Python 3.9-3.12
  - pip install wxauto4 pywin32
"""

import csv
import time
import random
from datetime import datetime

try:
    import win32gui
    import win32con
    import win32process
    import win32api
    _HAS_PYWIN32 = True
except ImportError:
    _HAS_PYWIN32 = False

from wxauto4 import WeChat

from .paths import FRIENDS_FILE, OUTPUT_DIR, ensure_dirs
from .ledger import LEDGER_FIELDS, load_ledger, append_to_ledger
from .show_wechat import show_wechat_window


# ====== 默认配置（CLI 模式用，GUI 通过 params 覆盖） ======
DEFAULTS = {
    "PROBE_CHAR": "\u2060\u200b\u200c\u200d",
    "SEND_WAIT": (3.0, 6.0),
    "FRIEND_GAP": (8.0, 15.0),
    "BATCH_SIZE": 20,
    "BATCH_PAUSE": (60.0, 120.0),
    "LONG_PAUSE_EVERY": 50,
    "LONG_PAUSE": (180.0, 300.0),
    "SESSION_LIMIT": 80,
    "SHUFFLE": True,
    "RECHECK_ALL": False,
    "DELETED_KEYWORDS": ("开启了朋友验证", "你还不是他", "你还不是她", "朋友验证请求", "请先发送朋友验证"),
    "BLOCKED_KEYWORDS": ("被对方拒收", "拒收了"),
    "WECHAT_WINDOW_TITLE": "微信",
}


def test_wxauto4(log=print):
    """测 wxauto4 能否初始化。成功返回 WeChat 实例，失败返回 None。"""
    try:
        wx = WeChat(ads=False)
        try:
            info = wx.ChatInfo()
            log(f"[OK] wxauto4 初始化成功，当前聊天: {info}")
        except Exception:
            log("[OK] wxauto4 初始化成功")
        return wx
    except Exception as e:
        log(f"[失败] wxauto4 初始化失败: {e}")
        log("    请确认: 微信版本是 4.1.8.107，主窗口已显示")
        return None


def load_friends(log=print):
    if not FRIENDS_FILE.exists():
        log(f"[错误] 没找到 {FRIENDS_FILE}")
        log("    方式1: 用 GUI「抓名单」自动抓取 / python -m src.auto_scrape")
        log("    方式2: 手动新建 friends.txt，每行一个好友名（备注名优先）")
        return []
    names = []
    for line in FRIENDS_FILE.read_text(encoding="utf-8").splitlines():
        n = line.strip()
        if n:
            names.append(n)
    return names


def _sleep(a):
    time.sleep(random.uniform(*a) if isinstance(a, tuple) else a)


def _extract_msg_text(msg):
    for attr in ("content", "raw", "text"):
        v = getattr(msg, attr, None)
        if v:
            return str(v)
    return str(msg)


def _classify_messages(msgs, baseline_count, deleted_kw, blocked_kw):
    new_msgs = msgs[baseline_count:] if baseline_count < len(msgs) else msgs
    evidences = []
    text_all = []
    for m in new_msgs:
        t = _extract_msg_text(m).replace(" ", "").replace("\n", "")
        if not t:
            continue
        text_all.append(t)
        if any(k in t for k in deleted_kw):
            evidences.append(("deleted", t[:60]))
        elif any(k in t for k in blocked_kw):
            evidences.append(("blocked", t[:60]))

    if evidences:
        status, ev = evidences[0]
        return status, ev + " | all_new=" + " || ".join(text_all)[:120]
    if text_all:
        return "normal", "no_system_msg | new_msgs=" + " || ".join(text_all)[:120]
    return "uncertain", "no_new_msg_after_send"


def _check_one(wx, name, cfg):
    detail_parts = []
    try:
        wx.ChatWith(name, exact=True)
    except Exception as e:
        return "error", f"ChatWith_failed: {e}"
    _sleep((1.0, 2.0))

    try:
        info = wx.ChatInfo()
        chat_name = (info or {}).get("chat_name", "") if isinstance(info, dict) else str(info)
        if chat_name and name.replace(" ", "") not in chat_name.replace(" ", "") \
                and chat_name.replace(" ", "") not in name.replace(" ", ""):
            detail_parts.append(f"title_mismatch(info={chat_name!r})")
            return "uncertain", " | ".join(detail_parts) + " | abort_send"
    except Exception as e:
        detail_parts.append(f"ChatInfo_failed({e})")

    try:
        baseline = wx.GetAllMessage()
        baseline_count = len(baseline)
    except Exception as e:
        return "error", f"GetAllMessage_baseline_failed: {e}"

    try:
        wx.SendMsg(cfg["PROBE_CHAR"])
    except Exception as e:
        return "error", f"SendMsg_failed: {e}"

    _sleep(cfg["SEND_WAIT"])

    try:
        msgs = wx.GetAllMessage()
    except Exception as e:
        return "error", f"GetAllMessage_after_failed: {e}"

    status, evidence = _classify_messages(
        msgs, baseline_count, cfg["DELETED_KEYWORDS"], cfg["BLOCKED_KEYWORDS"])
    return status, " | ".join(detail_parts + [evidence])


def run_check(params=None, log=print, progress=None, stop_event=None):
    """跑检测主流程。供 GUI 或 CLI 调用。

    Returns:
        dict: {"csv_path", "summary", "results", "remaining"} 或 None
    """
    cfg = dict(DEFAULTS)
    if params:
        cfg.update(params)

    log("=" * 60)
    log("微信好友状态检测  |  wxauto4 探测消息法  |  免费版")
    log("=" * 60)
    log(f"  会话上限: {cfg['SESSION_LIMIT']} | 好友间隔: {cfg['FRIEND_GAP'][0]}-{cfg['FRIEND_GAP'][1]}s | "
        f"批大小: {cfg['BATCH_SIZE']}")
    probe = cfg["PROBE_CHAR"]
    if not probe:
        probe_desc = "空（可能发送失败）"
    elif not probe.strip():
        probe_desc = f"零宽/不可见字符（{len(probe)} 个），对方基本看不见"
    else:
        probe_desc = f"自定义文字 {probe!r}（⚠️ 会被对方真实看到）"
    log(f"  发送内容: {probe_desc}")

    log("\n[1/5] 加载好友名单...")
    friends = load_friends(log=log)
    if not friends:
        return None
    log(f"    friends.txt 共 {len(friends)} 个名字")

    log("\n[2/5] 唤起微信主窗口...")
    if not show_wechat_window(title=cfg["WECHAT_WINDOW_TITLE"], log=log):
        return None

    log("\n[3/5] 初始化 wxauto4 WeChat 实例...")
    wx = test_wxauto4(log=log)
    if wx is None:
        return None

    ledger = load_ledger()
    if cfg["RECHECK_ALL"]:
        unchecked = list(friends)
        log("\n    [RECHECK_ALL=True] 忽略账本，全部重测")
    else:
        unchecked = [n for n in friends if n not in ledger]
    log(f"    账本已测 {len(friends) - len(unchecked)}，待测 {len(unchecked)}")
    if not unchecked:
        log("    没有需要检测的好友了。如需全测: RECHECK_ALL=True 或清空账本")
        return None

    order = list(range(len(unchecked)))
    if cfg["SHUFFLE"]:
        random.shuffle(order)
    if cfg["SESSION_LIMIT"] and len(order) > cfg["SESSION_LIMIT"]:
        order = order[:cfg["SESSION_LIMIT"]]
        log(f"    [限量] 本次截断为 {cfg['SESSION_LIMIT']} 个，剩余下次再跑")
    log(f"    本次将检测: {len(order)} 个")

    log("\n[4/5] 开始检测（运行期间请勿动鼠标键盘！）...")
    log("    紧急中断: 点停止按钮 / Ctrl+C")
    results = []
    ensure_dirs()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUTPUT_DIR / f"wx_status_{ts}.csv"
    session_start = time.time()

    def _stopped():
        return stop_event is not None and stop_event.is_set()

    try:
        for cnt, idx in enumerate(order, start=1):
            if _stopped():
                log("\n[中断] 用户请求停止，已测的会落盘")
                break
            who = unchecked[idx]
            log(f"[{cnt}/{len(order)}] {who} ... ", end="", flush=True)
            try:
                status, detail = _check_one(wx, who, cfg)
            except Exception as e:
                status, detail = "error", f"unexpected: {type(e).__name__}: {e}"
            log(status)
            if status in ("uncertain", "error"):
                log(f"      {detail[:120]}")

            results.append({
                "who": who,
                "status": status,
                "detail": detail,
                "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "session_ts": ts,
            })
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as fp:
                w = csv.DictWriter(fp, fieldnames=list(results[0].keys()))
                w.writeheader()
                w.writerows(results)

            if progress:
                progress(cnt, len(order))

            if cnt < len(order) and not _stopped():
                if cfg["BATCH_SIZE"] and cnt % cfg["BATCH_SIZE"] == 0:
                    log(f"  [批间停顿] 已测 {cnt} 个，停 {cfg['BATCH_PAUSE'][0]}-{cfg['BATCH_PAUSE'][1]}s ...")
                    _sleep(cfg["BATCH_PAUSE"])
                elif cfg["LONG_PAUSE_EVERY"] and cnt % cfg["LONG_PAUSE_EVERY"] == 0:
                    log(f"  [长停顿] 已测 {cnt} 个，停 {cfg['LONG_PAUSE'][0]}-{cfg['LONG_PAUSE'][1]}s ...")
                    _sleep(cfg["LONG_PAUSE"])
                else:
                    _sleep(cfg["FRIEND_GAP"])
    except KeyboardInterrupt:
        log("\n\n[中断] Ctrl+C，已测的会落盘并写入账本")

    elapsed = time.time() - session_start
    if results:
        added = append_to_ledger(results, ts)
        log(f"\n[账本] 新增/更新 {added} 条 -> ledger")
    else:
        log("\n[账本] 没有结果可写入")

    log("\n[5/5] 统计：")
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    for k, v in summary.items():
        log(f"    {k}: {v}")
    m, s = divmod(int(elapsed), 60)
    h, m = divmod(m, 60)
    log(f"    本次耗时: {h}时{m}分{s}秒")

    for st in ("deleted", "blocked", "uncertain"):
        sub = [r for r in results if r["status"] == st]
        if sub:
            p = OUTPUT_DIR / f"{st}_{ts}.csv"
            with open(p, "w", newline="", encoding="utf-8-sig") as fp:
                w = csv.DictWriter(fp, fieldnames=list(sub[0].keys()))
                w.writeheader()
                w.writerows(sub)
            log(f"    {st} 清单: {p}  ({len(sub)} 个)")

    log(f"\n完整结果: {csv_path}")

    full_ledger = load_ledger()
    remaining = sum(1 for n in friends if n not in full_ledger)
    if remaining > 0:
        log(f"\n[续跑] 还剩 {remaining} 个未测。直接再跑自动跳过已测的。")
    else:
        log("\n[完成] 全部已检测。如需全测: 清空账本")

    return {
        "csv_path": csv_path,
        "summary": summary,
        "results": results,
        "remaining": remaining,
    }


def main():
    """CLI 入口。用 DEFAULTS 配置跑。"""
    run_check(DEFAULTS)


if __name__ == "__main__":
    main()
