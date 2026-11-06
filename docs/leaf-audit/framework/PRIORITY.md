# 按用户损害排序，不按目录排95轮

目录ID不带永久优先级。P0–P5仅用于具体项目问题，不把一个维度统一排高或排低。排序先看影响严重性与发生/暴露证据，再看影响范围、恢复能力、依赖与成本；不要用机械加权分数掩盖判断。

| 档 | 具体问题的含义 | 例子（必须有当前证据） |
|---|---|---|
| P0 | 正在发生的重大损失/安全暴露，或发布会造成不可接受损害 | 跨租户删数据、可用凭证泄漏、核心流程普遍崩溃 |
| P1 | 支持用户无法完成核心流程，或高可信重大风险 | SDK调用旧路由、付款重复、读屏/键盘用户无法提交、弱网导致关键数据丢失 |
| P2 | 常见场景明显受损，或使故障恢复/验证失真 | 重连不恢复、必要平台根本未编译、错误探针造成部署误判 |
| P3 | 可复现的次要体验/成本损害，修复收益明确 | 指定查询/页面超过已接受预算、可恢复的边界错误 |
| P4 | 有具体消费者的维护/接入改进 | README真实安装步骤失效、可确认无用代码造成维护问题 |
| P5 | 有明确目标的可选实验或远期改进 | 小范围性能实验；没有当前价值/验收的候选仍不得进入ready |

## 使用规则

- 同根因合并，按完整结果排序；比如“重试复用签名”同时关联STAB/XPROJ/BUG，不开三轮。
- 无障碍、弱网、错误反馈、文档可执行性均可因实际损害升到更高档；安全扫描的一个high也未必自动P0。
- 已实现未验收优先补所需证据，避免重复实现。验证成本较高不说明风险较低。
- 高优先级失败/blocked不消失，不自动转skip。必要时先解除关键阻塞；可做独立任务时仍保留未解决问题与下一动作。
- 只有covered/no-gap/not-applicable/duplicate等有明确证据，或有授权的放弃决定，才可归档。目录全部归档不等于产品全部通过。
- 资源窗口/max_priority限制能执行什么，不能把没执行的结果记done。队列无值得执行的工单就停止，不烧到P5。

## 95个ID索引（仅追溯，不是顺序）

- BUG：`BUG-BE-01`、`BUG-BE-02`、`BUG-BE-03`、`BUG-BE-04`、`BUG-BE-05`、`BUG-BE-06`、`BUG-FE-01`、`BUG-FE-02`、`BUG-FE-03`、`BUG-FE-04`、`BUG-FE-05`、`BUG-FE-06`、`BUG-MW-01`、`BUG-MW-02`、`BUG-MW-03`、`BUG-MW-04`。
- EDGE：`EDGE-BE-01`、`EDGE-BE-02`、`EDGE-BE-03`、`EDGE-BE-04`、`EDGE-BE-05`、`EDGE-BE-06`、`EDGE-BE-07`、`EDGE-FE-01`、`EDGE-FE-02`、`EDGE-FE-03`、`EDGE-MW-01`、`EDGE-MW-02`。
- SEC：`SEC-BE-01`、`SEC-BE-02`、`SEC-BE-03`、`SEC-BE-04`、`SEC-BE-05`、`SEC-BE-06`、`SEC-FE-01`、`SEC-FE-02`、`SEC-MW-01`、`SEC-MW-02`。
- XPROJ：`XPROJ-01`、`XPROJ-02`、`XPROJ-03`、`XPROJ-04`、`XPROJ-05`、`XPROJ-06`、`XPROJ-07`、`XPROJ-08`、`XPROJ-09`、`XPROJ-10`。
- STAB：`STAB-BE-01`、`STAB-BE-02`、`STAB-BE-03`、`STAB-BE-04`、`STAB-BE-05`、`STAB-BE-06`、`STAB-FE-01`、`STAB-FE-02`、`STAB-MW-01`。
- PERF：`PERF-FE-01`、`PERF-FE-02`、`PERF-FE-03`、`PERF-FE-04`、`PERF-FE-05`、`PERF-FE-06`、`PERF-FE-07`、`PERF-FE-08`、`PERF-BE-01`、`PERF-BE-02`、`PERF-BE-03`、`PERF-BE-04`、`PERF-BE-05`、`PERF-BE-06`、`PERF-MW-01`、`PERF-MW-02`、`PERF-DB-01`、`PERF-DB-02`、`PERF-DB-03`。
- ENG：`ENG-01`、`ENG-02`、`ENG-03`、`ENG-04`、`ENG-05`、`ENG-06`、`ENG-07`、`ENG-08`、`ENG-09`、`ENG-10`。
- OBS：`OBS-01`、`OBS-02`、`OBS-03`、`OBS-04`、`OBS-05`。
- A11Y：`A11Y-01`、`A11Y-02`、`A11Y-03`、`A11Y-04`。

