# 微信好友状态检测

用 [wxauto4](https://github.com/cluic/wxauto4) 免费版（UI 自动化）检测微信里**哪些好友把你删除 / 拉黑**，导出清单供手动删除。适合大批量好友（如 3000 人）分多次跑完。

---

## 一、原理

向每个好友发送一个"近乎不可见"的零宽探测字符，读取微信返回的系统消息判定状态：

| 系统消息 | 判定 | 输出标记 |
|----------|------|---------|
| "开启了朋友验证，你还不是他(她)朋友..." | 已删除你 | `deleted` |
| "消息已发出，但被对方拒收了" | 已拉黑你 | `blocked` |
| 无系统消息 | 仍是好友 | `normal` |
| 读不到 / 超时 / 异常 | 待人工复核 | `uncertain` |

> ⚠️ **不是 100% 零打扰**：零宽字符在部分微信版本会显示为"空气泡"，对方可能看到一个空白消息。

---

## 二、环境要求

| 项 | 要求 |
|----|------|
| 操作系统 | Windows 10/11 |
| Python | 3.9-3.12 |
| **微信 PC 版本** | **4.1.8.107**（wxauto4 免费版支持上限，再新控件 ID 会变、初始化失败） |
| 微信状态 | 已登录、主窗口可见（不能最小化到托盘） |

---

## 三、程序入口总览

5 个 Python 脚本，按下面的顺序跑。前 3 个一次性准备，后 2 个日常使用。

| # | 脚本 | 作用 | 何时跑 | 产物 |
|---|------|------|--------|------|
| 1 | `show_wechat.py` | 唤起微信主窗口 + 测 wxauto4 能否初始化 | 安装/降级微信后，第一次跑前 | 无（只输出诊断） |
| 2 | `calibrate.py` | 校准通讯录坐标（2 项） | 一次性，窗口位置固定后 | `coords.json` |
| 3 | `scrape_friends.py` | OCR 滚动通讯录抓名字 | 一次性，或好友变动后重跑 | `friends.txt` |
| 4 | **`wx_check.py`** | **主检测**（探测消息法） | 重复跑，直到全部测完 | `output/*.csv` |
| 5 | `ledger.py` | 查看/清空已检测账本 | 想看进度或重测时 | 无（只输出/删账本） |

**辅助模块**（不要直接跑）：
- `ocr_utils.py` — OCR 引擎封装（PaddleOCR 优先，Tesseract 备用），被 `scrape_friends.py` 调用
- `ledger.py` 也可作为模块被 `wx_check.py` 导入，提供账本读写函数

---

## 四、完整使用流程

### 准备：安装依赖
```bash
cd C:\Users\chenj\wechat_friend_check
pip install -r requirements.txt
```
> PaddleOCR 较大（含 paddlepaddle，约几百 MB），中文准确度最高，强烈建议装。装不上会自动退到 Tesseract（需另装 Tesseract-OCR 程序 + chi_sim 中文包）。

### 第 1 步：确认/降级微信到 4.1.8.107
```powershell
# 查看当前版本
Get-Item "C:\edward\file_jieya\Weixin\Weixin.exe" | % VersionInfo ProductVersion
```
如果不是 4.1.8.107（比如更新的 4.1.11），需要降级：
1. 下载：https://github.com/SiverKing/wechat4.0-windows-versions/releases/download/v4.1.8.107/weixin_4.1.8.107.exe
2. **完全退出当前微信**（包括托盘图标右键退出，确保所有 `Weixin.exe` 进程关闭）
3. 运行下载的 exe 覆盖安装
4. **登录后立刻关掉自动更新**：微信 → 设置 → 通用设置 → 取消"有更新时自动升级"
   - 否则微信会偷偷升回新版，wxauto4 又用不了

### 第 2 步：测 wxauto4 能否初始化
```bash
python show_wechat.py --test
```
**预期输出**：
```
[找到] hwnd=xxx class='Qt51514QWindowIcon' visible=False iconic=False
[结果] visible=True is_foreground=True
--- 测试 wxauto4 初始化 ---
初始化成功，获取到已登录窗口：Edward
[OK] wxauto4 初始化成功！
```
看到 `[OK]` 才能继续。失败常见原因：
- 微信版本太新（不是 4.1.8.107）
- 微信主窗口没显示（脚本会自动唤起，但如果微信没登录就唤不出）
- 没装 wxauto4：`pip install wxauto4`

### 第 3 步：校准通讯录坐标（一次性）
```bash
python calibrate.py
```
只需校准 2 项：
1. **通讯录标签** —— 点左侧导航栏"通讯录"图标
2. **联系人列表区域** —— 在通讯录页框选右侧联系人列表（点左上角 + 右下角）

操作要点：
- 脚本启动后，每项提示 `选择 [回车=保留 / r=重校 / s=跳过]:`
- 第一次跑直接按提示在微信里点击目标位置即可
- 校准结果存 `coords.json`，**以后微信窗口位置别动**
- 紧急中断：鼠标甩到屏幕左上角 (0,0)

### 第 4 步：抓好友名单
```bash
python scrape_friends.py
```
自动点通讯录 → 滚动 → OCR 每屏名字 → `friends.txt`。

**为什么需要这步**：wxauto4 免费版没有 `GetFriendDetails`（拿不到好友列表），只能靠 OCR 抓或手动编辑 `friends.txt`。

**跑完务必人工核对 `friends.txt`**：
- 删掉明显不是人名的行（单字母、群名、公众号等 OCR 误识别）
- 确认行数接近你实际好友数（OCR 滚动会有漏）
- 建议用**备注名**（唯一）而不是昵称（可能重名），避免后面 `wx_check.py` 搜索时匹配错人

### 第 5 步：跑检测（可分多次）
```bash
python wx_check.py
```
**行为**：
- 默认每会话限量 80 个（探测法有发消息行为，不要一口气跑太多）
- 自动跳过账本里已测过的好友
- 实时落盘，跑一半中断（Ctrl+C）已测的不会丢
- 跑完导出 `deleted`/`blocked`/`uncertain` 三个清单
- **续跑**：直接再跑 `python wx_check.py`，自动从剩余的继续

**运行期间**：
- 不要动鼠标键盘（脚本在自动操作微信）
- 紧急中断：Ctrl+C，已测的会落盘并写入账本

**预期输出**：
```
[1/80] 张三 ... normal
[2/80] 李四 ... deleted
      开启了朋友验证... | all_new=...
[3/80] 王五 ... blocked
      ...
  [批间停顿] 已测 20 个，停 60-120s 模拟人类...
...
[账本] 新增/更新 80 条 -> output/checked_ledger.csv

[5/5] 统计：
    normal: 75
    deleted: 3
    blocked: 1
    uncertain: 1
    本次耗时: 0时18分32秒

deleted 清单: output/deleted_20260707_161500.csv  (3 个)
blocked 清单: output/blocked_20260707_161500.csv  (1 个)
uncertain 清单: output/uncertain_20260707_161500.csv  (1 个)

完整结果: output/wx_status_20260707_161500.csv

[续跑] 还剩 2920 个未测。直接再跑 python wx_check.py 自动跳过已测的。
```

### 第 6 步：处理结果
```bash
python ledger.py        # 看已测统计
python ledger.py show   # 看全部明细
python ledger.py clear  # 清空账本（下次全测）
```
- `output/deleted_*.csv` → 微信手动删除这些人
- `output/blocked_*.csv` → 微信手动删除这些人
- `output/uncertain_*.csv` → 手动转账法复核（少量，几百个里可能就几十个）

---

## 五、配置项详解

所有可调参数都在脚本顶部的 `# 配置区` 注释下，改数值即可。

### `wx_check.py` 主检测脚本

| 参数 | 默认 | 说明 |
|------|------|------|
| `PROBE_CHAR` | `"\u2060\u200b\u200c\u200d"` | 探测字符（零宽组合）。如被微信撤回，可换其他不可见 Unicode |
| `SEND_WAIT` | `(3.0, 6.0)` | 发送后等待系统回执秒数。`uncertain` 多时调大 |
| `FRIEND_GAP` | `(8.0, 15.0)` | 每个好友间隔秒数。想更安全调到 `(15, 30)` |
| `BATCH_SIZE` | `20` | 每批数量。每批后停 `BATCH_PAUSE` |
| `BATCH_PAUSE` | `(60.0, 120.0)` | 批间停顿秒数 |
| `LONG_PAUSE_EVERY` | `50` | 每测 N 个插一次长停顿 |
| `LONG_PAUSE` | `(180.0, 300.0)` | 长停顿秒数 |
| `SESSION_LIMIT` | `80` | 单会话上限。3000 人建议分 30-40 次跑完 |
| `SHUFFLE` | `True` | 顺序打乱，不按 friends.txt 顺序连续发 |
| `RECHECK_ALL` | `False` | 设 `True` 忽略账本全部重测 |
| `DELETED_KEYWORDS` | `(...)` | deleted 判定关键词，可加新文案 |
| `BLOCKED_KEYWORDS` | `(...)` | blocked 判定关键词 |
| `WECHAT_WINDOW_TITLE` | `"微信"` | 微信主窗口标题（用于唤起） |

### `scrape_friends.py` 抓名单脚本

| 参数 | 默认 | 说明 |
|------|------|------|
| `SCROLL_PAUSE` | `1.2` | 每次滚动后等界面渲染秒数 |
| `MAX_ROUNDS` | `400` | 最多滚动轮数，防死循环 |
| `STABLE_STOP` | `3` | 连续 N 轮无新名字则停 |
| `SKIP_NAMES` | `{...}` | 过滤的系统项（新的朋友、群聊、公众号等） |

### `calibrate.py` / `show_wechat.py`
无重要可调参数，按提示操作即可。

---

## 六、输出文件说明

```
output/
├── checked_ledger.csv          # 账本：跨会话去重依据（who, status, check_time, session_ts）
├── wx_status_<时间>.csv         # 本次完整结果（含 detail 调试字段）
├── deleted_<时间>.csv           # 已删除你的好友清单
├── blocked_<时间>.csv           # 已拉黑你的好友清单
└── uncertain_<时间>.csv         # 待人工复核清单
```

**`wx_status_*.csv` 字段**：
- `who` — 好友名
- `status` — `normal` / `deleted` / `blocked` / `uncertain` / `error`
- `detail` — 调试信息（OCR 文本、系统消息内容、错误原因等），排查问题时看这个
- `check_time` — 检测时间
- `session_ts` — 本次会话时间戳（用于关联 `wx_status_*.csv` 和账本）

**`checked_ledger.csv` 字段**：`who, status, check_time, session_ts`（和 `wx_status` 类似但没 detail，用于跨会话去重）

---

## 七、封号风险

**中-低**。风险来源是"短时间内给大量好友发消息"这个行为本身，不是工具。已通过默认低风险模式缓解：
- 单会话限量 80 个
- 好友间隔 8-15 秒
- 每 20 个停 1-2 分钟（批间停顿）
- 每 50 个停 3-5 分钟（长停顿）
- 顺序打乱，不按通讯录顺序连续发

**绝不要把 `SESSION_LIMIT` 调到几百一口气跑完**。3000 人建议分 30-40 次会话，跨几天跑完。

---

## 八、已知局限（务必读）

1. **依赖微信版本**：wxauto4 免费版只支持到 4.1.8.107，再新的版本控件 ID 会变、初始化失败。
2. **不是 100% 零打扰**：零宽字符在部分微信版本会显示为空气泡，对方可能看到。
3. **OCR 准确率 ~85-95%**：`scrape_friends.py` 抓名字会有漏/错，跑完务必人工核对 `friends.txt` 数量是否接近实际好友数。
4. **搜索可能匹配错人**：昵称重复时 `ChatWith` 可能打开错对象。`wx_check.py` 有 `ChatInfo` 标题核对会降级为 `uncertain`，但不是 100% 可靠。建议 `friends.txt` 用备注名（唯一）。
5. **`scrape_friends.py` 滚动可能漏名字**：OCR 列表会有漏。
6. **`deleted`/`blocked` 分支未经实战验证**：如果从未测出过删除/拉黑的好友，关键词匹配逻辑没经过验证。第一次测出 deleted/blocked 时看 `detail` 字段确认逻辑对不对。

---

## 九、调试建议

### 第一次跑前
1. `python show_wechat.py --test` 确认 wxauto4 能初始化
2. 在 `friends.txt` 里只放 1-2 个已知好友测一下 `wx_check.py`，看 `output/wx_status_*.csv` 的 `detail` 字段，确认能正确读到消息

### 常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| `wxauto4 初始化失败: 未找到已登录的客户端主窗口` | 微信没登录/最小化到托盘 | `python show_wechat.py` 先唤起，或手动打开微信主窗口 |
| `wxauto4 初始化失败: LookupError: Find Control Timeout` | 微信版本太新 | 降级到 4.1.8.107 |
| 大量 `uncertain` | `SEND_WAIT` 太短，系统消息还没返回就读了 | 调大 `wx_check.py` 顶部 `SEND_WAIT`，如 `(5.0, 10.0)` |
| `detail` 里出现"你撤回了一条消息" | 微信把零宽字符消息自动撤回了 | 通常不影响判定（撤回也算"无系统回执"→ normal）。如想避免，换 `PROBE_CHAR` |
| `friends.txt` 名字明显偏少 | OCR 漏抓，或滚动提前停了 | 调大 `scrape_friends.py` 的 `STABLE_STOP` 和 `MAX_ROUNDS`，重跑 |
| `detail` 里 `title_mismatch` | 搜索没匹配到对的人（昵称重复/搜不到） | `friends.txt` 改用备注名 |

---

## 十、如果 PaddleOCR 装不上
```bash
# Tesseract 备用方案（需先装程序）
# 1. 下载安装 Tesseract-OCR: https://github.com/UB-Mannheim/tesseract/wiki
# 2. 安装时勾选 Chinese (Simplified) 语言包
# 3. pip install pytesseract
# 4. 可能需设置 tesseract.exe 路径:
#    import pytesseract; pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
```
