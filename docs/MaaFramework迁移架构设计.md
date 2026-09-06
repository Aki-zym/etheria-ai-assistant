# Etheria Assistant 迁移架构设计 —— 基于 MaaFramework

> 2026-09-05 · 基于对 MAA v6.1.1 源码的完整精读、MaaFramework 官方协议文档、以及同类项目调研后的架构决策文档。
> 结论先行：**采用 MaaFramework 作为核心引擎，Etheria 现有代码退役为"游戏内容数据 + 少量 Python Custom 逻辑"。**
>
> **2026-09-06 状态**：因模拟器暂无法运行伊瑟最新版本，本文 4.1 的「模拟器+ADB 推荐主路」调整为**封存待接入**（现状、纪律与重启清单见《Etheria升级总计划》第六章），主线改为 PC 客户端（Win32 控制器）；第 5 节排期由《Etheria升级总计划》第五章取代。

---

## 1. 调研结论：游戏挂机助手的"核心"已经收敛

对主流开源游戏自动化项目的调研结果：

| 项目 | 游戏 | 核心引擎 | 现状 |
|---|---|---|---|
| [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights) | 明日方舟 | 自研 MaaCore → 抽出 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) | 母项目，26k+ stars |
| [March7thAssistant](https://github.com/moesnow/March7thAssistant) | 崩坏:星穹铁道 | 自研 image_pipeline → **v3.0.0 (2025-01) 全量迁移 MaaFramework** | 官方原话："自研截图器与识别算法和 MaaFramework 重复，不再维护" |
| [StarRailCopilot/SRC](https://github.com/MAA1999/SRC) | 崩坏:星穹铁道 | ALAS 架构 → **基于 MaaFramework 重新实现** | 1.5k stars |
| [ALAS](https://github.com/LmeSzinc/AzurLaneAutoScript) | 碧蓝航线 | 自研 Python → **7.0 版 Assets 层替换为 MaaFramework** | 最成熟的 Python 项目也做了迁移 |
| [M9A](https://github.com/MaaXYZ/M9A) | 重返未来:1999 | MaaFramework | 1.2k stars，生态标杆 |
| MAABH / MNGA / MMA / MSBA | 崩3 / NIKKE / 物华弥新 / 少前2 | MaaFramework | 生态项目十余个 |
| [BGI (BetterGenshinImpact)](https://github.com/baboon921/better-genshin-impact) | 原神 | 自研 C#（.NET8 + WPF + OpenCV + YOLO） | PC 端 3D 游戏有特殊需求（键鼠/地图追踪），保留自研 |
| Airtest (网易) | 通用 | 通用 UI 自动化 | 偏 App 测试，游戏挂机场景弱 |
| [EtheriaHelper](https://github.com/idk505/EtheriaHelper) | 伊瑟 | pywinauto UIA + pydirectinput | 未完成，PC 端 only，无 ADB |

**判断**：对「手游/模拟器 + 图像识别 + 任务流水线」这一形态，MaaFramework 已是事实标准——
MAA 自己、ALAS、M7A、SRC 四个最强项目全部收敛到它上面。自研核心（BGI 路线）只在 PC 原生 3D 游戏（键鼠、自由视角、地图追踪）这种 MaaFramework 覆盖不好的场景才值得。

**伊瑟（Etheria: Restart）是 XD 的手游**，模拟器运行是自然路径，恰好落在 MaaFramework 最强的场景里。

---

## 2. 为什么 MaaFramework 正好解决 Etheria 的痛点

Etheria 审计出的痛点 vs MaaFramework 的现成能力：

| Etheria 痛点 | MaaFramework 对应能力 |
|---|---|
| 想接入模拟器 + ADB（≈重写全部截图/输入层） | **原生 ADB 控制器**：7 种截图方式自动赛马择优（MuMu 12 / 雷电 9 / AVD / 应用宝有 EmulatorExtras 极速无损直通），4 种输入方式按优先级自动选（EmulatorExtras > Maatouch > Minitouch > AdbShell） |
| 后台点击抢前台、遮挡截到遮挡物 | Win32 控制器 12 种输入（PostMessage 系 / WithCursorPos / **AnchoredTouch 合成触控**不抢焦点）× 6 种截图（FramePool/PrintWindow 支持后台 + 伪最小化），全都是 MAA 战斗验证过的 |
| 5 套重复识别实现、阈值散布 | 管线节点里声明 `recognition` + `threshold` + `roi`，一套实现 |
| zhuxian 手写扫描循环 = 原始 next 链 | 管线协议的 `next` / `on_error` / `timeout` / `[JumpBack]` / `anchor` 原生支持，还带可视化编辑器 [MaaPipelineEditor](https://mpe.codax.site/stable/) |
| 约 240 处 time.sleep 拍节奏 | `pre_delay` / `post_delay` / `pre_wait_freezes` / `post_wait_freezes`（等画面静止）/ `rate_limit`，节奏进数据 |
| 无重试/兜底，失败即 return | `timeout`（默认 20s）+ `on_error` 链 + `max_hit` 次数限制，框架统一处理 |
| 无失败现场、排查靠猜 | `save_on_error` 默认开启：任务失败自动存截图；`save_draw` 可存识别可视化结果 |
| 无模板缓存、15 尺度暴力匹配 | MaaFW 统一 720p 逻辑坐标系，内置识别缓存与批量优化 |
| EasyOCR 5 处初始化、400MB torch 打包 | 内置 PaddleOCR ONNX（官方 [MaaCommonAssets](https://github.com/MaaXYZ/MaaCommonAssets/tree/main/OCR) 现成中文模型），torch 依赖整体退役 |
| GUI 手写 25 个 run_xxx 包装 | `interface.json`（ProjectInterface V2 协议）声明任务列表，通用 UI（MFW-PyQt6 / MFAAvalonia）零 GUI 代码直接跑；自研前端也可读同一份协议 |

---

## 3. 目标架构

### 3.1 分层

```
┌────────────────────────────────────────────────────────────┐
│  前端层（三选一，可渐进）                                     │
│   A. MFW-PyQt6 / MFAAvalonia 通用 UI —— 零开发，读 interface.json │
│   B. 现有 Vue3 + pywebview 前端 —— 读 interface.json 生成任务面板， │
│      经 Python 绑定驱动 Tasker（保留"瑞玛丽"品牌 UI）           │
├────────────────────────────────────────────────────────────┤
│  编排层  Python (maa 绑定, pip install MaaFw)                 │
│   Toolkit 发现设备/窗口 → Tasker.bind_resource + bind_controller │
│   → post_task(入口名) → 消费回调（focus 消息/日志/进度）         │
├────────────────────────────────────────────────────────────┤
│  自定义逻辑层  AgentServer（独立进程，复杂逻辑逃生舱）           │
│   @AgentServer.custom_recognition：选牌 OCR 决策、RTA 先后手判定、 │
│     虚烬层数 OCR、体力数字识别…（现有 core/* 里的算法逻辑搬这里）  │
│   @AgentServer.custom_action：3D 走位按键序列、滚动找副本…       │
├────────────────────────────────────────────────────────────┤
│  游戏内容层（纯数据，零代码）                                  │
│   interface.json + resource/pipeline/*.json + resource/image/*  │
├────────────────────────────────────────────────────────────┤
│  核心引擎  MaaFramework (C++, 官方维护, 我们零维护)             │
│   识别: TemplateMatch/OCR/FeatureMatch/ColorMatch/NN/And/Or     │
│   控制: Adb 控制器(模拟器) | Win32 控制器(PC 客户端)             │
└────────────────────────────────────────────────────────────┘
```

### 3.2 仓库目录（参照 [MaaPracticeBoilerplate](https://github.com/MaaXYZ/MaaPracticeBoilerplate)）

```
EtheriaAssistant/
├── assets/
│   ├── interface.json          # 任务声明（通用 UI 与自研前端共用）
│   └── resource/
│       ├── default_pipeline.json   # 全局默认值(rate_limit/threshold/timeout)
│       ├── image/                  # 模板图（720p 标准裁剪）
│       │   ├── common/             #   公共：主界面/侧边栏/弹窗关闭
│       │   ├── daily/  trial/  event/  rta/
│       ├── model/ocr/              # PaddleOCR onnx（从 MaaCommonAssets 拷入）
│       └── pipeline/
│           ├── common/             #   返回主界面/关闭弹窗/领奖等公共子图
│           ├── daily/  trial/  event/  rta/
├── agent/                      # AgentServer（Python 自定义逻辑）
│   ├── main.py                 #   注册 + 启动
│   ├── recogs/                 #   自定义识别（OCR 决策类）
│   └── actions/                #   自定义动作（走位/滚动/连招类）
├── app/                        # 编排 + 前端桥（瘦身后的 ui/app.py）
├── frontend/                   # 现有 Vue3 前端（改造为读 interface.json）
└── core/                       # 【退役】迁移完成后删除
```

### 3.3 interface.json 骨架（示意，以 ProjectInterface V2 协议为准）

```jsonc
{
  "controller": ["Win32", "Adb"],
  "resource": ["assets/resource"],
  "task": [
    { "name": "智壳", "entry": "Daily_ZhiKe" },
    { "name": "源器", "entry": "Daily_YuanQi" },
    { "name": "主线推图", "entry": "Daily_ZhuXian",
      "option": { "target_stage": { "cases": [ {"name": "1-1"}, {"name": "2-5"} ] } } },
    { "name": "一键日常", "entry": "Daily_All" }
  ],
  "agent": { "child_exec": "{PROJECT_DIR}/agent/main.py", "identity": "etheria_agent" }
}
```

### 3.4 管线写法示例（把现有 Python 翻译成数据）

现有 `anlong_battle.py` 的「等图标→点前往→等战斗按钮→战斗」线性流：

```jsonc
{
  "Daily_All": { "next": [ "智能壳", "源器", "一键领取" ] },

  "智能壳": {
    "recognition": "TemplateMatch",
    "template": "daily/zhike_entry.png",
    "roi": [/* 主界面侧栏区域 */],
    "action": "Click",
    "next": [ "智壳选难度", "[JumpBack]智壳通用弹窗处理" ],
    "on_error": [ "公共_回主界面" ],
    "focus": { "display": "开始智壳" }
  },
  "智壳通用弹窗处理": {   // jump_back：处理完弹窗自动回到智壳主流程
    "recognition": "Or",
    "any_of": [
      { "recognition": "TemplateMatch", "template": "common/close_x.png" },
      { "recognition": "OCR", "expected": ["确定", "知道了"] }
    ],
    "action": "Click"
  }
}
```

原 `zhuxian_battle.py:363-532` 的优先级扫描链可直接映射为一条 next 列表；
`exit_battle` 的 35 处角落偏移点击收敛为一个公共节点。

### 3.5 AgentServer 示例（现有 Python 逻辑的安身之处）

```python
from maa.agent.agent_server import AgentServer

@AgentServer.custom_action("XuJin_Move")      # 虚烬 3D 走位（W/A/S/D + 视角）
class XuJinMove:
    def run(self, ctx, param):
        # 现 xujin_battle.py 的按键序列原样搬入，ctx.controller 提供输入能力
        ...

@AgentServer.custom_recognition("YuanWang_CardPick")  # 源网征令选牌 OCR 决策
class CardPick:
    def analyze(self, ctx, param):
        # 现 yuanwang_battle.py 的 OCR 优先级匹配逻辑
        return ctx.run_recognition(...)  # 命中框 or None
```

> 复杂逻辑进 Agent、简单流程进 JSON——这正是 M7A/ALAS 迁移后的分工方式。
> 通用 UI 会自动连接 Agent 进程，自研前端同样通过绑定接口注册。

---

## 4. 关键决策点

### 4.1 模拟器 vs PC 客户端（双控制器并行）

| | 模拟器 + ADB（推荐主路） | PC 客户端 + Win32（保留） |
|---|---|---|
| 截图 | 7 种自动赛马；MuMu 12/雷电 9 走 EmulatorExtras 极速无损 | FramePool/PrintWindow 后台截图 |
| 输入 | Minitouch/Maatouch 稳定后台 | PostMessage 系 / AnchoredTouch |
| 分辨率 | 模拟器设 1280×720，即 MaaFW 标准坐标系 | 窗口任意，MaaFW 内部归一到 720p |
| 稳定性 | 最高（MAA/ALAS/M7A 战斗验证） | 取决于游戏窗口实现（伊瑟 Unreal 窗口） |
| 打包 | 无需管理员 | 视方式可能需要 |

**建议**：interface.json 同时声明 `["Adb", "Win32"]`，用户选连接方式；管线完全一致（同一套 720p 模板），只需 UI 布局在两端一致（伊瑟手游/PC 端 UI 若有差异，差异部分用 `template` 数组多模板兜底）。

### 4.2 模板迁移

- MaaFW 标准是 **720p（1280×720）无损裁剪**；现有 `templates/` 是 960×540 裁剪。
- 960×540 × 4/3 = 1280×720，**整倍数关系**：可写脚本把 198 张旧模板批量放大 4/3 作为起步，跑通后用 [ImageCropper](https://github.com/MaaXYZ/MaaFramework/tree/main/tools/ImageCropper) 或 VSCode 插件（`nekosu.maa-support`，支持连接后截图裁剪）逐步重裁关键模板。
- 模板命名沿用现有分类（richang/shilian/huodong/rta → daily/trial/event/rta）。

### 4.3 前端取舍

- **验证期（Phase 0-1）**：直接用 MFW-PyQt6 通用 UI，零 GUI 开发，专注管线数据。
- **正式版**：二选一——
  - A. 保留 Vue3 + pywebview，前端读 `interface.json` 渲染任务面板，后端用 Python 绑定驱动 Tasker（保留现有品牌与交互投资，工作量约 1-2 周）；
  - B. 直接用 MFW-PyQt6 发行（M9A/M7A 的做法，零维护成本，但 UI 无品牌个性）。
- 推荐 A，因为现有前端只剩"任务面板 + 日志"职责，改造成本低，且日志推送可改用 Tasker 回调（替换现在的 evaluate_js 轮询）。

### 4.4 复杂功能归属

| 功能 | 归属 |
|---|---|
| 智壳/源器/潜能/公会/主线/暗笼/超能二十一 | 纯 JSON 管线 |
| 源网征令选牌、虚烬层数 OCR | Custom Recognition（现成 OCR 逻辑搬家） |
| 虚烬 3D 走位按键、滚动找副本 | Custom Action |
| RTA 先后手置信度判定、三阶段选人 | Custom Recognition + Action |
| 战斗自动化（若做自动战斗） | 先 JSON 轮询技能模板；不够再上 Custom / NN 分类（MaaFW 支持 YOLO ONNX 检测） |

---

## 5. 迁移路线

- **Phase 0：跑通骨架（1-2 天）**
  `pip install MaaFw` → 装模拟器（推荐 MuMu 12）设 720p → 按 Boilerplate 建目录 → 写 `interface.json` + 一条 3 节点管线（回主界面/点侧栏/点挑战）→ 通用 UI 跑通。验证 ADB 截图/点击链路。
- **Phase 1：移植最简单的一个日常（3-5 天）**
  选"暗笼激斗"（现有代码最线性）翻译成管线；模板批量放大 4/3 起步；验证 `on_error`、`[JumpBack]` 弹窗处理、失败存图。
- **Phase 2：批量迁移 + Agent（1-2 周）**
  逐功能翻译管线；把 OCR 决策类逻辑搬进 AgentServer；`default_pipeline.json` 收敛全局节奏参数；MFW-PyQt6 验收。
- **Phase 3：前端接线 + 旧代码退役（1 周）**
  Vue 前端改为读 interface.json + Tasker 回调日志；删 `core/`、`easyocr_models`、torch 钩子；重新设计打包（maafw 原生库 + 资源目录，告别 400MB 单文件）。

每个 Phase 结束项目都处于可发布状态（旧版 exe 仍可并行使用）。

## 6. 风险与对策

1. **伊瑟模拟器兼容性**：XD 手游在主流模拟器（MuMu 12 优先）运行待实测；若有反模拟器检测，回退 Win32 控制器路径（架构已预留双控制器）。
2. **模板 4/3 放大的识别精度**：插值放大模板可能略降鲁棒性 → Phase 1 起用 ImageCropper 重裁高频模板，Phase 2 全量替换。
3. **学习成本**：管线协议字段多（recognition 10 种 / action 20 种 / NodeAttr）→ 用 MaaPipelineEditor 可视化编辑 + VSCode 插件补全，协议文档已在 `tmp/maafw-docs/` 本地留档。
4. **账号风险**：不变。模拟点击性质与现在相同，但模拟器 ADB 路径的检测面与真机/PC 端不同，需观察。
5. **社区项目撞车**：EtheriaHelper（未完成、无 ADB）证明有需求但无强竞争；基于 MaaFW 反而可接入其生态（MaaHub 分发管线、MFW 通用 UI 免维护）。

---

## 7. 本地留档

- MaaFramework 协议文档（管线/快速开始/Custom&Agent/控制方式）：`tmp/maafw-docs/`
- MAA v6.1.1 核心源码分析：`docs/MAA-架构分析与Etheria升级路线.md`（其中的 Phase 0-4 自研移植路线**已被本文档取代**）
