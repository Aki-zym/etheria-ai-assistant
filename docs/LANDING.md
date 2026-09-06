# 伊瑟 AI 助手 — 项目 Landing 文档

> 新成员 / AI 协作伙伴上手指南。读完本文即可理解代理游戏时的完整算法逻辑：
> 如何感知画面、如何识别当前状态、如何决定下一步操作。
>
> 基于代码实地阅读整理（2026-09，commit `839f4b5`）。行号可能随后续提交漂移，以函数名为准。

---

## 0. 快速上手

### 环境与启动

```powershell
# 后端 + GUI（推荐入口，自动处理 sys.path 和 DPI）
.\.venv\Scripts\python.exe scripts/run.py

# 前端热更新开发（另一个终端）
cd frontend && npm run dev     # pywebview 自动连接 localhost:5173

# CLI 模式（无界面调试）
.\.venv\Scripts\python.exe scripts/run.py --cli        # 交互式 find/click/截图
.\.venv\Scripts\python.exe scripts/run.py --capture    # 快速截图
```

技术栈：Python 3.11 + pywebview（桌面窗口）+ Vue 3 / Vite（前端）+ OpenCV（模板匹配）+ EasyOCR / PaddleOCR（文字识别）。

### ⚠️ 已知坑

- **不要直接 `python ui/app.py`** —— 会报 `No module named 'core'`（`sys.path.insert` 在 app.py:124，晚于第 6 行的 import）。必须走 `scripts/run.py` 入口。
- `config.py` 默认 `ocr_engine = "paddle"`，但打包分发实际用 EasyOCR（仓库自带 `easyocr_models/`）。开发机两个都装了，改 `GAME_CONFIG.ocr_engine` 可切换。
- 仓库 `requirements.txt` 与 README 技术栈描述不完全一致（paddle vs easyocr），以代码实际 import 为准。
- 远程仓库是 fork 结构：`origin` → `Aki-zym/etheria-ai-assistant`（自己的），`upstream` → `WhiteFree22333/etheria-ai-assistant`（原仓库，用于同步）。

---

## 1. 总体架构：四层结构

```
Vue 3 前端 (frontend/src)          面板 / 开关 / 日志展示
        │  pywebview JS Bridge —— Api 类方法直接暴露给 JS 调用
        ▼
Api 类 (ui/app.py)                 参数校验、调用任务函数（同步执行）
        ▼
GameBot (core/_common/bot.py)      统一操作接口：截图/找图/找字/点击/日志
        ▼
战斗模块 (core/daily|events|rta/)  每个副本/活动一个 run_xxx_battle 流程脚本
        ▼
基础能力层 (core/_base/)           capture / template_match / ocr / input / window
```

配置集中在 `core/config.py`：`GAME_CONFIG`（阈值、超时、偏移等所有可调参数，支持 `.env` 覆盖）+ `DUNGEONS`（副本查表）。

---

## 2. 感知层：程序如何"看见"游戏

### 2.1 五路截图降级链 — `capture.py: capture_game_screen`

```
WGC (Windows.Graphics.Capture)      ← 最优先：DWM 合成层，窗口被完全遮挡也能出帧（需 windows-capture 包）
   ↓ 失败/帧过期(如最小化，>2s 无新帧)
PrintWindow(PW_RENDERFULLCONTENT)   ← 非 Unreal 窗口：直接从 DWM 拿窗口内容
   ↓ 失败/黑帧
DXCam
   ↓
BitBlt                              ← 非 Unreal；窗口可被遮挡但需可见
   ↓
MSS 前台截图（自动抢焦点，会短暂打扰用户）
```

WGC 会话常驻（识别时只取最新帧 ~40ms），窗口句柄/尺寸变化自动重建；
伊瑟是 UnrealWindow（PrintWindow/BitBlt 拿到黑帧/脏缓冲会被跳过），
实际主路 = **WGC → MSS**。窗口最小化时游戏停止渲染，WGC 帧过期自动回落
（如需纯后台，把窗口移出屏幕外保持还原状态即可）。

- 每张截图做**黑帧检测**（`is_black_image`，均值 < 10 判为后台截图失败，自动跳下一路）。
- 超时兜底：`wait_for_image` 超时后会新建 MSS 实例强制截一张"新鲜帧"，绕过 DXGI 缓存/脏帧问题。

### 2.2 状态识别的三把尺子

| 工具 | 用途 | 关键参数 |
|---|---|---|
| **模板匹配** `template_match.py` | 识别图标/按钮 | `TM_CCOEFF_NORMED`，**15 尺度 0.5x–2.67x** 适应任意分辨率；默认阈值 0.75。固定尺寸按钮（如"返回"）关多尺度、单尺度阈值提到 0.82 防误判 |
| **OCR** `ocr.py` | 识别文字 | 双引擎（Paddle / EasyOCR）；小字三重增强：**CLAHE 对比度 + 2x 立方放大 + 多轮识别拼接兜底**；数字识别 `allowlist='0123456789'` 强约束 |
| **颜色检测** `battle_common.find_all_by_color` | 识别红点标记 | `cv2.inRange` 按色号筛 → 找轮廓 → 面积 ≥3 过滤 → 10px 去重 → 按 Y 排序 |

模板路径辅助：`tpl()` 拼 `templates/richang/`，`_stpl()` 拼 `templates/shilian/`，`_rtpl()` 拼 `templates/rta/`。中文路径统一用 `_imread`（open + imdecode），因为 `cv2.imread` 在 Windows 下不支持中文。

### 2.3 全项目最重要的防坑模式：二次确认

所有"检测到"必须过一道：

```python
match = bot.find_image(tpl)
if match:
    time.sleep(0.15)          # 等动画帧过去
    match2 = bot.find_image(tpl)
    if match2 is not None:    # 还在 → 真的出现了
```

游戏动画帧会让模板短暂闪现，单次匹配不可信。`wait_for_image`（battle_common.py）内置了此逻辑。

---

## 3. 状态识别哲学：没有状态机的状态机 ⭐

**理解这个项目最重要的一点：它没有显式的全局状态机，也没有世界模型。**

- **"当前状态"** = 此刻截图里哪些模板可见。
- **"转移确认"** = 预期模板的出现 / 消失，由游戏画面自己"回答"。

三个核心原语（`battle_common.py`，所有模块共用）：

| 原语 | 语义 | 实现 |
|---|---|---|
| `wait_for_image(bot, 名, timeout)` | 阻塞等某界面出现 | 0.5s 轮询 + 二次确认；超时后 MSS 强制前台截图兜底再试一次 |
| `wait_for_image_gone(bot, 名)` | 确认页面已切走 | 连续 2 次匹配不到才确认；超时**放宽**为"曾消失过 1 次"就算（防 Unity 偶尔不吃 PostMessage 导致死等） |
| `post_click(hwnd, x, y)` | 后台无干扰点击 | 见第 5 节 |

所以"点挑战 → 等挑战按钮消失 → 等副本入口出现"这一串，本质上就是**用模板的出现/消失作为状态转移的确认信号**。

**防御性弹窗处理**散布在流程各处，每个都是"等模板 → 出现就点掉 → 不中断主流程"：

体力不足（`_wait_battle_or_stamina`）· 源器超出上限（`handle_over_limit`）· 装备占用（setup_preset 内）· 前往清理（`handle_cleanup_popup`）· 已成功招募（源网）· 巅峰直接胜利（RTA，用哨兵异常中断）。

---

## 4. 决策层：五个智能层级

### Level 1 — 线性查表（`bot.py: run_dungeon`）

按 `DUNGEONS` 配置顺序点文字按钮：入口 → 选副本 → 开始 → 挂机等 → 领奖 → ESC。纯执行，最老代码。

### Level 2 — 带验证的流程（`daily/zhike_battle.py` 智壳，280 行）

每步 `wait_for_image` 前置确认，失败即 `[FAIL]` 返回。两个亮点模式：

- **`scroll_and_find`**（zhike_battle.py:13）：拖动列表 → 每拖一次重新模板匹配 → 找到后二次确认才点，最多 30 次。拖动用 SendInput（Unity 用 Raw Input 读鼠标，后台无效），所以先短暂抢焦点 ~200ms。
- **次数设置交互**：点"连续战斗R" → 弹窗后「减号 ×15 清零 → 加号 ×N 设到目标次数」。

### Level 3 — 地图探索算法（`events/yuanwang_battle.py` 源网征令，538 行）⭐ 全项目核心算法

真正的"感知 → 决策 → 行动 → 反馈"循环（run_yuanwang_battle 主循环）：

```
while 未停止:
  1. 感知   色号 RGB(226,33,40)±30 找出所有六边形红点
  2. 预处理 20px 聚类合并（一个六边形碎成多点）+ 排除已知误报点 (733,537)
  3. 决策   按"离圆心距离"降序排序 → 外围优先，同圈内 Y 小的先
            圆心优先用「终极圆心.png」模板定位，找不到退化用画面中心
  4. 行动   逐个点红点 → 验证「源网前往挑战」出现才算导航成功
  5. 反馈   成功 → 进战斗（可能第二场）→ OCR 选牌 → 回到 1
            失败 → 该点标记已试 → 退回地图 → 重扫红点
            └─ 对比新旧红点快照：>50% 的点位移 >30px 或数量变化
               → 判定"地图已刷新" → 重新排序重新规划
  6. 卡死保护 连续 3 轮所有红点都打不开 → 放弃循环（stale_rounds 计数器）
```

**OCR 选牌算法** `_select_card_by_ocr`：三张牌逐个点击（固定客户区坐标）→ 每次截详情区域 OCR → 按**优先级表**排序（晶格 > 强化 > 全量 > 质补 > 晋升 > 突破）→ 回点最优。关键词带单字备选（"晶"可命中"晶格"），应对 OCR 识别不全。

另有 `detect_region`：识别当前区域（蜃都/坎特/洛莱）= 模板匹配 + **取匹配框内最暗像素判断激活态**（黑字=活跃，白字=未激活）。

### Level 4 — 数值驱动的循环（`events/xujin_battle.py` 虚烬探索，535 行）

- **层数感知**：右上角裁剪 → 找红色竖条 RGB(220,26,84) → OCR 找 "-" 号 → 只识别其左侧窄条的数字（`allowlist` 数字）→ 当前层数 → **循环直到层数 ≥ 43 且「虚烬已获得」**。
- **3D 行走**：按住 W 键 + **0.2s 高频截图扫描**宝箱图标（防走过头），找到即松键点击。
- **卡牌收集**：多匹配找「虚烬卡牌」，要求 ≥4 张才继续，最多重扫 3 次。
- **状态清理仪式**（xujin_battle.py 末尾）：每轮结束 `keyUp('wasd') + mouseUp(三键) + 光标甩出窗口外`。**原因**：SendInput 残留按键会让下一轮 PostMessage 点击被 Unity 误判成拖拽/滚轮。实战踩坑痕迹，新模块必抄。

### Level 5 — 对抗性博弈（`rta/weekly_battle.py` 巅峰竞技场，461 行）

- **先手/后手判定**：交替探测「先手bp」「后手bp」模板，两边都识别到后**比置信度取高者**（处理识别抖动）。
- **BP 选人策略**：多匹配找所有「置顶角色」→ 从左到右逐个点 → 每点一个检测三种封锁标志（对方已选/已禁用/我方已选）→ **全被封锁就拖动刷新列表重扫**。
- **对手投降**：「巅峰直接胜利」界面随时可能出现 → 哨兵异常 `_VictoryDetected` + 所有等待点内嵌 `_check_victory` 快速中断当前局，跳到下一局。

---

## 5. 执行层：三种输入通道按场景选用

| 方式 | 原理 | 用途 | 代价 |
|---|---|---|---|
| `post_click` | PostMessage 直接投 WM_MOUSEMOVE/LBUTTONDOWN/UP 到 **UnityWndClass 子窗口**的消息队列 | 99% 的 UI 点击 | 零干扰、后台可点、鼠标不动；被遮挡时 Unity 可能忽略（所以有"短暂提到前台"的补丁） |
| `post_drag` / `scroll` | SendInput + `lock_input` 锁 | 列表滚动、拖地图 | 需抢焦点 ~200ms，期间 BlockInput 锁用户 |
| `pyautogui.keyDown/press` | 前台键盘 | 3D 行走（W）、Tab/F | 必须真焦点 + `lock_input` 包裹 |

`lock_input`（input.py）上下文管理器 = `AttachThreadInput` 挂接游戏线程 + `BlockInput` 锁物理输入 + 清空消息队列残留鼠标事件。防止用户此刻动鼠标把脚本点击顶掉。

窗口定位（window.py）：`find_game_window` 按标题关键词找顶层窗口 → 递归搜索 **UnityWndClass 子窗口**确认是游戏（排除浏览器同标题窗口）→ 排除自己进程和最小化窗口。`focus_window` 用 AttachThreadInput 技法绕过 Windows 防抢焦点限制。

---

## 6. 线程模型与停止机制

- 前端点「开始」→ `Api` 方法在 pywebview API 线程上同步调用 `run_xxx_battle`（ui/app.py；仅遗留的 start_dungeon 走 daemon 线程）。任务调度收敛到统一 Tasker 属于升级 Phase 2，见 `docs/MAA-架构分析与Etheria升级路线.md`。
- **停止** = 设置 `bot._running = False`；所有 `wait_for_image` / 循环开头都检查 `bot.is_running`，秒级响应。
- **日志** = `bot.on_log(回调)` → `Api._push_log` → 队列 → 刷线线程 → webview JS 事件 → 前端日志面板。
- 后端同时维护 `run.bat` 兼容入口（走 `scripts/run.py`）。

---

## 7. 工程防坑清单（新代码必读）

1. **二次确认**：所有模板命中 sleep(0.15) 再验一次（动画帧闪现）。
2. **消失确认要放宽**：`wait_for_image_gone` 超时后"曾消失过 1 次"即算切走——Unity 偶尔不吃 PostMessage，死等会卡死全流程。
3. **截图超时 MSS 兜底**：DXGI 有缓存/脏帧问题，超时后用新建 MSS 实例强制前台截图再验一次。
4. **回到主界面**：`go_back_to_main` 循环点「返回」最多 10 次，两个模板（返回/返回2）都找不到 = 已到主界面。
5. **退出战斗**：`exit_battle` 点**窗口左下角固定偏移坐标**（不是模板），默认双击防段位升级弹窗。
6. **wasd/鼠标状态清理**：SendInput 轮次结束后彻底 keyUp/mouseUp + 光标甩出窗口，否则残留输入污染下一轮。
7. **中文路径**：cv2.imread 换 `_imread`（imdecode）。
8. **DPI 感知**：`scripts/run.py` 开头 `SetProcessDpiAwareness(1)`，防止缩放导致坐标偏移。必须在所有 import 之前。
9. **OCR 稳定性**：小字先 CLAHE / 2x 放大 / 多轮识别；数字用 allowlist；关键词匹配留单字备选。
10. **固定坐标兜底**：选牌、退出等位置用**客户区坐标 + 偏移**硬编码（对 16:9 固定布局够用），与模板匹配互为补充。

---

## 8. 新功能开发指南

### 标准骨架（照抄 zhike_battle.py）

```python
def run_my_feature(bot, ...):
    hwnd = bot.game_window.hwnd
    bot._running = True
    try:
        bot.go_back_to_main(tpl('返回.png'))        # 1. 归位
        open_sidebar(bot)                            # 2. 侧边栏
        pos = wait_for_image(bot, '入口.png')        # 3. 每步 wait_for_image 确认
        if pos is None:
            return False                             # 4. 失败打 [FAIL] 日志并返回
        post_click(hwnd, pos[0], pos[1])             # 5. post_click 点击
        wait_for_image_gone(bot, '入口.png')         # 6. 等切页确认
        ...
        return True
    finally:
        bot._running = False                         # 必须还原运行标志
```

### 复用组件清单

| 需求 | 用 | 来自 |
|---|---|---|
| 等界面出现 | `wait_for_image(bot, 名)` | battle_common |
| 确认切页 | `wait_for_image_gone(bot, 名)` | battle_common |
| 等战斗打完 | `wait_battle_end` / Buff 消失模式 | battle_common / 各模块特化版 |
| 入场（手动→预设→F战斗） | `enter_and_wait_battle` | battle_common |
| 找所有红点/色块 | `find_all_by_color(bot, rgb, tol)` | battle_common |
| 滚动列表找图标 | `scroll_and_find`（zhike） | zhike_battle |
| 找"手动"按钮（模板+OCR 双保险） | `_find_manual_button` | battle_common |
| 弹窗防御 | `handle_cleanup_popup` 等 | battle_common / 各模块 |

### 新增模板图片

用 GUI 的截图预览 + 裁剪功能（`Api.save_template`），或 CLI `--capture` 截图后手动裁剪，存入对应 `templates/richang|shilian|rta/` 目录。命名与代码中引用保持一致。

### 对接前端

1. `ui/app.py` 的 Api 类加 `run_my_feature` 方法（照抄 `run_zhike_battle`：校验 → import → 调用）。
2. `frontend/src/components/` 对应面板加开关，composable 里绑定 Api 方法。

---

## 9. 文件地图

```
ui/app.py                    pywebview 入口 + Api 桥（1014 行，含打包 torch DLL 预加载）
scripts/run.py               开发统一入口（sys.path + DPI 修复 + CLI 模式）
core/
  config.py                  GAME_CONFIG 全部可调参数 + DUNGEONS 副本表
  _base/capture.py           四路截图降级链
  _base/template_match.py    单尺度/15尺度多尺度模板匹配
  _base/ocr.py               Paddle / EasyOCR 双引擎 + find_text
  _base/input.py             post_click / post_drag / scroll / lock_input / wasd
  _base/window.py            find_game_window(Unity子窗口) / focus_window
  _common/battle_common.py   全部共用原语（wait_for_image 系 / 入场 / 退出 / 颜色查找）
  _common/bot.py             GameBot 统一接口 + 老版 run_dungeon
  daily/zhike_battle.py      智壳（scroll_and_find、次数清零设数）
  daily/guild_battle.py      公会全套（1002 行，最大模块）
  daily/yuanqi_battle.py     源器
  daily/qianneng_battle.py   潜能/经验
  events/yuanwang_battle.py  源网征令 ⭐ 外围优先地图探索 + OCR 选牌
  events/xujin_battle.py     虚烬探索（层数 OCR 循环 + 3D 行走找宝箱）
  events/chaoneng_battle.py  超能二十一（托管循环）
  events/anlong_battle.py    暗笼激斗
  rta/weekly_battle.py       巅峰竞技场（先手判定 + BP 选人 + 投降处理）
templates/                   richang(日常) / shilian(试炼) / huodong(活动) / rta
frontend/src/components/     daily / events 面板组件
hooks/                       PyInstaller 打包钩子
```

---

*本文档由 AI 协作伙伴（Cindy / Claude）通读全部核心代码后整理，供后续开发参考。发现与代码不符时以代码为准，并欢迎更新本文。*
