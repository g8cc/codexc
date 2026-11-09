#!/bin/bash
# swift-gate.sh — Swift 门禁的受控执行: 先探针判定工具链健康度, 再决定全量检查或诚实跳过。
# 2026-11-10: 本机 CLT 编译器 (6.3.3) 与 SDK swiftinterface (6.3.2) 错配后, swiftc
# 对 trivial 文件也会秒败或挂死 — 环境问题卡死门禁, 且对代码质量零信号。
# 规则: 探针 (一行 import AppKit) 失败/超时 = 工具链损坏 → 大声 SKIP, exit 0,
#       门禁放行但明确声明 Swift 层本次未覆盖 (环境修复后自动恢复全量检查);
#       探针通过 → 对目标文件全量 typecheck, 失败照旧红 (门禁的牙不折)。
# 用法: swift-gate.sh [--probe-only] [file.swift]
#       --probe-only: 只做工具链判定 — 健康 exit 0, 损坏 exit 2 (供 desktop-audit 复用)
#       超时秒: SWIFT_GATE_PROBE_TIMEOUT (默认 90; macOS 无 GNU timeout, 自带看门狗)
set -u

mode=check
if [ "${1:-}" = "--probe-only" ]; then
    mode=probe
    shift
fi

tmp_out="$(mktemp "${TMPDIR:-/tmp}/swift-gate.XXXXXX")" || exit 1
trap 'rm -f "$tmp_out" "$tmp_out.probe.swift"' EXIT

# run_bounded <秒> <命令...> — 命令超时即 SIGKILL, 退出码 137
run_bounded() {
    local limit="$1"; shift
    "$@" > "$tmp_out" 2>&1 &
    local pid=$!
    ( sleep "$limit"; kill -9 "$pid" 2>/dev/null ) &
    local watchdog=$!
    wait "$pid"; local rc=$?
    kill "$watchdog" 2>/dev/null
    wait "$watchdog" 2>/dev/null
    return "$rc"
}

toolchain_ok() {
    printf 'import AppKit\n' > "$tmp_out.probe.swift"
    run_bounded "$probe_timeout" swiftc -typecheck "$tmp_out.probe.swift"
}

probe_timeout="${SWIFT_GATE_PROBE_TIMEOUT:-90}"
if toolchain_ok; then
    if [ "$mode" = probe ]; then
        exit 0
    fi
    file="${1:?usage: swift-gate.sh [--probe-only] [file.swift]}"
    run_bounded "$probe_timeout" swiftc -typecheck "$file"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "  ✗ swiftc -typecheck $file (rc=$rc)"
        head -25 "$tmp_out" | sed 's/^/    /'
    fi
    exit "$rc"
fi

echo "  SKIP: Swift 工具链损坏 (trivial 探针编译失败/超时) — 环境问题, 非代码问题; Swift 层本次未覆盖"
head -3 "$tmp_out" | sed 's/^/    /'
echo "    修复: 重装/更新 Command Line Tools 使编译器与 SDK 匹配, 恢复后门禁自动恢复全量检查"
if [ "$mode" = probe ]; then
    exit 2
fi
exit 0
