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
| `codexc` | 接入/创建本目录的会话（无参数 = 接入模式） |
| `codexc codex <参数>` | `codexc codex -m o3 --search` → 本目录新开会话并携带 codex 参数 |
| `codexc resume --last` | 续跑最近一次 codex 会话 |
| `codexc resume <会话id>` | 续跑指定会话 |
| `codexc -t 10:00 "prompt"` | 10:00 定时发送（也支持 `+30m`） |
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
- `codexc-daily` 解析 `$CODEX_HOME/sessions/` 下的 JSONL rollout 文件定位最近会话；调度委托给 launchd（`com.codexc.daily`）。
- 随附 `tmux.conf` 通过 `sync-prefix2.sh` 把 `prefix` 键表镜像到 tmux 默认为空的 `prefix2` 表，两个前缀行为完全一致。

## 卸载

```bash
codexc-daily uninstall          # 移除 launchd 任务（如已安装）
rm ~/.codex/bin/codexc ~/.codex/bin/codexc-daily ~/.codex/bin/sync-prefix2.sh
rm -f ~/Library/LaunchAgents/com.codexc.daily.plist
```

`install.sh` 覆盖任何文件前都会备份（同名 `*.bak.<时间戳>`）。

## 许可

[MIT](LICENSE)
