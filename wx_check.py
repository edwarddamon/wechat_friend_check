# -*- coding: utf-8 -*-
"""
微信好友状态检测  |  wxauto4 探测消息法（免费版 API）
====================================================
用 wxauto4 免费版（UI 自动化）检测哪些好友把你删除/拉黑。

原理：
  向每个好友发送一个"近乎不可见"的零宽探测字符，读取微信返回的系统消息：
    "开启了朋友验证，你还不是他(她)朋友..."  -> 对方已删除你（deleted）
    "消息已发出，但被对方拒收了"             -> 对方已拉黑你（blocked）
    无系统消息                              -> 仍是好友（normal）
    超时/异常                               -> 待人工复核（uncertain）

为什么不是 100% 零打扰：
  零宽字符在部分微信版本里会显示为一个"空消息气泡"，对方可能看到一个空白气泡。
  相比转账法（绝对零打扰），这是它的代价 —— 换来的是判定准确、不依赖坐标、不限微信窗口位置。
  如需完全零打扰，用同目录的 check.py（OCR 转账法）。

环境要求：
  - Windows 10/11
  - 微信 PC 客户端 4.1.8.107（wxauto4 免费版支持上限，再新的版本控件 ID 会变）
  - Python 3.9-3.12
  - pip install wxauto4 pywin32
  - 微信已登录、主窗口可见（不能最小化到托盘）

前置：
  1. python scrape_friends.py  已生成 friends.txt（wxauto4 免费版没有 GetFriendDetails）
  2. 或手动编辑 friends.txt，每行一个好友名（备注名优先，回退昵称）

特点：
  - 低风险模式：单会话限量 + 长间隔 + 顺序打乱 + 批间停顿
  - 账本去重，跨会话续跑（和 check.py 共用 output/checked_ledger.csv）
  - 实时落盘，跑一半中断不丢结果
  - 自动唤起微信主窗口（从托盘隐藏状态拉出来）
"""

import csv
import sys
import time
import random
from datetime import datetime
from pathlib import Path

# 启动前先把微信主窗口显示出来（wxauto4 找不到隐藏窗口）
try:
    import win32gui
    import win32con
    import win32process
    import win32api
    _HAS_PYWIN32 = True
except ImportError:
    _HAS_PYWIN32 = False

from wxauto4 import WeChat

from ledger import LEDGER_FILE, LEDGER_FIELDS, load_ledger, append_to_ledger


# ====== 配置区 ======
FRIENDS_FILE = Path(__file__).parent / "friends.txt"
OUTPUT_DIR = Path(__file__).parent / "output"

# 探测字符：零宽字符组合（替代已被微信特征库标记的 జ్ఞ ా）
# 注：零宽字符在部分微信版本会显示为空消息气泡（对方能看到一个空白气泡），
#     但比 జ్ఞ ా 更不易被反垃圾系统识别为"查单删"行为
PROBE_CHAR = "\u2060\u200b\u200c\u200d"   # WORD JOINER + ZWSP + ZWNJ + ZWJ

# 时序（低风险模式）
SEND_WAIT = (3.0, 6.0)        # 发送后等待系统回执秒数
FRIEND_GAP = (8.0, 15.0)      # 每个好友之间间隔（拉长模拟人类）
BATCH_SIZE = 20               # 每批数量
BATCH_PAUSE = (60.0, 120.0)   # 批间停顿秒数
LONG_PAUSE_EVERY = 50         # 每测 N 个插一次长停顿
LONG_PAUSE = (180.0, 300.0)   # 长停顿秒数

# 会话控制
SESSION_LIMIT = 80            # 单会话上限（探测法有发消息行为，建议比转账法少）
SHUFFLE = True
RECHECK_ALL = False

# 判定关键词
DELETED_KEYWORDS = ("开启了朋友验证", "你还不是他", "你还不是她", "朋友验证请求", "请先发送朋友验证")
BLOCKED_KEYWORDS = ("被对方拒收", "拒收了")

# 微信窗口
WECHAT_WINDOW_TITLE = "微信"
# ==================


def show_wechat_window():
    """从托盘/隐藏状态把微信主窗口拉出来。"""
    if not _HAS_PYWIN32:
        print("[警告] 缺 pywin32，无法自动唤起微信窗口。请手动把微信主窗口打开。")
        return False

    hits = []
    def enum(hwnd, _):
        if win32gui.GetWindowText(hwnd) == WECHAT_WINDOW_TITLE \
                and win32gui.GetClassName(hwnd).startswith("Qt"):
            hits.append(hwnd)
    win32gui.EnumWindows(enum, None)
    if not hits:
        print(f"[警告] 没找到 title='{WECHAT_WINDOW_TITLE}' 的 Qt 窗口，请确认微信已登录")
        return False

    hwnd = hits[0]
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    try:
        fg = win32gui.GetForegroundWindow()
        cur = win32api.GetCurrentThreadId()
        fg_t, _ = win32process.GetWindowThreadProcessId(fg)
        win32process.AttachThreadInput(cur, fg_t, True)
        try:
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
        finally:
            win32process.AttachThreadInput(cur, fg_t, False)
    except Exception:
        pass
    time.sleep(1.0)
    print(f"[微信窗口] 已激活 hwnd={hwnd} visible={bool(win32gui.IsWindowVisible(hwnd))}")
    return True


def load_friends():
    if not FRIENDS_FILE.exists():
        raise SystemExit(
            f"没找到 {FRIENDS_FILE}\n"
            f"  方式1: python scrape_friends.py  自动 OCR 抓取通讯录\n"
            f"  方式2: 手动新建 friends.txt，每行一个好友名（备注名优先）"
        )
    names = []
    for line in FRIENDS_FILE.read_text(encoding="utf-8").splitlines():
        n = line.strip()
        if n:
            names.append(n)
    return names


def sleep(a):
    time.sleep(random.uniform(*a) if isinstance(a, tuple) else a)


def extract_msg_text(msg):
    """从 wxauto4 消息对象里尽量取出文本内容。不同版本属性不同。"""
    for attr in ("content", "raw", "text"):
        v = getattr(msg, attr, None)
        if v:
            return str(v)
    return str(msg)


def classify_messages(msgs, baseline_count):
    """根据发送探测后新增的消息分类。返回 (status, evidence)。"""
    new_msgs = msgs[baseline_count:] if baseline_count < len(msgs) else msgs
    evidences = []
    text_all = []
    for m in new_msgs:
        t = extract_msg_text(m).replace(" ", "").replace("\n", "")
        if not t:
            continue
        text_all.append(t)
        # 系统消息通常包含这些关键词
        if any(k in t for k in DELETED_KEYWORDS):
            evidences.append(("deleted", t[:60]))
        elif any(k in t for k in BLOCKED_KEYWORDS):
            evidences.append(("blocked", t[:60]))

    if evidences:
        # 取第一个命中（一般只有一条系统回执）
        status, ev = evidences[0]
        return status, ev + " | all_new=" + " || ".join(text_all)[:120]
    # 没命中任何系统消息关键词 —— 看是否有"自己发出去的那条"
    # 如果新消息里只有自己发的探测字符，说明对方正常收到（没拒收没删除）→ normal
    # 如果连自己发的都没看到，可能是读取太早
    if text_all:
        return "normal", "no_system_msg | new_msgs=" + " || ".join(text_all)[:120]
    return "uncertain", "no_new_msg_after_send"


def check_one(wx, name):
    """检测单个好友。返回 (status, detail)。"""
    detail_parts = []
    # 1. 切到目标聊天（精确匹配，避免误发给重名好友）
    try:
        wx.ChatWith(name, exact=True)
    except Exception as e:
        return "error", f"ChatWith_failed: {e}"
    sleep((1.0, 2.0))

    # 2. 校验当前聊天确实是目标对象
    try:
        info = wx.ChatInfo()
        chat_name = (info or {}).get("chat_name", "") if isinstance(info, dict) else str(info)
        # 简单包含判断（备注名/昵称可能不完全一致）
        if chat_name and name.replace(" ", "") not in chat_name.replace(" ", "") \
                and chat_name.replace(" ", "") not in name.replace(" ", ""):
            # 名字对不上：可能是搜索没匹配到，微信停在了上一个聊天
            detail_parts.append(f"title_mismatch(info={chat_name!r})")
            # 不发消息，直接降级
            return "uncertain", " | ".join(detail_parts) + " | abort_send"
    except Exception as e:
        detail_parts.append(f"ChatInfo_failed({e})")

    # 3. 记录发送前的消息列表 baseline
    try:
        baseline = wx.GetAllMessage()
        baseline_count = len(baseline)
    except Exception as e:
        return "error", f"GetAllMessage_baseline_failed: {e}"

    # 4. 发送探测字符
    try:
        wx.SendMsg(PROBE_CHAR)
    except Exception as e:
        return "error", f"SendMsg_failed: {e}"

    # 5. 等系统回执
    sleep(SEND_WAIT)

    # 6. 读取新增消息
    try:
        msgs = wx.GetAllMessage()
    except Exception as e:
        return "error", f"GetAllMessage_after_failed: {e}"

    status, evidence = classify_messages(msgs, baseline_count)
    return status, " | ".join(detail_parts + [evidence])


def main():
    print("=" * 60)
    print("微信好友状态检测  |  wxauto4 探测消息法  |  免费版")
    print("=" * 60)
    print(f"  会话上限: {SESSION_LIMIT} | 好友间隔: {FRIEND_GAP[0]}-{FRIEND_GAP[1]}s | "
          f"批大小: {BATCH_SIZE}（批间停 {BATCH_PAUSE[0]}-{BATCH_PAUSE[1]}s）")
    print(f"  探测字符: 零宽字符组合（不是 100% 零打扰，对方可能看到空气泡）")

    print("\n[1/5] 加载好友名单...")
    friends = load_friends()
    print(f"    friends.txt 共 {len(friends)} 个名字")
    if not friends:
        print("    名单为空，请先运行 scrape_friends.py 或手动编辑 friends.txt")
        return

    print("\n[2/5] 唤起微信主窗口...")
    if not show_wechat_window():
        print("    无法自动唤起，请手动把微信窗口打开后再跑")
        return

    print("\n[3/5] 初始化 wxauto4 WeChat 实例...")
    try:
        wx = WeChat(ads=False)
        print(f"    初始化成功，当前聊天: {wx.ChatInfo()}")
    except Exception as e:
        print(f"    ❌ 初始化失败: {e}")
        print("    请确认: 微信版本是 4.1.8.107（不是更新的版本），主窗口已显示")
        return

    # 账本去重
    ledger = load_ledger()
    if RECHECK_ALL:
        unchecked = list(friends)
        print("\n    [RECHECK_ALL=True] 忽略账本，全部重测")
    else:
        unchecked = [n for n in friends if n not in ledger]
    print(f"    账本已测 {len(friends) - len(unchecked)}，待测 {len(unchecked)}")
    if not unchecked:
        print("    没有需要检测的好友了。如需全测: RECHECK_ALL=True 或 python ledger.py clear")
        return

    order = list(range(len(unchecked)))
    if SHUFFLE:
        random.shuffle(order)
    if SESSION_LIMIT and len(order) > SESSION_LIMIT:
        order = order[:SESSION_LIMIT]
        print(f"    [限量] 本次截断为 {SESSION_LIMIT} 个，剩余下次再跑")
    print(f"    本次将检测: {len(order)} 个")

    print("\n[4/5] 开始检测（运行期间请勿动鼠标键盘！）...")
    print("    紧急中断: Ctrl+C，已测的会落盘")
    results = []
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUTPUT_DIR / f"wx_status_{ts}.csv"
    session_start = time.time()
    last_batch_idx = 0

    try:
        for cnt, idx in enumerate(order, start=1):
            who = unchecked[idx]
            print(f"[{cnt}/{len(order)}] {who} ... ", end="", flush=True)
            try:
                status, detail = check_one(wx, who)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                status, detail = "error", f"unexpected: {type(e).__name__}: {e}"
            print(status)
            if status in ("uncertain", "error"):
                print(f"      {detail[:120]}")

            results.append({
                "who": who,
                "status": status,
                "detail": detail,
                "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "session_ts": ts,
            })
            # 实时落盘（每测一个就写一次，中断也不丢）
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as fp:
                w = csv.DictWriter(fp, fieldnames=list(results[0].keys()))
                w.writeheader()
                w.writerows(results)

            if cnt < len(order):
                # 批间停顿
                if BATCH_SIZE and cnt % BATCH_SIZE == 0:
                    print(f"  [批间停顿] 已测 {cnt} 个，停 {BATCH_PAUSE[0]}-{BATCH_PAUSE[1]}s 模拟人类...")
                    sleep(BATCH_PAUSE)
                elif LONG_PAUSE_EVERY and cnt % LONG_PAUSE_EVERY == 0:
                    print(f"  [长停顿] 已测 {cnt} 个，停 {LONG_PAUSE[0]}-{LONG_PAUSE[1]}s ...")
                    sleep(LONG_PAUSE)
                else:
                    sleep(FRIEND_GAP)
    except KeyboardInterrupt:
        print("\n\n[中断] 用户 Ctrl+C，已测的会落盘并写入账本")

    elapsed = time.time() - session_start
    added = append_to_ledger(results, ts)
    print(f"\n[账本] 新增/更新 {added} 条 -> {LEDGER_FILE}")

    print("\n[5/5] 统计：")
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    for k, v in summary.items():
        print(f"    {k}: {v}")
    m, s = divmod(int(elapsed), 60)
    h, m = divmod(m, 60)
    print(f"    本次耗时: {h}时{m}分{s}秒")

    # 导出各类清单
    for st in ("deleted", "blocked", "uncertain"):
        sub = [r for r in results if r["status"] == st]
        if sub:
            p = OUTPUT_DIR / f"{st}_{ts}.csv"
            with open(p, "w", newline="", encoding="utf-8-sig") as fp:
                w = csv.DictWriter(fp, fieldnames=list(sub[0].keys()))
                w.writeheader()
                w.writerows(sub)
            print(f"    {st} 清单: {p}  ({len(sub)} 个)")

    print(f"\n完整结果: {csv_path}")

    # 续跑提示
    full_ledger = load_ledger()
    remaining = sum(1 for n in friends if n not in full_ledger)
    if remaining > 0:
        print(f"\n[续跑] 还剩 {remaining} 个未测。直接再跑 python wx_check.py 自动跳过已测的。")
    else:
        print("\n[完成] 全部已检测。如需全测: python ledger.py clear")

    print("\n下一步：")
    print("  - deleted/blocked 清单里的人 → 微信手动删除")
    print("  - uncertain 清单里的人 → 手动转账法复核（少量）")


if __name__ == "__main__":
    main()
