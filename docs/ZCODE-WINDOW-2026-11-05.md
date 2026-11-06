# ZCode 夜间套餐越界运行修复 · 2026-11-05

用户套餐每天 UTC+8 的 23:00 生效，次日 09:00 结束。本次只处理 `zcodec run` / `ck zcode run` 及其 watchdog、worker、门禁、独立审查和桌面状态。Codex 手动会话、ZCode 网关与领取服务没有被停止；`codexc-daily` 属于 Codex，未改动其调度。

## 已确认的根因

1. 原 `zcodec run` 虽叫夜间 runner，但没有可用时段检查，worker、门禁、审查都可跨过 09:00。
2. quota 被当成暂时故障，等待 10/20/30/40 分钟后直接恢复，没有等待下一次套餐生效。
3. 旧 watchdog 仍持有旧脚本，下午继续清除暂停并拉起三个项目，日志重复计为复燃 #0。上一轮只更新源码，没有让这个旧实例退出，运行中行为没有随源码更新。
4. 本地网关将“套餐尚未生效”转换为 HTTP 200 的说明文本；worker 当成正常响应，runner 又因缺少完成标记进行重试。
5. 存活、退避等待与正在执行混在状态里；另外存在两个桌面横幅实例。

09:00 后的日志有 158 条 headless `turn started` 记录，最后观测到 17:26:42；旧 watchdog 17:29 仍在复燃。17:30 的进程快照中三个 runner 都只有 sleep 子进程，16:34–17:29 的只读记账总量稳定为 290.0M。因此可确认时段外启动和重试，不能将这些记录或横幅直接等同于持续计费。

## 已实施的控制

- `zcodec run` 默认窗口为 `[23:00, 次日09:00)`，明确使用 `Asia/Shanghai`。窗口外只等待，不启动任务；非法时段、时区、策略读取失败均停止执行。
- worker、gate 和串行/并行 reviewer 在启动前、执行期间及接受成功结果前检查。到点或人工 halt 终止自身子进程树，返回独立的中止结果；未完成的队列不标完成。
- quota 写入 `.codingkeeper/quota-until`，在下一次开放前不重试，跨进程重启仍有效；同样覆盖 gate/review 的修复回合。`CODEXC_AUTO_RESUME=0` 保持人工恢复语义。
- watchdog 的复燃与探测都检查窗口，不清除项目 halt；日常记账显式只读。
- 精确识别完整的未生效通知和失败态 1005/1006，普通模型正文讨论配额不会被误判；通知不会替换有用的会话 ID。
- 状态区分 `waiting_window`、`waiting_quota`、`backoff` 与实际执行。等待时 `active=false`，桌面及 CLI 都显示原因；桌面使用进程锁避免新版本双开。

上述截止控制停止本机受管进程；已经提交到服务端的请求是否立即取消、是否计费取决于服务端，不能从进程状态保证远端计费结果。

## 运行状态与验证

已按 PID、命令和工作目录核实并暂停旧 watchdog 47420、fingerprint 37232、sale 41882、soul2soul 42065；停止了其 8 个受管进程，保留原状态备份于 `/private/tmp/ck-zcode-paused-tvmwwc3u`。未改项目队列或代码。

修复在 `/private/tmp/codexc-window-ayy76mek` 独立开发。新增窗口核心、ZCode runner、watchdog 和错误分类回归均使用假 worker/reviewer 及隔离项目，不依赖实际套餐请求。完整 `tests/run-all integration faultinjection watchdog unit audit conformance keys syntax` 已结束，退出码 0，`ALL STAGES PASS`。针对本问题的四套新回归共 **65 项**（23+17+14+11）全部通过；桌面 13 个数据/UI 场景及单实例竞争、崩溃恢复、软链拒绝检查通过。既有四工具集成、headless、故障注入、40 项 conformance 及 Bash/Python/Swift 编译检查也全部通过。完整日志：`/private/tmp/ck-tests-41fwfaar`。

真实安装检查还发现 macOS `/dev/fd/9` 的虚拟设备号导致 Bash `-ef` 误报 watchdog 锁丢失；已改用描述符 `fstat` 校验，并补充完整 `run → Python → Bash` 入口的启动、互斥、重启和锁不继承回归。横幅通过真实 GUI 进程采样确认进入绘制/事件循环，并确认主实例持锁、第二实例退出 0；安装验证改为等待实际锁持有人，避免将尚未完成初始化误认为单实例失败。

最终实际运行复核（2026-11-05 18:24，UTC+8）：

- sale、soul2soul：`waiting_window`、`active=false`，下次开放为当日 23:00；已安装的 `zcodec status` 同样显示“等待时段”。
- fingerprint：修复前已经存在的暂停被保留，`parked=true`，未擅自恢复。
- 新 watchdog PID 49912 正常存活；桌面实际持锁 PID 29289，第二实例退出码 0。
- 这两个受管 runner 的进程树中模型 worker 数量为 0；未使用真实模型请求验证套餐。

运行验证记录：`/private/tmp/ck-window-final-k5jjsxmo/verification.json`。GUI 采样：`/private/tmp/ck-desktop-probe-64qo394w`。源码切换前备份：`/private/tmp/ck-before-window-hv4abd9y`；旧桌面二进制备份：`/private/tmp/ck-window-installed-_nst6eif/CodingKeeperBar.before`。临时目录可能被系统清理。本轮未修改项目任务队列，未提交或推送 Git。
