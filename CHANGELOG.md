# Changelog

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
