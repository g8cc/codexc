# 工具矩阵与凭证（Tools & Credentials）

| 工具 | 通道 | 入口 | 错误续命源 | 凭证位置 | 当前状态 |
|---|---|---|---|---|---|
| codex | TUI | `codexc` / `ck codex` | rollout 尾 task_complete.error | ~/.codex（cc-switch 中转 127.0.0.1:15721） | ✅ 可用 |
| claude | TUI | `ck claude`（或 `codexc -T claude`） | JSONL isApiErrorMessage | ~/.claude/settings.json env（eazydata 中转） | ⚠ 中转曾宕机, 恢复即闭环 |
| opencode | TUI | `ck opencode`（或 `codexc -T opencode`） | opencode.db session_message 错误行 | ~/.local/share/opencode | ✅ 可用(真实E2E验收) |
| pi | TUI | `ck pi`（或 `codexc -T pi`） | stopReason:"error" | ~/.pi/agent（provider key 已失效→需重新登录） | ⚠ 待凭证 |
| zcode | headless | `ck zcode run` | 子进程 stdout/exit | 桌面应用共享登录 + zcode.cjs 自动探测 | ✅ 可用(会话接力实测) |
| dsh | headless | `ck dsh run` | 子进程 stdout/exit | keydrop 动态注入（失效→去 keydrop 刷新） | ⚠ 待凭证 |

## 钥匙自检

```sh
tests/keys.sh            # 各工具凭证健康报告
echo "Reply OK" | dsh --profile headless -     # dsh 钥匙快速自检
pi -p 'Reply OK'                               # pi 钥匙快速自检
```

## dsh 密钥说明

dsh 的 provider（keydrop-f6788e3a / keydrop-cparesid）配置在 `~/.dsh/settings.yaml`，
key 经 `apiKeyEnv` 由 keydrop 工具动态注入——失效的 `****DaUD` 需在 keydrop 里刷新。
认证失败形态: `dsh --profile headless -` 输出 `AUTH: Authentication Fails`。

## zcode 说明

- CLI 本体: 桌面应用自带 `/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs`，
  用 Node >= 24 运行；`ZCODE_CJS` 可覆盖。
- 会话库: `~/.zcode/cli/db/db.sqlite`（会话按 directory 字段绑定项目，只读查询）。
- 官方自动化文档: apps/zcode-cli/docs/usage（zai-org/ZCode 仓库）。
