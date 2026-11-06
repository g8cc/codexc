# Soul2Soul 自动叶子审计

审计日期：2026-11-05。只读基线：`bfa860a4d4f7770417f5b93f5f89ea1bed084fd1`，App 源码版本 `0.2.72 / 72`。读取了仓库 `AGENTS.md`、framework 工单合同、完整 queue/gate/review/journal，以及下列实现和测试。未调用模型、运行 runner、修改外部代码/队列/服务或触碰设备。

**结论：不应继续按原来的 7 条未勾叶自动烧。** BAT-03 已有实现，BAT-04 的状态维度不对应当前策略，BAT-05 的 timeout 要求不符合 WifiLock API，server 超时叶选的是纯计算模块，warning/perf 两叶尚无明确缺陷或用户预算。电量下降、发热和通话可达性仍缺真机证据；追加常量/注释扫描不能替代这些结果。

## 状态与验收可靠性

- `ready` 有 10 条：3 条 `[x]`、7 条 `[ ]`；`review-needed`、`done` 均空。journal 只有 ENG-04、BAT-01、BAT-02 三次 accepted。BAT-03 在 Git 中已提交但 queue/journal 未同步，不能直接重复实现，也不能因为有 commit 就补成 accepted。
- status 仍为 `waiting_window`，描述“套餐未开放，等待 23:00”，`active=false`；本次未改变。
- 已执行 `bash -n .codingkeeper/gate.sh .codingkeeper/review-leaf.sh`，退出码 0。未执行完整 gate：它会写 Gradle 构建产物等，且本次仅获准只读外部仓库。因此下文历史全绿只归于历史记录，绝不代表本轮实测。
- gate 仅 `exec bash scripts/test.sh`。`scripts/test.sh:75–90` 只在 FAIL 时置非零，T1 缺 Gradle/JDK/SDK（`:679–690`）返回 SKIP 后可整体 rc=0。**BAT/Android 叶需要显式 T1 PASS，不能只看 gate 退出码。** 默认 T4 在 `:83` 直接不执行；电量、手感、实际接听与自然待机均不在这个门禁的证明范围。
- review 包装器不是可靠的叶级证据：`:21/34` 只要求 `git log -3 -p`，没有精确的本叶 base/head；纯审计/基线与“预期有改动”通过文本关键词区分。无改动达标的审计可能落到错误分支。`:25` 在 codex 后无条件 `exit 0`；zcode 用 `--mode yolo`（`:36`），子进程状态只进错误描述，末尾 `rm` 的成功可覆盖失败。没有证明上层已严拒缺失/非法 BUGS，不能据此断言每条 accepted 都无效，但门禁本身不提供该保证。
- `AGENTS.md` 要求先测量、已达标零改动；BAT-01/03 实际仍新增 155/204 行文本扫描测试。这些可作为回归守卫的明确例外，不应包装成新的耗电优化或为了产 commit 继续扩张。

## 逐叶处置

| 原叶 / 原状态 | 真实证据与收益判断 | 建议处置 |
|---|---|---|
| ENG-04 / ready `[x]` | journal `2026-11-05 01:54:45` accepted；基线可防止把旧失败归责新任务。但 journal 没保存层级数字/耗时/源码 SHA，现有 gate 也可能带 SKIP 返回 0。 | 归档为“历史基线验收记录”，不得无限重复。下一次真正改码时正常跑所需基线并附 T0–T3 状态。 |
| BAT-01 / ready `[x]` | `12c41f1` + `BatteryWakeLockTest.kt`：PresenceService 带 6h timeout、5h 续期，解绑/待机/销毁释放；WifiKeeper 两调用者销毁释放已扫描。产品代码未改。测试用源码字符串存在性验证接线，不能证明每次真实生命周期已执行释放。 | 历史回归守卫归档，保留测试；不再作为优化任务重跑。不得声称已有电量收益。 |
| BAT-02 / ready `[x]` | `886a1db`：仅两处理由注释 + `BatteryTimersTest.kt`；3 个 <5s runner 是会话计时、录音手势、RTT，均有生命周期边界。待机 15min 已在原策略。`BatteryTimersTest:140–144` 甚至把 `RTT_POLL_MS=2000L` 和理由文本锁死。 | 已完成的文档/守卫归档；保留历史理由但不用“补注释=降频”计收益。后续仅实际唤醒/CPU 基线退化时开叶。 |
| BAT-03 / ready `[ ]` | `bfa860a` 已新增 `webrtc/WebRtcPowerTest.kt` 204 行；`getStats` 是 2s，详细诊断是 `5×2s=10s`。队列举例“stats interval≥10s”与真正测量对象模糊；已有 BatteryTimersTest/VideoTrafficPolicyTest/IceRestartBudgetTest 重叠。测试部分要求特定文本，不等于行为频率上限；例如静止 FPS 只断言 `<ACTIVE_FPS`，并不锁注释所称的 12。journal 尚无本叶 accepted。 | 移到 review-needed，精确审 `bfa860a^..bfa860a`。确认 RTT 与诊断口径并取得新 T1 证据；通过后以“新增回归锁、未改变功耗”归档。禁止再生成第二份测试。 |
| BAT-04 / ready `[ ]` | `PresencePowerPolicy.kt:3–15` 仅有 paired/sessionBusy 输入及待机常量；`StandbyPolicy.kt` 为心跳门控/单调时钟/补报策略，不存在前台后台锁屏×充电调频表。既有 `StandbyPolicyTest.kt` 已覆盖待机会话频率、唤醒锁与四组合心跳；BatteryTimersTest 补接线。 | 原叶撤出自动队列，归档“需求维度错误且与已有测试重叠”。不为了满足测试新造充电状态机。实际自然锁屏/耗电证据并入既有 V-05/H6。 |
| BAT-05 / ready `[ ]` | `WifiKeeper.kt:16–30` 使用 `WifiManager.WifiLock.acquire()`；它没有 WakeLock 的 `acquire(timeout)`。BAT-01 `12c41f1` 已明确这一点，`BatteryWakeLockTest:130–153` 已检查 SessionActivity/ScreenShareService 的 acquire→onDestroy release 和句柄清理。 | 原叶归档“不适用的 API 要求 + 已覆盖配对”。不得机械加周期释放，长通话可能因此失去防断流保障。未发现真实漏锁路径前不另开同义审计。 |
| SEC-BE-03 / ready `[ ]` | 有实际受保护资产：签名 keystore、TURN secret。`scripts/test.sh:275–286` 已保护 Gradle 内联口令与 ignore；跟踪文件含 `.env.example`/`keystore.properties.example`/公有 CA 证书，未发现通用已跟踪文本扫描。当前无“真实泄漏已确认”的证据。 | 保留但收敛为一次有限的已跟踪凭证保护，见草案 S2S-SEC-01。不得将整个 Kotlin 构建当扫描本身或把公共证书/配置字段名判作 secret。 |
| STAB-BE-01 / ready `[ ]` | 队列路径省略 `src/`；实际 `server/src/heartbeat.js` 是状态/间隔纯函数，`turn.js` 是本地 HMAC 签发，`call-lifecycle.js` 是信令生命周期辅助，不是远端 HTTP 客户端。网络心跳在 index.js 的现有 60s/15s、两次 missedPong 终止机制，已有 heartbeat/call-lifecycle 测试。 | 原叶归档“所选模块无出站依赖、无需 timeout 改码”；这不是宣称全服务器所有 I/O 都有上限。若将来接入真实外部服务再按具体调用建叶。 |
| ENG-02 / ready `[ ]` | 原框架 ENG-02 是 type error=0，本地被改为 Kotlin warning=0；`scripts/test.sh` 只要求编译/断言成功，没有 warning 预算或白名单来源。当前没有新 warning 数/用户故障证据。零警告易促成大范围注解和格式性改动。 | 归档为“无具体基线的低价值泛化任务”；只在具体 warning 指向兼容性、资源或错误行为时按问题命名开叶。 |
| PERF-BE-01 / ready `[ ]` | 项目主要是 WebSocket 信令，未指明“关键接口”、端到端还是服务端、消息类型、在线连接数、持久化数据规模；泛用 p95≤200ms 与伴侣端来电/恢复体验没有已知对应。媒体流是 WebRTC，测 server REST 不能说明媒体体验。 | 撤出 ready，归档“缺工作负载与用户预算”。如来电/信令可达性出现延迟证据，再对特定 signal 的发送→收到测量，不能凭通用阈值增造压测套件。 |

## 真正缺少的项目证据

`docs/VALIDATION-TODO.md:8` 已明确 2026-11-02 功耗代码完成但无 Mi10 在线 adb，V-05/H5/H6 仍待真机。当前继续扫描常量不会补足这一缺口。保留一条设备依赖的具体验收卡：同一安装包和已记录机型下采集自然待机、正常接听/共享/结束、温升电量与自然断线；按照现有 V-05 的轮次和字段记录，设备或 baseline 缺失就记未执行，不伪造 before/after。

另有文档基线漂移：VALIDATION-TODO 的页首仍称 0.2.66，而源码是 0.2.72、当前结论含 11-02 更新。实际执行设备验收前必须先写明 APK SHA/源码 SHA/设备版本，避免把不同版本证据拼成“通过”；无需独立开一轮大范围文档清理。

## 采用草案的条件

草案仅在主仓库供审阅，不是已应用队列。自动执行前由控制器保证叶级 base/head、代码叶所需 tier PASS、review 非零/无结果均不验收，并避免向等待 23:00 的 runner 原样投喂旧 BAT-03。可执行的凭证叶只有一条，已实现未验收与设备依赖分别保留；没有证据的新“持续改进”不自动转 ready。
