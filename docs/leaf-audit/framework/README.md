# 工程质量候选目录

这里维护95个可复用检查ID及如何把证据变成小而完整的工单。**目录不是待办清单，也不是需要跑完的95轮任务。** 找不到值得解决的当前差距时，正确结果是保留证据并停止派单。

实际文件：

- [taxonomy.md](taxonomy.md)：95项适用条件、重叠和有效验收。
- [job-contract.md](job-contract.md)：具体工单的准入、实施和验证合同。
- [scheduler.md](scheduler.md)：候选筛选、状态、失败与重试规则。
- [PRIORITY.md](PRIORITY.md)：按真实用户影响排序。
- [thresholds.yaml](thresholds.yaml)：参考值及预算证据要求，不是全项目强制门槛。
- [project-profile.example.yaml](project-profile.example.yaml)：可选项目事实记录示例。
- 原框架的 `prompts/`：九份历史假设线索，本次替换稿未复制；使用前必须结合新合同、当前源码与验收重写。核心流程不依赖它们。
- [AGENTS.md](AGENTS.md)、[SKILL.md](SKILL.md)：入口约定；[DIMENSIONS.md](DIMENSIONS.md)：标签边界。

本包没有附带runner、模型连接器或名为quality-leaf的独立子目录。不要使用不存在的scripts/run_loop.sh、references或assets路径。本包可以保留在兄弟仓库；框架实际位置由用户上下文或可验证路径确定，不要求复制进每个目标仓。

## 使用流程

1. 明确目标项目与用户要改善的结果，读取适用的仓库约定、当前SHA或可识别快照和已有变更。
2. 从缺陷报告、真实测试失败、用户流程、测量或发布风险挑候选，再用taxonomy定位相关ID；不是按ID依次找事做。
3. 只读核查适用性、当前差距、已有实现/测试/任务、收益与验收。一个完整问题可关联多个目录ID。
4. 五项准入通过后写可复现工单，范围含必要实现/调用方/测试；按现有授权实施。具体重要风险尚缺证据时，只能先派有范围、成本和停止条件的验证任务。缺设备/真实权限等前置保留blocked，不能编造通过或归档为no-gap。
5. 用精确代码基线和足够的验证判定implemented或verified，记录限制；提交/推送/部署遵循当前授权与仓库约定。

项目profile用于记录事实，不是启动工作前强制向用户索要的表格。可以从仓库命令和源码可靠推断的字段直接填明来源；无法推断且影响正确性时只暂停依赖动作，继续独立工作。profile不能覆盖用户授权边界。

这些Markdown/YAML本身不实现调度或权限。接入现有控制器时，先确认它能区分候选、ready、implemented、verified和blocked，保留精确diff与失败记录，并通过离线fixture验证；不能只换文档就宣称runner行为已经改变。

