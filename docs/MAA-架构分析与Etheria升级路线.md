# MAA v6.1.1 架构精读 与 Etheria Assistant 升级路线

> **2026-09-06 状态**：本文第七节的自研五期路线已被《Etheria升级总计划》（MaaFramework 引擎 + PC 客户端主线，模拟器封存待接入）取代；第一~六节保留为机制精读与素材库，继续有效。

> 依据：4 个并行分析报告（MAA C++ 核心源码 / MAA 功能实现层 / MAA 本地资源包 / Etheria 现状审计），
> 关键结论均经行号级核实。源码取自 GitHub v6.1.1 tag（本地克隆：`/tmp/maa-src-core`、`/tmp/maa-src-features`），
> 发布包参考：`C:\Users\zym04\Desktop\Tools\MAA-v6.1.1`（含 4407 张模板图、4843 个 JSON、12 个 ONNX）。
> 生成日期：2026-09-05。

---

## 一、MAA 总体架构：五层单向闭环

```
GUI(WPF) / Python(ctypes)          ← 宿主只见到「句柄 + JSON 字符串 + 回调」
   │  AsstCaller.cpp (C ABI, ~10 个函数)
   ▼
Assistant 实例层                    ← 每实例 3 线程: working(任务串行执行) / msg(回调外抛) / call(异步IO)
   │  append_task → start → working_proc FIFO
   ▼
Task 层                             ← InterfaceTask(PackageTask) 组合 ProcessTask + Plugin
   │  ProcessTask 状态机: 截图→识别→next 链跳转→action
   ▼
Vision 识别层                       ← PipelineAnalyzer 按序短路匹配 (MatchTemplate/OcrDetect/…)
   ▲
Controller 控制层                   ← 截图五通道赛马择优 + 触控注入, 统一 1280×720 逻辑坐标系
```

数据流单向：`append_task → working 线程执行 → ProcessTask 循环 → 回调外抛`。
宿主集成面极小：`load → create(callback) → connect → append_task×N → start → 消费回调 → stop`（`src/Python/asst/asst.py`）。

**对 Etheria 最重要的一课**：MAA 的 GUI 与引擎之间只有一个极薄的异步接口，
任务调度、状态、停止全部收敛在引擎内部单线程 Tasker 里——Etheria 目前恰好相反（调度逻辑散落在前端 TS + 25 个手写 API 包装里）。

---

## 二、核心循环精读（用户最关心的部分）

### 2.1 三层循环嵌套

```
AbstractTask::run()      外层  失败重试循环, m_retry_times 默认 20 (AbstractTask.h:84)
  └ PackageTask::run()   中继  顺序执行子任务, 子任务失败即整链失败 (PackageTask.cpp:6-38)
      └ ProcessTask::_run()   内层 —— 真正的「截图→识别→判断→行动」状态机

  while(true):                                        (ProcessTask.cpp:66-128)
    hit = find_first(to_be_recognized)                (:140-190)
      · 头节点是 JustReturn 算法 → 直接命中, 不截图    (:148-151)
      · 否则 ctrler->get_image() 截一帧               (:153)
      · PipelineAnalyzer 按 next 列表顺序短路匹配     (PipelineAnalyzer.cpp:15-57)
    命中 → run_task():                                (:235-333)
      maxTimes 超限→Runout → pre_delay → 执行 action
      → Status 记时间戳 → reduce_other_times → post_delay → sub 递归 → SubTaskCompleted
    to_be_recognized = hit->next          (Success)   (:103)
    to_be_recognized = hit->exceededNext  (Runout)    (:99)
    识别 20 轮落空 → on_error_next; 没有则整链失败     (:89-96, :369-371)
    Stop 动作 / need_exit → Interrupted → 正常结束    (:105-107)
    next 列表走空 → 正常结束                          (:116)
```

**关键认知：MAA 没有「等待超时」概念。** 一切"等画面出现"都用"重复识别若干次 × task_delay(500ms) 间隔"表达，
兜底统一走 `onErrorNext`。等待、超时、重试、容错全部被统一进同一个状态机语义。

### 2.2 识别层（Vision/）

| algorithm | 用法 | 要点 |
|---|---|---|
| MatchTemplate | 缺省且有 template 时启用 | `TM_CCOEFF_NORMED` + maskRange 掩码; templThreshold 默认 0.7, 可按 template 一一对应 |
| OcrDetect | 全包 395 处主力 | PPOCR det+rec; `ocrReplace` 正则归一化; `withoutDet` 只跑 rec 提速 |
| FeatureMatch | 仅 3 处 | SIFT/BRISK, 用于小图标; `count` 控制最少匹配对 |
| ColorMatch | colorScales 出现 77 次 | RGBCount 数色法, 免模板 |
| JustReturn | 705 处 | 无识别纯路由节点, 零截图成本 |

**性能三板斧**：
1. **ROI 缓存**——`cache=true` 任务首次命中的 rect 存入 Status, 之后识别范围收缩到上次命中框（`PipelineAnalyzer.cpp:70-85`）；
2. **JustReturn 短路**——纯流程节点不截图（`ProcessTask.cpp:148-151`）;
3. **神经网络按需惰性加载**——全包只有 3+1 个 ONNX（技能就绪分类/干员检测/部署朝向/肉鸽地图感知），按文件名懒建会话（`OnnxSessions.cpp:34-42`）。

### 2.3 控制层（Controller/）

- **截图五通道赛马**：连接时逐个试 RawByNc→RawWithGzip→Encode→MuMu→LD 并计时，择最快常驻，之后滚动统计耗时每 10 次回传（`AdbController.cpp:568-697, 744-778`）。
- **统一 1280×720 逻辑坐标系**：截图 resize 后识别，坐标 ×scale 回设备；模板/ROI 全库只做一套（`ControlScaleProxy.cpp:44-69`）。
- **拟人输入**：点击点在识别框内正态分布取样；adb swipe 的"划过头"bug 用回拉短滑补偿（`ControlScaleProxy.cpp:168-198`）。
- `get_image()` 最多重试 20 次，失败回传黑帧 + 回调（`Controller.cpp:335-380`）。

### 2.4 核心设计要点（10 条浓缩）

1. 声明式 pipeline + `@` 继承 + baseTask，业务扩展零 C++ 代码；
2. `next / exceededNext / onErrorNext` 三张后继表 + exec_times 构成显式状态机；
3. 识别与行动解耦：识别器只产出 rect/score/text，行动收敛为 click/swipe/input 原语；
4. JustReturn 短路 + ROI 缓存 = 识别性能的两大杠杆；
5. 截图通道运行时赛马择优并持续统计；
6. 统一 720p 逻辑坐标系，多分辨率适配只做一次；
7. 拟人化输入（正态分布点击、滑动补偿）；
8. 无单步超时——重试 ×500ms 表达等待，onErrorNext 兜底，协作式停止（need_exit）；
9. 单执行线程 + 独立消息线程，任务 FIFO 串行、回调异步解耦；
10. C ABI + JSON + 回调的极简集成面。

---

## 三、声明式管线设计（最值得移植的部分）

### 3.1 任务 Schema（注意：MAA 用自己的字段名，非 MaaFramework 命名）

```jsonc
{
  "任务名": {
    "algorithm": "MatchTemplate | OcrDetect | FeatureMatch | ColorMatch | JustReturn",
    "template": "xx.png",              // MatchTemplate 用
    "templThreshold": 0.7,             // 可传数组与 template 一一对应
    "text": ["开启时间"],               // OcrDetect 用; 空数组=任意文本
    "ocrReplace": [[regex, repl]],     // OCR 结果归一化
    "colorScales": [[64,96]],          // ColorMatch 用
    "roi": [243, 598, 147, 122],       // 基于 1280×720; x/y 可负 = 右/底边锚定
    "cache": true,                     // 首次命中锁定 roi
    "action": "ClickSelf | ClickRect | Swipe | DoNothing | Stop",
    "specificRect": [x,y,w,h],         // ClickRect/Swipe 起点; rectMove 终点
    "specialParams": [duration, ...],  // Swipe: 时长/额外滑动/缓入/缓出
    "preDelay": 0, "postDelay": 500,   // 动作前后等待 ms
    "next": ["候选1", "候选2"],         // 状态机主干: 按序识别, 命中即转入
    "sub": ["前置子任务"],              // 独立 ProcessTask, 先于本任务执行
    "maxTimes": 20,                    // 默认无限
    "exceededNext": ["..."],           // 次数耗尽出口
    "onErrorNext": ["..."],            // 执行异常兜底
    "reduceOtherTimes": ["其他任务"],   // 命中时扣减他任务计数(防重复统计)
    "baseTask": "可复用基任务名"        // 字段级继承后再覆写
  }
}
```

全包实际只用 5 种 action（ClickSelf 748 / ClickRect 166 / Swipe 50 / DoNothing 87 / Stop 12）——**动作空间极小，识别空间极大**。

### 3.2 任务图组织

- **文件拆分**：`tasks/` 下 tasks.json(938 任务) + Copilot/ + MiniGame/ + RA/ + Roguelike/(base.json 270 任务公共底座) + Stages/(一活动一文件，45 个) + UiTheme/。合并进全局扁平命名空间，跨文件直接引用。
- **`A@B` 三层机制**：① B 未显式定义时以 B 为模板派生，next 自动加 `A@` 前缀展开；② 模板图查找优先 `A@B.png` 回落 `B.png`（6 职业变体就这么实现）；③ `#next`/`#self` 动态拼接符。
- **baseTask 继承**：8 个四方向 Swipe 手势做成标准件，子任务只覆写 postDelay/maxTimes/exceededNext（927 处使用）。
- **虚拟节点**：JustReturn + next 纯路由（Block/CloseAnnos/ReturnButtons）。
- **Hijack 钩子**：`RoguelikeCustom-Hijack*` 命名约定——资源只给识别锚点，运行逻辑由代码侧插件接管（JSON 表达力不够时的逃生门）。

### 3.3 资源与增量覆盖

- 模板图命名与任务名**严格镜像**（`SwitchTheme@ToggleSettingsMenu ↔ SwitchTheme@ToggleSettingsMenu.png`），运行时按文件名递归查找；
- `global/`（四服差异）与 `platform_diff/iOS/`（22 个任务纯阈值/roi 微调）都是**只放 diff 的增量覆盖包**，加载时主资源 + incremental 两层合并；
- `stages.json / recruitment.json / battle_data.json / item_index.json` 是识别结果的语义字典。

### 3.4 可观测性闭环（debug/ 目录）

运行期按模块分桶落盘原始截图：drops/recruit/oper/infrast/roguelike…，
其中 `skill_ready/{y,n,c}` 是分类器**正/负样本回收目录**——线上识别失败即落盘，回流训练 ONNX 模型。
「识别失败可复现 + 数据闭环」的完整工程实践。

---

## 四、功能层模式（哪些可抄，哪些不适用）

| 功能 | 实现模式 | 对 Etheria 可借鉴度 |
|---|---|---|
| 领奖励 Award | 纯 JSON 六条子链，零 C++ | ★★★★★ 直接照抄模式 |
| 关卡导航 StageNavigation | 名称正则解析→进章节页→**运行时改写 OCR 任务文本**→边滑动边 OCR | ★★★★★ Etheria 新关卡零代码的钥匙 |
| 作战 Fight | PackageTask 四段式 + 插件(连战/吃药/碎石/掉落)；「以重试表达等待」 | ★★★★ 掉落统计/消耗品管理可抄 |
| 基建 Infrast | 通用换班算法 + 效率公式表达式求值 + 选人复核 | ★★ 方舟专用逻辑为主 |
| 肉鸽 Roguelike | 单 ProcessTask + ~30 插件；主题差异全下沉数据 + set_task_base 热替换 | ★★★★ 状态机+插件架构可抄 |
| 抄作业 Copilot | 声明式 action 序列 + 条件等待(kills/costs/cost_changes) + groups 干员组 + skill_usage | ★★★★★ 可做成伊瑟「打法文件」 |
| 战斗底座 BattleHelper | 部署栏识别/头像缓存/帧差分读数/技能就绪检测/地形权重评分选落点 | ★★★★ RTA/超能二十一直接受益 |

**明日方舟专用**（不移植）：TileCalc 等距投影、理智/碎石/剿灭经济逻辑、基建效率公式、各肉鸽主题机制。

---

## 五、脚本记录体系（作业/配置）

- **作业 JSON 三协议**：通用作战（opers/groups/actions）、SSS 保全派驻（stages/strategies/tool_men）、肉鸽 autopilot（deploy_plan/replacement_home）+ 各主题 encounter/shopping/recruitment 数据文件——**肉鸽知识库全部外置成数据**。
- **用户配置**：`gui.json` 扁平点号键 + 多 profile + Global；新版 `gui.new.json` 收敛为 `$type` 多态强类型任务队列。
- **Python API 面**：`Asst.load(path, incremental_path, user_dir) → connect → append_task(type,params) → set_task_params(id,params) → start/stop → 回调消费`。

---

## 六、Etheria 现状对照

现状审计要点（详见 etheria worker 完整报告）：

- **架构**：pywebview 单进程；GUI 25 个手写 `run_xxx` 绕过 `core/tasks.py` 注册表；调度顺序硬编码在前端 TS；
- **执行**：两种风格并存（线性脚本流 / 反应式扫描循环），无统一主循环、无状态机、无重试框架；约 240 处 `time.sleep`；
- **识别**：5 套重复实现；模板无缓存每次磁盘 imread；15 尺度全屏暴力匹配；阈值 0.7~0.88 内联散布；
- **输入**：三种并存（PostMessage / SendInput+BlockInput / pyautogui），跑任务时用户无法用电脑；
- **状态**：零持久化——无断点续跑、无运行历史、无失败截图归档；错误靠字符串魔法标记跨语言传播；
- **工程**：spec 硬编码绝对路径、`.env` 打进发行包、OCR 初始化复制 5 份；
- **已有的好底子**：zhuxian 的优先级扫描链 ≈ 手写 next 链；TemplateCapture 一键截模板 ≈ 管线维护工具雏形；四路截图 ≈ 截图赛马的粗糙版。

| 维度 | 现状 | MAA 式目标 | 差距 |
|---|---|---|---|
| 识别 | 5 套原语、无缓存、全屏匹配 | 统一 Recognizer + ROI 缓存 + 参数进配置 | ★★★★★ |
| 管线 | 流程=Python 代码 | 声明式 JSON（next/exceededNext/onErrorNext） | ★★★★★ |
| 调度 | 前端编排 + 双路径分裂 | 单线程 Tasker + 消息回调 | ★★★★★ |
| 导航 | 每任务手写入口链 | 通用导航节点全任务复用 | ★★★★ |
| 容错 | fail-fast，无重试 | 重试表达等待 + onErrorNext + 协作式停止 | ★★★★ |
| 可观测 | 字符串日志+魔法标记 | 结构化回调 + 失败落盘 + 样本回流 | ★★★★ |
| 配置 | dataclass + .env 6 项 | 注册表自动生成 GUI/CLI + 增量覆盖 | ★★★ |

---

## 七、升级路线图（建议分五期，每期独立可交付）

### Phase 0 — 工程止血（半天）
- 修 `YiseAssistant.spec`：去掉硬编码绝对路径、从发行包剔除 `.env`；
- 删除根目录 `_fix_spec*.py` 一次性补丁，收编进构建流程；
- 版本号三处统一（core/__init__ / 窗口标题 / zip 名）。

### Phase 1 — 识别层收敛（2-3 天）
- 新建 `core/_base/recognizer.py`：统一 Recognizer 抽象（Template/OCR/Color/Custom 四类，带 roi/threshold/多目标 NMS）；
- **模板缓存**（首次 imread 后驻内存）+ **单尺度匹配**（窗口锁定 960×540 后 15 尺度循环直接砍掉，保留多尺度作为可选降级）；
- 五套等待原语收敛为一个 `wait_for(recognizer, timeout)`，超时语义改为「重试 N 次 × interval」，对齐 MAA；
- 顺手消灭 5 处 OCR 初始化复制（改为单例）。

### Phase 2 — Tasker + 声明式管线（核心，1-2 周）
- 新建 `core/tasker.py`：单执行线程 + FIFO 任务队列 + 结构化回调（task_id/stage/event/detail），对齐 Assistant.cpp 模型；
- 新建 `core/pipeline.py`：ProcessTask 等价物——加载 `resource/pipeline/*.json`，实现 `next 按序识别 / maxTimes+exceededNext / sub 前置 / onErrorNext 兜底 / baseTask 继承 / #next #self 符号` 六件套；
- 资源目录：`resource/pipeline/base.json`（返回/弹窗/加载通用导航）→ `<功能>.json` → `stages/<关卡组>.json`；模板图与任务名镜像；
- 建 `interface.json` 式任务注册表，GUI 面板与 CLI 子命令由注册表自动生成，删除 25 个手写 `run_xxx` 与前端调度；
- 迁移顺序：先迁最线性的任务（暗笼）验证执行器，再迁 zhuxian（其扫描链逐条翻译成 next 链）。

### Phase 3 — 导航器 + 容错 + 可观测（1 周）
- StageNavigation 式导航器：关卡名/副本名 → 解析 → 通用入口链 → 运行时改写 OCR text，全任务复用；
- 可中断等待（等待原语内嵌停止检查，替代散落 40 处的旗标轮询）；
- 结构化日志落盘 + 失败自动存帧（按模块分桶 debug/ 目录，对齐 MAA 闭环）；
- 任务进度持久化（json 状态文件），支持断点续跑与运行历史。

### Phase 4 — 进阶能力（按需）
- Copilot 式「打法文件」：声明式 action 序列 + 条件等待（kills/costs），先服务 RTA 与超能二十一；
- 掉落/收益统计 + 外部上报；
- 资源热更新（cache/ 增量 tasks.json + etag 缓存，两层合并加载）；
- 识别失败样本回流目录（y/n/c），为后续上分类模型攒数据；
- Controller 输入后端可插拔，尽量纯 PostMessage，缩小 BlockInput 劫持范围。

### 风险与逃生舱
- 虚烬 3D 走位、源网选牌这类复杂逻辑保留 **Custom 节点**（等价 MAA Hijack 钩子）直通 Python 函数；
- 前端迁移到「注册表驱动渲染 + 订阅回调事件」后，再拆除 evaluate_js 轮询队列；
- 960×540 分辨率约定暂保留（模板已全按此截取），Phase 1 的 Recognizer 预留归一化 roi 接口，多分辨率支持放后期。

---

## 八、一页速查：MAA 机制 → Etheria 落点

| MAA 机制 | 源码锚点 | Etheria 落点 |
|---|---|---|
| ProcessTask 状态机 | Task/ProcessTask.cpp:66-128 | `core/pipeline.py`（新建） |
| Tasker 单线程+回调 | Assistant.cpp:420-510 | `core/tasker.py`（新建） |
| ROI 缓存 | PipelineAnalyzer.cpp:70-85 | recognizer.py 的 cache 字段 |
| JustReturn 短路 | ProcessTask.cpp:148-151 | pipeline 纯路由节点 |
| @ 继承 + baseTask | Config/TaskData.cpp:364-428 | pipeline 加载器 |
| 截图赛马 | AdbController.cpp:568-697 | capture.py 升级：实测计时择优 |
| 统一逻辑坐标系 | ControlScaleProxy.cpp:44-69 | 暂保 960×540，预留 scale 接口 |
| StageNavigation | Task/Fight/StageNavigationTask.cpp:11-121 | `core/navigator.py`（新建） |
| Copilot 作业 | Task/Miscellaneous/BattleProcessTask.cpp | Phase 4 打法文件 |
| debug 落盘闭环 | Task/Fight/StageDropsTaskPlugin.cpp 等失败路径 | Phase 3 失败存帧 + 样本回流 |
