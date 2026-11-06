# Fingerprint / UDFE 自动叶子审计

审计日期：2026-11-05。只读源码基线：`89b4aa9`。完整阅读了 `AGENTS.md`、queue/gate/review/journal/quality-leaves 映射及以下代码、测试、历史 commit。外部 `loop.halt` 原本存在，status 为 `parked / active=false`；本次保留暂停，未运行真实模型或修改外部仓库。

**结论：旧队列大部分已经落地，其中确有安全和正确性收益，不能统称垃圾；但它已不能指导下一步。** 21 条 `[x]` 仍挤在 ready，6 条 `[ ]` 被塞进 done，后续重要修复只记录成 idle。相比继续“全 handler/全重试/全时间极值”扫描，完成现有 iOS SDK 半成品和修复 iOS 重试协议更直接影响真实接入。

## 当前基线与验证边界

- 外部 dirty 两文件为 `sdks/ios/Sources/DeviceFingerprint/DeviceFingerprint.swift`（36+/12-）和 `HttpTransport.swift`（30+/12-）。这些是既有 WIP，本次未替用户提交、回滚或重写。
- 本轮实际执行只读测试：`node --test --test-reporter=spec test/security/secrets.test.mjs test/security/sdk-secrets.test.mjs test/unit/eng-deadcode.test.mjs`，**7 pass / 0 fail / 0 skip，302.8ms**。另外 `bash -n .codingkeeper/gate.sh .codingkeeper/review-leaf.sh` 退出 0。
- 本轮实际运行 `swiftc -typecheck -module-name DeviceFingerprint -module-cache-path /private/tmp/leaf-audit-fingerprint-swift-modules sdks/ios/Sources/DeviceFingerprint/*.swift`，**退出1，明确报 `DeviceFingerprint.swift:96:35: missing argument for parameter 'method' in call`**。仅模块缓存写到临时目录，外部源码未改，复核git status仍为原两文件。
- 未执行完整 `npm test`，因为它先编译并写 `dist`，多项 SQLite 测试还会写项目 `data/`；本轮外部仓库只读。Git message 中 106→207 green 是历史作者记录，不是本轮完整复测。
- `package.json:16` 的 gate 编译 TypeScript 后跑 Node 单测/集成/安全/perf/web SDK；**不编 iOS、Android，也不运行 desktop 独立测试目录**。因此 XPROJ-01 通过不能推出四平台 SDK 可交付。
- `AGENTS.md`/queue 仍写“106 项”基线，Git 历史最后称 207；它们没有给出不可删测试的机器可比 manifest。数量不是验收面的替代品。

## 逐叶处置：ready 的 21 条历史已勾项

| 原叶 | 源码/测试/历史证据 | 价值、缺口与处置 |
|---|---|---|
| ENG-04 | journal 11-04 07:58 accepted；`61e2189` 记录初始 106 通过。 | 一次性基线有价值，归档；不重开基线叶为消费额度。历史数字不保证当前 iOS WIP 可编。 |
| SEC-BE-03 | `f9b04c3`、`424ecc6`；`test/security/secrets.test.mjs` 三检查；本轮这三项通过。 | 防意外凭证入库有价值，保留。但“模式未命中”不等于数学意义的无密钥：PLACEHOLDER 正则按任意子串 `test/example/...` 放行；JSON 与文本有范围/长度跳过；忽略规则测试只断言 untracked。归档为有限规则保护，不继续泛化“密钥=0”。 |
| SEC-BE-01 | `36f0807`；`injection.test.mjs:69/104/128/162/184/198/238` 覆盖 SQLite 值、WHERE、IN、LIKE、审计、LIMIT。 | 存储攻击面真实，负例有行为判据，历史完成归档；不重复添加同一 SQL 字符串矩阵。 |
| SEC-BE-02 | `915dd39` 8 组鉴权矩阵；后续 `c719d29` 才修 risk/evaluate 跨租户，`fbfb711` 更正 allowManagement 仅限 audit-logs 的契约。 | 有价值但原“管理接口100%”过度概括；apps 没有运行时创建/吊销 API，不能为任务臆造。按当前路由权限矩阵归档，包含后续修正，不能用初次 accepted 证明不存在 IDOR。 |
| BUG-BE-03 | `6faef1a` + `invalid-payload.test.mjs` 空体/字段/类型/超大/嵌套/chunked；后续 `b416389` 与 `8a05a34` 增加配置键数与 SDK header 上限。 | 有实际请求边界收益；与 EDGE-BE-01/05 有交集但并非全重复。按具体回归案例归档，停止泛列“任何非法输入无500”。 |
| SEC-FE-02 | `6055946`；SDK 扫描覆盖四平台，本轮 3 pass。 | 硬编码 secret 保护有价值；“真实 endpoint host 即凭证”的单独断言过宽，公共服务地址不是 secret。保留现有保护但不要新增把端点配置正常化当安全漏洞的任务；不能证明运行时传入/打包 secret 安全。 |
| EDGE-BE-01 | `f734982`、`2fe9e1d`；`edge-missing.test.mjs:192` 的畸形 URL 编码已锁定 400，含真正 decodeURIComponent 修复。 | 已有具体用户输入故障修复，保留历史；重复空对象矩阵与 BUG-BE-03 合并看待。 |
| EDGE-BE-04 | `68b951e`、更正事实的 `919b0b7`；`edge-numeric.test.mjs` 测签名时间、confidence、risk、limit；client_time 明确不消费。 | 有边界收益，但不要往未消费字段写时区/溢出逻辑。按实际认证时间与算法数值边界归档。 |
| EDGE-BE-05 | `43be455`；`edge-strings.test.mjs` 空/1MB/NUL/emoji/RTL/有界 sink；放宽 body 上限验证截断同 token。 | 有限矩阵有价值；原“全部字符串无崩”不能成为无限注入入口，保留当前回归即可。 |
| BUG-BE-04 | `91fb4cd`；`60f6a76` 修复 before/after 引用同对象造成的空断言；`idempotency.test.mjs:45` 已快照原值，后续 `a41dadb` 再修并发副作用。 | 真正关键的业务语义，但初版 accepted 并不充分。以串行回放与并发执行两层证据归档；不要重复“同 token”当无副作用。 |
| SEC-BE-05 | `6bd2eef` 实际增加 `Retry-After`；`ratelimit.test.mjs:15/39/51` 检超限、非429不带头、app隔离。 | 有可见收益且范围适中，历史完成保留。 |
| STAB-BE-01 | `ab4cfe3`；无 server 网络下游，SQLite `busy_timeout=5000` 已有；`outbound-timeout.test.mjs` 持锁300ms后释放，只断写成功且 elapsed≥250ms。 | **原验收证明“会等待”，没有证明“最多等5s”**：将 busy_timeout 改为极大值也能通过。归档为部分证明，补一条精确上限测试候选 FP-SQLITE-BOUND，勿再巡查全仓“出站”。 |
| STAB-BE-04 | `12d428f`；真实子进程 SIGTERM，半发送 body 已受理，停止监听→请求完成→退出0；空闲关停另测。 | 有真实生命周期收益，适合保留；覆盖声明限于这些场景，不自动推及磁盘故障等。 |
| STAB-BE-05 | `5e6ea68`；`checkHealth` 读 sqlite_schema，测试破坏临时 SQLite/WAL/SHM 后 ready503/live200。 | 修掉静态 readiness 假绿有价值。`PRAGMA shrink_memory` 每次驱逐缓存是为满足原地破坏场景的实现取舍；尚无性能测量，不本次另开泛优化。 |
| ENG-08 | `517e0c8`、`05809e5` 真修 token 子串及未匹配路径原样入日志；`log-privacy.test.mjs:117` 起真实流逐行 JSON.parse。 | 隐私与可观测性都有收益，保留；OBS-01 的“单行JSON”大部分已覆盖。标题 PII=0 只限已验证入口，不宣称全部外部依赖日志。 |
| PERF-BE-01 | `adb1185` 最初共享一个 idempotency key，999/1000请求走回放；`1428854` 修成 body factory，`p95-budget.test.mjs` 现有200ms/500ms断言。 | **最初数字不是注册真实路径性能**，不可继续引用1ms为真实注册基线。现测试是 memory store + server x-processing-ms + 同环境设备，并非部署SQLite容量。归档时带更正；不重做同一性能叶。 |
| ENG-02 | `1216577`；`eng-typecheck.test.mjs` 再 execSync tsc--noEmit；`npm test` 已先 `npm run build`/tsc。 | 在正式 gate 中重复完整类型检查，新断言正常情况下在 tsc 编译失败时根本跑不到。已完成但收益低，停止追加此类测试；后续有计时证据再合并入口，不违背现有禁止删测试约束。 |
| ENG-07 | `0b05457`；`eng-deadcode.test.mjs` 自建导出/import正则+大豁免表，本轮通过。 | 只证明“导出被文本引用或豁免”，测试专用引用也算，非完整死代码证明；新增约200行扫描器并没有发现用户故障。低收益完成归档，不扩成全仓清理项目。 |
| ENG-05 | `2fd50c2`；README树/命令名/flag/路由存在性检查。 | 防入口文档腐烂有价值；不等于“所有命令复制就能成功”：只验证 npm script/flag 存在和路由非404。按此有限范围归档。 |
| XPROJ-01 | `1d5125a`；真 web/desktop SDK调用及 wire response 子集，字段缺失/类型变更有区分力。 | 已实现合同范围内有价值，但只覆盖两个平台，漏掉 iOS 旧路由和当前编译缺参。原叶归档为 web+desktop 子集，iOS另用具体修复叶，不能把“四端SDK”都算过。 |
| BUG-BE-06 | `247f8a7`；`edge-time.test.mjs` canonical UTC、两TZ子进程、过期与窗口。 | 有序列化/存储比较收益；R004 测9min/11min而非恰10min，标题“exactly”过强；getIdempotency“exactly-now”用了墙钟推进，边界证明应谨慎。不再新建 EDGE-BE-06 同文件矩阵。 |

## 逐叶处置：done 分区的 6 条未勾项

这些不是 completed。原 queue 的 `(空)` 后面却跟 6 条 `[ ]`，状态与目录语义冲突，必须保留原状态理由。

| 原叶 | 核实结果 | 处置 |
|---|---|---|
| EDGE-BE-02 单元素集合 | 没有 `edge-single.test.mjs`；apps registry 真实输入是 appId→entry 对象，没“并发创建 app/批量接口”。真实事件集合查询已有空/范围测试，但不能据此宣称全部0/1/2已测。 | 归档“输入形态错误/无具体缺陷”，不是 done；将来具体列表 API 出现再限定端点。 |
| EDGE-BE-06 时间极值矩阵 | 同文件 `edge-time.test.mjs` 已被 BUG-BE-06 占用；签名 Unix极值在 EDGE-BE-04；client_time 不被消费。 | 归档“与 BUG-BE-06/EDGE-BE-04 重叠”；未验证闰日/DST不可伪称覆盖，当前没有基于这些未消费输入的需求。 |
| STAB-BE-02 重试语义 | server 没外部网络重试，SDK却确有网络/5xx重试。iOS 在 send 一次生成 headers，HttpTransport每次复用；server签名器先占 replay key。 | 撤销泛审计任务，替换为 FP-IOS-RETRY 真修复；jitter 无已证实事故，暂不夹带进该叶。 |
| STAB-BE-06 并发写 | `a41dadb` 已用 inFlightIdempotency Map +8并发屏障用例锁单实例collect恰执行1次；SQLite同环境 upsert在 `sqlite.test.mjs:112` 已有。不存在运行时 app配置写接口。 | 移 review-needed 核精确 `a41dadb`；随后归档为“单实例同幂等键副作用”，不称跨进程恰一次或全存储无丢写。 |
| PERF-BE-02 p99 | `1428854` 已在 p95-budget测试增加p99≤500ms，尾部600ms注入的历史记录有区分力。该提交同时把 burst rps下限500→30、请求3000→1200（并发1000保留）。 | 已实现待精确验收，不能重做。门槛变更虽有“原回放基线不真实”的理由，仍违反当时禁止改阈值的合同，必须单独认定新负载/下限的依据，不能凭全绿抹平。 |
| OBS-01 结构化日志 | `logger.ts:62` JSON.stringify+newline；ENG-08真实请求日志已逐行解析；`edge-time.test.mjs:326` 校验ts。 | 归档“绝大部分重复，无独立用户结果”，不再建 obs-structured-logs 副本。level若确有缺口可并入现有logger断言，不能升级成自动巡查项目。 |

## idle 不是无价值，但现在的记录方法丢失问题身份

journal 的五条 `(idle 持续改进)` 对应期间确有真实成果：`c719d29` risk跨租户、`d5ff80d` 幂等响应明文token落盘、`e9e2bea` account-hash跨租户删除/风险污染、`b416389` 配置上限未执行、`8a05a34` 无界SDK版本存储，随后还有perf harness与并发幂等。无法仅凭时间把每次 accepted 精确映射提交，因此不伪造逐轮归属。应把提交/测试证据归回对应问题ID，保留历史，不再靠匿名 idle 扩充队列。

## 下一步应解决的具体问题

1. **完成 iOS 既有 WIP。** HEAD 的 revoke/delete 仍是不存在的 `/v1/fingerprints/revoke|delete`，server 只接受 `/v1/devices/:token/revoke`、`DELETE /v1/users/:user/device-data`（`server.ts:228/238`）。WIP 正在修路径/编码，但 `DeviceFingerprint.swift:96` 的 collect 仍调用 `send(path:payload:)`，新签名 `:197–200` 要求必填 `method`；本轮Swift类型检查已真实复现缺参错误。先完成这个已知半成品并加真实三操作契约，保留用户原改动。
2. **iOS 响应丢失后的重试失效。** `DeviceFingerprint.swift:204–224` 在重试前一次生成requestId/timestamp/signature，`HttpTransport.swift:96/114/133` 原样传headers；`signature.ts:99–104` 每次有效请求占requestId。首请求已被服务接收、客户端没拿到响应时，第二次相同requestId返回DFP_4013，无法利用业务幂等恢复。desktop/web/android已有逐attempt签名设计，可沿用协议而不是重新发明。
3. **SQLite 等待上限测试缺口。** 实现有5000ms预算但当前测试只测下限，适合一条小范围补证任务，不扩展为超时系统重构。

以上具体叶与旧状态归档见 `fingerprint.queue.md`。当前暂停保留；尤其存在外部WIP，不能自动 `stash/reset/checkout` 追求干净工作树。

## 审查器的独立风险

两仓共用 v3 review 包装器：只看 recent-3而不绑定叶级SHA；codex 分支无条件exit0；zcode `--mode yolo` 不是只读；模型退出码没有成为wrapper退出码，末尾rm成功可掩盖失败；含“基线核验/复核/不改代码”的文字分类与“写新测试”的任务并不一致。这个脚本没有证明上层runner错误接受，但它自身不足以作为可靠验收。精确SHA、所需SDK检查、缺失BUGS/非零失败闭合应由控制器统一落实，不再给每个项目各造一轮模糊“审计门禁”。
