# 改进燃料与人机交接

**方向叫「改进燃料」，具体可验收的任务叫「改进工单」。** 内部验收单元仍使用 leaf，历史 `ck leaves` 和叶子 ID 继续兼容。`ck fuel` 查询的是供应商和 token 消耗；`ck prompts` 管理的是改进方向。

## 44 类通用燃料与 85 类领域燃料

内置可用目录共 129 类：44 类通用燃料，以及 17 个领域包中的 85 类领域燃料。默认只启用通用目录；领域包按项目已有能力组合。燃料提供寻找问题的方法，不代表每个项目必须做 129 项改动。每轮先确认实际能力、已有工作、用户收益、成本和验收，再完成一个完整结果。不存在界面、SDK 或商业入口的项目可以记录不适用，不能凭空补出一套产品。

| 方向 | 燃料 ID | 可以交付的结果示例 |
|---|---|---|
| 工程质量 | `correctness`、`reliability`、`security`、`edge-cases`、`test-coverage`、`performance`、`observability`、`dependencies`、`maintainability`、`documentation`、`data-integrity`、`compatibility`、`resource-lifecycle`、`concurrency`、`operability` | 修复可复现错误；恢复不丢状态；关键行为回归；有基线的性能优化；有效诊断与可运行说明 |
| 用户体验 | `onboarding`、`usability`、`accessibility`、`responsive`、`empty-states`、`error-recovery`、`search-discovery`、`data-portability`、`localization`、`user-feedback`、`user-control`、`supportability`、`information-architecture` | 首次使用成功；少一次重复输入；键盘可达；窄屏可操作；空状态有下一步；失败可重试；数据可备份恢复 |
| 产品能力 | `product-flow`、`integrations`、`api-experience`、`trust-privacy`、`activation`、`retention`、`collaboration`、`product-measurement`、`domain-fit` | 补齐现有核心流程；SDK 样例真正跑通；隐私说明与实现一致；更快获得第一项价值；再次使用能恢复工作 |
| 商业与交付 | `conversion`、`packaging-value`、`pricing-evidence`、`operating-cost`、`release-readiness`、`product-discovery`、`experiment-design` | 价值表达符合实际功能；可离线运行的演示；收费决策的证据；单位资源成本下降；本地安装包可用；实现明确的小需求 |

所有燃料要求真实依据和适当验证。收入、转化率、客户评价、用户访谈、合规认证必须有来源；没有来源时保留假设和验证办法。测试通过不能替代用户流程、设备或浏览器验收。

## 领域包怎样选择

领域包是「某个细分领域内通用」的检查方法。例如检索包检查摄入、相关性、引用、权限与更新；学习包检查进度、测验、练习、课程关系与学习者控制。全部 17 包的目录、适用条件与真实项目示例见 [FUEL-DOMAINS.md](FUEL-DOMAINS.md)。

Agent 阅读实际代码、产品约定、测试与已有任务后选择；Keeper 只校验、持久化并轮换。`domain-fit` 是默认通用燃料，允许 Agent 使用 `ck prompts enable` 匹配已有能力并记录证据；不能按项目名字猜测或为延长运行启用所有包。新增业务、定价或市场定位仍是人类决策。

```bash
ck prompts packs                        # 领域目录、适用条件与当前启用状态
ck prompts packs learning               # 查看一个包的五类方向
ck prompts list                         # 当前实际轮换目录
ck prompts list --all                    # 全部可用方向，含未启用领域
ck prompts show rag-citations            # 查看不依赖启用状态或筛选
ck prompts enable retrieval ai-agents    # 为当前项目持久化组合领域
ck prompts disable ai-agents
ck prompts packs --json
```

配置保存在 `.codingkeeper/fuel-packs.json`：`{"version":1,"enabled":["retrieval","ai-agents"]}`。启用/禁用在 acceptance.lock 内原子写入，保留已有附加字段和决策依据；重复启用不改写文件。它不会移动队列、解除暂停或启动 runner。无效版本、未知/重复 ID、FIFO 和符号链接会报错，避免静默使用错误配置。

`CODEXC_FUEL_PACKS=retrieval,ai-agents` 对当前进程覆盖持久化配置；显式空值关闭当前进程的所有领域包。`CODEXC_PROMPT_IDS` 优先指定最终方向与顺序，也能显式选择未启用领域中的已知 ID。`packs --json` 分别报告配置包和环境生效包；显式方向筛选仍以 `list` 为准。检查命令不修改启用状态。源码能力变化时应重新审查适用性。

## 夜间怎么持续工作

1. 优先执行 `queue.md` 的 `ready` 工单。
2. 默认工作日09:00–23:00不下发；其余时间允许，同项目人工交互优先。队列空时轮换改进燃料，每轮选择一个适用、未被覆盖、可验证的问题。
3. 有源码变化的成果通过真实 gate 和独立审查后才记为已验收。headless 回合有改动却未提供证据时保留工作区、暂存内容与提交，停炉留待核对；不会重置 Git。
4. 连续两遍当前生效目录没有源码变化时进入 `waiting_fuel`（仅通用目录为 88 回合，启用检索包后为 98 回合），runner 保持在线且等待期间不请求模型。
5. 新 ready 工单立即执行；燃料/合同或 Git 源码状态变化会重新开放扫描；默认每 3600 秒复查一次耗尽的燃料。

`CODEXC_FUEL_RECHECK=1800` 把定时复查缩短为半小时；`0` 关闭定时复查，仍响应新工单、源码和燃料变化。合法范围为 0–604800 秒。复查不清除人工暂停，也不绕过配额、时段、测试失败或独立审查。它保证系统能继续寻找有价值的工作，不保证没有需求差距的项目一定能产生八小时成果。

可以给不同项目选择不同方向：

```bash
# 默认使用通用方向，叠加项目已启用的领域包。
ck prompts list
ck prompts show onboarding

# 当前启动的 runner 仅轮换这些方向，顺序与配置一致。
CODEXC_PROMPT_IDS=product-flow,onboarding,error-recovery,conversion ck zcode run

# 补充项目特定燃料，或直接加入已确定的改进工单。
ck prompts add export-quality --file ./export-quality.md
ck enqueue --file ./verified-improvement.md
```

项目自定义燃料保存在 `.codingkeeper/prompts/`，可以覆盖同名内置方向；自定义文件上限为 128，活动/可用目录校验上限为 512；全部 129 类内置加 128 类自定义可同时工作。自定义同名领域方向在禁用该包后仍是项目燃料。容量校验独立于方向筛选并在锁内执行，并发加料不能越过最后一个位置。选择了 `CODEXC_PROMPT_IDS` 的 runner 只扫描该名单；新增方向需要加入名单才会参与轮换。

runner使用 `next --reserve` 保留当前方向，成功核对无改动或真实验收后才 `complete` 推进。额度失败、超时、投喂失败、时段截止、人工让位及进程退出均不消耗当前方向；重启后继续同一方向。完成令牌在锁内校验，重复完成幂等，错误令牌不改状态；普通 `next` 不绕过已保留方向。

燃料内容、合同、启用领域或方向顺序变化时，从新目录首项重开扫描并重置无产出计数；已有旧格式 `burn-cursor.json` 继续兼容。修改发生在检查与取下一项之间时，变化会在随后检查中被确认，不会被耗尽标记吞掉。

## 人工交互让位

本轮按项目级让位：新版 `codexc` 的人工交互会话写入 `.codingkeeper/interactive/<token>.json`，绑定owner PID和出生标识。相同项目的worker/gate/review及watchdog让位，其他项目继续；用户会话结束后恢复等待的原任务。进程退出或PID被复用不会永久占住项目，多个会话各持有自己的token。无效或链接状态拒绝自动下发。

已知TUI连续空闲600秒后的接管会释放该owner的人工阶段，并再次检查输入框与归属；窗口默认工作日夜间及周末。其他前端可通过 `ck interaction begin --owner <会话PID>` / `ck interaction end <返回token>` 接入；`ck interaction check` 只读核对。未接入的ZCode/其他桌面原生会话不能仅凭应用开着判定有人正在操作，仍使用人工 `loop.halt` 保护，不能宣称自动检测已覆盖所有GUI。

## 人类决策如何交接

AI 在已授权范围内完成可逆的实现、测试、样例与文档。定价、产品方向、生产权限、对外沟通和发布等选择写成决策工单，其他独立工作继续进行。实际阻塞整个当前工作的条件仍使用 `TASK_RESULT: BLOCKED`；不能把它伪装成成功。

```bash
ck propose --file ./decision.md
ck morning                    # 默认跨登记项目汇总最近 12 小时
ck morning --hours 8
ck morning --json
ck morning --project /path/to/project
```

`ck propose` 原子写入 `review-needed`，与验收共享锁，重复的相同提案不会反复入队；以稳定 `DECISION-XXX` 开头的待决策项，换一种文本也不能重复加入（ID 大小写不敏感，需要核对已有提案），未完成验收事务会阻止改写。它不移动 ready/done，也不改变暂停状态。决策稿应包含：稳定 ID、受影响用户和目标、当前证据、候选方案、推荐、收益、代价、风险及验收办法。

晨报只读取文件：列出有 receipt 的近期验收、全部待决策项、ready 数量、暂停原因、已配置领域和状态陈旧/读取问题。配置领域不等于旧 runner 的实际环境；后者可被进程环境覆盖。状态时间允许整数/小数，超过 120 秒或提前超过 5 秒会明确显示陈旧。文本显示最近 20 条成果及前 20 项决策，完整列表在 JSON 中；journal 仅尾读 1 MiB，更早记录仍保留在原文件。没有 receipt 的历史自述不会自动成为已验收成果。

## 长期运行的存储

验收事务完成后，默认保留最近 50 份已验收证据。`CODEXC_EVIDENCE_KEEP=N` 设置 0–10000；0 关闭保留清理。活动工单、pending 事务和未验收证据始终保留，journal 不裁剪。共享 blob 只有在没有任何证据硬链接引用时才回收；快照写入和清理共用验收锁。清理失败会诊断，不撤销已持久化验收。

快照的 16 MiB/文件与 128 MiB/快照限制约束内容 blob。超限内容仍流式计算哈希并记录大小、类型和模式；缺少 blob 的变化会明确省略文本 diff，审查须结合哈希与当前源码，不静默丢掉路径。

运行日志默认位于 `~/.codingkeeper/codexc-watch.log` 和 `codexc-daily.log`；`CODEXC_LOG_DIR` 可覆盖。若新日志尚不存在，首次写日志时原子迁移旧 Codex 日志；新旧同时存在时保留两份历史，后续写新位置。
