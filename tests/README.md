# tests — CodingKeeper harness

一条命令跑全部验证: `tests/run-all`（或分阶段: `tests/run-all unit` 等）。

| 阶段 | 内容 |
|---|---|
| syntax | Bash 语法、Python 编译、Swift typecheck |
| watchdog | 看门狗自测 |
| unit | loop/headless 内嵌单元测试 |
| audit | 启动、验收、loop/daily、适配器、桌面、watcher、测试进程清理行为回归 |
| integration | Codex/Claude/Pi/OpenCode 四组并行的真实 tmux 场景及 headless 集成 |
| faultinjection | 进程终止、欺骗、超时、队列改写等故障注入 |
| conformance | 文档约定与实现核对 |
| keys | 本地二进制/配置存在性报告，不调用模型 |

`tests/run-all` 自动创建私有 HOME、状态目录、tmux socket 和进程组；退出清理自建进程与服务。输出中的 `Test artifacts` 目录保留各阶段完整日志。Swift 首次编译取决于本机缓存，完整集成需要数分钟以上。

规则:
- 任何阶段失败即整体失败（CI 可直接用作门禁）。
- integration 阶段零 API 依赖（假 worker/假审查），可在无网环境跑；
  真实凭证类验证归 keys 阶段（报告性）。
- 新增工具适配时: 单元进对应脚本内嵌 selftest，场景进对应集成套件，
  并在 tests/conformance.sh 增加该工具的声明核对行。

## 提交门禁（pre-commit hook）

`.githooks/pre-commit` 在每次 `git commit` 前自动跑 syntax + unit + conformance
（首次 Swift 编译耗时取决于缓存），任何失败都会拦截提交。启用（每个克隆一次性）:

    git config core.hooksPath .githooks

integration / faultinjection 耗时长（15min+），不进钩子，发布前手动
`tests/run-all` 跑全量。紧急提交可 `git commit --no-verify` 绕过，但别养成习惯。

## 共享库 ck-common.sh

三车道（codexc-loop / codexc-headless / codexc-daily）共用的队列/gate/审查/
标记/迁移/登记等语义只维护在 `ck-common.sh` 一份里；车道差异（日志标签/
通知标题/报错前缀）由 source 前设置的 `CK_LANE` 派生。改这些语义时改库 +
跑两车道测试，不再各抄一份。

新增回归也可单独运行，例如 `python3 tests/startup-audit.py`、`python3 tests/acceptance-audit.py`。全套测试不使用真实模型凭证。

## ZCode 套餐时段回归

完整入口 `tests/run-all` 包含 `window-audit.py`、`zcode-window-audit.py`、`watch-window-audit.py`、`zcode-quota-audit.py`。使用假 worker/reviewer、固定测试时刻及私有项目，覆盖 23:00/09:00 边界、中途截止、人工停止、重启后配额等待、watchdog 禁止跨时段复燃以及套餐通知分类；不会通过这些用例请求真实模型。

本轮新增 `leaf-runtime-audit.py`、`review-leaf-audit.py`、`leaves-audit.py`，覆盖候选绑定、脏树空跑、事务恢复、队列格式/多行合同和模型输出失败语义；均使用临时仓库与假 CLI，无真实模型请求。统一入口仍为 `tests/run-all`。
