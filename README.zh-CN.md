# codexc

[English](README.md) | 中文

让 [Codex CLI](https://developers.openai.com/codex/) 在你不在时也能继续跑。

`codexc` 把 codex 装进按项目划分的 tmux 会话里，并补上原生 codex 缺的三件事：

1. **自动 continue 看门狗** — 回合因瞬时错误挂掉时（429 限流、流断开、5xx、网络抖动），自动替你输入 `continue`，任务从断点继续。配额类错误会被识别并**故意不**自动续。
2. **定时与每日执行** — `codexc -t 10:00` 定时发 prompt；`codexc-daily install 10:00` 注册每日任务，每天早上自动续跑最近的会话——重启过电脑也行——但你在电脑前时会礼貌跳过。
3. **自动 Yes** — 用官方全自动参数启动 codex，并预信任工作目录，无人值守时不会被审批弹窗卡住。

> 仅支持 macOS（依赖 launchd、osascript、BSD 工具链）。

## 环境要求

- macOS
- [tmux](https://github.com/tmux/tmux) ≥ 3.5（CSI-u 扩展键需要）、`sqlite3`、`python3`
- [Codex CLI](https://developers.openai.com/codex/)（`npm i -g @openai/codex`）且已登录

## 快速开始

```bash
git clone https://github.com/g8cc/codexc.git
cd codexc
./install.sh            # 软链脚本到 ~/.codex/bin
exec $SHELL             # ~/.codex/bin 尚不在 PATH 时重载

cd ~/projects/myapp
codexc                  # 在以本目录命名的 tmux 会话里打开 codex
```

`Ctrl-a` `d` 脱离（codex 继续后台跑），再敲 `codexc` 接回来。纯 SSH 环境下所有命令同样可用。

## 用法

| 命令 | 作用 |
|---|---|
| `ck <tool> [args]` | 统一入口：`ck codex` / `ck claude` / `ck pi` / `ck opencode` / `ck zcode` / `ck dsh` |
| `ck status` | 跨项目总览 |
| `ck fuel [tool]` | 燃料表 |
| `codexc` | 兼容别名，等同 `ck codex` |
| `codexc` | 接入/创建本目录的会话 — 默认装配交付循环（首次运行自动生成 `.codingkeeper/`） |
| `codexc --no-loop` | 不带循环的裸会话 |
| `codexc codex <参数>` | `codexc codex -m o3 --search` → 本目录新开会话并携带 codex 参数 |
| `codexc resume --last` | 续跑最近一次 codex 会话 |
| `codexc resume <会话id>` | 续跑指定会话 |
| `codexc -t 10:00 "prompt"` | 10:00 定时发送（也支持 `+30m`） |
| `codexc loop` | 同 `codexc`（保留写法，显式表达） |
| `codexc fuel [codex\|claude]` | 锅炉燃料表：当前 provider、换煤队列、今日/本月消耗、中转错误 |
| `codexc -T claude` | 驱动 **Claude Code**（循环/门禁/审查完全一致） |
| `codexc -T opencode` | 驱动 **opencode**（同一管线；会话从 opencode.db 读取） |
| `zcodec` | 在 headless 通道驱动 **ZCode 的 CLI**：每任务一次阻塞回合（`zcode --prompt --mode yolo`），会话接力持久化到 `.codingkeeper/zcode-session-id`。需 `zcodec init` + gate.sh；需 Node >= 24 与桌面应用自带的 `zcode.cjs`（自动探测） |
| `ck status` | **跨项目总览**：所有已登记项目的燃烧/挂起/队列/最近验收 |
| `ck fuel [tool]` | `codexc fuel` 的简写 |
| `codexc -T pi` | 驱动 **pi**（同一管线；429 续命基于 `stopReason: "error"`） |
| `codexc-daily install 10:00` | 每天 10:00 自动续跑（launchd） |
| `codexc-daily` | 立即手动执行一次每日流程 |
| `codexc-daily pause` / `resume` | 暂停 / 恢复每日任务 |
| `codexc-daily status` / `uninstall` | 查看状态 / 移除注册 |

### 会话命名规则

每个工作目录一个 tmux 会话：取目录 basename，重名时逐级加父目录名，仍冲突则加 `-2`/`-3` 后缀。脱离 = 后台继续；pane 内命令退出则会话自然销毁。

## 自动 continue 规则

看门狗轮询 Codex 的 `logs_*.sqlite` 错误记录（大小写不敏感），对连续发送执行冷却间隔（默认 10 秒），并短暂等待 TUI 稳定后发送 `continue` + Enter。内置模式覆盖 429 限流、"server error"、"stream error"、overloaded、connection reset、fetch failed、超时等。**默认累计自动 continue 30 次**后暂停并通知；可用 `CODEXC_MAX_CONTINUES` 调整上限（`0` 禁用自动重试）。

两道保险：

- **配额墙永不自动续**。"usage limit"、"upgrade to"、"subscription"、"plan limit" 在黑名单里，且**优先于**其他一切匹配检查。
- **自定义模式**。`~/.codex/codexc.patterns` 每行一条正则；临时用可设 `CODEXC_EXTRA_RE`。

## 定时与每日任务

`codexc -t 10:00 "continue"` 在 10:00 向活跃会话发送 prompt（会话不在则冷启动）；一次性。重复性调度交给 codexc-daily。

`codexc-daily` 是**兜底而不是打断**。到点后：

- 找到最近一次 codex 会话的工作目录（rollout 文件的 `session_meta.cwd`）；
- 该目录的 tmux 会话还活着 — 等待空闲（回合在跑最多等 60 秒），然后发送 `continue`；
- 会话已不在 — 在原目录冷启动 `codexc resume --last continue`，看门狗同时武装；
- **若最近一次回合正常收尾（rollout 里的 `task_complete`）—— 整体跳过并通知**，不给已完成的任务发无意义的 continue；
- **若最近 30 分钟内你用过电脑（键鼠）— 跳过并通知**（阈值 `CODEXC_DAILY_IDLE`，分钟；`0` 关闭检查）；暂停状态下不执行。

## 无人值守交付循环（codexc-loop）

`codexc loop` 启动带监督交付管线的会话：任务逐条投喂，且必须先通过真实测试、再通过连续两轮零 bug 的独立审查才算完成。

```bash
codexc loop          # 启动循环 — 首次运行自动初始化 .codingkeeper/
                     # (从 uv/pytest/package.json/go/Cargo/Flutter/Makefile
                     #  探测测试命令; 生成的 gate.sh 请核对)
codexc-loop init     # 显式初始化（内容相同, 用于脚本化场景）
```

- `.codingkeeper/queue.md` — `## ready` 分区的任务从上往下自动投喂；codex 自评产生的后续任务写入 `## review-needed`，未经你确认不会执行；完成会被勾进 `## done`。
- `.codingkeeper/gate.sh` — 项目真实的测试命令。外环在 shell 里运行它、只认退出码；失败会把输出回灌给 codex 修复（次数受 `CODEXC_GATE_RETRIES` 限制）。
- 每个完成的任务由独立的只读 `codex exec --ephemeral` 审查上下文。连续 `CODEXC_REVIEW_PASS`（默认 2）次零 bug 才算通过；发现 bug 就回灌修复。重试耗尽会挂起循环（`touch .codingkeeper/loop.halt` 暂停，`rm` 恢复）并发通知。
- `CODEXC_LOOP_DRY=1 codexc loop` — 只记录动作、不触碰 TUI 的安全试跑。
- **桌面面板**：两个 runner 每次状态变化即发布 `status.json`；菜单栏应用（`desktop/CodingKeeperBar.swift`，install 自动编译）一屏显示所有项目的任务与挂起状态。**burn 模式（默认开启）**：队列烧干后，循环自动投喂持续改进指令——先按 worker 自己说的下一步做，否则做一轮专业收尾审查（正确性、安全、性能、可靠、鲁棒/边界、可维护、测试完整性、依赖健康、可观测、文档一致性），发现问题小步提交修复。worker 连续两轮报告无事可做，锅炉自动熄火并通知你。`CODEXC_LOOP_IDLE=0` 关闭；其他值替换内置指令；`CODEXC_IDLE_PARK` 调整空转上限。
- 工具说明：`codexc-daily` 的冷启动仅支持 codex。Claude 的续命基于会话 JSONL（`isApiErrorMessage`）；pi 基于 `stopReason: "error"`；opencode 基于 `opencode.db` 中的错误 assistant 行。审查始终用 codex，保证评分者与实现者不是同一个模型。没有终端 TUI 的工具走 **headless 通道**：`codexc-headless` 每任务一次阻塞子进程，队列/gate/审查/burn 语义完全一致。`zcodec` 就是以这种方式桥接 ZCode CLI 的；`dsh --profile headless` 配好凭证后同理（`CODEXC_HEADLESS_CMD="dsh --profile headless --session-id night -" codexc-headless run`）。

## 自动 Yes

| `CODEXC_AUTO_YES` | 行为 |
|---|---|
| `1`（默认） | 全自动：官方 `--dangerously-bypass-approvals-and-sandbox`，并在 codex 配置里预信任目录，首次"是否信任此目录"不再出现 |
| `2` | 跳过审批弹窗但保留工作区沙箱（`-a never -s workspace-write`） |
| `0` | 关闭，恢复 codex 原生确认行为 |

你显式传的参数（`-a`、`-s`、`--full-auto` 等）永远不会被覆盖。bypass 用的是 codex 官方参数，不是截屏模拟按键。**注意权衡**：模式 `1` 允许 codex 在你机器上不经审批执行命令——这正是无人值守运行的意义，前提是你信任自己的任务且有备份。

## tmux 快捷键（随附配置）

| 按键 | 作用 |
|---|---|
| `Ctrl-a` `d` | 脱离 — codex 继续跑 |
| `Ctrl-b` `d` | 同上（第二前缀键，键表完全同步） |
| `Ctrl-a` `Ctrl-a` | 向程序发送真正的 `Ctrl-a`（shell 里跳行首） |
| `Ctrl-b` `Ctrl-b` | 向程序发送真正的 `Ctrl-b` |

随附配置还让 tmux 区分 `Shift+Enter` 与 `Enter`（codex 输入框：换行 vs 发送），并支持滚轮滚动 pane 历史。

## 环境变量

| 变量 | 含义 | 默认 |
|---|---|---|
| `CODEXC_SESSION` | 覆盖 tmux 会话名 | 按目录命名 |
| `CODEXC_HOME` | codex 主目录 | `~/.codex` |
| `CODEXC_MESSAGE` | codexc-daily 到点发送的文本 | `continue` |
| `CODEXC_AT` | 定时规格（同 `-t`） | — |
| `CODEXC_EXTRA_RE` | 追加的自动 continue 正则（与内置取 OR） | — |
| `CODEXC_AUTO_YES` | `1` 全自动 / `2` 保留沙箱 / `0` 关闭 | `1` |
| `CODEXC_DAILY_IDLE` | 每日任务空闲阈值（分钟），`0` 关闭（范围 `0`–`10080`） | `30` |

## 工作原理

- `codexc` 创建/接入 tmux，注入 codex 参数与自愈重试配置，并启动后台看门狗轮询 Codex SQLite 错误日志；同时检查 pane，避免在回合运行时输入。
- `codexc-daily` 解析 `$CODEX_HOME/sessions/` 下的 JSONL rollout 文件定位最近会话；调度委托给 launchd（`com.codingkeeper.daily`）。
- 随附 `tmux.conf` 通过 `sync-prefix2.sh` 把 `prefix` 键表镜像到 tmux 默认为空的 `prefix2` 表，两个前缀行为完全一致。

- [处理逻辑手册](docs/OPERATIONS.md) · [架构与不变量](docs/ARCHITECTURE.md) · [工具矩阵与凭证](docs/TOOLS.md) · [商业化路线](docs/COMMERCIALIZATION.md) · [Changelog](CHANGELOG.md)

## 卸载

```bash
codexc-daily uninstall          # 移除 launchd 任务（如已安装）
rm ~/.codex/bin/codexc ~/.codex/bin/claudec ~/.codex/bin/opencodec ~/.codex/bin/pic ~/.codex/bin/codexc-headless ~/.codex/bin/codexc-zcode-worker ~/.codex/bin/codexc-dsh-worker ~/.codex/bin/zcodec ~/.codex/bin/dshc ~/.codex/bin/codexc-daily ~/.codex/bin/codexc-loop ~/.codex/bin/sync-prefix2.sh
rm -f ~/Library/LaunchAgents/com.codingkeeper.daily.plist
```

`install.sh` 覆盖任何文件前都会备份（同名 `*.bak.<时间戳>`）。

## 许可

[MIT](LICENSE)
