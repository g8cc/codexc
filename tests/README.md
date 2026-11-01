# tests — CodingKeeper harness

一条命令跑全部验证: `tests/run-all`（或分阶段: `tests/run-all unit` 等）。

| 阶段 | 内容 | 耗时 |
|---|---|---|
| syntax | 12 个可执行件 bash -n | ~1s |
| unit | codexc-loop / codexc-headless 纯逻辑断言 | ~5s |
| integration | 4 工具 × 13 场景 (TUI) + 4 场景 (headless)，真实 tmux | ~15min |
| faultinjection | 7 项破坏性注入（进程杀死/欺骗/超时/改写） | ~3min |
| conformance | HANDLING.md 声明 vs 实际行为矩阵 | ~5s |
| keys | 各工具凭证/二进制健康检查（报告性，不计失败） | ~2s |

规则:
- 任何阶段失败即整体失败（CI 可直接用作门禁）。
- integration 阶段零 API 依赖（假 worker/假审查），可在无网环境跑；
  真实凭证类验证归 keys 阶段（报告性）。
- 新增工具适配时: 单元进对应脚本内嵌 selftest，场景进对应集成套件，
  并在 tests/conformance.sh 增加该工具的声明核对行。
