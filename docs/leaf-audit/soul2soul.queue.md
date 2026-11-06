# Soul2Soul 精炼队列草案（未应用）

基线：`bfa860a`；保留外部 runner 的 23:00 等待状态。这里的 ready 表示任务足够具体，不表示已授权修改外部项目或恢复 runner。证据来源见同目录 `soul2soul.md`。一叶一个明确用户结果，范围按必要修改界定，既有测试不删/skip；没有异常基线时允许零产品改动，不为产提交扩写扫描器。

## ready

- [ ] S2S-SEC-01 跟踪文本中的运行凭证检测（P1）
  - 目标：防止签名口令、TURN secret、API bearer/private key 意外入库；当前未宣称存在泄漏。
  - 范围：已跟踪文本、现有 `.gitignore` 与签名守卫；公共 CA PEM、精确的 example/test fixture 允许。扫描只输出文件/行号/规则，不输出值；不读真实未跟踪 `.env`/keystore，不改签名或凭证。
  - 验收：列出扫描文件数、跳过类型与 finding 数；用独立临时 fixture 注入三类假凭证必须检出、示例与公有证书不得误报。零 finding 就归档证据，不强制加 Kotlin 测试；若确有泄漏，立即记录文件/规则并停止传播，凭证轮换另行处理。若增加持久守卫，复用现有验收入口且不弱化 gate。
  - 依赖：控制器先确认 gate/review 能保留精确范围及结果；不要再次重复 BAT-01 的 keystore ignore 检查作为新收益。

## review-needed

- [ ] BAT-03-R 验收已经提交的 WebRTC 回归锁（P1；不是重做 BAT-03）
  - 目标：防止同一叶重复实现，并澄清“2s RTT polling / 10s 详细诊断”口径。
  - 范围：精确审阅 `bfa860a^..bfa860a`，以及其依赖的既有 BatteryTimers/VideoTraffic/ICE 测试；只修这次新增测试真正的假断言。
  - 验收：当前 SHA 的 T1 明确 PASS，T0/T2/T3 按现有 gate 有实际结果；记录新增测试证明的回归面、与 BAT-02 重叠面。不得把“出现 if 字符串”当运行行为或把 12fps 写作已锁定而断言只要求小于30。若未改产品参数，结果必须写“无耗电 before/after，回归锁已核验”。
  - 依赖：可用 JDK17/Gradle/SDK；SKIP 不得通过；审查必须绑定本提交，不能看 recent-3 后泛报 BUGS:0。

- [ ] S2S-DEVICE-POWER 兑现现有 V-05/H5/H6 的真机验收（P1；有设备后执行）
  - 目标：确认 11-02 待机降频/释放锁实际减少耗电，同时保持来电、会话和锁屏恢复可用。
  - 范围：复用 `docs/VALIDATION-TODO.md` V-05、`docs/HANIS.md` H5/H6、`docs/MEASUREMENT.md` 既有流程；不新增重复状态机或先改频率。
  - 验收：记录源码 SHA、APK SHA、双设备型号/ROM、网络、是否充电、持续时间；执行现有 V-05 规定轮次并保存电量/温度/会话与自然待机断线结果。比较仅使用同条件可比 baseline；无 baseline 就产当前绝对读数，不声称优化百分比。H5 接听/通话存活独立记录，不能用功耗低掩盖消息不达。
  - 依赖：设备可用、按 AGENTS 取得当次装包同意（若需装包）；无设备保留待执行，不交自动模型空转。

## done

以下只转录历史 accepted，不代表本轮重新实测。

- [x] ENG-04 历史基线：journal 2026-11-05 01:54:45；后续任务正常跑基线即可，历史层级数字不足。
- [x] BAT-01 回归守卫：`12c41f1`；journal 08:13:40；产品未改变，不计新耗电收益。
- [x] BAT-02 定时器理由/回归守卫：`886a1db`；journal 08:45:02；主要为注释和测试。

## archived-with-reason

- BAT-03 原自动实现项 → BAT-03-R：已有 `bfa860a`，缺独立验收，未标 done。
- BAT-04 → 归档“状态输入不适配 + 既有 StandbyPolicyTest/BatteryTimersTest 覆盖”；真机证据归 S2S-DEVICE-POWER，不新造充电状态机。
- BAT-05 → 归档“WifiLock 没有 timeout overload + BAT-01 已验配对”；不强制定期掉锁。
- SEC-BE-03 → 替换为 S2S-SEC-01；不强制跨语言扫描装进 JVM 单测。
- STAB-BE-01 → 归档“所选模块为纯函数/本地 HMAC，无请求超时可补”；不等同全服务器无任何 I/O 风险。
- ENG-02 → 归档“无 warning 基线、无具体兼容性/错误行为”；不泛化清零。
- PERF-BE-01 → 归档“缺具体信令工作负载与用户预算”；有真实延迟证据再立项。

本文件保留审计时的方案；最终应用内容以 `prepared/soul2soul/.codingkeeper/queue.md` 为准。
