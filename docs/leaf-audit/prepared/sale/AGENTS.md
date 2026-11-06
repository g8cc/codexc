# sale — 销售人员个体培训系统

## 目标

把 `sale.txt` 的「高转化销售成交系统」（9 步闭环：筛钩信痛稳逼锁交裂）做成员工可自学的
培训系统。员工学完这一套，就能以销冠的话术和节奏去做销售。

## 形态与约束（验收契约，改动前必读）

- **零依赖纯前端**：双击 `index.html`（file://）即可使用；不引入任何 npm 包、不搞构建步骤。
- **data.js**：普通脚本（非 module），挂 `globalThis.TRAINING_DATA`。完整 schema 以
  `tests/phase1/content.test.js` 为准（meta/chapters/sections/scripts/quizzes）。
- **app.js**：挂 `globalThis.AppAPI` 暴露纯函数（`flattenSections` / `markDone` /
  `progressPercent` / `loadProgress` / `scoreQuiz` / `pickScript`，契约见 phase2-4 测试）。
  操作 DOM 的代码必须以 `typeof document !== 'undefined'` 守卫，保证 node 里可 require。
- **index.html 挂载点**：`#app`、`#outline`、`#lesson`、`#quiz`、`#scripts`。
- **`tests/` 是控制器写的验收契约，worker 不得修改 tests/ 下任何文件。**
- 每个任务完成后 `git commit`（不要 push），最后一条消息以 `TASK_RESULT: DONE` 结尾；
  受阻用 `TASK_RESULT: BLOCKED: 原因`。

## 质量要求

- 内容必须**逐字完整**覆盖 sale.txt（gate 有逐行锚点检查），不许概括改写丢内容。
- 测验题必须考察真实理解（题干具体、干扰项合理），不许凑数。
- 话术演练视图要能按关键词检索原文模板。

## 质量叶子工作约定（来源 ../quality-framework, 95 叶过滤出 20 条, 见 .codingkeeper/quality-leaves.tsv）

队列 `## ready` 里带 `(P0)`-`(P5)` 标记的任务是质量叶子，每条按以下合同执行：

1. **一叶一假设一提交**：只处理本叶的指标，禁止夹带其它维度；commit 标题 = `{LEAF_ID}: <假设一句话>`。
- **每叶开工前必读两份文件**（framework 方法论正文, 此前未接入执行链——2026-11-05 补）:
  `../quality-framework/job-contract.md`（工单合同）+ `../quality-framework/prompts/`
  对应维度文件中该 LEAF_ID 的段落（假设空间/允许路径/验证方法/禁止事项）。
  BAT-* 等项目自定义叶以队列文本中的验收标准为准（框架无对应段）。
2. **先测量后动手**：先跑验证命令/写基线测试记录数字；量不出来就补测量，不猜着改。
3. **禁止**：改 tests/ 下任何契约文件、skip/删除测试、改阈值凑达标、顺手格式化/重命名/大重构、动无关依赖。
4. **改动上限**：每叶 ≤ 8 个文件，超出即回滚重新想更小的假设。
5. **基线已达标**：不改任何代码，直接以 TASK_RESULT: DONE 结尾并在消息里附基线数字（不产生空 commit）。
6. **性能叶**：附 before/after 数字；变差或持平但改动超限 → git checkout 回滚。
7. 新测试统一放 `tests/quality/<leaf-id>.test.js`（gate 自动纳入），风格与 tests/functional 一致（node:test + assert，零依赖）。

## v2 表达训练营约定（docs/SPEC-v2.md 为唯一规格来源）

- 新代码: server.js (node:http 零依赖, **只绑 127.0.0.1**) + practice.html/practice.js/teleprompter.js/recorder.js
- 新测试放 tests/v2/*.test.mjs (node:test ESM), 与既有契约同地位——**不得修改既有 tests/**; 真实 AI 集成测试以 RUN_REAL_AI=1 门控
- 浏览器 API (getUserMedia/MediaRecorder/IndexedDB) 只许出现在薄壳层, 逻辑必须落可测纯函数/状态机; 存储走 driver 抽象 (node 用 memoryDriver)
- **禁止上传任何用户数据**; 服务无状态, 用户数据只在浏览器 IndexedDB
- 生成 prompt 组装必须是纯函数 (buildGeneratePrompt), zcode 调用错误按 auth/quota/transient/unknown 分类 (与 codexc-zcode-worker 同约定)

## 2026-11-05 叶子验收补充（覆盖上文旧质量叶的冲突规则）

- 95 项目录是候选检查清单，不代表 95 个缺陷；任务必须有项目适用性、当前差距或明确待验收证据、范围和可观察结果。新源码已实现的项先验收，不重复实现。
- ready 才是自动执行区；review-needed / blocked 不自动执行。节点内缩进的范围、验收、依赖同属合同。
- “一叶一假设”用于控制范围，不强制一处改动或八文件上限。需要跨层修改时按同一用户结果说明范围，不能为凑数量拆坏修复；超出合同则记录受阻，保留现场。
- 禁止按整文件 git checkout/reset 丢弃工作区；基线可能已有用户改动。只撤回本轮可归因的补丁，难以分离则保留并记录。不得删/skip 测试或放宽阈值凑绿。
- 测试数量/文件存在/源代码字符串不能替代业务行为。记录命令、PASS/FAIL/SKIP、平台与限制；未运行不写 PASS，基线达标可 no-change，禁止空提交。提交遵循当前用户授权与项目既有政策，本次控制器审计不自动提交。
- 性能阈值必须对应负载与用户预算，禁止为消化目录临时造指标。已有等价测试归档引用；设备/浏览器/真实模型依赖未满足时保留待验收，不发起模型空转。
- gate 和 review wrapper 由控制器管理，不能被 worker 改弱。审查读取本叶 baseline→candidate 的 changes.diff（包括已提交代码），只读检查；检查结果绑定候选指纹，队列与日志由控制器事务验收。
