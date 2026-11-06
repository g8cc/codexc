# 审计续接检查点 · 已收尾

更新时间：2026-11-05 23:03（UTC+8）。**本轮审计收尾已全部完成，无 active goal。** 最终结论与证据以 [docs/LEAF-AUDIT-2026-11-05.md](../LEAF-AUDIT-2026-11-05.md) 的「验证与部署记录」为准；本文件只保留终态与待决策项。

## 已完成（逐项核验）

1. **测试结果**：全套 `/private/tmp/ck-tests-6wk2scmk` 退出码 1，仅 integration codex/pi 的 5 秒审查超时夹具缺 PID 证据；夹具等待改 15 秒（产品默认值未动）后在 `/private/tmp/ck-tests-8_ff8jkj` 复测退出码 0，五条 integration lane 全 PASS。凭证 `/private/tmp/ck-leaf-suite-passed.json` 如实记录联合覆盖 26 阶段，未把 1 写成 0。
2. **源码应用**：`ck-leaf-tested.json` 中 28 个运行时文件已原子替换，读回哈希 28/28 一致；备份 `/private/tmp/ck-leaf-source-before-3nkoq_jy`。
3. **外部应用**：`/private/tmp/ck-leaf-deploy-jzltd0sc/verification.json` 于 20:52:19 记 `status=applied`、31 文件、无 error；读回 31/31 与 `prepared/plan.json` 的 after 一致。原队列/journal 已按项目备份到各 `.codingkeeper/audit/leaf-2026-11-05/`。likeclaw 只交草案。
4. **运行时**：watchdog 58185、sale 57993、soul2soul 57994；部署时 `managed_model_children=0`、两项 `waiting_window / active=false`；fingerprint 原 halt 与两个 iOS WIP 文件哈希未变。
5. **离线检查**：`ck leaves --registry` 输出 sale 3/15、soul2soul 1/3、fingerprint 1/5、test 与 zcode-exp 0/0；likeclaw 的 `L0 placeholder-gate` 是已说明的例外。
6. **文档**：总报告已写入验证与部署记录；本检查点已更新。中文交付已完成。

## 待用户决策（本轮未擅自处理）

- **23:00 窗口开启后的真实失败**：两个 runner 各 3 个 turn 全部 `zcode turn failed (rc=1, class=unknown)`、stdout/stderr 空，执行器正确 park 为 `backoff`（约 23:10 自动复燃 1/4），未误验收、未标完成、无模型 worker 子进程。原因指向 ZCode 网关/套餐侧空响应，需服务侧排查；是否暂停自动复燃、是否继续排查，等用户指令。
- `/private/tmp/codexc-hl-it.*` 下 5 个测试夹具残留 headless 进程，不在生产注册表，未清理。
- 未完成的产品验收（双设备功耗、真实浏览器录制、合法时窗内真实生成、iOS 修复与重试契约）保持原样，不记作 PASS。

## 约束（继续沿用）

禁止为验证发起真实模型请求；不停止手工 Codex、ZCode 网关或领取套餐服务；不自动 commit/push；改动前需用户显式批准，且只操作开发环境。
