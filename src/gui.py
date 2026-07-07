# -*- coding: utf-8 -*-
"""
微信好友状态检测  |  GUI 客户端
==============================
Tkinter + ttk 客户端。5 个 Tab 页，后台线程跑任务，日志通过队列推送。

入口：python main.py（根目录）或打包后的 exe。
"""

import csv
import os
import sys
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

from .paths import (BASE_DIR, DATA_DIR, OUTPUT_DIR, FRIENDS_FILE, COORDS_FILE,
                    LEDGER_FILE, ensure_dirs)
from .wx_check import run_check, test_wxauto4, load_friends, DEFAULTS as WX_DEFAULTS
from .scrape_friends import run_scrape
from .calibrate import run_calibrate, load_coords
from .ledger import load_ledger, _load_all as load_ledger_rows
from .ocr_utils import init_ocr
from .show_wechat import show_wechat_window


def friendly_path(p):
    try:
        return str(Path(p))
    except Exception:
        return str(p)


class GuiLogger:
    """把日志推到 queue，主线程定期 poll 写入文本框。同时打印到 stdout。"""

    def __init__(self, log_queue):
        self.q = log_queue

    def __call__(self, msg="", end="\n", flush=False):
        text = msg if end == "\n" else msg + end
        self.q.put(text)
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except Exception:
            pass


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("微信好友状态检测  |  wxauto4 探测消息法")
        self.root.geometry("900x720")
        self.root.minsize(800, 640)

        ensure_dirs()

        # 共享状态
        self.log_queue = queue.Queue()
        self.stop_event = None
        self.bg_thread = None

        # 样式
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # 顶部状态栏
        top = ttk.Frame(root, padding=(10, 6))
        top.pack(fill="x")
        ttk.Label(top, text="微信好友状态检测", font=("Microsoft YaHei", 14, "bold")).pack(side="left")
        self.status_var = tk.StringVar(value="状态: 就绪")
        ttk.Label(top, textvariable=self.status_var, font=("Microsoft YaHei", 10)).pack(side="right")

        # Notebook
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        self.tab_prep = ttk.Frame(self.nb)
        self.tab_scrape = ttk.Frame(self.nb)
        self.tab_check = ttk.Frame(self.nb)
        self.tab_results = ttk.Frame(self.nb)
        self.tab_advanced = ttk.Frame(self.nb)
        self.nb.add(self.tab_prep, text=" 1. 微信准备 ")
        self.nb.add(self.tab_scrape, text=" 2. 抓名单 ")
        self.nb.add(self.tab_check, text=" 3. 跑检测 ")
        self.nb.add(self.tab_results, text=" 4. 查看结果 ")
        self.nb.add(self.tab_advanced, text=" 5. 高级设置 ")

        self._build_tab_prep()
        self._build_tab_scrape()
        self._build_tab_check()
        self._build_tab_results()
        self._build_tab_advanced()

        # 底部日志区
        log_frame = ttk.LabelFrame(root, text="日志输出", padding=4)
        log_frame.pack(fill="both", expand=False, padx=8, pady=(0, 8))
        self.log_text = tk.Text(log_frame, height=10, wrap="word", font=("Consolas", 9),
                                bg="#1e1e1e", fg="#d4d4d4", insertbackground="#d4d4d4")
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=log_scroll.set)
        self.log_text.tag_configure("err", foreground="#f48771")
        self.log_text.tag_configure("ok", foreground="#89d185")
        self.log_text.tag_configure("warn", foreground="#cca700")

        self._poll_log()

        self._refresh_friends_count()
        self._refresh_coords_display()
        self._refresh_ledger_stats()

    # ============ 日志 ============
    def _log(self, msg="", tag=None):
        self.log_queue.put(("__direct__", msg, tag))

    def _poll_log(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__direct__":
                    _, msg, tag = item
                    self._write_log(msg, tag)
                else:
                    self._write_log(item)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log)

    def _write_log(self, text, tag=None):
        self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")

    def _set_status(self, text):
        self.status_var.set(f"状态: {text}")

    def make_logger(self):
        return GuiLogger(self.log_queue)

    # ============ 后台任务 ============
    def _is_running(self):
        return self.bg_thread is not None and self.bg_thread.is_alive()

    def _start_bg(self, target, status_text):
        if self._is_running():
            messagebox.showwarning("提示", "已有任务在跑，请先停止")
            return
        self.stop_event = threading.Event()
        self.bg_thread = threading.Thread(target=target, daemon=True)
        self.bg_thread.start()
        self._set_status(status_text)

    def _stop_bg(self):
        if self.stop_event:
            self.stop_event.set()
            self._set_status("正在停止...")

    # ============ Tab 1: 微信准备 ============
    def _build_tab_prep(self):
        f = ttk.Frame(self.tab_prep, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="准备微信环境", font=("Microsoft YaHei", 12, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(f, text="这一步确认微信版本对得上、wxauto4 能初始化。首次使用必做。",
                  font=("Microsoft YaHei", 9)).pack(anchor="w")

        box = ttk.LabelFrame(f, text="操作", padding=12)
        box.pack(fill="x", pady=12)

        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Button(row, text="唤起微信主窗口", command=self.act_show_wechat).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="测试 wxauto4 初始化", command=self.act_test_wxauto4).pack(side="left")

        info = ttk.LabelFrame(f, text="环境要求", padding=12)
        info.pack(fill="both", expand=True)
        req = (
            "• Windows 10/11\n"
            "• 微信 PC 客户端 4.1.8.107（wxauto4 免费版支持上限）\n"
            "  下载: https://github.com/SiverKing/wechat4.0-windows-versions/releases/download/v4.1.8.107/weixin_4.1.8.107.exe\n"
            "• 微信已登录、主窗口可见（不能最小化到托盘）\n"
            "• 登录后立即关闭微信自动更新（设置→通用设置→取消\"有更新时自动升级\"）"
        )
        ttk.Label(info, text=req, font=("Microsoft YaHei", 9), justify="left").pack(anchor="w")

    def act_show_wechat(self):
        if self._is_running():
            messagebox.showwarning("提示", "已有任务在跑")
            return
        log = self.make_logger()
        def task():
            show_wechat_window(log=log)
            self._set_status("就绪")
        threading.Thread(target=task, daemon=True).start()

    def act_test_wxauto4(self):
        if self._is_running():
            messagebox.showwarning("提示", "已有任务在跑")
            return
        log = self.make_logger()
        self._set_status("测试 wxauto4...")
        def task():
            show_wechat_window(log=log)
            wx = test_wxauto4(log=log)
            if wx:
                self._set_status("wxauto4 就绪")
                self._log("[OK] 可以进入下一步抓名单", "ok")
            else:
                self._set_status("wxauto4 不可用")
                self._log("[失败] 请按日志提示检查", "err")
        threading.Thread(target=task, daemon=True).start()

    # ============ Tab 2: 抓名单 ============
    def _build_tab_scrape(self):
        f = ttk.Frame(self.tab_scrape, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="抓好友名单", font=("Microsoft YaHei", 12, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(f, text="wxauto4 免费版拿不到好友列表，必须靠 OCR 抓通讯录生成 friends.txt。",
                  font=("Microsoft YaHei", 9)).pack(anchor="w")

        cal = ttk.LabelFrame(f, text="第 1 步: 校准通讯录坐标（一次性）", padding=12)
        cal.pack(fill="x", pady=8)
        self.coords_var = tk.StringVar(value="未校准")
        ttk.Label(cal, textvariable=self.coords_var, font=("Microsoft YaHei", 9)).pack(anchor="w")
        row = ttk.Frame(cal)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="开始校准", command=self.act_calibrate).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="刷新显示", command=self._refresh_coords_display).pack(side="left")

        sc = ttk.LabelFrame(f, text="第 2 步: OCR 抓好友名单", padding=12)
        sc.pack(fill="x", pady=8)
        self.friends_count_var = tk.StringVar(value="friends.txt: 0 个名字")
        ttk.Label(sc, textvariable=self.friends_count_var, font=("Microsoft YaHei", 9)).pack(anchor="w")

        params = ttk.Frame(sc)
        params.pack(fill="x", pady=6)
        ttk.Label(params, text="滚动最大轮数:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.max_rounds_var = tk.IntVar(value=400)
        ttk.Entry(params, textvariable=self.max_rounds_var, width=8).grid(row=0, column=1, padx=(0, 12))
        ttk.Label(params, text="连续N轮无新名字停止:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.stable_stop_var = tk.IntVar(value=3)
        ttk.Entry(params, textvariable=self.stable_stop_var, width=8).grid(row=0, column=3)

        row2 = ttk.Frame(sc)
        row2.pack(fill="x", pady=(6, 0))
        self.btn_scrape = ttk.Button(row2, text="开始抓取", command=self.act_scrape)
        self.btn_scrape.pack(side="left", padx=(0, 8))
        self.btn_scrape_stop = ttk.Button(row2, text="停止", command=self._stop_bg, state="disabled")
        self.btn_scrape_stop.pack(side="left")
        ttk.Button(row2, text="打开 friends.txt", command=self._open_friends_file).pack(side="left", padx=12)

        ttk.Label(sc, text="⚠️ 抓完请人工核对 friends.txt，删掉非人名行（OCR 有噪声）",
                  font=("Microsoft YaHei", 9), foreground="#cc6600").pack(anchor="w", pady=(6, 0))

    def _refresh_coords_display(self):
        c = load_coords()
        if "contacts_tab" in c and "contacts_list_region" in c:
            self.coords_var.set(f"已校准 ✓  contacts_tab={c['contacts_tab']}  list_region={c['contacts_list_region']}")
        else:
            self.coords_var.set("未校准（缺 contacts_tab 或 contacts_list_region）")

    def _refresh_friends_count(self):
        try:
            if FRIENDS_FILE.exists():
                lines = [l for l in FRIENDS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
                self.friends_count_var.set(f"friends.txt: {len(lines)} 个名字  ({FRIENDS_FILE})")
            else:
                self.friends_count_var.set(f"friends.txt: 不存在（先抓取或手填）  路径: {FRIENDS_FILE}")
        except Exception as e:
            self.friends_count_var.set(f"读取失败: {e}")

    def act_calibrate(self):
        if self._is_running():
            messagebox.showwarning("提示", "已有任务在跑")
            return
        log = self.make_logger()
        hint = tk.Toplevel(self.root)
        hint.title("校准中 - 请在微信里点击")
        hint.geometry("420x140")
        hint_label = ttk.Label(hint, text="即将开始校准...\n\n请切换到微信窗口，按日志提示点击目标位置",
                               font=("Microsoft YaHei", 10), justify="center", padding=20)
        hint_label.pack(fill="both", expand=True)
        hint.attributes("-topmost", True)

        def update_hint(key, kind, prompt, value=None):
            def do():
                if value is not None:
                    hint_label.config(text=f"已完成: {key}\n{prompt}\n捕获: {value}")
                else:
                    hint_label.config(text=f"当前步骤: {key}\n{prompt}\n\n请在微信里点击目标位置")
            self.root.after(0, do)

        def on_done(coords):
            def do():
                hint.destroy()
                self._refresh_coords_display()
                self._set_status("就绪")
                self._log("[OK] 校准完成", "ok")
            self.root.after(0, do)

        def task():
            self._set_status("校准中（请在微信点击）")
            run_calibrate(log=log, on_step=update_hint, on_done=on_done)

        self._start_bg(task, "校准中")

    def act_scrape(self):
        if self._is_running():
            messagebox.showwarning("提示", "已有任务在跑")
            return
        coords = load_coords()
        if "contacts_tab" not in coords or "contacts_list_region" not in coords:
            messagebox.showwarning("未校准", "请先校准通讯录坐标")
            return
        log = self.make_logger()
        params = {
            "MAX_ROUNDS": self.max_rounds_var.get(),
            "STABLE_STOP": self.stable_stop_var.get(),
        }
        self.btn_scrape.config(state="disabled")
        self.btn_scrape_stop.config(state="normal")

        def task():
            run_scrape(params=params, log=log, stop_event=self.stop_event)
            def done():
                self.btn_scrape.config(state="normal")
                self.btn_scrape_stop.config(state="disabled")
                self._refresh_friends_count()
                self._set_status("就绪")
            self.root.after(0, done)

        self._start_bg(task, "抓名单中")

    def _open_friends_file(self):
        try:
            if FRIENDS_FILE.exists():
                os.startfile(str(FRIENDS_FILE))
            else:
                messagebox.showinfo("提示", f"{FRIENDS_FILE} 不存在")
        except Exception as e:
            messagebox.showerror("错误", str(e))

    # ============ Tab 3: 跑检测 ============
    def _build_tab_check(self):
        f = ttk.Frame(self.tab_check, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="跑检测", font=("Microsoft YaHei", 12, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(f, text="配置参数后点开始。运行期间请勿动鼠标键盘。",
                  font=("Microsoft YaHei", 9)).pack(anchor="w")

        form = ttk.LabelFrame(f, text="参数配置", padding=12)
        form.pack(fill="x", pady=8)

        self.var_session_limit = tk.IntVar(value=WX_DEFAULTS["SESSION_LIMIT"])
        self.var_recheck = tk.BooleanVar(value=WX_DEFAULTS["RECHECK_ALL"])
        self.var_shuffle = tk.BooleanVar(value=WX_DEFAULTS["SHUFFLE"])
        self.var_friend_gap_min = tk.DoubleVar(value=WX_DEFAULTS["FRIEND_GAP"][0])
        self.var_friend_gap_max = tk.DoubleVar(value=WX_DEFAULTS["FRIEND_GAP"][1])
        self.var_send_wait_min = tk.DoubleVar(value=WX_DEFAULTS["SEND_WAIT"][0])
        self.var_send_wait_max = tk.DoubleVar(value=WX_DEFAULTS["SEND_WAIT"][1])
        self.var_batch_size = tk.IntVar(value=WX_DEFAULTS["BATCH_SIZE"])
        self.var_batch_pause_min = tk.DoubleVar(value=WX_DEFAULTS["BATCH_PAUSE"][0])
        self.var_batch_pause_max = tk.DoubleVar(value=WX_DEFAULTS["BATCH_PAUSE"][1])
        self.var_long_every = tk.IntVar(value=WX_DEFAULTS["LONG_PAUSE_EVERY"])
        self.var_long_pause_min = tk.DoubleVar(value=WX_DEFAULTS["LONG_PAUSE"][0])
        self.var_long_pause_max = tk.DoubleVar(value=WX_DEFAULTS["LONG_PAUSE"][1])

        r = 0
        ttk.Label(form, text="单会话上限:").grid(row=r, column=0, sticky="w", padx=(0, 4), pady=4)
        ttk.Entry(form, textvariable=self.var_session_limit, width=8).grid(row=r, column=1, padx=(0, 16))
        ttk.Checkbutton(form, text="忽略账本全部重测", variable=self.var_recheck).grid(row=r, column=2, sticky="w")
        ttk.Checkbutton(form, text="顺序打乱", variable=self.var_shuffle).grid(row=r, column=3, sticky="w")

        r = 1
        ttk.Label(form, text="好友间隔(秒):").grid(row=r, column=0, sticky="w", padx=(0, 4), pady=4)
        ttk.Entry(form, textvariable=self.var_friend_gap_min, width=6).grid(row=r, column=1, sticky="w")
        ttk.Label(form, text="~").grid(row=r, column=2, sticky="w")
        ttk.Entry(form, textvariable=self.var_friend_gap_max, width=6).grid(row=r, column=3, sticky="w")

        r = 2
        ttk.Label(form, text="等待回执(秒):").grid(row=r, column=0, sticky="w", padx=(0, 4), pady=4)
        ttk.Entry(form, textvariable=self.var_send_wait_min, width=6).grid(row=r, column=1, sticky="w")
        ttk.Label(form, text="~").grid(row=r, column=2, sticky="w")
        ttk.Entry(form, textvariable=self.var_send_wait_max, width=6).grid(row=r, column=3, sticky="w")

        r = 3
        ttk.Label(form, text="批大小:").grid(row=r, column=0, sticky="w", padx=(0, 4), pady=4)
        ttk.Entry(form, textvariable=self.var_batch_size, width=6).grid(row=r, column=1, sticky="w")
        ttk.Label(form, text="批间停(秒):").grid(row=r, column=2, sticky="w", padx=(8, 4))
        ttk.Entry(form, textvariable=self.var_batch_pause_min, width=6).grid(row=r, column=3, sticky="w")
        ttk.Label(form, text="~").grid(row=r, column=4, sticky="w")
        ttk.Entry(form, textvariable=self.var_batch_pause_max, width=6).grid(row=r, column=5, sticky="w")

        r = 4
        ttk.Label(form, text="每N个长停:").grid(row=r, column=0, sticky="w", padx=(0, 4), pady=4)
        ttk.Entry(form, textvariable=self.var_long_every, width=6).grid(row=r, column=1, sticky="w")
        ttk.Label(form, text="长停(秒):").grid(row=r, column=2, sticky="w", padx=(8, 4))
        ttk.Entry(form, textvariable=self.var_long_pause_min, width=6).grid(row=r, column=3, sticky="w")
        ttk.Label(form, text="~").grid(row=r, column=4, sticky="w")
        ttk.Entry(form, textvariable=self.var_long_pause_max, width=6).grid(row=r, column=5, sticky="w")

        preset_frame = ttk.Frame(form)
        preset_frame.grid(row=5, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Label(preset_frame, text="快速预设:").pack(side="left", padx=(0, 6))
        ttk.Button(preset_frame, text="默认(平衡)", command=lambda: self._apply_preset("default")).pack(side="left", padx=2)
        ttk.Button(preset_frame, text="更安全", command=lambda: self._apply_preset("safe")).pack(side="left", padx=2)
        ttk.Button(preset_frame, text="更快", command=lambda: self._apply_preset("fast")).pack(side="left", padx=2)

        ctrl = ttk.Frame(f)
        ctrl.pack(fill="x", pady=8)
        self.btn_start = ttk.Button(ctrl, text="▶ 开始检测", command=self.act_start_check)
        self.btn_start.pack(side="left", padx=(0, 8))
        self.btn_stop = ttk.Button(ctrl, text="■ 停止", command=self._stop_bg, state="disabled")
        self.btn_stop.pack(side="left")

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_label_var = tk.StringVar(value="0 / 0")
        ttk.Progressbar(f, variable=self.progress_var, maximum=100).pack(fill="x", pady=(0, 4))
        ttk.Label(f, textvariable=self.progress_label_var, font=("Microsoft YaHei", 9)).pack(anchor="w")

        pre = ttk.LabelFrame(f, text="开始前检查", padding=8)
        pre.pack(fill="x", pady=8)
        self.pre_check_var = tk.StringVar(value="点击 \"开始检测\" 前会自动检查")
        ttk.Label(pre, textvariable=self.pre_check_var, font=("Microsoft YaHei", 9), justify="left").pack(anchor="w")

    def _apply_preset(self, name):
        presets = {
            "default": dict(SESSION_LIMIT=80, FRIEND_GAP=(8.0, 15.0), SEND_WAIT=(3.0, 6.0),
                            BATCH_SIZE=20, BATCH_PAUSE=(60.0, 120.0),
                            LONG_PAUSE_EVERY=50, LONG_PAUSE=(180.0, 300.0)),
            "safe": dict(SESSION_LIMIT=50, FRIEND_GAP=(15.0, 30.0), SEND_WAIT=(5.0, 10.0),
                         BATCH_SIZE=10, BATCH_PAUSE=(180.0, 300.0),
                         LONG_PAUSE_EVERY=30, LONG_PAUSE=(600.0, 900.0)),
            "fast": dict(SESSION_LIMIT=150, FRIEND_GAP=(5.0, 10.0), SEND_WAIT=(2.0, 4.0),
                         BATCH_SIZE=30, BATCH_PAUSE=(30.0, 60.0),
                         LONG_PAUSE_EVERY=100, LONG_PAUSE=(120.0, 180.0)),
        }
        p = presets[name]
        self.var_session_limit.set(p["SESSION_LIMIT"])
        self.var_friend_gap_min.set(p["FRIEND_GAP"][0])
        self.var_friend_gap_max.set(p["FRIEND_GAP"][1])
        self.var_send_wait_min.set(p["SEND_WAIT"][0])
        self.var_send_wait_max.set(p["SEND_WAIT"][1])
        self.var_batch_size.set(p["BATCH_SIZE"])
        self.var_batch_pause_min.set(p["BATCH_PAUSE"][0])
        self.var_batch_pause_max.set(p["BATCH_PAUSE"][1])
        self.var_long_every.set(p["LONG_PAUSE_EVERY"])
        self.var_long_pause_min.set(p["LONG_PAUSE"][0])
        self.var_long_pause_max.set(p["LONG_PAUSE"][1])

    def _collect_params(self):
        return {
            "SESSION_LIMIT": self.var_session_limit.get(),
            "RECHECK_ALL": self.var_recheck.get(),
            "SHUFFLE": self.var_shuffle.get(),
            "FRIEND_GAP": (self.var_friend_gap_min.get(), self.var_friend_gap_max.get()),
            "SEND_WAIT": (self.var_send_wait_min.get(), self.var_send_wait_max.get()),
            "BATCH_SIZE": self.var_batch_size.get(),
            "BATCH_PAUSE": (self.var_batch_pause_min.get(), self.var_batch_pause_max.get()),
            "LONG_PAUSE_EVERY": self.var_long_every.get(),
            "LONG_PAUSE": (self.var_long_pause_min.get(), self.var_long_pause_max.get()),
            "PROBE_CHAR": self.adv_probe_char.get(),
            "DELETED_KEYWORDS": tuple(k.strip() for k in self.adv_deleted_kw.get().split(",") if k.strip()),
            "BLOCKED_KEYWORDS": tuple(k.strip() for k in self.adv_blocked_kw.get().split(",") if k.strip()),
        }

    def act_start_check(self):
        if self._is_running():
            messagebox.showwarning("提示", "已有任务在跑")
            return
        friends = load_friends(log=lambda *a, **k: None)
        if not friends:
            self.pre_check_var.set("❌ friends.txt 为空或不存在，请先抓名单")
            messagebox.showwarning("未准备好", "friends.txt 为空，请先到「抓名单」Tab 抓取好友名单")
            return
        ledger = load_ledger()
        unchecked = [n for n in friends if n not in ledger] if not self.var_recheck.get() else friends
        self.pre_check_var.set(
            f"✓ friends.txt 共 {len(friends)} 个，账本已测 {len(friends) - len(unchecked)}，"
            f"本次将测 {min(len(unchecked), self.var_session_limit.get())} 个"
        )
        if not unchecked:
            messagebox.showinfo("提示", "没有需要检测的好友了（账本已全部覆盖）。如需全测，勾选\"忽略账本全部重测\"")
            return

        params = self._collect_params()
        log = self.make_logger()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.progress_var.set(0)
        self.progress_label_var.set("0 / 0")
        self._set_status("检测中...")

        def progress_cb(cnt, total):
            def do():
                self.progress_var.set(cnt / total * 100 if total else 0)
                self.progress_label_var.set(f"{cnt} / {total}")
            self.root.after(0, do)

        def task():
            try:
                init_ocr()
            except Exception:
                pass
            result = run_check(params=params, log=log, progress=progress_cb, stop_event=self.stop_event)
            def done():
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")
                self._refresh_ledger_stats()
                self._set_status("就绪")
                if result:
                    self._log(f"[完成] 结果: {result['csv_path']}", "ok")
                    self.nb.select(self.tab_results)
            self.root.after(0, done)

        self._start_bg(task, "检测中")

    # ============ Tab 4: 查看结果 ============
    def _build_tab_results(self):
        f = ttk.Frame(self.tab_results, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="查看结果", font=("Microsoft YaHei", 12, "bold")).pack(anchor="w", pady=(0, 8))

        stat = ttk.LabelFrame(f, text="账本统计", padding=12)
        stat.pack(fill="x", pady=8)
        self.stat_var = tk.StringVar(value="点\"刷新\"查看")
        ttk.Label(stat, textvariable=self.stat_var, font=("Microsoft YaHei", 10), justify="left").pack(anchor="w")
        row = ttk.Frame(stat)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="刷新", command=self._refresh_ledger_stats).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="清空账本", command=self.act_clear_ledger).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="打开 output 目录", command=self._open_output_dir).pack(side="left")

        lists = ttk.LabelFrame(f, text="本次会话清单（最近一次）", padding=12)
        lists.pack(fill="both", expand=True, pady=8)
        self.lists_var = tk.StringVar(value="无")
        ttk.Label(lists, textvariable=self.lists_var, font=("Microsoft YaHei", 9), justify="left").pack(anchor="w")

        detail = ttk.LabelFrame(f, text="全部已测明细（最近 200 条）", padding=8)
        detail.pack(fill="both", expand=True, pady=8)
        cols = ("who", "status", "check_time")
        self.tree = ttk.Treeview(detail, columns=cols, show="headings", height=8)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=180 if c == "who" else 120)
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(detail, command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.config(yscrollcommand=sb.set)

    def _refresh_ledger_stats(self):
        rows = load_ledger_rows()
        if not rows:
            self.stat_var.set("账本为空（还没检测过）")
            self.lists_var.set("无")
            self.tree.delete(*self.tree.get_children())
            return
        from collections import Counter
        c = Counter(r.get("status", "") for r in rows)
        lines = [f"总计: {len(rows)} 个", "按状态："]
        for s, n in c.most_common():
            lines.append(f"  {s or '(空)':12s} {n}")
        lines.append(f"最近检测: {rows[-1].get('check_time', '')}")
        self.stat_var.set("\n".join(lines))

        self.tree.delete(*self.tree.get_children())
        for r in rows[-200:]:
            self.tree.insert("", "end", values=(r.get("who", ""), r.get("status", ""), r.get("check_time", "")))

        ts = rows[-1].get("session_ts", "")
        self._refresh_lists_display(ts)

    def _refresh_lists_display(self, ts):
        if ts is None:
            files = sorted(OUTPUT_DIR.glob("wx_status_*.csv")) if OUTPUT_DIR.exists() else []
            ts = files[-1].stem.replace("wx_status_", "") if files else None
        if not ts:
            self.lists_var.set("无")
            return
        lines = [f"会话 {ts}:"]
        for kind in ("deleted", "blocked", "uncertain"):
            p = OUTPUT_DIR / f"{kind}_{ts}.csv"
            if p.exists():
                with open(p, "r", encoding="utf-8-sig", newline="") as fp:
                    n = sum(1 for _ in csv.DictReader(fp))
                lines.append(f"  {kind}: {n} 个  ->  {p.name}")
        full = OUTPUT_DIR / f"wx_status_{ts}.csv"
        if full.exists():
            lines.append(f"  完整结果: {full.name}")
        self.lists_var.set("\n".join(lines))

    def act_clear_ledger(self):
        if not messagebox.askyesno("确认", "清空账本后下次会全部重测，确定？"):
            return
        if LEDGER_FILE.exists():
            LEDGER_FILE.unlink()
        self._log("[账本] 已清空", "warn")
        self._refresh_ledger_stats()

    def _open_output_dir(self):
        try:
            ensure_dirs()
            os.startfile(str(OUTPUT_DIR))
        except Exception as e:
            messagebox.showerror("错误", str(e))

    # ============ Tab 5: 高级设置 ============
    def _build_tab_advanced(self):
        f = ttk.Frame(self.tab_advanced, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="高级设置", font=("Microsoft YaHei", 12, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(f, text="一般不用改。仅当默认值不工作时调整。",
                  font=("Microsoft YaHei", 9)).pack(anchor="w")

        box = ttk.LabelFrame(f, text="探测字符与判定关键词", padding=12)
        box.pack(fill="x", pady=8)

        ttk.Label(box, text="探测字符 (PROBE_CHAR):").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=4)
        self.adv_probe_char = tk.StringVar(value=WX_DEFAULTS["PROBE_CHAR"])
        ttk.Entry(box, textvariable=self.adv_probe_char, width=30).grid(row=0, column=1, sticky="w")
        ttk.Label(box, text="(零宽字符组合，被微信撤回时才需换)",
                  font=("Microsoft YaHei", 8), foreground="#888").grid(row=0, column=2, sticky="w", padx=8)

        ttk.Label(box, text="deleted 关键词 (逗号分隔):").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=4)
        self.adv_deleted_kw = tk.StringVar(value=",".join(WX_DEFAULTS["DELETED_KEYWORDS"]))
        ttk.Entry(box, textvariable=self.adv_deleted_kw, width=60).grid(row=1, column=1, columnspan=2, sticky="w")

        ttk.Label(box, text="blocked 关键词 (逗号分隔):").grid(row=2, column=0, sticky="w", padx=(0, 4), pady=4)
        self.adv_blocked_kw = tk.StringVar(value=",".join(WX_DEFAULTS["BLOCKED_KEYWORDS"]))
        ttk.Entry(box, textvariable=self.adv_blocked_kw, width=60).grid(row=2, column=1, columnspan=2, sticky="w")

        paths = ttk.LabelFrame(f, text="文件路径", padding=12)
        paths.pack(fill="x", pady=8)
        for i, (label, p) in enumerate([
            ("friends.txt:", FRIENDS_FILE),
            ("coords.json:", COORDS_FILE),
            ("账本 ledger:", LEDGER_FILE),
            ("data 目录:", DATA_DIR),
            ("output 目录:", OUTPUT_DIR),
        ]):
            ttk.Label(paths, text=label).grid(row=i, column=0, sticky="w", padx=(0, 8), pady=2)
            ttk.Label(paths, text=friendly_path(p), font=("Consolas", 9)).grid(row=i, column=1, sticky="w")

        about = ttk.LabelFrame(f, text="关于", padding=12)
        about.pack(fill="x", pady=8)
        ttk.Label(about, text=(
            "微信好友状态检测客户端  |  wxauto4 探测消息法\n"
            "原理: 向好友发零宽字符 + 读系统消息判定删除/拉黑\n"
            "环境: 微信 4.1.8.107 + wxauto4 免费版\n"
            "风险: 中-低（已默认低风险模式：限量、长间隔、批间停顿）\n"
            "局限: 不是 100% 零打扰（对方可能看到空气泡）"
        ), font=("Microsoft YaHei", 9), justify="left").pack(anchor="w")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
