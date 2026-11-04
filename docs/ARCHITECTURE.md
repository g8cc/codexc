# 架构（Architecture）

CodingKeeper = 编码 Agent 的无人值守运行时。核心命题: **智能全部在 Agent 内，机械全部在 Keeper 内，且机械层零智能**（bash + tmux + 退出码），因此可审查、可测试、不会被上游 Agent 的快速迭代碾掉。

## 两条驱动通道

| 通道 | 入口 | 驱动方式 | 适用 |
|---|---|---|---|
| TUI | `ck codex` / `ck claude` / `ck opencode` / `ck pi` | tmux 会话 + 按键投喂 + 屏幕特征判忙闲 + watcher 错误续命 | 有终端 TUI 的工具 |
| headless | `ck zcode run` / `ck dsh run`（经 codexc-headless） | 每任务一次阻塞子进程（`CODEXC_HEADLESS_CMD`），stdin 进任务、stdout 出结论 | 只有程序化接口的工具 |

两条通道的项目文件与验收管线**完全一致**，可互换。

## 共享验收管线（acceptance pipeline）

```
queue.md(## ready) → 投喂 → worker 回合 → gate.sh(真实退出码)
  → 独立审查(codex exec, 跨模型, 双零收敛) → journal → 队列勾选
```

- gate 失败: 输出回灌修复（上限 3）；审查出 bug: 回灌修复、收敛清零（上限 6 轮）。
- 一切无法判定的情况 **park**（写 loop.halt + 系统通知），绝不带病续跑。

## 设计不变量（改代码前必读）

1. 验收只认真实证据: gate 退出码 + 独立审查 BUGS 行；worker 自述不算数。
2. 失败方向是 park: 无法判定即挂起等人，绝不虚假验收。
3. 完成事件一次性消费: 水位 + 活动门 + 新鲜度令牌三层防陈旧误收。
4. 每层都有上限: 续命 30 / gate 3 / 审查 6 / 空转 2 / 回合 3600s / 审查 1800s。
5. 外环零智能: 不做任何"聪明"的推断，机械规则全部可测试。
6. **keeper 自医必带回归锁**: 修 keeper 自身的 bug 必须附对应回归测试（selftest/conformance
   相应套件），无测试不入库（pre-commit 强制）；测试不可达的层（真 TTY 交互/浏览器 API）
   列入人工冒烟清单并由控制器执行记录。看门狗 (burn-watch.sh) 入库受同一门禁管辖,
   修改部署铁律: 先杀运行实例再改文件 (bash 增量读, 教训 ×3)。

## 状态目录

项目级状态统一在 **`.codingkeeper/`**（队列/门禁/台账/停炉标记/会话接力文件），
与 worker 无关——同一项目换任何 worker，队列与台账延续。v2.0 起自动迁移：
旧 `.codexc/` 在 runner 启动时一次性 `mv` 为 `.codingkeeper/`（journal/queue 无损）。
全局日志: `~/.codex/codexc-watch.log`（计划 v2.1 迁往 `~/.codingkeeper/`）。

## 工具适配面（加新工具时只动这里）

| 适配点 | TUI 通道 | headless 通道 |
|---|---|---|
| 启动 flags / 信任门预种 | codexc 内 profile | 无（headless 无弹窗） |
| 会话发现与回合解析 | codexc-loop `find_rollout_*` / `turn_status_*` | worker 适配器（会话接力） |
| 忙/闲标记 | codexc-loop `pane_busy` | 无（子进程退出即完成） |
| 错误源（watcher） | codexc 内 `watch_and_run_*` | 子进程 stdout/exit code |

现有实现: codex(sqlite→rollout尾)、claude(JSONL isApiErrorMessage)、pi(stopReason)、
opencode(session_v2/message 表)、zcode(--prompt/--resume, 会话文件)、dsh(--session-id, zstd 存储)。
