# zcode-exp 任务队列

本队列于 2026-11-05 完成源码与证据审计。原始 queue、gate、review wrapper 和审计记录保存在 .codingkeeper/audit/leaf-2026-11-05/（部署时生成）。历史勾选仅表示此前记录，不等于本轮重新验证。

只有 ready 内未勾选任务会执行；blocked 和 review-needed 由控制器核对依赖/证据后再转入 ready，不能按列表顺序假定依赖已经满足。叶子完整合同包含首行及其缩进续行。基线已经达标则记录 no-change 证据，不制造重复测试或空提交。保留用户已有改动，禁止按文件整体 checkout/reset 进行回滚。

## ready

## review-needed

## done

- [x] 在 README.md 末尾追加一节"实验记录", 写入当前时间与一句本次实验的观察, 完成后 git commit

## archived-with-reason

- 原 fizzbuzz(1..15) 任务：实验夹具，无产品收益，不再自动执行；原文保留在审计备份。
