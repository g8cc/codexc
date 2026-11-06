# 工具矩阵与凭证（Tools & Credentials）

本轮覆盖全部六种工具。下表表示离线协议与管控回归范围，真实服务与凭证未在本轮调用验证。历史在线验收和凭证失效记录不能代表当前状态。

| 工具 | 通道与入口 | 本轮离线覆盖 | 主要套件 |
|---|---|---|---|
| Codex | TUI：`codexc` / `ck codex` | 启动、当前轮完成/中止、重试、队列/gate/review、清理 | startup、loop-daily、四工具 integration、faultinjection |
| Claude Code | TUI：`ck claude` | 启动、sidechain 隔离、tool_use 非完成、错误续命及配额、验收 | startup、loop-daily、tool-watchers、integration |
| Pi | TUI：`ck pi` | 启动、toolUse 非完成、错误续命及配额、验收 | startup、loop-daily、tool-watchers、integration |
| OpenCode | TUI：`ck opencode` | SQLite 会话/完成读取、特殊路径、稀疏序号、原地流更新、错误续命、验收 | startup、loop-daily、tool-watchers、integration |
| ZCode | headless：`ck zcode run` / `zcodec` | sess_ ID、首次失败/超时续接、最终结果隔离、quota/auth、窗口/复燃、独立审查 | zcode-session、zcode-quota、zcode-window、watch-window、review-leaf |
| dsh | headless：`ck dsh run` / `dshc` | JSON 会话归属、原子保存/续接、超时前保存、final 隔离、失败分类、退出码及损坏文件 | dsh-session、edges、共享 headless integration |

dsh 协议已按本机安装的 dsh-headless 源码及 README 核对：`--json` 首事件为 session（sessionId/cwd），末事件为 final（text），turn_end.reason 与进程退出码共同表示成功。旧版本或自定义 profile 缺少该协议时适配器明确报错。ZCode 同样需要已核对的 stream-json 协议；离线假 CLI 无法证明未来版本保持兼容。

## 钥匙自检

```sh
tests/keys.sh            # 各工具凭证健康报告
echo "Reply OK" | dsh --profile headless -     # dsh 钥匙快速自检
pi -p 'Reply OK'                               # pi 钥匙快速自检
```

## dsh 密钥说明

dsh 的 provider（keydrop-f6788e3a / keydrop-cparesid）配置在 `~/.dsh/settings.yaml`，
key 经 `apiKeyEnv` 由 keydrop 工具动态注入；是否有效需另行在线验证。
认证失败形态: `dsh --profile headless -` 输出 `AUTH: Authentication Fails`。

## zcode 说明

- CLI 本体: 桌面应用自带 `/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs`，
  用 Node >= 24 运行；`ZCODE_CJS` 可覆盖。
- 会话库: `~/.zcode/cli/db/db.sqlite`（会话按 directory 字段绑定项目，只读查询）。
- 官方自动化文档: apps/zcode-cli/docs/usage（zai-org/ZCode 仓库）。

## 自动确认覆盖

Codex、Claude Code、OpenCode 的交互包装入口默认 `CODEXC_AUTO_YES=1`。用户显式传入的审批参数优先。

| 工具 | 默认确认方式 | 限制 |
|---|---|---|
| Codex | `--dangerously-bypass-approvals-and-sandbox`，预设目录信任 | `CODEXC_AUTO_YES=2` 改用 `--ask-for-approval never --sandbox workspace-write`；`0` 关闭 |
| Claude Code | `--dangerously-skip-permissions`，预设目录信任和 bypass 确认 | `2` 使用 `--permission-mode acceptEdits`，仍可能要求其他操作确认；`0` 关闭 |
| OpenCode | `--auto` | 只有 `1` 添加该参数；兼容性取决于安装的 CLI 版本 |
| ZCode 自动 worker | `--mode yolo` | 使用 `ZCODE_MODE` 覆盖，与 `CODEXC_AUTO_YES` 独立；交互透传不自动添加 |
| Pi / dsh | 沿用工具及 profile 配置 | 外层没有额外的通用确认弹窗适配 |

这些机制使用 CLI 原生权限模式。项目尚无识别任意 GUI 按钮并点击 Yes 的通用功能，登录、验证码和新交互弹窗也不属于自动 continue。
