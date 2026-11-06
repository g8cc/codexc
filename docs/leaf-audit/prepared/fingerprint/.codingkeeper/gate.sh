#!/bin/bash
# 验收门禁 — UDFE: tsc 构建 + 全部测试 (unit/integration/security/perf/web-sdk)
set -e
cd "$(dirname "$0")/.."
exec npm test
