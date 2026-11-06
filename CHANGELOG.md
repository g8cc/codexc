# Changelog

## 2026-11-05 ZCode 套餐时段修复

- ZCode 自动任务默认限定 UTC+8 的 23:00–次日09:00，覆盖 worker、门禁、独立审查和 watchdog 复燃。
- 配额等待持久化到下次开放，修复套餐未生效通知被当普通失败反复请求；截止和人工暂停停止受管子进程。
- 等待/退避不再显示正在执行；桌面防止重复实例。

## v2.1.0 (unreleased)

2026-11-05 深度审计加固（[完整报告](docs/AUDIT-2026-11-05.md)）：
- 修复启动 watcher 阻塞、配置损坏、工具/参数/会话归属与 tmux 环境传播；配置编辑要求 Python 3.11+。
- worker/reviewer 退出码与协议双校验，修复后 gate 强制通过；每次投喂的新鲜度水位防止旧 DONE 被误验收。
- 跨车道原子锁、owner 清理、有效恢复预算、人工 halt 保护；补齐三工具 watcher。
- ZCode 输出文件解析及接力校验，安全安装路径，桌面有界后台读取与极端时间戳保护。
- `ck status` 单进程聚合：本机 100 项目离线基准中位 11.37s → 0.16s。
- 新增离线行为回归和独立 HOME/tmux 全套测试环境，keys 不再发送模型请求。

悬浮条任务面板 + 监督链路自愈（v2.0 的显示与监督体系全面落地）:
- 悬浮条任务面板: 空闲 3px 细线 / 悬停弹出状态计数 (品牌 logo + 转圈运行数 +
  暂停待处理数) / 新任务蓝闪·完成绿闪 4s (10s 去重) / ⛔⏸ 琥珀常驻警示 /
  点击展开自适应任务卡片 (状态色点 + 时长 + 完成时刻, 封顶半屏滚动)
- 生命周期: 会话退出自动收线 (心跳过期语义), 闲置会话持续等待不自弃
- 监督自愈: attach 补挂 watcher、rollout 发现 cwd 匹配 fallback (适配新版
  codex 日期子目录)、逐会话判活、回扫无窗口上限
- codexc 交互默认化: 默认纯交互不自动投喂, 无人值守显式 `codexc loop`
- 通知: 完成绿闪+系统通知、不可续跑错误常驻警示 (stderr 尾带回), 全局弹窗
  间隔总闸 (CODEXC_NOTIFY_GAP)
- 治理: 集成测试 /tmp 世界不再污染项目注册表; 交互会话注册补齐
- 无人值守韧性: 瞬时 park 有界自愈 (10/20/30/40min 退避, CODEXC_AUTO_RESUME) +
  worker 错误分类决策 + 回合心跳 + runner cwd 扫描锁 (双开竞态根治, 配合 tmux 脱管承载)
  worker 错误分类 (auth 即停/quota 等重置/transient 退避) + 回合心跳保活面板
- 产品命名入口: `zcodec`/`dshc` — 与 codexc 家族同构 (裸命令 = 非自动:
  zcodec 唤起 ZCode 应用 / dshc 打印说明, 绝不自动跑; `run` = 夜间 runner;
  其余保留动词或 CLI 参数透传), 补齐 `*c` 命名家族统一
- 诊断: zcode worker 失败带回 stderr 尾; 门禁加 swift -typecheck
- 修复: 投喂消息进程级单行化 (剥离 CR/LF) — 尾随换行被 send-keys -l 字面
  打进 composer 会被 TUI 当作换行而非提交 ("continue 已输入未发送");
  watcher 启动记录消息逐字节形态, 此类事故可直接对账

## v2.0.0 (unreleased)
多工具运行时（CodingKeeper 首个完整版）:
- 工具适配: claude / pi / opencode (TUI), zcode / dsh (headless), 六工具矩阵
- codexc-headless: headless 夜间通道（队列/gate/审查/burn 与 TUI 管线同语义）
- burn 模式（默认开）: 队列空闲自动投喂持续改进指令, 十维收尾审查
- 熄火保护: 连续空转自动停炉通知
- c 家族命令面: claudec / opencodec / pic / zcodec / dshc
- codexc fuel: 四工具燃料表（cc-switch 数据源）
- 可靠性: 新鲜度令牌(防陈旧误收)、runner 锁、kill_tree、双路径信任预种、
  符号链接/CJK 会话名、容量错误续命(rollout 尾检测)
- 测试: 4 工具×13 集成场景 + 7 故障注入 + headless 4 场景 + 一致性矩阵
- 文档: HANDLING.md 处理逻辑手册 + docs/ 体系

## v1.0.0
- 按目录 tmux 会话 + 429 自动续命 watcher + codexc-daily 每日恢复

### Leaf audit hardening (2026-11-05)

- ZCode defaults to queue-only execution and requires a configured gate.
- Capture exact leaf baseline/candidate evidence, detect verification mutation, and recover queue/journal acceptance transactions.
- Preserve reviewer failure/final-output semantics; add offline `ck leaves` audits and complete multiline task contracts.
- Reconcile project leaf queues and the 95-check candidate catalog with source evidence.
