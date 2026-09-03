# 工作仓库规范 — etheria-ai-assistant

> 本文档只存在于我自己的 fork / 本地（`local/dev` 分支），不向上游提 PR。
> 上游仓库：`WhiteFree22333/etheria-ai-assistant`（默认分支 `main`，注意**不是 master**）

## 1. 仓库布局

| Remote | 指向 | 用途 |
|---|---|---|
| `origin` | `github.com/Aki-zym/etheria-ai-assistant` | 我的 fork，推送自己的分支、PR 备份 |
| `upstream` | `github.com/WhiteFree22333/etheria-ai-assistant` | 上游，只读，只 fetch 不 push |

本地目录：`E:\projects\etheria assistant`（主工作区）。
认证走 `gh auth setup-git`（credential helper = gh，账号 Aki-zym）。

## 2. 分支模型

```
upstream/main ──► main（纯镜像，禁止提交，有 pre-commit 钩子拦截）
       │
       ├──► local/dev（自用集成分支：个人功能 + 自用修复，日常运行/打包用这个）
       │        ▲
       │        └── merge --no-ff（自用功能完成时收编）
       │
       └──► feat/xxx、fix/xxx（一个任务一个分支，从 main 切出，走 PR 到上游）
```

- **main**：只做 fast-forward 对齐 upstream，永远不产生自己的 commit。
- **local/dev**：我的自用版。不追求进上游的功能都堆在这里；定期 rebase 到最新 main 上。个人分支可以 force push（只有我一个人用它）。
- **feat/\*、fix/\***：准备贡献给上游的改动，**从 main 切出**（不从 local/dev，避免把自用功能混进 PR）。若该修复依赖自用功能，再考虑从 local/dev 切，并在 PR 描述里说明。

命名约定：`fix/<issue号>-<简述>`、`feat/<简述>`，如 `fix/12-arena-stop`。

## 3. 日常：修 issue → 提 PR

```bash
git up                                   # 同步上游（见 §5）
git checkout -b fix/12-xxx main          # 从 main 切任务分支
# ...开发、测试...
git add -p && git commit                 # commit 风格：中文一行式，参考上游（如「虚烬探索执行bug修复」），可带 (#12)
git push -u origin fix/12-xxx
gh pr create --repo WhiteFree22333/etheria-ai-assistant \
             --head Aki-zym:fix/12-xxx --base main
```

- review 中被要求改：直接追加 commit push，**不要** force（除非维护者要求 rebase）。
- 被要求 rebase：`git fetch upstream && git rebase upstream/main && git push --force-with-lease`。
- PR 合并后清理：

```bash
git up
git branch -d fix/12-xxx
git push origin --delete fix/12-xxx
```

## 4. 自用功能（不进上游）

```bash
git checkout local/dev
# ...直接开发提交...
# 想长期备份就推 fork：
git push origin local/dev                # rebase 过之后需要 --force-with-lease
```

## 5. 上游更新后怎么处理（`git up` 一条龙）

已配置别名 `git up` = fetch upstream → 切 main → `merge --ff-only` → push origin main。

```bash
git up                        # 1. main 对齐 upstream/main 并备份到 fork
git checkout local/dev
git rebase main               # 2. 自用分支变基到新 main（保持线性历史）
git push --force-with-lease origin local/dev   # 3. 远端备份（个人分支允许 force）
```

还在进行中的 PR 分支同理：`git rebase main` 后 `--force-with-lease` 推回。
若 rebase 冲突太多，可退回用 `git merge main`（local/dev 是个人分支，merge 也可接受，二选一保持一致即可）。

## 6. 多个 subagent 并行开发

原则：**每个并行任务一个独立 worktree（独立目录 + 独立分支），同一时刻一个目录只跑一个 agent。**

```bash
# 为主会话之外的任务开并行工作区
git worktree add ../etheria-fix12 -b fix/12-xxx main
git worktree add ../etheria-featA -b feat/xxx   main

# 完成后收编 + 清理
git checkout local/dev && git merge --no-ff fix/12-xxx
git worktree remove ../etheria-fix12
```

并行纪律：
1. agent 只在自己的 worktree 里干活，**禁止**在 worktree 里 checkout / rebase / push 共享分支（main、local/dev）。
2. 共享分支操作（`git up`、rebase local/dev、push、开 PR）统一由主会话串行执行。
3. 并行任务尽量改不同文件；会动同一文件的任务不要并行。
4. 每个 worktree 有独立的 `.env` / 运行时数据，互不干扰（需各自配置）。
5. Cindy / Claude Code 里可直接用 EnterWorktree 工具，会自动在 `.claude/worktrees/` 下建 worktree 并把会话切过去，退出用 ExitWorktree。

查看现状：`git worktree list`。

## 7. 使用版 vs 开发版

| 版本 | 来源 | 用途 |
|---|---|---|
| **稳定使用版** | 上游 [Releases](https://github.com/WhiteFree22333/etheria-ai-assistant/releases) 的 zip（exe） | 纯玩游戏用，跟随上游发版 |
| **自用开发版** | `local/dev` 检出 → `python ui/app.py` 直接跑，或 `python build.py` 打 exe | 带自己功能；dist/ 已 gitignore，不会误提交 |
| **固定快照（可选）** | `git worktree add ../etheria-stable v1.1.0` | 想钉在某个 tag 上长期跑时用 |

自用版想留版本标记：本地打 tag 如 `local/v1.1.0+myfeat1`（不必推远端）。

## 8. 环境与运行

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python ui/app.py
```

- 当前机器 Python 3.14；若 paddleocr / pyinstaller 等轮子不兼容，装个 3.11/3.12 的 venv。
- `.env` 按需从 `.env.example` 复制，**永远不提交**（.gitignore 已覆盖）。
- `easyocr_models/` 是 115MB 的已跟踪模型文件，不要本地改动它，也不要往里加东西。

## 9. 已就位的保护与工具

- pre-commit 钩子（`C:\Users\zym04\.githooks\pre-commit`，经 `core.hooksPath` 生效）：在 main 上提交会被拒绝。确需绕过：`git commit --no-verify`。
- `fetch.prune=true`：fetch 自动清理已删远端分支。
- `rebase.autoStash=true`：rebase 前自动 stash 未提交改动。
- `core.longpaths=true`：Windows 长路径支持。
- `git up`：一条命令同步上游。

## 10. 速查

```bash
git up                                  # 同步上游
git checkout -b fix/N-slug main         # 开任务分支
git push -u origin HEAD                 # 推当前分支
gh pr create --repo WhiteFree22333/etheria-ai-assistant --head Aki-zym:$(git branch --show-current)
git rebase main && git push --force-with-lease   # 变基后推回
git worktree add ../wt-x -b feat/x main          # 并行 worktree
```
