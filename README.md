# codexc

在 tmux 中运行 [Codex CLI](https://github.com/openai/codex)，并内置 429 限频/瞬时错误的自动 continue 看门狗。按目录自动分配 tmux 会话，跨设备（电脑 / 手机 SSH）无缝接续。

## 快速开始

```bash
./install.sh          # 软链到 ~/.codex/bin/codexc 和 ~/.tmux.conf
codexc                # 进入当前目录的会话（不存在则创建）
```

## 用法

```bash
codexc                        # 进入当前目录的 tmux 会话；会话名 = 目录名
codexc -n <名字>              # 显式会话名（同一目录开多个、或跨目录共用）
codexc resume --last          # 其余参数原样透传给 codex
codexc "do the task"          # 直接传 prompt
codexc ls                     # 列出所有 tmux 会话
codexc -h                     # 帮助
```

## 会话命名规则（重点）

- 会话名 = 当前目录名（`~/projects/api` → 会话 `api`）。
- **重名自动避让**：若 `api` 已被另一个目录占用，自动逐级加父目录名直到唯一（`api` → `a-api` → `x-a-api`）。同一目录再次进入时，能准确认回自己的会话。
- 会话名里的特殊字符（`.`、`:` 等）会被替换为 `-`。

## 原理

- `codexc` 在 tmux 会话里跑 `codex`，一个轻量 watcher 轮询 `~/.codex/logs_*.sqlite`。
- 检测到瞬时错误（429、retry limit、流断开等）时，自动向 TUI 输入 `continue` + Enter，等价于手动重试。
- 配额/订阅上限类错误（usage limit reached 等）**不会**自动 continue，需要人工处理。
- 会话持续运行，`C-a d` 脱离后 codex 继续在后台跑；任何设备 SSH 进来再 `codexc` 即可接回。

## 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `CODEXC_SESSION` | 显式指定会话名 | 自动按目录 |
| `CODEXC_MESSAGE` | 自动 continue 时输入的文本 | `continue` |
| `CODEXC_COOLDOWN` | 两次自动 continue 的最小间隔（秒） | `10` |
| `CODEXC_MAX_CONTINUES` | 单次会话最大自动 continue 次数 | `30` |
| `CODEXC_POLL` | watcher 轮询间隔（秒） | `2` |

## 配套的 tmux 配置（tmux.conf）

- `extended-keys on` + `csi-u`：让 Shift+Enter（codex 输入框换行）不被 tmux 折叠成 Enter。
- `mouse on`：滚轮滚动屏幕历史，不再变成 ↑ 键翻 codex 输入框历史。
- 前缀键改为 `Ctrl+a`（detach = `C-a d`；发真正的行首 `Ctrl+a` 需按两下 `C-a C-a`）。

## 依赖

`tmux`、`sqlite3`、`python3`、`codex` CLI。均为 macOS 常见环境自带/易装。

## 维护

- 修改 `codexc` / `tmux.conf` 后提交即可；软链用户自动同步（tmux 配置需 `tmux source-file ~/.tmux.conf` 或重开会话生效）。
- 安装前如有旧版真实文件，`install.sh` 会自动备份为 `.bak.<时间戳>`。
