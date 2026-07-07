# -*- coding: utf-8 -*-
"""微信主窗口工具：从托盘/隐藏状态唤起主窗口，并测 wxauto4 能否初始化。

用法：
    python show_wechat.py           唤起微信主窗口
    python show_wechat.py --test    唤起 + 测 wxauto4 初始化

适用于微信 4.x（Qt 自渲染窗口，wxauto4 找不到托盘隐藏的窗口）。
"""
import sys
import time

try:
    import win32gui
    import win32con
    import win32process
    import win32api
except ImportError:
    print("缺少 pywin32，正在安装: pip install pywin32")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pywin32"])
    import win32gui
    import win32con
    import win32process
    import win32api


WECHAT_WINDOW_TITLE = "微信"


def find_wechat_main():
    """严格找 title='微信' 的 Qt 主窗口。"""
    hits = []
    def enum(hwnd, _):
        if win32gui.GetWindowText(hwnd) == WECHAT_WINDOW_TITLE \
                and win32gui.GetClassName(hwnd).startswith("Qt"):
            hits.append(hwnd)
    win32gui.EnumWindows(enum, None)
    return hits


def show_wechat_window():
    """从托盘/隐藏/最小化状态把微信主窗口拉出来并前置。返回是否成功。"""
    hits = find_wechat_main()
    if not hits:
        print(f"[错误] 没找到 title='{WECHAT_WINDOW_TITLE}' 的 Qt 窗口")
        print("       请确认: 微信已登录、进程在跑")
        return False

    hwnd = hits[0]
    cls = win32gui.GetClassName(hwnd)
    print(f"[找到] hwnd={hwnd} class={cls!r} "
          f"visible={bool(win32gui.IsWindowVisible(hwnd))} "
          f"iconic={bool(win32gui.IsIconic(hwnd))}")

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
    except Exception as e:
        print(f"  [警告] 前置失败(忽略): {e}")

    time.sleep(1.0)
    is_fg = win32gui.GetForegroundWindow() == hwnd
    is_vis = bool(win32gui.IsWindowVisible(hwnd))
    print(f"[结果] visible={is_vis} is_foreground={is_fg}")
    return is_vis


def test_wxauto4():
    """测 wxauto4 免费版能否初始化。"""
    print("\n--- 测试 wxauto4 初始化 ---")
    try:
        from wxauto4 import WeChat
    except ImportError:
        print("[错误] 没装 wxauto4，请运行: pip install wxauto4")
        return False
    print("Python:", sys.version.split()[0])
    print("正在初始化 wxauto4...")
    try:
        wx = WeChat(ads=False)
        print("[OK] wxauto4 初始化成功！")
        try:
            info = wx.ChatInfo()
            print("当前聊天信息:", info)
        except Exception as e:
            print(f"  ChatInfo 调用失败(不影响主功能): {e}")
        return True
    except Exception as e:
        print(f"[失败] {type(e).__name__}: {e}")
        print("\n常见原因：")
        print("  1. 微信版本太新（wxauto4 免费版只支持到 4.1.8.107）")
        print("  2. 微信主窗口没显示出来")
        print("  3. 微信没登录")
        import traceback
        traceback.print_exc()
        return False


def main():
    test = "--test" in sys.argv
    ok = show_wechat_window()
    if not ok:
        sys.exit(1)
    if test:
        if not test_wxauto4():
            sys.exit(2)


if __name__ == "__main__":
    main()
