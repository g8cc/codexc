# Changelog

## v2.1.0 (unreleased)
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
