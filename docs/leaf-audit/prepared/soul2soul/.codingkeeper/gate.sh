#!/bin/bash
# 验收门禁 — Soul2Soul: 项目自带分层测试 harness (T0 静态+T1 Android 单测+T2 服务端+T3 协议黑盒)
set -e
cd "$(dirname "$0")/.."
exec bash scripts/test.sh
