# 商业化路线（Commercialization Checklist）

## 定位
CodingKeeper — 编码 Agent 的无人值守运行时（会话监督 + 任务投喂 + 验收门禁 + 燃料管理）。
一句话: 把"有人盯着的编码 Agent"变成"锅炉"——智能在 Agent，机械与审查在 Keeper。

## 已具备（当前完成度）
- [x] 六工具适配（4 TUI + 2 headless），统一验收管线
- [x] 测试 harness: 统一入口 + 一致性矩阵 + 故障注入（CI 可用）
- [x] 运维手册（docs/OPERATIONS.md）+ 工具矩阵 + 架构文档
- [x] 真实项目无人值守实证（test 项目: 投喂→验收→burn→自主安全修复）

## 商业化前必办（按序）
1. **授权决定**: 当前 LICENSE 为开源许可。商业化的两条路:
   a. 双许可（开源 core + 商业扩展包）——需要拆分代码边界；
   b. 专有许可——把 LICENSE 换成 EULA，删除/改写开源痕迹。
   （决定权在所有者；涉及 README 的开源表述一并调整）
2. **打包分发**: install.sh 单机软链模式适合自用；商业版需要
   npm/homebrew 安装包 + 版本升级通道（VERSION + CHANGELOG 已就位）。
3. **密钥与安全**: 商业用户共享cc-switch/keydrop 等本机依赖需要抽象为
   通用 provider 接口；secret 处理已全程避免落盘/进日志（审计通过）。
4. **支持边界**: docs/OPERATIONS.md 的"情况→处理"表即 SLA 蓝本；
   park/通知语义已覆盖全部失败模式。
5. **遥测与计量**: token 消耗已在 fuel 中可见（cc-switch 数据源）；
   商业计量需独立于用户本机工具。

## 产品化功能候选（数据已就位，纯读取渲染）

**多项目管理面板（Dashboard）**：一屏看所有项目的所有任务与进度。数据源已全部机器可读，
面板是纯读取渲染，零智能、不触碰运行时（符合外环不变量）:

| 数据 | 位置（每项目 .codingkeeper/） | 面板呈现 |
|---|---|---|
| 任务与状态 | queue.md（ready/review-needed/done 勾选） | 任务列表 + 打勾 |
| 验收台账 | journal（时间戳 + 审查轮次 + gate 重试） | 交付历史 |
| 运行/挂起 | loop.pid / loop.halt | 燃烧中 / 已熄火 徽标 |
| 全局时间线 | ~/.codex/codexc-watch.log（带时间戳全事件） | 活动流 |
| 产出 | 各项目 git log | commit 流 |
| token 消耗 | codexc fuel（cc-switch 数据源） | 燃料仪表 |

- 发现机制: 项目登记表（~/.codingkeeper/projects）或扫描工作区根下含 .codingkeeper/ 的目录。
- 落地形态: v1 = `keeper status --all` 文本看板（终端原生，成本低）; v2 = 本地 Web 面板
  （只读 server 渲染聚合数据，商业化阶段）; v3 = 桌面/IDE 集成。
- 触发时机: 多项目日常真实使用出现后再建（与 harness/文档同原则——数据先于面板）。

## 风险与依赖
- 上游 Agent（codex/claude/opencode/pi/zcode/dsh）版本迭代快——
  测试 harness 是防护网，新版本发布先跑 `tests/run-all integration`。
- tmux/macOS 依赖: 商业版需明确平台支持矩阵（当前 macOS 实证，Linux 理论可移植）。
