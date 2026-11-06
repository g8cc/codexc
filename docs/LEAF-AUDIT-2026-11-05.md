# 叶子节点与执行器深度审计 · 2026-11-05

本轮检查全部六个登记项目的 **68 条现有队列记录（34 条待办、34 条历史勾选）**，并逐项核对来源目录的 **95 个检查 ID**。源代码审计、复现和项目已有测试表明：主要浪费来自无边界空闲改进、重复实现和无效验收；节点数量不能代表项目收益。

## 新确认的执行器问题与修复

| 问题 | 复现后果 | 本轮处理 |
|---|---|---|
| 旧脏改动被算成本轮产出 | 假 worker 连续 DONE(idle)、没有改代码仍不断验收 | 开工记录文件清单与内容指纹；只有本轮文件变化算产出，空提交也不算 |
| 空队列默认持续改进 | 原任务完成后继续泛审查、追加提交、消耗额度 | zcodec run 默认 CODEXC_LOOP_IDLE=0；空队列 inactive/idle，明确开启才空闲改进 |
| 审查只看 git diff HEAD | worker 已提交的本叶改动完全不在审查diff中 | 持久基线→候选内容差异，包含提交、原有脏改动对照和多次修复；断点后保留原基线 |
| gate/review 与候选没有绑定 | reviewer 更改源码、门禁或 index 后仍能通过 | gate后、review后、最终验收前核对内容/HEAD/语义index指纹，变化拒绝验收 |
| 勾选先于日志，失败不可恢复 | journal 失败丢失待办；TUI仍继续 | 持久pending事务、原子队列替换、唯一receipt和幂等恢复；冲突不覆盖、写失败恢复待办；半截日志也能恢复 |
| 队列解析不一致 | checkbox多空格可选不可勾；UTF8/读失败变成空队列烧额度；续行合同被丢 | 共享解析与匹配；完整缩进续行投喂；格式/读失败停止；代码围栏示例不执行；大小、FIFO/软链、NUL边界受控 |
| DONE出现在正文就算完成 | 先引用DONE再报告失败，仍进入验收 | 只认最后非空行的任务终止协议 |
| 审查包装吞失败、回退旧成功 | exit42或最终空响应，仍输出之前BUGS:0 | 共享适配器保留退出码与最后响应；非法/空结果拒绝，16MiB输出上限；不再付费ping探测或暗换车道 |
| 审查使用yolo，可执行修改 | 审查阶段拥有写/执行/委托能力 | ZCode plan+禁已知写/执行/委托工具；fresh session；Codex只读沙箱；候选变更额外检测 |
| 成功退出后留下审查后台进程 | 主CLI已退出，后台sleep/MCP仍存活 | runner为每次审查建立专有session/group，正常/失败/超时/时窗关闭/退出统一清理；核对token及进程启动身份 |
| 官方占位gate也准入自动任务 | echo+exit0被当作测试成功 | zcodec run 在任何worker调用前拒绝缺失和官方占位gate；任意自定义gate的业务质量仍需项目审查 |

上述修复保持 23:00–次日09:00（Asia/Shanghai，UTC+8）的套餐窗口约束。验证使用假模型/假CLI，不产生真实推理请求。

## 叶子逐项目结论

| 项目 | 审计前 | 整理内容 | 详细证据 |
|---|---|---|---|
| sale | 24条：5勾选、19待办 | 已实现M2c/刷新恢复进入待验收；6条重复或已达标质量叶归档；合并输入/键盘/label验收；拆开录制、持久化、容量与复盘；只把当前前置满足的3项放ready | [sale](leaf-audit/sale.md) |
| soul2soul | 10条：3勾选、7待办 | BAT-03已有提交，补验而非重做；BAT-04状态输入不适配；BAT-05要求的WifiLock超时API不存在；已有电量优化应兑现V-05/H5/H6实机证据 | [Soul2Soul](leaf-audit/soul2soul.md) |
| fingerprint | 27条：21勾选、6待办 | 6条未勾选误放done，runner无法取出；保留历史，恢复具体待办；iOS现有WIP实测缺method编译失败，另有重试复用签名问题；重复性能/并发实现改为补验 | [Fingerprint](leaf-audit/fingerprint.md) |
| test | 4条历史勾选 | 保留历史；仅检查PROJECT_NOTES的gate不能证明后续网关/鉴权修复，标明门禁不适用代码任务 | [其他项目](leaf-audit/auxiliary.md) |
| zcode-exp | 2条：1勾选、1待办 | fizzbuzz为实验夹具，带理由归档；修正编译失败仍exit0的门禁为明确不可准入的实验占位 | [其他项目](leaf-audit/auxiliary.md) |
| likeclaw | 1条泛读仓库待办 | 任务没有具体差距与验收，已给清理草案；当前主分支ahead/dirty，依据项目规则保留现场；新严格gate在worker调用前阻断该官方占位 | [整理草案](leaf-audit/likeclaw.queue.md) |

“历史accepted”没有被重新包装为本轮已验证。原队列和journal备份保留；有实现但缺证据的节点仍待验收。Fingerprint 原来的暂停保持。

## 门禁、安全和性能的实际价值

- sale gate原来按全队列[x]数量选择phase1–4。重写队列会降级门禁；现固定全部既有阶段及functional/perf/quality/v2，传入文件名用参数数组并兼容空格，强制RUN_REAL_AI=0防止继承环境打开计费测试。
- sale全量199项：198通过、0失败、1跳过（显式禁用的真实模型集成）。已有v1只读选定集159/159，40个JS/MJS语法通过。主要三文件gzip **25,662 B**，现有性能门禁通过；没有为200KiB模板预算再造优化任务。
- snapshot预检：sale 54文件/559,064 B，soul2soul 289文件/2,196,560 B，fingerprint 117文件/644,202 B；全部在预算内。内容blob跨叶去重；文本diff渲染有大小/行数预算，保留完整内容hash与blob，避免大文件diff拖死执行器。
- fingerprint只读安全/SDK/死码测试7项通过；Swift typecheck明确复现当前两文件WIP缺method。Node门禁不能代替Swift编译，因此新节点明确真实SDK请求契约、逐次重签名与丢响应恢复验收。
- ZCode的plan+工具禁用不是操作系统沙箱，未知插件不受这份已知工具列表全面覆盖。已降低审查能力并检测候选变化；不声称可隔离任意恶意本机进程。

## 让节点持续有用的准入规则

每条ready必须写清：当前适用性、具体差距/待证明的风险、已有源码/测试/提交去重、对用户的价值、改动范围和前置、可观察验收。已实现先补验；已有等价测试引用证据；基线已满足允许no-change；设备、真实浏览器或外部决策缺失时保留blocked/review-needed。

95项来源已逐项保留ID并重写适用条件和验收口径，取消默认逐号派工、两次失败就skip、固定数字自动当bug、全文件checkout回滚等规则。十份入口/合同/调度文档统一；[95项逐条对照](leaf-audit/catalog.md)和[新版框架](leaf-audit/framework/README.md)可审阅。

新增 `ck leaves --registry` / `zcodec leaves . --json` 做离线结构检查：重复ID、错误分区待办、占位gate、格式问题。它不调用模型，也不替代源码价值判断。runner只执行ready，blocked/review-needed依赖需要核对后显式移入。

## 验证与部署记录

### 测试证据（如实记录两轮）

- 完整全套 `/private/tmp/ck-tests-6wk2scmk`：**退出码 1**。仅 `integration codex` / `integration pi` 各 1 项失败，日志为 `FAIL: reviewer child survived kill_tree or PID evidence missing` —— 5 秒审查超时夹具在子进程启动前就超时，PID 证据未生成，属测试夹具问题，不是产品代码失败。
- 只把该集成夹具的启动等待从 5 秒改为 15 秒、保留 PID 校验，产品超时默认值未调整；受影响阶段在 `/private/tmp/ck-tests-8_ff8jkj` 复测**退出码 0**，五条 integration lane（codex / claude / pi / opencode / headless）全部 PASS，headless HL-1～HL-8 通过。
- 联合覆盖 **26 个阶段**，凭证 `/private/tmp/ck-leaf-suite-passed.json` 明确记录 `full_suite_exit_code=1`、`affected_stage_rerun_exit_code=0`，不把第二轮的 1 写成 0。
- 12 套 unittest 型审计共 **172 项**全通过（window 23、zcode-window 18、watch-window 14、quota 11、leaf-runtime 19、review-leaf 18、leaves 9、startup 22、loop-daily 17、edges 12、harness 6、tool-watchers 3），另有 acceptance / desktop 脚本式检查、conformance 40/40、故障注入、四工具集成与 headless 场景。全程假 worker/reviewer，无真实模型请求。

### 应用与读回

- 源码：`/private/tmp/ck-apply-leaf-source.py` 在全套通过后原子替换 20 个运行时文件，连同此前窗口修复共 **28 个文件** SHA256 与 `/private/tmp/ck-leaf-tested.json` 一致；备份 `/private/tmp/ck-leaf-source-before-3nkoq_jy`，读回复核 28/28 无偏差。
- 外部元数据：`/private/tmp/ck-apply-leaf-audit.py --apply` 于 **20:52:19** 完成，`status=applied`、31 个文件、无 error；原文件与 journal 备份于 `/private/tmp/ck-leaf-deploy-jzltd0sc`（含 `verification.json` / `manifest.json`）。读回 31/31 与 `prepared/plan.json` 的 `after` 哈希一致。likeclaw 仍只交草案，未动其 ahead/dirty 主工作区。
- 进程切换：旧 watchdog 49912 → 58185，sale 99760 → 57993、soul2soul 99761 → 57994；部署完成瞬间 `managed_model_children=0`，两项目 `waiting_window`、`active=false`、`CODEXC_LOOP_IDLE=0`。fingerprint 原 `loop.halt` 保留、iOS 两个 WIP 文件哈希与 `/private/tmp/ck-leaf-ios-wip-before.json` 一致。
- `ck leaves --registry`（离线、不调用模型）：sale ready 3 / pending 15、soul2soul 1 / 3、fingerprint 1 / 5、test 与 zcode-exp 0 / 0；likeclaw 1 / 1 并报 `L0 placeholder-gate` 与 `L4 unbounded-task`，即已说明的占位 gate 例外，新严格 gate 会在 worker 调用前阻断。

### 23:00 窗口开启后的真实运行观察

23:00:02 起两个 runner 各自领取 1 条 ready 叶子并尝试 3 个 turn，`~/.codex/codexc-watch.log` 显示每次都是 `zcode turn failed (rc=1, class=unknown)`，stdout/stderr 为空，随后 `parked: repeated empty turns`、`transient park — auto-resume #1/4 in 600s`，状态变为 `backoff` / `parked=true`，`next_run_at` 约 23:10。执行器没有把旧 DONE 或空输出误验收，队列未被勾选，也没有模型 worker 子进程存活；watchdog 只读记账仍为 290.0M。失败原因指向 ZCode 网关/套餐侧的空响应，**本轮未定位、未擅自重启或修改**，需要服务侧排查后再决定是否人工恢复。此观察是真实运行记录，不作为审计测试的 PASS 证据。

另有 5 个 `/private/tmp/codexc-hl-it.*` 测试夹具残留的 headless 进程，不在生产注册表中，本轮未清理。未停止手工 Codex / ZCode 网关 / 领取套餐服务，未提交或推送 Git。

### 未完成的产品验收

Soul2Soul 双设备功耗/会话，sale 真实浏览器录制/存储/可用性及合法时窗内真实生成，fingerprint iOS 修复和重试契约。这些已写成可执行或待依赖节点，不把缺少设备/模型结果记作 PASS。
