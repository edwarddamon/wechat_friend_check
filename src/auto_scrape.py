# -*- coding: utf-8 -*-
"""自动抓好友名单（免校准、免 OCR）

原理：
  wxauto4 免费版 SwitchToContact() 自动切到通讯录页，
  再用 uiautomation 直接读联系人列表控件的子项 Name（=昵称），
  滚动 + 去重 + 到底检测，生成 data/friends.txt。
  不需要手动校准坐标，不依赖 OCR/截图。

用法：
  python -m src.auto_scrape probe    只探测控件结构（调试用）
  python -m src.auto_scrape          探测 + 抓取并保存

模块：
  from .auto_scrape import probe_contacts, run_scrape, save_friends

注意：
  微信 4.x (Qt) 的 UIA 控件树结构不确定，必须先跑 probe 看输出。
  如果列表项 Name 不是昵称（空或 ID），本方案失效，回退手动导入。
"""
import sys
import time

try:
    import pythoncom
except ImportError:
    pythoncom = None


# 通讯录里的非好友条目（分组入口/功能入口），抓取时按"前缀+可选数字"过滤
# 例如 "群聊4"、"公众号32"、"联系人551" 都会被过滤
JUNK_PREFIXES = [
    "新的朋友", "群聊", "公众号", "服务号", "企业微信联系人", "联系人",
    "标签", "设备", "我的团队", "朋友圈", "仅聊天的朋友",
]


def _get_wechat_window(log=print):
    """找微信主窗口的 uiautomation 控件。"""
    import uiautomation as ua
    win = ua.WindowControl(Name="微信", ClassName="Qt51514QWindowIcon")
    if not win.Exists(2, 0.5):
        win = ua.WindowControl(Name="微信")
    if not win.Exists(2, 0.5):
        log("[错误] uiautomation 没找到微信主窗口")
        return None
    return win


def _walk(c, fn, depth=0, max_depth=7):
    """深度优先遍历控件树，对每个控件调 fn(control, depth)。"""
    if depth > max_depth:
        return
    try:
        fn(c, depth)
    except Exception:
        return
    try:
        for ch in c.GetChildren():
            _walk(ch, fn, depth + 1, max_depth)
    except Exception:
        pass


def probe_contacts(log=print, wx=None):
    """切到通讯录页，全面探测控件结构。

    打印：
      - 窗口直接子控件（顶层结构）
      - 所有有 Name 的控件（ControlType + ClassName + Name + 深度），前 100 个
      - 控件类型分布统计
    返回找到的联系人列表控件（子项 Name 最多的容器控件），没有则 None。
    """
    import uiautomation as ua
    if wx is None:
        from wxauto4 import WeChat
        wx = WeChat(ads=False)
    log("切换到通讯录页...")
    try:
        wx.SwitchToContact()
    except Exception as e:
        log(f"[错误] SwitchToContact 失败: {e}")
        return None
    time.sleep(1.5)

    win = _get_wechat_window(log=log)
    if win is None:
        return None
    log(f"微信窗口: Name={win.Name!r} Class={win.ClassName!r}")

    # 1. 顶层子控件
    try:
        top = win.GetChildren()
        log(f"\n=== 顶层子控件: {len(top)} 个 ===")
        for i, c in enumerate(top[:15]):
            try:
                log(f"  [{i}] {c.ControlTypeName} cls={c.ClassName!r} name={c.Name!r} "
                    f"子项={len(c.GetChildren())}")
            except Exception as e:
                log(f"  [{i}] 读取失败: {e}")
    except Exception as e:
        log(f"  顶层读取失败: {e}")

    # 2. 全量遍历：收集所有控件 + 有 Name 的 + 类型分布
    named, type_count, all_count = [], {}, 0

    def collect(c, depth):
        nonlocal all_count
        all_count += 1
        try:
            ct = c.ControlTypeName
            type_count[ct] = type_count.get(ct, 0) + 1
            nm = (c.Name or "").strip()
            if nm:
                named.append((depth, ct, c.ClassName or "", c.AutomationId or "", nm))
        except Exception:
            pass

    _walk(win, collect, max_depth=8)

    log(f"\n=== 控件总数: {all_count}，类型分布 ===")
    for ct, n in sorted(type_count.items(), key=lambda x: -x[1]):
        log(f"  {ct}: {n}")

    log(f"\n=== 有 Name 的控件: {len(named)} 个，前 100 个 ===")
    for d, ct, cls, aid, nm in named[:100]:
        log(f"  [深度{d}] {ct} cls={cls!r} aid={aid!r} name={nm!r}")

    # 3. 找联系人列表容器：子项 Name 最多的容器型控件
    containers = ("ListControl", "TreeControl", "DataGridControl",
                  "PaneControl", "GroupControl", "CustomControl")
    best_ref = [None, 0]

    def find_best(c, depth):
        try:
            if c.ControlTypeName in containers:
                ch = c.GetChildren()
                named_n = sum(1 for x in ch if (x.Name or "").strip())
                if named_n > best_ref[1]:
                    best_ref[0] = c
                    best_ref[1] = named_n
        except Exception:
            pass
        try:
            for ch in c.GetChildren():
                find_best(ch, depth + 1)
        except Exception:
            pass
    _walk(win, find_best)

    if best_ref[0] is not None:
        c = best_ref[0]
        log(f"\n[候选容器] {c.ControlTypeName} cls={c.ClassName!r} "
            f"子项={len(c.GetChildren())} 有Name={best_ref[1]}")
        try:
            ch = c.GetChildren()
            log("  前 20 个子项 Name:")
            for x in ch[:20]:
                log(f"    {x.ControlTypeName} name={x.Name!r}")
        except Exception:
            pass
        return c

    log("\n[警告] 没找到带昵称的容器控件。")
    log("微信 Qt 自渲染可能没向 UIA 暴露联系人列表。")
    log("回退方案: 用「手动导入」粘贴好友昵称。")
    return None


def _is_valid_name(name):
    """过滤拼音字母索引、通讯录分组入口（含带数字计数的，如'群聊4'）等非好友条目。"""
    import re
    s = name.strip()
    if not s:
        return False
    if len(s) == 1 and s.isalpha():
        return False  # A-Z 拼音索引
    for p in JUNK_PREFIXES:
        # 精确匹配 或 "前缀+数字"（如 群聊4、公众号32、联系人551）
        if s == p or re.match(rf"^{re.escape(p)}\d+$", s):
            return False
    return True


def run_scrape(log=print, stop_event=None, wx=None,
               max_no_new=15, scroll_pause=0.6, max_rounds=300,
               list_control=None):
    """抓取好友昵称列表。返回 list[str]。

    list_control: 可选，probe_contacts 返回的控件引用。None 则自动定位。
    """
    import uiautomation as ua
    if wx is None:
        from wxauto4 import WeChat
        wx = WeChat(ads=False)
    try:
        wx.SwitchToContact()
    except Exception as e:
        log(f"[错误] SwitchToContact 失败: {e}")
        return []
    time.sleep(1.2)

    win = _get_wechat_window(log=log)
    if win is None:
        return []

    lst = list_control
    if lst is None:
        # 自动定位：子项有 Name 最多的 ListControl（StickyHeaderRecyclerListView 等）
        best = [None, 0]

        def find(c, depth):
            try:
                if c.ControlTypeName in ("ListControl", "TreeControl", "DataGridControl"):
                    ch = c.GetChildren()
                    named = sum(1 for x in ch if (x.Name or "").strip())
                    if named > best[1]:
                        best[0] = c
                        best[1] = named
            except Exception:
                pass
            try:
                for ch in c.GetChildren():
                    find(ch, depth + 1)
            except Exception:
                pass
        _walk(win, find, max_depth=8)
        lst = best[0]

    if lst is None:
        log("[错误] 没定位到联系人列表控件")
        log("请先跑「探测联系人控件」查看结构，或改用「手动导入」。")
        return []

    log(f"定位到列表: {lst.ControlTypeName} cls={lst.ClassName!r} 子项={len(lst.GetChildren())}")

    # 预点击列表第一个 ListItemControl，确保焦点在列表项上（PAGEDOWN 才生效）
    try:
        first = lst.GetChildren()[0]
        first.Click(waitTime=0.2)
        log("已点击列表首项，焦点就位")
    except Exception as e:
        log(f"  [提示] 点击首项失败(忽略): {e}")
        # 兜底：点击列表矩形中部
        try:
            r = lst.BoundingRectangle
            cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
            ua.Click(cx, cy, waitTime=0.1)
        except Exception:
            pass

    seen, names, no_new, round_idx = set(), [], 0, 0
    while round_idx < max_rounds:
        if stop_event and stop_event.is_set():
            log("[停止] 用户中止")
            break
        round_idx += 1
        try:
            children = lst.GetChildren()
        except Exception as e:
            log(f"  [警告] GetChildren 失败: {e}")
            time.sleep(0.4)
            continue

        new = 0
        for it in children:
            try:
                nm = (it.Name or "").strip()
            except Exception:
                continue
            if _is_valid_name(nm) and nm not in seen:
                seen.add(nm)
                names.append(nm)
                new += 1

        if new:
            no_new = 0
            log(f"  第{round_idx}轮: 可见{len(children)} +{new}  累计={len(names)}")
        else:
            no_new += 1
            if no_new >= max_no_new:
                log(f"  连续 {max_no_new} 轮无新增，判定到底")
                break

        # 滚动一屏：PAGEDOWN 优先（翻一屏），WheelDown 兜底
        try:
            ua.SendKeys("{PAGEDOWN}")
        except Exception:
            try:
                lst.WheelDown(15)
            except Exception:
                pass
        time.sleep(scroll_pause)

    log(f"\n抓取结束: 共 {len(names)} 个好友昵称")
    return names


def save_friends(names, log=print):
    """去重写入 data/friends.txt，每行一个。返回写入数量。"""
    from .paths import FRIENDS_FILE, ensure_dirs
    ensure_dirs()
    seen, lines = set(), []
    for n in names:
        s = n.strip()
        if s and s not in seen:
            seen.add(s)
            lines.append(s)
    FRIENDS_FILE.write_text("\n".join(lines) + ("\n" if lines else ""),
                            encoding="utf-8")
    log(f"[OK] 已保存 {len(lines)} 个好友到 {FRIENDS_FILE}")
    return len(lines)


def main():
    if pythoncom:
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else "scrape"
        if mode == "probe":
            probe_contacts()
        else:
            names = run_scrape()
            if names:
                save_friends(names)
    finally:
        if pythoncom:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


if __name__ == "__main__":
    main()
