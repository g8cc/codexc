# codexc 处理逻辑手册（遇到什么情况，怎么处理）

> 面向使用者与维护者的完整行为手册。架构: **CodingKeeper** —— 编码 Agent 的无人值守运行时，
> 两条驱动通道（TUI 投喂 / headless 子进程）共享同一套验收管线。

## 一、总览：两条通道，一套验收

```
                       ┌──────────── 验收管线（共用） ────────────┐
队列 .codingkeeper/queue.md  │  worker 回合 → gate.sh(真实退出码)        │
   │ 逐条投喂           │  → 独立审查(codex exec, 跨模型, 双零收敛) │
   ▼                   │  → journal 落账 → 队列勾选               │
worker(codex/claude/   └──────────────────────────────────────────┘
pi/opencode = TUI 通道;  zcode/dsh = headless 通道)
```

- **TUI 通道**（`ck codex`/`ck claude`/`ck opencode`/`ck pi`）：tmux 会话 + 按键投喂，
  watcher 盯错误自动续命；适用于有终端界面的工具。
- **headless 通道**（`ck zcode run`/`ck dsh run`，产品入口 `zcodec`/`dshc`，经 `codexc-headless`）：每任务一次阻塞子进程，
  worker 命令经 `CODEXC_HEADLESS_CMD` 注入；无界面、无弹窗、硬超时兜底。

两条通道的项目文件完全一致（`.codingkeeper/queue.md`、`.codingkeeper/gate.sh`、
`.codingkeeper/journal`、`.codingkeeper/loop.halt`），随时可换通道。

## 二、核心状态机

```
idle(队列取任务) ──投喂──▶ task(work → gate → review) ──双零──▶ 验收(勾选+journal)
   ▲                        │                                    │
   │                        │ gate 连续失败 / 审查出 bug 回灌      │
   │                        ▼ (回灌后回 work, 计数清零)           │
   └──── 队列空 + burn 开 ──▶ 空闲投喂(持续改进指令) ◀────────────┘
                                │ 连续 2 轮无事可做 (idle 标记+git 干净)
                                ▼
                             park(挂起): 写 loop.halt + 系统通知 → 等人
```

任何 park 都可以复燃：`rm .codingkeeper/loop.halt`（runner 若在运行会自动继续；
已退出的重新 `... run` 一次）。

## 三、情况 → 处理 对照表

### 队列与任务

| 情况 | 处理 |
|---|---|
| 队列有任务 | 从 `## ready` 顶部逐条投喂；完成后勾选进 `## done` |
| 队列空（burn 默认开） | 投喂持续改进指令: 先按 worker 自己说的下一步做，否则做十维收尾审查（正确性/安全/性能/可靠/鲁棒/可维护/测试/依赖/可观测/文档），发现问题小步 commit 修复 |
| worker 自评的后续任务 | 写进 `## review-needed`，**人工确认**挪到 `## ready` 才会执行 |
| worker 报"无事可做"(idle) 连续 2 轮 | 熄火: park + 通知"没有可烧的活了" |
| worker 完成但无 TASK_RESULT 标记 | park + 通知（防止半成品当交付） |
| worker 报 TASK_RESULT: BLOCKED | park + 通知（等人工解锁） |
| 队列行被 worker 中途改写 | 验收时勾选失配 → park 等人工核对（不会无限重投） |
| 陈旧完成事件（上一任务的） | 新鲜度令牌（终态事件计数）拦截，忽略并等待本回合自己的事件 |

### gate（测试门禁）

| 情况 | 处理 |
|---|---|
| gate 失败 | 输出尾部回灌 worker 修复，最多 `CODEXC_GATE_RETRIES`(3) 次 |
| gate 超时（`CODEXC_GATE_TIMEOUT`=900s） | 整个进程树 kill → 回灌/挂起 |
| gate.sh 不存在 | 视为跳过（放行）——想强制测试必须提供 gate.sh |
| gate.sh 是任意代码 | 信任边界 = 你自己写的 CI 脚本；爆炸半径 = 用户权限 |

### 独立审查（双零收敛）

| 情况 | 处理 |
|---|---|
| 审查发现 bug | bug 清单回灌修复，**收敛计数清零重来** |
| 连续 `CODEXC_REVIEW_PASS`(2) 轮 0 bug | 验收 |
| 审查轮次超 `CODEXC_REVIEW_ROUNDS`(6) | park + 通知 |
| 审查输出无 `BUGS: <n>` 行 | park（安全方向，不瞎猜） |
| 审查器挂起 | `CODEXC_REVIEW_TIMEOUT`(1800s) 整树 kill → park |
| 审查器与实现者 | 永远是 codex（跨模型），worker 是谁都不变 |

### 错误续命（watcher，仅 TUI 通道）

| 情况 | 处理 |
|---|---|
| 429 / 502 / 断流 / **模型容量满** 等瞬时错误 | 自动发 continue（冷却 10s，上限 30 次） |
| usage limit / 订阅额度类 | **永不续命**——等待窗口重置才是正解，可排 `codexc -t` 定时 |
| 错误来源 | 每工具不同: codex=rollout 尾部 task_complete.error；claude=JSONL `isApiErrorMessage`(内置重试耗尽后)；pi=`stopReason:"error"`；opencode=opencode.db 错误 assistant 行 |
| 连续续命 30 次仍错 | watcher 停止 + 通知（防 token 无底洞） |
| 长跑会话的 watcher 版本旧 | 重新 `codexc` attach 即自动补挂当前代码的 watcher（watcher 死亡/升级同理）；无需重启会话 |

### 运行器自身

| 情况 | 处理 |
|---|---|
| 同项目启动第二个 runner | 锁（`.codingkeeper/loop.pid`）拒绝 |
| runner 被 kill -9 | 临时文件/pid 残留由下一个驱动清扫接管 |
| worker 会话/进程死亡 | 驱动自回收（无孤儿、无虚假验收） |
| 用户想暂停 | `touch .codingkeeper/loop.halt`；复燃 `rm .codingkeeper/loop.halt` |
| dry 试跑 | `CODEXC_LOOP_DRY=1`（TUI 通道跑完首条即停；headless 只记录不执行） |

### 环境与边界

| 情况 | 处理 |
|---|---|
| 项目目录经符号链接访问（/tmp↔/private/tmp、~/Documents/ai） | 全部 realpath 对账（会话归属/信任/gate 发现） |
| 含引号的路径 | SQL/AppleScript 参数已转义 |
| 中文目录名（tmux 会话名） | 塌缩时追加内容哈希保证唯一 |
| codex 信任门 / claude 信任+Bypass 弹窗 | 启动前自动预种（双路径形态） |
| 任务文本特殊字符/换行 | b64/stdin 传递，不进 shell；逐字 send-keys |
| CRLF 队列文件 | 解析容错 |
| 投喂后 worker 长时间无进展（卡弹窗/登录门） | `CODEXC_LOOP_STALL`(300s) 无进展 park + 通知 |

## 四、headless 通道专属

| 情况 | 处理 |
|---|---|
| worker 回合超时（`CODEXC_HEADLESS_TIMEOUT`=3600s） | 整树 kill → 失败计数，连续 `CODEXC_TURN_RETRIES`(3) 次 park |
| worker 空输出（认证失效等） | 失败计数，连续 3 次 park + 通知（日志含输出尾迹） |
| 会话连续性 | zcode: sessionId 存 `.codingkeeper/zcode-session-id` 每轮 `--resume`；dsh: `.codingkeeper/dsh-session-id`（从 zstd 会话文件提取） |
| zcode 升级后 | 重跑 `codexc-headless selftest-integration` + 一次冒烟（文档声明过版本间行为差异） |

## 五、燃料（provider/token 管理）

| 命令/情况 | 说明 |
|---|---|
| `codexc fuel [tool]` | 当前 provider、换煤队列、今日/本月消耗、最近中转错误、循环状态 |
| 中转日志落库延迟 | "今日消耗"可能有秒级少算 |
| keydrop 轮换的 dsh key 失效 | 去 keydrop 刷新；自检: `echo "Reply OK" \| dsh --profile headless -` |
| 自动换煤 | cc-switch 里开启 failover + 把 token 加入队列 + 设日限额（当前未开启） |

## 六、按键（TUI 会话内）

| 按键 | 效果 |
|---|---|
| `Ctrl+a` 松开，`d` | 标准 detach |
| 按住 Ctrl 敲 `a` `d`（即 C-a C-d） | 同上（已绑定） |
| `Ctrl+b d` / 按住变体 | 第二前缀，等价 |
| `Ctrl+]` / `F12` 单键 | 无前缀一键 detach（保险通道） |

## 七、任务可见性（两层）

### 终端内横幅（tmux 窗格顶部）
runner 运行时在所在 tmux 窗格顶部常驻一行横幅，随状态机实时刷新:
`📋 任务 ｜ 队列剩余 n │ 执行中` → `🔍 独立审查中` → `✅ 已验收` → `⛔ 已挂起`。
关闭: `CODEXC_BANNER=0`。

### 桌面任务面板（CodingKeeperBar，单一状态机）

屏幕顶边居中的任务面板，渲染状态按优先级: **展开 > 闪现 > (悬停∨待处理)=计数 > 空闲**:

1. **空闲** — 3px 绿色细线贴在菜单栏行（无文字，不干扰）
2. **悬停/待处理** — 弹出状态计数（品牌 logo + 转圈运行数 + 暂停待处理数）
3. **闪现** — 新任务蓝闪 4s / 完成绿闪 4s（同一事件 10s 去重），自动收回
4. **待处理常驻** — ⛔ 停止 / ⏸ 循环挂起时琥珀色计数常驻，直到处理
5. **点击展开** — 任务卡片表格（状态色点 + 工具·项目 + 时长/完成时刻 + 任务文本），封顶半屏滚动

install 自动编译（Swift/AppKit，`desktop/CodingKeeperBar.swift`）。
每 2 秒从各项目的 `status.json` 与 `loop.pid` 刷新（活跃回合另有 30s 心跳保活）。
不占 Dock、不抢焦点、空白区域可点穿。

## 八、排查入口

| 看什么 | 位置 |
|---|---|
| 全部时间线（投喂/审查/park/续命） | `~/.codex/codexc-watch.log` |
| 每任务验收记录 | `<项目>/.codingkeeper/journal` |
| 队列/门禁/挂起状态 | `<项目>/.codingkeeper/`；`codexc fuel` 一屏汇总 |
| 测试回归 | `codexc-loop selftest` / `selftest-integration <tool>` / `selftest-faultinjection` / `codexc-headless selftest[-integration]` |

## 九、设计不变量（改代码前必读）

1. **验收只认真实证据**: gate 的退出码 + 独立审查的 BUGS 行；worker 自述永远不算数。
2. **失败方向是 park**: 任何无法判定的情况挂起等人，绝不带病续跑或虚假验收。
3. **完成事件一次性消费**: 水位 + 活动门 + 新鲜度令牌三层防陈旧误收。
4. **每层都有上限**: 续命 30 / gate 3 / 审查 6 / 空转 2 / 回合超时 3600s——无界循环不存在。
5. **外环零智能**: bash + tmux + 退出码；智能全部在 Agent 内，机械全部可审查。
