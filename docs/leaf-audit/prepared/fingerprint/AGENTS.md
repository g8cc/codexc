# UDFE — Universal Device Fingerprint Engine (v1.1 烧炼中)

TS 后端服务 (src/server) + 4 平台 SDK (sdks/) + 106 项测试 (test/{unit,integration,security,perf})。
构建: npm test (= tsc + node --test 全套)。零外部服务依赖, 本地自足。

## 质量叶子工作约定 (来源 ../quality-framework, 控制器过滤 ~20 条, 见 .codingkeeper/quality-leaves.tsv)

1. **一叶一假设一提交**: 只做本叶指标; commit 标题 = `{LEAF_ID}: <假设一句话>`。
- **每叶开工前必读两份文件**（framework 方法论正文, 此前未接入执行链——2026-11-05 补）:
  `../quality-framework/job-contract.md`（工单合同）+ `../quality-framework/prompts/`
  对应维度文件中该 LEAF_ID 的段落（假设空间/允许路径/验证方法/禁止事项）。
  BAT-* 等项目自定义叶以队列文本中的验收标准为准（框架无对应段）。
2. **先测量后动手**: 先跑基线记录数字; 量不出来就补测量。
3. **禁止**: 删/skip 既有测试凑绿、改阈值达标、顺手重构/格式化、动无关依赖、把 config/apps.json 或 .env 的真实值写进测试。
4. 每叶 ≤ 8 文件, 超限回滚重来。
5. **基线已达标**: 零改动, TASK_RESULT: DONE 附基线数字, 不产生空 commit。
6. 新测试放对应既有目录 (test/unit|integration|security|perf), 风格随现有 .test.mjs (node:test, ESM)。
7. 服务端敏感面提醒: 指纹数据本身是 PII 类数据 — 日志/存储/日志导出叶子按隐私优先处理 (src/server/services/privacy.ts 是现行实现参照)。

## 2026-11-05 叶子验收补充（覆盖上文旧质量叶的冲突规则）

- 95 项目录是候选检查清单，不代表 95 个缺陷；任务必须有项目适用性、当前差距或明确待验收证据、范围和可观察结果。新源码已实现的项先验收，不重复实现。
- ready 才是自动执行区；review-needed / blocked 不自动执行。节点内缩进的范围、验收、依赖同属合同。
- “一叶一假设”用于控制范围，不强制一处改动或八文件上限。需要跨层修改时按同一用户结果说明范围，不能为凑数量拆坏修复；超出合同则记录受阻，保留现场。
- 禁止按整文件 git checkout/reset 丢弃工作区；基线可能已有用户改动。只撤回本轮可归因的补丁，难以分离则保留并记录。不得删/skip 测试或放宽阈值凑绿。
- 测试数量/文件存在/源代码字符串不能替代业务行为。记录命令、PASS/FAIL/SKIP、平台与限制；未运行不写 PASS，基线达标可 no-change，禁止空提交。提交遵循当前用户授权与项目既有政策，本次控制器审计不自动提交。
- 性能阈值必须对应负载与用户预算，禁止为消化目录临时造指标。已有等价测试归档引用；设备/浏览器/真实模型依赖未满足时保留待验收，不发起模型空转。
- gate 和 review wrapper 由控制器管理，不能被 worker 改弱。审查读取本叶 baseline→candidate 的 changes.diff（包括已提交代码），只读检查；检查结果绑定候选指纹，队列与日志由控制器事务验收。
