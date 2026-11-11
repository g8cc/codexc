#!/bin/bash
# ck-common.sh — CodingKeeper 三车道共享底层 (codexc-loop / codexc-headless / codexc-daily)。
#
# 被 source, 不直接执行。调用方在 set -u 之后、首个归一化行之前:
#   CK_LANE=codex-loop            # 或 codexc-headless / codexc-daily
#   . "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")/ck-common.sh"
#
# 队列/gate/审查/标记/迁移/登记等语义只在这一份实现里维护; 车道差异
# (日志标签/通知标题/报错前缀) 由 CK_LANE 派生, 不再各抄一份。
#
# 提供: normalize_uint log notify kill_tree loop_cleanup queue_next
#       queue_mark_done journal_append gate_run gate_tail parse_bugs
#       review_run review_tail result_marker migrate_state_dir
#       status_write register_project usage
# 本文件定义的全局: CODEX_HOME_DIR WATCHLOG TAB LOOP_TMP_FILES CK_TURN_TS

CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
WATCHLOG="$CODEX_HOME_DIR/codexc-watch.log"
TAB="$(printf '\t')"
LOOP_TMP_FILES=""
# 当前任务/回合的起始 epoch — runner 在投喂时设置, 验收或复燃时清零;
# banner_set 经 status_write 写进 status.json, 桌面面板据此显示真实时长
CK_TURN_TS=0
: "${CK_LANE:=codexc}"
CK_TAG="${CK_LANE#codexc-}"

# The helper is resolved relative to the sourced library, including bin symlinks.
CK_COMMON_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")" && pwd -P)"

ck_window_check() {  # rc 0=allowed; 125=closed/invalid/unavailable
    local answer extra helper_rc=0
    CK_WINDOW_ALLOWED=0; CK_WINDOW_DEADLINE=0; CK_WINDOW_NEXT_OPEN=0
    CK_WINDOW_REASON=check_failed
    if [ -z "${CODEXC_ACTIVE_WINDOW:-}" ]; then
        CK_WINDOW_ALLOWED=1; CK_WINDOW_REASON=disabled
        return 0
    fi
    answer="$(CODEXC_ACTIVE_WINDOW="$CODEXC_ACTIVE_WINDOW" CODEXC_ACTIVE_TZ="${CODEXC_ACTIVE_TZ-Asia/Shanghai}" python3 "$CK_COMMON_DIR/ck-window.py" --format tsv 2>/dev/null)" || helper_rc=$?
    IFS="$TAB" read -r CK_WINDOW_ALLOWED CK_WINDOW_DEADLINE CK_WINDOW_NEXT_OPEN CK_WINDOW_REASON extra <<< "$answer"
    # A failed/partial helper must never accidentally open the gate.
    case "$CK_WINDOW_ALLOWED" in 0|1) ;; *) CK_WINDOW_ALLOWED=0; CK_WINDOW_REASON=invalid_response; return 125 ;; esac
    case "$CK_WINDOW_DEADLINE" in ''|*[!0-9]*) CK_WINDOW_ALLOWED=0; CK_WINDOW_REASON=invalid_response; return 125 ;; esac
    case "$CK_WINDOW_NEXT_OPEN" in ''|*[!0-9]*) CK_WINDOW_ALLOWED=0; CK_WINDOW_REASON=invalid_response; return 125 ;; esac
    if [ "${#CK_WINDOW_DEADLINE}" -gt 12 ] || [ "${#CK_WINDOW_NEXT_OPEN}" -gt 12 ] || [ -n "$extra" ]; then
        CK_WINDOW_ALLOWED=0; CK_WINDOW_REASON=invalid_response; return 125
    fi
    case "$answer" in *$'\n'*) CK_WINDOW_ALLOWED=0; CK_WINDOW_REASON=invalid_response; return 125 ;; esac
    if [ "$helper_rc" != 0 ]; then
        CK_WINDOW_ALLOWED=0
        case "$CK_WINDOW_REASON" in invalid_window|invalid_timezone|invalid_clock) ;; *) CK_WINDOW_REASON=check_failed ;; esac
        return 125
    fi
    case "$CK_WINDOW_ALLOWED:$CK_WINDOW_REASON" in
        1:allowed) [ "$CK_WINDOW_DEADLINE" != 0 ] && return 0 ;;
        1:weekend) return 0 ;;                                # 周末全天开放, 无截止
        0:outside_window) return 125 ;;
    esac
    CK_WINDOW_ALLOWED=0; CK_WINDOW_REASON=invalid_response
    return 125
}

ck_run_check() {  # a manual project halt takes precedence over clock policy
    if [ -e .codingkeeper/loop.halt ]; then
        CK_WINDOW_ALLOWED=0; CK_WINDOW_DEADLINE=0; CK_WINDOW_NEXT_OPEN=0
        CK_WINDOW_REASON=manual_stop
        return 125
    fi
    ck_window_check
}

normalize_uint() {
    local name="$1" value="$2" fallback="$3" minimum="$4" maximum="$5" number
    case "$value" in
        ''|*[!0-9]*) echo "$CK_LANE: invalid $name '$value'; using $fallback" >&2; printf '%s' "$fallback"; return ;;
    esac
    # 64 位算术上限防护: 超长数字会被 bash 静默回绕成看似合法的正数
    value="${value#"${value%%[!0]*}"}"
    if [ "${#value}" -gt 18 ]; then
        echo "$CK_LANE: $name must be between $minimum and $maximum; using $fallback" >&2
        printf '%s' "$fallback"; return
    fi
    number=$((10#${value:-0}))
    if [ "$number" -lt "$minimum" ] || [ "$number" -gt "$maximum" ]; then
        echo "$CK_LANE: $name must be between $minimum and $maximum; using $fallback" >&2
        number=$fallback
    fi
    printf '%s' "$number"
}

# watch log 自裁剪: >5MB 时原 inode 截断保留最近 2000 行 (tail>tmp, cat>file —
# 追加方持有的 fd 不失效); 直接 echo >> 追加的调用点同样受益 (同一 inode)
trim_watchlog() {
    [ -f "$WATCHLOG" ] || return 0
    [ "$(stat -f '%z' "$WATCHLOG" 2>/dev/null || echo 0)" -lt 5242880 ] && return 0
    local temp
    temp="$(mktemp "$WATCHLOG.trim.XXXXXX")" || return 0
    tail -n 2000 "$WATCHLOG" > "$temp" 2>/dev/null \
        && cat "$temp" > "$WATCHLOG" 2>/dev/null
    rm -f "$temp" 2>/dev/null
    return 0
}

log() {
    trim_watchlog
    (umask 077; mkdir -p "$CODEX_HOME_DIR" && touch "$WATCHLOG") 2>/dev/null || return 1
    echo "$(date '+%F %T') $CK_TAG: $*" >> "$WATCHLOG"
}

notify() {
    [ "${CODEXC_LOOP_NOTIFY:-1}" = "1" ] || return 0
    # global popup gap: 多车道并行时防弹窗风暴 — 共享时间戳, 距上一条不足
    # CODEXC_NOTIFY_GAP 秒(默认3, 0=关)的本条直接丢弃 (通知是糖, 不是投递保证)
    local gap="${CODEXC_NOTIFY_GAP:-3}" last now
    case "$gap" in ''|*[!0-9]*) gap=3 ;; esac
    if [ "$gap" -gt 0 ]; then
        last="$(cat "$HOME/.codingkeeper/.notify-last" 2>/dev/null || echo 0)"
        case "$last" in ''|*[!0-9]*) last=0 ;; esac
        now="$(date +%s)"
        if [ $((now - last)) -lt "$gap" ]; then
            echo "$(date '+%F %T') $CK_TAG: notification suppressed (global gap ${gap}s): ${1:0:60}" >> "$WATCHLOG"
            return 0
        fi
        mkdir -p "$HOME/.codingkeeper" 2>/dev/null
        printf '%s\n' "$now" > "$HOME/.codingkeeper/.notify-last" 2>/dev/null
    fi
    # task/bug text is LLM-authored: escape it or quotes break (and inject
    # into) the AppleScript
    local esc="${1//\\/\\\\}"; esc="${esc//\"/\\\"}"
    command -v osascript >/dev/null && \
        osascript -e "display notification \"$esc\" with title \"$CK_LANE\"" 2>/dev/null
    return 0
}

# The lock file inode is never removed: flock serializes both acquisition and
# release. The separate owner survives accidental deletion of legacy loop.pid.
runner_lock_acquire() {
    CK_LOCK_TOKEN="$(python3 - "$$" <<'PYLOCK'
import errno, fcntl, json, os, secrets, sys, tempfile
pid = int(sys.argv[1])
state = ".codingkeeper"
os.makedirs(state, exist_ok=True)
with os.fdopen(os.open(os.path.join(state, "runner.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "a+") as lock:
    os.chmod(lock.name, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    candidates = []
    for name in ("runner.owner", "loop.pid", "../.codexc/loop.pid"):
        try:
            with open(os.path.join(state, name)) as fh:
                data = fh.read().strip()
            owner = json.loads(data).get("pid") if name == "runner.owner" else int(data)
            if not isinstance(owner, int) or owner <= 1:
                raise ValueError("invalid PID")
            candidates.append(owner)
        except FileNotFoundError:
            pass
        except (ValueError, TypeError, AttributeError):
            print("runner lock contains invalid metadata; inspect .codingkeeper/" + name, file=sys.stderr)
            raise SystemExit(1)
    for owner in candidates:
        try:
            os.kill(owner, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            pass
        print(f"another runner (pid {owner}) is already running for this project", file=sys.stderr)
        raise SystemExit(1)
    token = secrets.token_hex(16)
    for name, value in (("runner.owner", json.dumps({"pid": pid, "token": token})), ("loop.pid", str(pid))):
        fd, temp = tempfile.mkstemp(prefix=".runner-", dir=state)
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(value + "\n")
            os.replace(temp, os.path.join(state, name))
        finally:
            if os.path.exists(temp): os.unlink(temp)
    print(token, end="")
PYLOCK
)" || { log "another runner owns the project lock, or its metadata cannot be read"; return 1; }
    return 0
}

kill_tree() {  # stop parents before walking so they cannot fork during cleanup
    local pid="${1:-}" p
    case "$pid" in ''|*[!0-9]*) return 1 ;; esac
    [ "${#pid}" -le 10 ] && [ "$pid" -gt 1 ] && [ "$pid" != "$$" ] || return 1
    kill -STOP "$pid" 2>/dev/null || return 0
    for p in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$p"; done
    kill -KILL "$pid" 2>/dev/null
    return 0
}

review_groups_prepare() {
    export CK_PROCESS_OWNER_PID="$$"
    [ -n "${CK_REVIEW_GROUP_DIR:-}" ] && return 0
    CK_REVIEW_GROUP_DIR="$(mktemp -d .codingkeeper/.review-groups.XXXXXX)" || return 1
    CK_REVIEW_GROUP_TOKEN="${CK_LOCK_TOKEN:-$$-$RANDOM-$RANDOM}"
}

review_group_stop() {
    local review_pid="$1" cleanup_pid
    if [ -f "$CK_REVIEW_GROUP_DIR/$review_pid.json" ]; then
        # Keep cleanup in its own child: Bash 3.2 can tail-exec this nested
        # function in a background review, losing the caller's final verdict.
        command python3 "$CK_COMMON_DIR/ck-review-process.py" cleanup "$CK_REVIEW_GROUP_DIR" "$CK_REVIEW_GROUP_TOKEN" "$review_pid" &
        cleanup_pid=$!
        wait "$cleanup_pid"
    else
        # Registration precedes exec; no MCP descendants can exist yet.
        kill_tree "$review_pid"
    fi
}

loop_cleanup() {
    local child
    for child in $(pgrep -P "$$" 2>/dev/null); do kill_tree "$child"; done
    if [ -n "${CK_REVIEW_GROUP_DIR:-}" ]; then
        command python3 "$CK_COMMON_DIR/ck-review-process.py" cleanup "$CK_REVIEW_GROUP_DIR" "$CK_REVIEW_GROUP_TOKEN" || true
        rmdir "$CK_REVIEW_GROUP_DIR" 2>/dev/null || true
    fi
    # Paths are runner-generated names without spaces, never user queue text.
    # shellcheck disable=SC2086
    rm -f $LOOP_TMP_FILES 2>/dev/null
    [ -n "${CK_LOCK_TOKEN:-}" ] || return 0
    python3 - "$$" "$CK_LOCK_TOKEN" <<'PYLOCK'
import fcntl, json, os, sys
state = ".codingkeeper"
try:
    with os.fdopen(os.open(os.path.join(state, "runner.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(os.path.join(state, "runner.owner")) as fh:
            owner = json.load(fh)
        if owner == {"pid": int(sys.argv[1]), "token": sys.argv[2]}:
            for name in ("loop.pid", "runner.owner"):
                try: os.unlink(os.path.join(state, name))
                except FileNotFoundError: pass
except (OSError, ValueError, TypeError):
    pass
PYLOCK
    return 0
}

queue_next() {  # rc 0 = found or empty; rc 2 = unreadable/invalid, never burn
    python3 "$CK_COMMON_DIR/ck-leaf.py" next "$1"
}

queue_mark_done() {  # compatibility API; runners use leaf_accept transaction
    python3 "$CK_COMMON_DIR/ck-leaf.py" mark "$1" "$2"
}

burn_rotating() {
    [ "${CODEXC_PROMPT_ROTATION:-1}" != 0 ] && [ "$IDLE_PROMPT" = "$IDLE_PROMPT_DEFAULT" ]
}

burn_fuel_check() {  # 0=ready; 1=exhausted; 2=invalid; renewed resets no-op count
    BURN_FUEL_STATE=ready
    burn_rotating || return 0
    BURN_FUEL_STATE="$(python3 "$CK_COMMON_DIR/ck-prompts.py" available)" || return 2
    case "$BURN_FUEL_STATE" in ready|renewed) return 0 ;; waiting) return 1 ;; *) return 2 ;; esac
}

burn_exhaust() {
    python3 "$CK_COMMON_DIR/ck-prompts.py" exhaust >/dev/null
}

burn_prompt_prepare() {
    BURN_PROMPT="$IDLE_PROMPT"; BURN_PROMPT_ID=custom
    BURN_NOOP_LIMIT="$CODEXC_IDLE_PARK"
    burn_rotating || return 0
    local answer count encoded extra
    answer="$(python3 "$CK_COMMON_DIR/ck-prompts.py" next --format tsv)" || return 1
    IFS="$TAB" read -r BURN_PROMPT_ID count encoded extra <<< "$answer"
    case "$count" in ''|*[!0-9]*) return 1 ;; esac
    [ "$count" -ge 1 ] && [ "$count" -le 64 ] && [ -n "$encoded" ] && [ -z "$extra" ] || return 1
    BURN_PROMPT="$(python3 -c 'import base64,sys; print(base64.b64decode(sys.argv[1],validate=True).decode("utf-8"),end="")' "$encoded")" || return 1
    BURN_NOOP_LIMIT=$((CODEXC_IDLE_PARK * count))
    return 0
}

leaf_begin() {
    CODEXC_LEAF_EVIDENCE_DIR="$(python3 "$CK_COMMON_DIR/ck-leaf.py" begin "$1")" || return 1
    export CODEXC_LEAF_EVIDENCE_DIR
    if [ -z "$1" ] && [ -n "${BURN_PROMPT:-}" ]; then
        printf '%s' "$BURN_PROMPT" > "$CODEXC_LEAF_EVIDENCE_DIR/goal.txt" || return 1
    fi
}

leaf_candidate() {
    [ -n "${CODEXC_LEAF_EVIDENCE_DIR:-}" ] || return 1
    python3 "$CK_COMMON_DIR/ck-leaf.py" candidate "$CODEXC_LEAF_EVIDENCE_DIR" || return 1
    CODEXC_LEAF_BASE_HEAD="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("head") or "")' "$CODEXC_LEAF_EVIDENCE_DIR/baseline.json")" || return 1
    CODEXC_LEAF_CANDIDATE_HEAD="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("head") or "")' "$CODEXC_LEAF_EVIDENCE_DIR/candidate.json")" || return 1
    export CODEXC_LEAF_BASE_HEAD CODEXC_LEAF_CANDIDATE_HEAD
}

leaf_verify() {
    [ -n "${CODEXC_LEAF_EVIDENCE_DIR:-}" ] || return 1
    python3 "$CK_COMMON_DIR/ck-leaf.py" verify "$CODEXC_LEAF_EVIDENCE_DIR"
}

leaf_gate_run() {
    local leaf_rc
    leaf_candidate || return 126
    : > "$1" || return 126
    gate_run "$1"; leaf_rc=$?
    [ "$leaf_rc" != 125 ] || return 125
    leaf_save_output "$1" gate || return 126
    leaf_verify || return 126
    return "$leaf_rc"
}

leaf_changed() {
    python3 "$CK_COMMON_DIR/ck-leaf.py" changed "$CODEXC_LEAF_EVIDENCE_DIR"
}

leaf_accept() {
    python3 "$CK_COMMON_DIR/ck-leaf.py" accept "$CODEXC_LEAF_EVIDENCE_DIR" "$1" "$2"
}

leaf_recover() { python3 "$CK_COMMON_DIR/ck-leaf.py" recover; }

leaf_save_output() {
    [ -n "${CODEXC_LEAF_EVIDENCE_DIR:-}" ] || return 0
    python3 - "$1" "$CODEXC_LEAF_EVIDENCE_DIR" "$2" <<'PYSAVE'
import os, shutil, sys, tempfile
src, directory, label = sys.argv[1:]
fd, out = tempfile.mkstemp(prefix=label + "-", suffix=".log", dir=directory)
with os.fdopen(fd, "wb") as target, open(src, "rb") as source:
    shutil.copyfileobj(source, target)
PYSAVE
}

require_gate_check() {
    [ "${CODEXC_REQUIRE_GATE:-0}" = "1" ] || return 0
    if [ ! -f .codingkeeper/gate.sh ]; then
        echo "真实验收 gate 缺失: 请配置 .codingkeeper/gate.sh" >&2
        return 1
    fi
    if grep -qE '^# CK_GATE_PLACEHOLDER=1$|^echo "\(gate placeholder[ :—]' .codingkeeper/gate.sh; then
        echo "gate 仍是官方占位模板: 请配置真实测试命令" >&2
        return 1
    fi
}

journal_append() {
    printf '%s | %s | %s\n' "$(date '+%F %T')" "$1" "$2" >> ".codingkeeper/journal"
}

gate_run() {  # $1=outfile; 0=pass
    local outfile="$1" gpid waited=0 rc
    review_groups_prepare || return 126
    : > "$outfile" || return 1
    if ! ck_run_check; then
        printf '[gate interrupted: %s]\n' "$CK_WINDOW_REASON" >> "$outfile"
        return 125
    fi
    require_gate_check >> "$outfile" 2>&1 || return 1
    if [ ! -e ".codingkeeper/gate.sh" ] && [ ! -L ".codingkeeper/gate.sh" ]; then
        printf 'no gate.sh — gate skipped\n' > "$outfile"
        return 0
    fi
    command python3 "$CK_COMMON_DIR/ck-review-process.py" launch "$CK_REVIEW_GROUP_DIR" "$CK_REVIEW_GROUP_TOKEN" /bin/bash ".codingkeeper/gate.sh" > "$outfile" 2>&1 &
    gpid=$!
    while kill -0 "$gpid" 2>/dev/null; do
        if ! ck_run_check; then
            review_group_stop "$gpid"
            wait "$gpid" 2>/dev/null
            printf '\n[gate interrupted: %s]\n' "$CK_WINDOW_REASON" >> "$outfile"
            return 125
        fi
        if [ "$waited" -ge "$CODEXC_GATE_TIMEOUT" ]; then
            review_group_stop "$gpid"
            wait "$gpid" 2>/dev/null
            printf '\n[gate timed out after %ss]\n' "$CODEXC_GATE_TIMEOUT" >> "$outfile"
            return 124
        fi
        # 阶段心跳: gate 最长 900s, 无心跳横幅会误显"已停"
        [ $((waited % 30)) -eq 29 ] && status_touch
        sleep 1
        waited=$((waited + 1))
    done
    wait "$gpid" 2>/dev/null
    rc=$?
    review_group_stop "$gpid" || return 126
    if ! ck_run_check; then
        printf '\n[gate interrupted: %s]\n' "$CK_WINDOW_REASON" >> "$outfile"
        return 125
    fi
    return "$rc"
}

gate_tail() { tr '\n' ' ' < "$1" | tail -c 500 | LC_ALL=C iconv -c -f UTF-8 -t UTF-8; }
# iconv -c: gate 输出可能含非法 UTF-8 字节 (测试工具吐二进制) — 原样嵌入下一轮
# 提示词会让 worker argv 带毒, 全机器 pgrep -f 瘫痪 (2026-11-11 实证)

parse_bugs() {  # only a complete verdict line, with a bounded decimal count
    python3 - "$1" <<'PYBUGS'
import re, sys
try:
    with open(sys.argv[1], "rb") as fh:
        text = fh.read().replace(b"\x00", b"").decode("utf-8", "replace")
except OSError:
    print("parse-fail", end=""); raise SystemExit(0)
lines = [line.strip() for line in text.splitlines() if line.strip()]
match = re.fullmatch(r"BUGS:[ \t]*([0-9]+)", lines[-1]) if lines else None
value = match.group(1).lstrip("0") or "0" if match else ""
print(value if value and len(value) <= 6 else "parse-fail", end="")
PYBUGS
}

review_capture_output() {  # defaults use the CLI's final-message file only
    [ -n "${cli_out:-}" ] || return 0
    local capture_rc=0
    leaf_save_output "$cli_out" review-cli || capture_rc=1
    if [ "$1" = 0 ]; then
        python3 - "$final_out" > "$out" <<'PYFINAL'
import os, stat, sys
fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
with os.fdopen(fd, "rb") as f:
    if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
        raise ValueError("review final message is not a regular file")
    data = f.read(16 * 1024 * 1024 + 1)
if not data.strip() or len(data) > 16 * 1024 * 1024:
    raise ValueError("review final message is empty or exceeds 16 MiB")
sys.stdout.buffer.write(data)
PYFINAL
        [ "$?" = 0 ] || capture_rc=1
    else
        cat "$cli_out" > "$out" 2>/dev/null || capture_rc=1
    fi
    rm -f "$cli_out" "$final_out"
    return "$capture_rc"
}

review_run() {  # -> decimal / parse-fail / timeout; window-closed returns rc 125
    local out="$2" instrfile="$2.instr" rpid waited=0 rc instr goal="$1" cli_out="" final_out=""
    [ "${task_kind:-}" != idle ] || goal="${BURN_PROMPT:-$1}"
    review_groups_prepare || { printf 'parse-fail'; return 0; }
    : > "$out" || { printf 'parse-fail'; return 0; }
    if ! ck_run_check; then
        printf '[review interrupted: %s]\n' "$CK_WINDOW_REASON" >> "$out"
        printf 'window-closed'
        return 125
    fi
    instr="你是独立代码审查员, 与实现者是两个互不相干的会话。本任务目标: $goal 。请先用 git status --short 和 git diff HEAD 查看当前仓库的全部未提交改动, 再阅读相关文件。只报告真实的 bug(错误行为/数据损坏/安全问题/明确的逻辑错误), 忽略风格和主观建议。先列出发现的问题(文件:行号 + 一句话说明), 最后一行必须是 BUGS: <数量>; 没有问题就写 无问题 并输出 BUGS: 0。"
    if [ -n "${CODEXC_LEAF_EVIDENCE_DIR:-}" ]; then
        instr="你是独立验收审查员。本叶目标: $goal 。本叶基线 HEAD=${CODEXC_LEAF_BASE_HEAD:-unborn}；候选 HEAD=${CODEXC_LEAF_CANDIDATE_HEAD:-unborn}。先读取 $CODEXC_LEAF_EVIDENCE_DIR/changes.diff 和 baseline.json/candidate.json；它们给出本叶开工前到本次候选的精确变化（包括 worker 已提交改动，勿只看 git diff HEAD）。按目标检查实现和证据，再阅读相关源文件。只读审查，不修改源码、测试、门禁或队列。只有目标已满足、未发现真实bug才输出 BUGS: 0；否则列出文件:行号及真实问题，最后一行 BUGS: <数量>。"
    fi
    printf '%s' "$instr" > "$instrfile" || { printf 'parse-fail'; return 0; }
    if [ -n "${CODEXC_REVIEW_CMD:-}" ]; then
        command python3 "$CK_COMMON_DIR/ck-review-process.py" launch "$CK_REVIEW_GROUP_DIR" "$CK_REVIEW_GROUP_TOKEN" /bin/bash -c "$CODEXC_REVIEW_CMD" < "$instrfile" > "$out" 2>&1 &
    else
        cli_out="$out.cli"; final_out="$out.final"
        rm -f "$cli_out" "$final_out"
        command python3 "$CK_COMMON_DIR/ck-review-process.py" launch "$CK_REVIEW_GROUP_DIR" "$CK_REVIEW_GROUP_TOKEN" codex exec --ephemeral -s read-only --output-last-message "$final_out" - < "$instrfile" > "$cli_out" 2>&1 &
    fi
    rpid=$!
    while kill -0 "$rpid" 2>/dev/null; do
        if ! ck_run_check; then
            review_group_stop "$rpid"
            wait "$rpid" 2>/dev/null
            review_capture_output 1 || true
            printf '\n[review interrupted: %s]\n' "$CK_WINDOW_REASON" >> "$out"
            rm -f "$instrfile"
            printf 'window-closed'
            return 125
        fi
        if [ "$waited" -ge "$CODEXC_REVIEW_TIMEOUT" ]; then
            review_group_stop "$rpid"
            wait "$rpid" 2>/dev/null
            review_capture_output 1 || true
            printf '\n[review timed out after %ss]\n' "$CODEXC_REVIEW_TIMEOUT" >> "$out"
            rm -f "$instrfile"
            printf 'timeout'
            return 0
        fi
        [ $((waited % 30)) -eq 29 ] && status_touch
        sleep 1
        waited=$((waited + 1))
    done
    wait "$rpid" 2>/dev/null; rc=$?
    review_group_stop "$rpid" || { review_capture_output 1 || true; printf 'parse-fail'; return 0; }
    if ! review_capture_output "$rc"; then
        rm -f "$instrfile"
        printf 'parse-fail'; return 0
    fi
    rm -f "$instrfile"
    if ! ck_run_check; then
        printf '\n[review interrupted: %s]\n' "$CK_WINDOW_REASON" >> "$out"
        printf 'window-closed'
        return 125
    fi
    if [ "$rc" -ne 0 ]; then
        printf '\n[review exited with status %s]\n' "$rc" >> "$out"
        printf 'parse-fail'
        return 0
    fi
    leaf_save_output "$out" review || { printf 'parse-fail'; return 0; }
    parse_bugs "$out"
}

review_batch() {  # 0=all zero; 1=findings; 2=timeout; 3=unusable; 125=window/stop
    local task="$1" base="$2" count="${3:-$CODEXC_REVIEW_PASS}" i p pids=() rc=0 child_rc b first_bad=""
    : > "$base"
    REVIEW_BATCH_RESULT=0
    for ((i=1; i<=count; i++)); do
        review_run "$task" "$base.$i" > "$base.$i.result" &
        pids+=($!)
    done
    for p in "${pids[@]}"; do
        wait "$p" 2>/dev/null; child_rc=$?
        if [ "$child_rc" = 125 ]; then
            rc=125; REVIEW_BATCH_RESULT=window-closed
        elif [ "$child_rc" != 0 ] && [ "$rc" != 125 ]; then
            rc=3; REVIEW_BATCH_RESULT=parse-fail
        fi
    done
    for ((i=1; i<=count; i++)); do
        b="$(cat "$base.$i.result" 2>/dev/null)"
        case "$b" in
            window-closed) rc=125; REVIEW_BATCH_RESULT=window-closed ;;
            timeout) [ "$rc" = 125 ] || { rc=2; REVIEW_BATCH_RESULT=timeout; } ;;
            parse-fail|''|*[!0-9]*) [ "$rc" = 125 ] || [ "$rc" -eq 2 ] || { rc=3; REVIEW_BATCH_RESULT=parse-fail; } ;;
            0) ;;
            *) [ "$rc" -ne 0 ] || { rc=1; REVIEW_BATCH_RESULT=bugs; } ;;
        esac
        if [ "$b" != "0" ]; then
            printf '\n[review %s: %s]\n' "$i" "$b" >> "$base"
            cat "$base.$i" >> "$base" 2>/dev/null
        fi
    done
    return "$rc"
}

review_collect() {  # Direct call only: command substitution defers TERM traps.
    local resultfile="$2.result" review_job review_rc
    REVIEW_RESULT=parse-fail
    : > "$resultfile" || return 1
    review_run "$1" "$2" > "$resultfile" &
    review_job=$!
    wait "$review_job"; review_rc=$?
    REVIEW_RESULT="$(cat "$resultfile")"
    rm -f "$resultfile"
    return "$review_rc"
}

review_tail() { LC_ALL=C tr -d '\000' < "$1" | tr '\n' ' ' | tail -c 600 | LC_ALL=C iconv -c -f UTF-8 -t UTF-8; }

result_marker() {  # only the final nonempty line may complete the protocol
    python3 - "$1" <<'PYMARK'
import re, sys
try:
    lines = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
except OSError:
    lines = []
last = next((line.strip() for line in reversed(lines) if line.strip()), "")
if re.search(r"TASK_RESULT:[ \t]*DONE(?:[ \t]+\(idle\))?$", last, re.I):
    print("DONE", end="")
elif re.search(r"TASK_RESULT:[ \t]*BLOCKED(?::.*)?$", last, re.I):
    print("BLOCKED", end="")
else:
    print("none", end="")
PYMARK
}

# one-time state-dir migration (v2.0: .codexc -> .codingkeeper). Runs before
# anything creates the new dir; if a fresh scaffold already exists, the old
# authoritative files (journal/queue/halt/sessions) override it.
# 运行时残渣 (loop.pid/.hl-*/.loop-*) 不迁: 旧目录的 pid 合并过来会被锁误读
migrate_state_dir() {
    [ -d .codexc ] || return 0
    # Migrate only durable data. The current runner may already hold its lock;
    # old runtime files must never replace that ownership or another live lane.
    python3 - <<'PYMIGRATE'
import os
source, target = ".codexc", ".codingkeeper"
os.makedirs(target, exist_ok=True)
for name in os.listdir(source):
    if name in {"loop.pid", "runner.lock", "runner.owner", "watcher.pid", "status.json"} or name.startswith((".hl-", ".loop-", ".runner-")):
        continue
    # Existing new-format data is authoritative; keep conflicts for inspection.
    dest = os.path.join(target, name)
    if not os.path.lexists(dest):
        os.rename(os.path.join(source, name), dest)
try: os.rmdir(source)
except OSError: pass
PYMIGRATE
    log "state migration checked: durable .codexc data copied without replacing current state"
}

status_write() {  # text tool active started_at [phase] [next_run_at]
    local pdir=".codingkeeper"
    # 记录最近载荷供 status_touch 心跳复用 (gate/review 阶段保活)
    _ST_TASK="$1"; _ST_TOOL="${2:-}"; _ST_ACTIVE="${3:-0}"; _ST_STARTED="${4:-0}"
    _ST_PHASE="${5:-}"; _ST_NEXT="${6:-0}"
    python3 - "$pdir" "$PWD" "$1" "${2:-}" "${3:-0}" "${4:-0}" "${5:-}" "${6:-0}" "$CK_COMMON_DIR/ck-leaf.py" <<'PYEOF'
import importlib.util, json, os, sys, tempfile
pdir, project, task = sys.argv[1], sys.argv[2], sys.argv[3]
task = " ".join(str(task).split())
if len(task) > 32:
    task = task[:30].rstrip() + "…"
tool, active, started_at = sys.argv[4], sys.argv[5] == "1", int(sys.argv[6] or 0)
phase = sys.argv[7] or task
try:
    next_run_at = max(0, int(sys.argv[8] or 0))
except (ValueError, OverflowError):
    next_run_at = 0
parked = os.path.exists(os.path.join(pdir, "loop.halt"))
# ready 计数口径 = 仅 ## ready 区 (review-needed 的自评任务不计入)
ready = 0
try:
    spec = importlib.util.spec_from_file_location("leaf", sys.argv[9])
    leaf = importlib.util.module_from_spec(spec); spec.loader.exec_module(leaf)
    ready = len(leaf.queue_entries(leaf.read_queue(os.path.join(pdir, "queue.md"))))
except (OSError, ValueError, UnicodeError):
    pass
snap = {"project": project, "task": task, "phase": phase, "parked": parked,
        "tool": tool, "active": active, "started_at": started_at,
        "next_run_at": next_run_at, "ready": ready,
        "ts": int(__import__("time").time())}
# 原子替换: 桌面面板每 2s 轮询本文件, 非原子写会被读到半截 JSON
os.makedirs(pdir, exist_ok=True)
fd, tmp = tempfile.mkstemp(prefix=".status-", dir=pdir)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, ensure_ascii=False)
    os.replace(tmp, os.path.join(pdir, "status.json"))
finally:
    if os.path.exists(tmp): os.unlink(tmp)
PYEOF
    return 0
}

# 心跳: 用最近一次 status_write 的载荷刷新 ts (gate/review 同步阻塞期间保活,
# 横幅的 running 判定依赖 ts 新鲜度 — 阻塞阶段无心跳会被误显"已停")
status_touch() {
    [ -n "${_ST_TASK:-}" ] || return 0
    status_write "$_ST_TASK" "$_ST_TOOL" "$_ST_ACTIVE" "$_ST_STARTED" "${_ST_PHASE:-}" "${_ST_NEXT:-0}"
}

register_project() {
    local real
    real="$(pwd -P)" || return 1
    if [ "${CODEXC_REGISTER_TEMP:-0}" != "1" ]; then
        case "$real/" in /tmp/*|/private/tmp/*|"${TMPDIR:-/tmp/}"*) return 0 ;; esac
    fi
    python3 - "$HOME/.codingkeeper" "$real" <<'PYREGISTER'
import fcntl, os, sys, tempfile
state, project = sys.argv[1:]
if "\n" in project or "\r" in project:
    print("project path contains a newline and cannot be registered", file=sys.stderr)
    raise SystemExit(1)
os.makedirs(state, mode=0o700, exist_ok=True)
with os.fdopen(os.open(os.path.join(state, "projects.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "a+") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    registry = os.path.join(state, "projects")
    try:
        with open(registry, encoding="utf-8") as fh:
            entries = [os.path.realpath(p) for p in fh.read().splitlines() if p]
    except FileNotFoundError:
        entries = []
    entries = list(dict.fromkeys(entries + [project]))
    fd, tmp = tempfile.mkstemp(prefix=".projects-", dir=state)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(entries) + "\n")
        os.replace(tmp, registry)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
PYREGISTER
}

usage() {
    awk 'NR == 1 { next } /^set -u/ { exit } { sub(/^# ?/, ""); print }' "$0"
}

detect_test_cmds() {  # 探测项目测试命令 (uv/pytest/npm/bun/pnpm/yarn/go/cargo/flutter/make)
    # python
    if [ -f uv.lock ]; then
        echo "uv run pytest -q"
    elif [ -f pyproject.toml ] && grep -q 'pytest' pyproject.toml 2>/dev/null; then
        echo "python3 -m pytest -q"
    elif [ -f pytest.ini ] || [ -f setup.cfg ]; then
        echo "python3 -m pytest -q"
    elif [ -f requirements.txt ] && grep -qi 'pytest' requirements.txt 2>/dev/null; then
        echo "python3 -m pytest -q"
    fi
    # node (runner picked from the lockfile)
    if [ -f package.json ] && grep -q '"test"' package.json 2>/dev/null; then
        if [ -f bun.lockb ] || [ -f bun.lock ]; then echo "bun run test"
        elif [ -f pnpm-lock.yaml ]; then echo "pnpm test"
        elif [ -f yarn.lock ]; then echo "yarn test"
        else echo "npm test"
        fi
    fi
    [ -f go.mod ] && echo "go test ./..."
    [ -f Cargo.toml ] && echo "cargo test --quiet"
    [ -f pubspec.yaml ] && echo "flutter test"
    if [ -f Makefile ] && grep -qE '^test[[:space:]]*:' Makefile 2>/dev/null; then
        echo "make test"
    fi
    return 0
}

gate_init_write() {  # 生成 .codingkeeper/gate.sh: 探测到命令=真门禁, 否则占位。
    # 两通道 (codexc-loop / codexc-headless) 共用 — 曾漂移: loop 探测生成,
    # headless 永远占位, 而 headless 的 require_gate_check 对占位当场停炉,
    # 无人值守通道永远无法自举 (2026-11-10 可维护性轮实证)。返回 0=已探测。
    local cmds
    cmds="$(detect_test_cmds)"
    if [ -n "$cmds" ]; then
        {
            echo '#!/bin/bash'
            echo '# 验收门禁: 由 init 自动探测生成 — 请核对是否符合本项目'
            echo '# 外环只认本脚本的真实退出码; 命令写错会在第一次任务时暴露'
            echo 'set -e'
            while IFS= read -r c; do
                [ -n "$c" ] || continue
                echo "echo \"[gate] $c\""
                echo "$c"
            done <<< "$cmds"
        } > ".codingkeeper/gate.sh"
        chmod +x ".codingkeeper/gate.sh"
        GATE_INIT_CMDS="$cmds"
        return 0
    fi
    cat > ".codingkeeper/gate.sh" <<'EOF'
#!/bin/bash
# CK_GATE_PLACEHOLDER=1
# 未探测到测试命令 — 把本项目的真实测试放进来; 外环只认退出码。
# 示例: set -e; pytest -q --cov-fail-under=80
echo "(gate placeholder: 未探测到测试命令 — 请编辑本文件)"
exit 0
EOF
    chmod +x ".codingkeeper/gate.sh"
    GATE_INIT_CMDS=""
    return 1
}
