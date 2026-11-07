# codexc / CodingKeeper — 智能全部在 Agent 内, 机械全部在 Keeper 内

本仓库是 CodingKeeper 控制器本体。改这里之前:

1. **任何行为修复必须带回归测试**, 并通过 `tests/run-all` 全绿后提交
   (pre-commit 钩子会强制执行)。没有测试的 bug 修复等于没修。
2. **排障必须先读 `docs/triage-playbook.md`**——五条铁律: 先看后搜 / 宽松检索变体矩阵 /
   零命中+用户坚持=假定自己漏了 / 验证回到用户视图 / 实体删除同步派生物。
   2026-11-07 的三次误判事件全部源于违反这些规则。
3. 本仓库所有会话状态文件 (status.json / queue.md / loop.halt / registry) 使用原子写入,
   bash 3.2 兼容 (无 declare -A), 运行中的脚本禁止原地编辑 (写新文件 + mv)。
4. 会话/任务对用户可见的存储有两套 (CLI db.sqlite + 桌面侧栏 tasks-index.sqlite /
   dsh 投影缓存)——任何清理必须双库同步, 见 tests/session-hygiene-audit.py 的静态断言。
