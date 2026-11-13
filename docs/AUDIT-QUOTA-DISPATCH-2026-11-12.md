# 时段、额度失败与任务续做审计 · 2026-11-12

用户确认的规则：周一至周五09:00–23:00不自动运行；其余时间可运行，用户交互优先。本轮按项目级让位实现，其他独立项目继续运行。时区为UTC+8，入口默认Asia/Shanghai，本机launchd显式Asia/Singapore。

## 实际观察

先读取用户可见的 `ck morning --json`、队列、暂停和状态，再核对进程、部署plist与日志。快照保存在 `/private/tmp/ck-quota-before-20261112.json`。

- 起始检查仅观察到watchdog PID73587，无活动的CodingKeeper worker/loop。磁盘plist没有时段配置，旧源码默认未设置就全天开放。macOS进程查询没有暴露完整环境，不能把查不到变量当作变量不存在；具体白天下发由下述日志及回归确认。
- 四个额度暂停项目为aifinance、producthunter、airesearch、agentos；aifinance的7项ready仍保留。没有解除这些暂停或改写历史验收。
- `~/.codex/codexc-watch.log` 的最后2MiB包含今天09:38、10:13、16:42下发及随后额度错误的记录；这一读取范围内最后一次验收为08:48。全局旧日志缺少可靠的每条进程/项目归属，不能仅按相邻行把全部事件归到某个项目，也不能把有限尾读当成全部历史的证明。
- watchdog运行副本已与仓库相同，但bin中缺少共享helper，靠仓库回退路径运行；旧Bash进程仍保留全天策略，必须重载才能取得新默认值。

## 队列与燃料的区别

普通ready队列只在完整gate、独立审查和原子验收事务成功后结项。worker非零退出会否定DONE标记，额度错误会暂停/等待；同一ready继续在队首，不会自动移动到第二项。

燃料此前在下发前调用next并推进游标。最小回归复现：第一次correctness遭遇额度错误后，第二次变为security；TUI投喂失败同样消耗方向。这是用户担心的“未执行成功却轮到下一项”的实际路径，虽然没有伪造验收receipt。

修复为先 `next --reserve` 保留方向，只有有效无改动检查或真实验收成功后才 `complete <token>`。失败、超时、截止、人工让位和重启继续同一方向；错误token不改状态，重复完成幂等。仍保留旧游标和普通CLI的兼容。合同增加失败不等于idle的约束，使旧扫描重新核对方向，历史receipt不改写。

## 运行策略修复

1. ZCode、headless、TUI loop、watchdog和daily自动入口默认工作日夜间，launchd模板显式保存时段。纯时段函数的空策略仍可用于人工显式覆盖和隔离测试。
2. watchdog此前拒绝weekend结果；现在与共享校验一致接受周末。
3. 合并连续的周末和每日开放区间，周五23:00至周一09:00连续开放；周末worker得到真实周一截止，避免deadline=0越过周一白天。额度等待可在配置的日窗口/周末边界再次检查，不在等待期间持续请求模型。
4. TUI在选队列/燃料前检查时段，截止时中断自己投喂的工作并保留任务；headless、gate和review沿用受管进程组截止。定时投喂在目标时间及实际发送前复验，daily白天不启动救援回合。

## 人工交互让位

新版 `codexc` 人工会话使用项目级 `.codingkeeper/interactive/<token>.json`，绑定owner PID及出生标识。自动worker/gate/review和watchdog遇到活动人工会话让位；会话结束或owner退出后继续原任务。多个会话各持自己的token，PID复用不造成永久阻塞，损坏/链接状态拒绝下发。

已知TUI连续空闲600秒且输入框、归属和时段确认通过后，原夜间接管流程释放该owner人工阶段再进入循环。原生ZCode或其他未接入前端不能仅凭应用进程存在判定用户交互；它们可接入 `ck interaction begin/end`，现有人工loop.halt仍优先。未宣称所有桌面前端都已自动检测。

## 验证与部署

先复现再修复：燃料两项、默认白天阻断及周末放行三个失败子项、连续周末截止一项。修复后专项通过；普通双ready额度失败且输出含陈旧DONE的用例确认不验收、不执行第二项。`interaction`八项覆盖项目隔离、多会话、退出/PID复用、坏状态、阻止下发、交互结束续做原任务、运行中仅停止受管worker。

初版修复已通过一次完整46阶段门禁并发布三个launchd作业和桌面程序。发布时20个项目的queue.md、loop.halt、acceptance.pending.json均与起始快照一致；之后跨过23:00，正常自动恢复产生了新的暂停记录，不能将这些运行中状态伪称为“部署后全部仍未变化”。回归与诊断均未额外投喂真实模型，夜间控制器继续按用户授权运行。

发布核验发现旧PID73587是未受新launchd作业管理的副本，仍持有单实例锁。已核实其命令及出生时间后定向停止，再启动新作业。最终核验须同时确认loaded arguments/environment、活动PID及kernel lock owner；仅bootstrap成功不能证明运行位已经接管。macOS未暴露进程完整环境，记录为不可观测，使用已加载环境、源码默认值和锁归属核对，不伪造直接观测。

夜间恢复暴露另一个真实失败：中文错误按字节截断后被tr拒绝，原始失败信息丢失。新增离线回归先复现，再改为ck-log.py的有界UTF-8读取；worker和TUI共用，坏编码替换为可读字符，FIFO/链接拒绝且不改原文件。专项通过。

保留下来的错误指出ZCode内置provider路径定位失败：文件实际在Resources/config/provider/zcode-builtin.json，CLI自动候选遗漏该安装布局。第一次适配误用了ZCODE_BUILTIN_PROVIDER_BUNDLED_CONFIG_FILE，假CLI只检查变量存在，未覆盖真实启动契约，因此测试通过而实际仍失败。复查本机SDK的tbs/nbs/rbs函数确认：真正的启动输入是ZCODE_BUILTIN_PROVIDER_CONFIG_FILE，BUNDLED_CONFIG_FILE是准备完成后的输出；--help跳过这段启动流程，不能作为修复证据。

最终适配由ck-zcode-session.py共享设置正确输入，覆盖worker、独立审查及探测。用户显式CONFIG_FILE优先，兼容此前显式BUNDLED_CONFIG_FILE作为输入种子；自动发现只提供内置文件，不伪设personal路径，让SDK继续准备正常的endpoint对应active缓存与personal默认。endpoint和凭证保持继承。worker、独立审查及exec探测回归检查实际输入契约；worker测试显式隔离session db，避免宿主历史会话影响离线结果。

从真实安装包提取启动函数，以文件读取stub替代配置刷新和网络：旧输出变量稳定复现定位错误；正确输入通过，并确认正常active缓存准备和personal默认。证据在 `/private/tmp/ck-real-bootstrap-evidence-20261113.json`。授权夜间worker随后已有aifinance、wechatflow、AIContent、AIGEO的正常DONE输出，记录在 `/private/tmp/ck-provider-live-worker-evidence-20261113.json`；worker的DONE仍须经过gate和独立审查，不能直接认定任务已验收。

随后 `ck morning --json --hours 2` 读到四条完整验收回执：aifinance顺序验收两项，ready从7降至5；wechatflow和AIContent各验收一项。快照 `/private/tmp/ck-quota-live-morning-20261113.json`。这是正常夜间业务执行产生的证据，没有额外发送诊断模型任务。

本会话给控制器本项目登记临时交互让位；实际状态出现waiting_interaction，其他项目照常运行。完成后释放本会话token。未接入前端的键盘操作仍不能自动观测。

已退出的soul2soul、likeclaw、fingerprint、producthunter、aimarket、airesearch六项目均留下repeated empty turns。逐项目核对最后一条归档worker错误、暂停文件哈希、进程和人工lease，错误与停炉间隔均小于2秒。恢复预演已通过；实际恢复将原暂停文件原子移为备份，队列、journal、pending验收保持完整，由看门狗按当前并发上限与正常有界预算接管，不直接同时启动六个项目。人工、认证、额度及无法对应此错误的暂停不适用该恢复。

完整门禁还揭示两项验证问题：健康探测的一条旧测试读取了SDK输出变量，已改为真实输入；隔离测试取消后，私有tmux清理超时会抛异常并覆盖原退出结果。新增两个确定性失败回归，清理仍有5秒上限，取消保持130并报告清理失败，原本成功的门禁遇到清理超时必须返回失败。繁忙主机上，将执行完整控制器或worker的fixture整体预算统一为60秒，覆盖初始化和收尾；注入的真实时段截止、任务保留、重试次数及逃逸进程断言不变。只有fixture执行预算调整，产品运行限制保持原值。

进一步复查发现watchdog-deploy测试使用全局固定临时目录，多轮测试会共享目录并删除另一轮的fixture。新增并列实例隔离回归先复现失败，再改为每例独立临时目录并完整回收自己的进程；隔离回归和真实启动/描述符回归随后在1.96秒内通过。清理超时fixture使用shell内建命令先记录调用，避免Python冷启动本身耗尽5秒的客户端上限。

最终完整门禁、运行副本核验和恢复结果将在完成后补记。

## 最终门禁、部署与恢复结果

最终 tests/run-all 在 /private/tmp/ck-tests-i8imf9gu 返回 0，终端标记为 ALL STAGES PASS，共 46 个阶段通过。语法、四种工具集成、headless、故障注入、conformance、额度窗口、燃料保留、交互让位、ZCode 会话及 watchdog 部署均通过；git diff --check 通过，冻结的 88 个源码/配置文件 SHA-256 无漂移。阶段日志和核对摘要见该目录的 verification.json 与 source-sha256.json。

已按冻结快照同步本机运行副本：三个 launchd 作业均加载预期的 program/arguments，工作日策略为 CODEXC_ACTIVE_WINDOW=23:00-09:00、CODEXC_ACTIVE_TZ=Asia/Singapore；watchdog 活动 PID 与 watchdog.lock.flock 一致，桌面二进制哈希一致，共享 helper 无漂移，旧的未受管 watchdog 不存在。macOS ps 不暴露完整进程环境，因此只把 launchctl 已加载环境、源码哈希和锁归属作为证据，不把不可见字段宣称为已观测。运行核验输出为 /private/tmp/ck-quota-runtime-after-20261112.json。

六个因真实 ZCode 内置 provider 定位错误而暂停的项目已逐项复核，并原子备份旧 loop.halt 后交给 watchdog 调度；队列、journal 和 pending 验收收据在修复前后哈希一致。恢复不是直接并发启动。随后观察到它们分别因新的、独立的认证失败、gate 修复失败、审查结论不可解析或缺少变更证据而再次暂停；这些暂停被保留，不能把“解除旧暂停”误报成“已稳定完成”。每个恢复备份和后续状态见 /private/tmp/ck-provider-restore-applied-20261113.json 与 /private/tmp/ck-quota-final-observation-20261113.json。

最新只读晨报 /private/tmp/ck-quota-final-morning-20261113.json 覆盖 21 个项目，没有读取错误；最近 6 小时记录到 37 条带收据的验收和 35 条待决策事项。认证、审核、额度、人工交互及缺少证据的暂停都仍然是暂停，不会因燃料轮换被自动清除。当前 root 会话的交互 lease 在完成核验后释放。
