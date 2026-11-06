# test 任务队列

本队列于 2026-11-05 完成源码与证据审计。原始 queue、gate、review wrapper 和审计记录保存在 .codingkeeper/audit/leaf-2026-11-05/（部署时生成）。历史勾选仅表示此前记录，不等于本轮重新验证。

只有 ready 内未勾选任务会执行；blocked 和 review-needed 由控制器核对依赖/证据后再转入 ready，不能按列表顺序假定依赖已经满足。叶子完整合同包含首行及其缩进续行。基线已经达标则记录 no-change 证据，不制造重复测试或空提交。保留用户已有改动，禁止按文件整体 checkout/reset 进行回滚。

## ready

## review-needed

## done

- [x] 通读本项目的目录与文件, 写一份 PROJECT_NOTES.md(用中文, 含: 项目用途推测、目录结构说明、每个主要文件的用途), 并 git commit; 完成以 TASK_RESULT: DONE 结尾
- [x] 为 zcode-suite 建立最小回归测试套件 — 已完成 (2026-10-31 第六轮, commit 6272aa0): tests/ 30 项 stdlib unittest 全绿 (`python3 -m unittest discover -s zcode-suite/tests`), 覆盖怪表名/怪列名动态 SQL 全链路、_merge_index 交集、token_user_id 兜底、parse_hhmm、Pool 记账/绑定/LRU; 随 2.11.0 重打包
- [x] 实现 gateway 的真·会话绑号 — 已完成 (2026-10-31 第六轮, commit aa81a00, 2.11.0): sticky 路由可读, 同会话回绑定号; strict(默认)绑定不迁移、号恢复回切, --no-strict-session 改绑; 绑定号冷却期间由当前号顶上 (exhausted 不换绑定避免饿死); sticky 保留 LRU 4096; 沙箱 12 项断言+回归测试钉住
- [x] 收紧 genie/scripts/60_skill_server.py 的鉴权: 未设 SAY_TOKEN 时 /say 全开放、/netinfo 回设备 SSID/BSSID/MAC 任何人可查 (常驻局域网/公网属隐私暴露), 加 --allow-open 显式开关或启动横幅显著告警; 三处 token 比较用普通 != 改 hmac.compare_digest 防时序侧信道; /tmp 沙箱验证设/不设 token 两态行为 — 已完成 (2026-10-31 第七轮, commits 16fdb30/2c9b6a9/dff9bf5): 未设 SAY_TOKEN 时 /say /ask /voice /netinfo 默认锁定 (403 locked), --allow-open 显式放开+启动横幅告警; /netinfo (SSID/BSSID/MAC) 纳入鉴权 (此前设 token 也不设防); 三处 token 比较改 hmac.compare_digest; /tmp 沙箱三态 24 项断言全过; 顺带清死代码 SKILL_TOKEN/import re; RUNBOOK/BRIDGE 文档同步

## archived-with-reason

- 旧文档 gate 只验 PROJECT_NOTES，不能承接后续网关/鉴权代码；具体新任务应配置相关现有测试。禁止用已完成的文档叶继续泛化烧额度。
