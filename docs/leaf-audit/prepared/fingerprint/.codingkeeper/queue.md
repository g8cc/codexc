# fingerprint 任务队列

本队列于 2026-11-05 完成源码与证据审计。原始 queue、gate、review wrapper 和审计记录保存在 .codingkeeper/audit/leaf-2026-11-05/（部署时生成）。历史勾选仅表示此前记录，不等于本轮重新验证。

只有 ready 内未勾选任务会执行；blocked 和 review-needed 由控制器核对依赖/证据后再转入 ready，不能按列表顺序假定依赖已经满足。叶子完整合同包含首行及其缩进续行。基线已经达标则记录 no-change 证据，不制造重复测试或空提交。保留用户已有改动，禁止按文件整体 checkout/reset 进行回滚。

## ready

- [ ] FP-IOS-CONTRACT 完成 iOS 三个公开操作的请求契约（P1）
  - 目标：iOS SDK能编译，collect/revoke/deleteData真正调用当前服务器路由。
  - 范围：现有 `DeviceFingerprint.swift`、`HttpTransport.swift` WIP及iOS契约测试/必要的测试fixture；沿用现有路径编码与method改造，不stash或覆盖原改动。
  - 已知缺陷：collect调用没有传send新增必填method；HEAD的revoke/delete旧路由返回404，WIP尚无验证。
  - 验收：`swift test --package-path sdks/ios`成功；从实际Swift公开SDK调用临时UDFE服务，collect200得token→revoke200→再collect得到新token→deleteData202并轮询完成。userId含空格、斜杠、中文时签名路径与实际URL一致且删到目标用户；原旧路径或错误method必使该用例失败。另跑现有 `npm test`；结果明示Node+Swift，不能拿Node全绿替代Swift。
  - 依赖：先登记并保留当前两文件WIP，使用可用Swift工具链与纯临时server/config/store；无需部署或真凭证。

## blocked

- [ ] FP-IOS-RETRY 首次响应丢失后使用新签名恢复同一业务操作（P1）
  - 目标：网络重试不被服务端重放防护拒绝、不重复产生collect事件。
  - 范围：iOS签名生成/transport attempt边界与对应测试；不更改服务端重放/幂等契约，不夹带jitter、跨SDK重构。
  - 验收：受控本地fixture让首次请求被真实服务受理但响应丢失，第二次必须携带新requestId和匹配签名、保持业务body/idempotency_key不变；最终成功且store恰1条collect事件。5xx最多2次重试、4xx零重试、completion恰一次；移除逐次签名则测试红于DFP_4013。运行Swift相关测试及现有npm test。
  - 依赖：FP-IOS-CONTRACT完成；`collectPayload:170` 已生成业务幂等键，必须保留同次业务操作的payload，仅逐attempt更新认证信息，不能每次重试重建业务key导致副作用重复。

## review-needed

- [ ] FP-SQLITE-BOUND 补齐锁争用最大等待的判别性验收（P2）
  - 目标：证明SQLite争锁最终失败/返回而不是无限阻塞；现有测试只有elapsed≥250ms。
  - 范围：`test/unit/outbound-timeout.test.mjs`与必要的store测试注入；不改变5000ms产品预算。
  - 验收：在worker持锁超过5000ms，另一写入在合理调度容差内以明确busy错误结束，worker主进程带独立hard timeout防挂；持锁300ms后释放的成功对照仍通过。临时把busy_timeout调大必须使新增用例失败，不能只断source常量存在。全套npm test通过。
  - 依赖：隔离临时数据库；先把该有限验证缺口从原“全部出站上限已证明”中剥离。优先级低于已知SDK坏路径。

- [ ] FP-REVIEW-CONCURRENCY 验收已有 `a41dadb` 并对齐旧STAB-BE-06状态（P2）
  - 目标：避免重复实现；确认单实例同key恰执行一次且失败后in-flight条目可清。
  - 范围：精确`a41dadb^..a41dadb`、既有8并发屏障用例、相关幂等失败/tenant隔离路径；无需新建concurrent-write副本。
  - 验收：记录单实例scope、同key collect事件恰1、不同tenant独立及异常后可重试；当前Node门禁通过后归档，缺证据则保留本项。不能扩大为多实例exactly-once。
  - 依赖：精确base/head审查；保留iOSWIP。

- [ ] FP-REVIEW-PERF 确认已有 `1428854` 的测量更正和预算变更（P3）
  - 目标：历史“真实注册p95=1ms”不再被引用，阈值更改不被全绿掩盖。
  - 范围：原p95/p99+load测试与该提交证据；不新增性能框架、不拿内存fixture数字当线上容量。
  - 验收：每请求独立业务key，确认确实走注册handler；分别记录memory/server处理时间与负载；说明burst 3000→1200及rps500→30的依据并由任务负责人认定新预算。p95200/p99500保持，旧回放基线标作失效；没有部署容量需求不再额外压测。
  - 依赖：先核新负载合同，不能靠复跑一次绿就把阈值变更视作已批准。

## done

下列保留原历史accepted，只有标明的3文件7项是本轮实测。旧数字与历史修复不隐去。

- [x] ENG-04：journal 11-04 07:58历史基线，当前另按所改平台测试。
- [x] SEC-BE-03：`f9b04c3/424ecc6`；本轮规则测试3pass，结论限规则扫描。
- [x] SEC-BE-01：`36f0807` SQLite参数化行为负例。
- [x] SEC-BE-02：`915dd39`并纳入`c719d29/fbfb711`后续对象级/权限契约修正。
- [x] BUG-BE-03：`6faef1a`，后续`b416389/8a05a34`配置上限与header入库边界另有证据。
- [x] SEC-FE-02：`6055946`，本轮3pass；真实host不是凭证，保留检查范围说明。
- [x] EDGE-BE-01：`f734982/2fe9e1d`缺省和编码路径400。
- [x] EDGE-BE-04：`68b951e/919b0b7`数值边界及事实更正。
- [x] EDGE-BE-05：`43be455`已验证字符串边界。
- [x] BUG-BE-04：`91fb4cd/60f6a76`串行幂等与快照断言修正；并发提交另待验收。
- [x] SEC-BE-05：`6bd2eef`Retry-After与隔离。
- [x] STAB-BE-04：`12d428f`真实SIGTERM排空。
- [x] STAB-BE-05：`5e6ea68`readiness实际查store。
- [x] ENG-08：`517e0c8/05809e5`日志字段/未匹配path隐私修复。
- [x] PERF-BE-01：历史已完成；原共享key基线失效，当前实现更正由FP-REVIEW-PERF处理，不重复实现。
- [x] ENG-02：`1216577`历史已完成但与build重复；不继续扩写。
- [x] ENG-07：`0b05457`有限导出扫描，本轮1pass；不是完整死代码证明。
- [x] ENG-05：`2fd50c2`README引用/入口存在性，不等于所有文档命令已真跑。
- [x] XPROJ-01：`1d5125a`web+desktop契约；iOS由FP-IOS-CONTRACT补实，不扩大旧结论。
- [x] BUG-BE-06：`247f8a7`UTC序列化与时间比较既有覆盖，按实际边界表述。

## archived-with-reason

- STAB-BE-01：曾accepted，但最大等待没有行为证明；保留`ab4cfe3`历史，待FP-SQLITE-BOUND，不重标完全done。
- EDGE-BE-02：未完成，原输入形态与真实API不符；不为0/1/2矩阵造批量接口。
- EDGE-BE-06：未独立完成，与EDGE-BE-04/BUG-BE-06重复；不向未消费client_time字段扩展业务。
- STAB-BE-02：未完成的泛审计替换成具体FP-IOS-RETRY。
- STAB-BE-06：已有`a41dadb`，由FP-REVIEW-CONCURRENCY补验，非直接done。
- PERF-BE-02：已有`1428854`，由FP-REVIEW-PERF补验，非直接done。
- OBS-01：现有ENG-08已逐行JSON.parse；不再写同义测试文件。
- idle后续成果：`d5ff80d`（幂等token密封）、`e9e2bea`（account-hash租户隔离）、`b416389`（maxFeatureKeys）、`8a05a34`（SDK版本限界）保留提交证据；journal缺精确映射，不假造五轮对应关系、不重复实现。
