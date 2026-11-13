# codexc 处理逻辑手册（遇到什么情况，怎么处理）

> 面向使用者与维护者的完整行为手册。架构: **CodingKeeper** —— 编码 Agent 的无人值守运行时，
> 两条驱动通道（TUI 投喂 / headless 子进程）共享同一套验收管线。

## 一、总览：两条通道，一套验收

```
                       ┌──────────── 验收管线（共用） ────────────┐
队列 .codingkeeper/queue.md  │  worker 回合 → gate.sh(真实退出码)        │
   │ 逐条投喂           │  → 独立审查(codex exec, 独立上下文, 双零收敛) │
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
                                │ 燃料库连续两遍无产出后等待新料 (idle 标记+git 干净)
                                ▼
                             waiting_fuel: 在线等待 → 新任务/新 Prompt 自动复燃
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
| 内置燃料库连续两遍无产出 | 在线 waiting_fuel，不请求模型；新任务或 Prompt 变更自动复燃 |
| worker 完成但无 TASK_RESULT 标记 | park + 通知（防止半成品当交付） |
| worker 报 TASK_RESULT: BLOCKED | park + 通知（等人工解锁） |
| 队列行被 worker 中途改写 | 验收时勾选失配 → park 等人工核对（不会无限重投） |
| 陈旧完成事件（上一任务的） | 新鲜度令牌（终态事件计数）拦截，忽略并等待本回合自己的事件 |

### gate（测试门禁）

| 情况 | 处理 |
|---|---|
| gate 失败 | 输出尾部回灌 worker 修复，最多 `CODEXC_GATE_RETRIES`(3) 次 |
| gate 超时（`CODEXC_GATE_TIMEOUT`=900s） | 整个进程树 kill → 回灌/挂起 |
| gate.sh 不存在/官方占位 | 自动入口默认停止，先配置真实门禁；非 ZCode 可显式 CODEXC_REQUIRE_GATE=0 使用旧兼容行为 |
| gate.sh 是任意代码 | 信任边界 = 你自己写的 CI 脚本；爆炸半径 = 用户权限 |

### 独立审查（双零收敛）

| 情况 | 处理 |
|---|---|
| 审查发现 bug | bug 清单回灌修复，**收敛计数清零重来** |
| 连续 `CODEXC_REVIEW_PASS`(2) 份成功且 0 bug 的独立报告 | 验收 |
| 审查轮次超 `CODEXC_REVIEW_ROUNDS`(6) | park + 通知 |
| 审查输出无 `BUGS: <n>` 行 | park（安全方向，不瞎猜） |
| 审查器挂起 | `CODEXC_REVIEW_TIMEOUT`(1800s) 整树 kill → park |
| 审查器与实现者 | 审查使用独立 Codex 上下文；底层模型不保证与 worker 不同 |

### 错误续命（watcher，仅 TUI 通道）

| 情况 | 处理 |
|---|---|
| 429 / 502 / 断流 / **模型容量满** 等瞬时错误 | 自动发 continue（冷却 10s，上限 30 次） |
| usage limit / 订阅额度类 | **永不续命**——等待窗口重置才是正解，可排 `codexc -t` 定时 |
| 错误来源 | 每工具不同: codex=rollout 尾部 task_complete.error；claude=JSONL `isApiErrorMessage`(内置重试耗尽后)；pi=`stopReason:"error"`；opencode=opencode.db 错误 assistant 行 |
| 连续续命 30 次仍错 | watcher 停止 + 通知（防 token 无底洞） |
| 长跑会话的 watcher 版本旧 | attach 复用已验证活跃的 watcher，缺失时补挂；升级旧 watcher 需重新启动会话 |

### 运行器自身

| 情况 | 处理 |
|---|---|
| 同项目启动第二个 runner | 锁（`.codingkeeper/loop.pid`）拒绝 |
| runner 被 kill -9 | 下个驱动在共享锁内确认旧 PID 已死后接管；无效元数据需检查 |
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
| 会话连续性 | zcode: sessionId 存 `.codingkeeper/zcode-session-id` 每轮 `--resume`；dsh: `.codingkeeper/dsh-session-id`（从本次 --json session 事件原子保存，每轮 --session-id；失败/超时保留） |
| zcode 首次失败/空响应/超时 | stream-json 的 `turn.started` 提前将 `sess_...` 保存至 `.codingkeeper/zcode-session-id.retry`，下一轮续接；成功后提升为主会话并移除 retry。已有主会话始终优先，失败不覆盖有效上下文 |
| zcode 本地 ID 损坏/恢复 ID 突变 | 报错并阻止继续建会话。新建上下文前同时备份并移走 `zcode-session-id` 和 `zcode-session-id.retry`；手动 halt 不受此机制影响 |
| dsh 会话恢复失败 | 保留已保存 ID 并明确报错，不静默新建上下文；dsh 自身校验持久化历史、项目目录及 profile。确需重建时先备份并移走 `dsh-session-id`。适配器不再依赖 DSH_DIR/zstd 查找目录，数据位置由 dsh 自身配置决定 |
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

1. **空闲** — 透明收起（保留顶边悬停区域，无文字）
2. **悬停/待处理** — 弹出状态计数（品牌 logo + 转圈运行数 + 暂停待处理数）
3. **闪现** — 透明背景任务提示 4s（同一事件 10s 去重），自动收回
4. **待处理常驻** — ⛔ 停止 / ⏸ 循环挂起时计数常驻，背景透明，直到处理
5. **点击展开** — 任务卡片表格（状态色点 + 工具·项目 + 时长/完成时刻 + 任务文本），封顶半屏滚动；仅展开时显示毛玻璃底板

install 自动编译（Swift/AppKit，`desktop/CodingKeeperBar.swift`）。
收起时不启用模糊，保留 1% 不透明度的点击底层，确保透明横幅也能在未激活时单击展开。
每 2 秒从各项目的 `status.json` 与 `loop.pid` 刷新（活跃回合另有 30s 心跳保活）。
不占 Dock、不抢焦点、空白区域可点穿。

## 八、排查入口

| 看什么 | 位置 |
|---|---|
| 全部时间线（投喂/审查/park/续命） | `~/.codingkeeper/codexc-watch.log` |
| 每任务验收记录 | `<项目>/.codingkeeper/journal` |
| 队列/门禁/挂起状态 | `<项目>/.codingkeeper/`；`codexc fuel` 一屏汇总 |
| 测试回归 | `codexc-loop selftest` / `selftest-integration <tool>` / `selftest-faultinjection` / `codexc-headless selftest[-integration]` |

## 九、设计不变量（改代码前必读）

1. **验收只认真实证据**: gate 的退出码 + 独立审查的 BUGS 行；worker 自述永远不算数。
2. **失败方向是 park**: 任何无法判定的情况挂起等人，绝不带病续跑或虚假验收。
3. **完成事件一次性消费**: 水位 + 活动门 + 新鲜度令牌三层防陈旧误收。
4. **每层都有上限**: 续命 30 / gate 3 / 审查 6 / 空转 2 / 回合超时 3600s——无界循环不存在。
5. **外环零智能**: bash + tmux + 退出码；智能全部在 Agent 内，机械全部可审查。

## 本轮审计补充

- 安全配置编辑要求 Python 3.11+；损坏的 TOML/JSON 保留原文件并报错。inline projects 无法安全扩展时仅跳过自动预信任。
- headless 可用 `CODEXC_REVIEW_PARALLEL=1` 同批运行独立审查（默认开启）；每个审查仍计入 `CODEXC_REVIEW_ROUNDS` 总预算，全部成功且零 bug 才验收。`0` 恢复串行。
- watcher.pid 是兼容状态文件；新版按 pane 保存 watcher 元数据，不按未经验证的 PID 杀进程。
- 定时发送绑定 owner/项目/tool，每次提交前复验；`-t` 与 loop 同时使用会报错。
- 详细修复与测试结果：[深度审计](AUDIT-2026-11-05.md)。

## 交互会话的夜间空闲接管

`codexc` 的交互 TUI 可在新加坡时间工作日23:00–09:00或周末内，连续空闲 600 秒后接入已有队列循环。`CODEXC_NIGHT_IDLE=0` 或 `--no-loop` 关闭；`CODEXC_NIGHT_IDLE`、`CODEXC_NIGHT_WINDOW`、`CODEXC_NIGHT_TZ` 分别设置空闲秒数、接管时段和时区。已有显式 loop 或定时投喂时不启动该监视器。

接管要求 pane 所有者、项目及工具匹配、Git 项目有真实 gate、没有 `loop.halt`、输入框为空且画面持续稳定；Codex、Claude、Pi 的已知输入框布局可识别，OpenCode 与未知布局暂不接管。交接前再次检查；每个交互会话只交接一次，不自动重启已暂停的循环。这里的时段限制控制交接时机，循环运行时段仍由 `CODEXC_ACTIVE_WINDOW` 和 `CODEXC_ACTIVE_TZ` 控制。

## ZCode 夜间套餐

`zcodec run` 默认工作日23:00–09:00、周末全天可运行，时区默认 Asia/Shanghai（本机launchd显式Asia/Singapore，同为UTC+8）。显式空的 CODEXC_ACTIVE_WINDOW 为人工不限时覆盖。到期停止受管子进程，队列只有完整验收后才修改；等待期间 runner 保持存活，但 `active=false`，不是正在执行模型任务。

配额耗尽时 `.codingkeeper/quota-until` 持久化下一次开放的 epoch；复开服务不会清除此标记。`loop.halt` 仍为人工/不可恢复错误暂停，优先于自动时段。无效时段、时区或配额标记会停止执行；排查后才清理对应状态。`burn-watch` 同样遵守窗口并保留项目 halt；它不负责清除人工暂停。

ZCode 的窗口不改变 `codexc-daily`（该入口仅负责 Codex）的调度。原有 `CODEXC_AUTO_RESUME=0` 会让配额失败停靠，需人工恢复。

## 叶子队列审计与恢复

- `ck leaves --registry`：离线结构检查。错误返回非零，质量提示需要结合源码判断；不会跑 gate/worker。
- `zcodec run`：默认轮换工程 Prompt 持续 burn；CODEXC_LOOP_IDLE=0 时空队列等待，占位 gate 直接挂起。正式 gate 的业务覆盖仍由项目维护者负责，不能从任意 shell 代码自动证明。
- 续行必须缩进；待依赖的任务放 `## blocked`，已实现但缺验收的任务放 `## review-needed`。runner 不自动把依赖当完成。
- `.codingkeeper/acceptance.pending.json` 是未提交完的验收事务。恢复会核对队列前/后内容并幂等补齐 journal/receipt；队列已被外部修改则停住供核对。不要随意删除它或手工勾选以绕过失败。
- `.codingkeeper/evidence/<id>/` 保留任务基线、候选、输出与 receipt；blobs 按内容去重复用。内容 blob 上限 16 MiB/文件、128 MiB/快照；超限文件仍流式记录完整哈希和元数据，缺内容时明确省略文本 diff。50,000 路径上限仍会停止；不能静默忽略文件。已验收历史默认保留最近 50 份，活动/pending/未验收证据和 journal 保留，见 [改进燃料](FUEL.md)。
- ZCode `review-lane=auto` 现在直接选择 Codex；不会 ping 模型或自动换渠道。`zcode` 与 `codex` 明确选择车道。审查失败/空响应不算 BUGS: 0。
- gate 输出中的 SKIP 不是 PASS，设备与真实浏览器结果必须独立记录。队列归档前核对 gate 是否依赖勾选数量；本次已解除 sale 的此类耦合。

## 工程燃料与受管进程

`ck prompts list/show/add` 管理44类通用、已启用领域及 `.codingkeeper/prompts/*.md` 项目燃料；`packs/enable/disable` 查看和原子配置领域包，配置保存在 fuel-packs.json；`ck enqueue` 接受文本、`--file` 或 `--prompt`，与验收共享锁。轮换游标持久化，任务优先于 burn；默认两遍燃料库无源文件产出后在线等待新料，不发送模型请求；新任务或项目 Prompt 变更自动恢复。验收一个队列任务后重置空转计数。自定义 CODEXC_LOOP_IDLE 文本不轮换；CODEXC_PROMPT_ROTATION=0 保留单条通用指令。

headless worker、gate、reviewer 使用独立的受管进程组。阶段结束先清理后台组成员再验证源码；runner 被 SIGKILL 后，监护进程发现 owner 消失会停止本组。主动创建新 session 的守护进程不属于这个进程组；需要由项目 gate/工具自身管理。headless evidence 保留 worker Prompt、输出及 burn 目标。

审计与验证范围：[2026-11-12 复审与改进燃料](AUDIT-2026-11-12.md)；历史记录见 [2026-11-06 审计](AUDIT-2026-11-06.md)。

默认审查器通过 Codex --output-last-message 提取最终回答，日志单独保存；最后非空行必须为 BUGS: <n>。自定义审查命令同样需遵守最终行契约，较早的 BUGS: 0 不再放行。

## 改进燃料与晨报

内置目录为44类通用改进燃料及17包/85类领域燃料，领域默认不启用，Agent读取实际能力后选择；具体成果称为改进工单。队列空时持续轮换；两遍无改动后在线等待，默认每小时复查，源码/燃料变化即时复燃。待人类决策的事项用 `ck propose --file decision.md` 记录到 review-needed，早晨 `ck morning` 汇总。完整规则、目录与保留策略见 [FUEL.md](FUEL.md) 和 [领域指南](FUEL-DOMAINS.md)，回归结果见 [领域扩展复审](AUDIT-FUEL-EXTENSION-2026-11-12.md)。
