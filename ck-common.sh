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

log() {
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

kill_tree() {  # $1=pid — kill a timed-out gate/review and its whole child tree
    local p
    for p in $(pgrep -P "$1" 2>/dev/null); do kill_tree "$p"; done
    kill -9 "$1" 2>/dev/null
    return 0
}

loop_cleanup() {
    # shellcheck disable=SC2086
    rm -f $LOOP_TMP_FILES ".codingkeeper/loop.pid" 2>/dev/null
    return 0
}

queue_next() {  # $1=queue file -> prints "lineno<TAB>b64(task)" or nothing
    python3 - "$1" <<'PYEOF'
import base64, sys
try:
    lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
except OSError:
    raise SystemExit(0)
section = ""
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if stripped.startswith("##"):
        section = stripped.lstrip("#").strip().lower()
        continue
    if section != "ready" or not stripped.startswith("- [ ]"):
        continue
    task = stripped[len("- [ ]"):].strip()
    if not task:
        continue
    b64 = base64.b64encode(task.encode("utf-8")).decode("ascii")
    print(f"{i}\t{b64}")
    break
PYEOF
}

queue_mark_done() {  # $1=queue file $2=b64(task) -> prints "marked" or "not-found"
    python3 - "$1" "$2" <<'PYEOF'
import base64, os, sys
queue, b64 = sys.argv[1], sys.argv[2]
task = base64.b64decode(b64).decode("utf-8", "replace")
try:
    lines = open(queue, encoding="utf-8").read().splitlines()
except OSError:
    print("not-found"); raise SystemExit(0)
section = ""
done_it = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith("##"):
        section = stripped.lstrip("#").strip().lower()
        continue
    if section == "ready" and stripped == f"- [ ] {task}":
        lines[i] = line.replace("- [ ]", "- [x]", 1)
        done_it = True
        break
# 原子替换: queue.md 是循环的任务源真相, 半截写会让任务行凭空消失
tmp = queue + ".codingkeeper-tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
os.replace(tmp, queue)
print("marked" if done_it else "not-found")
PYEOF
}

journal_append() {
    printf '%s | %s | %s\n' "$(date '+%F %T')" "$1" "$2" >> ".codingkeeper/journal"
}

gate_run() {  # $1=outfile; 0=pass
    local outfile="$1" gpid waited=0 rc
    : > "$outfile"
    if [ ! -x ".codingkeeper/gate.sh" ]; then
        printf 'no gate.sh — gate skipped\n' > "$outfile"
        return 0
    fi
    bash ".codingkeeper/gate.sh" > "$outfile" 2>&1 &
    gpid=$!
    while kill -0 "$gpid" 2>/dev/null; do
        if [ "$waited" -ge "$CODEXC_GATE_TIMEOUT" ]; then
            kill_tree "$gpid"
            wait "$gpid" 2>/dev/null
            printf '\n[gate timed out after %ss]\n' "$CODEXC_GATE_TIMEOUT" >> "$outfile"
            return 124
        fi
        sleep 1
        waited=$((waited + 1))
    done
    wait "$gpid" 2>/dev/null
    rc=$?
    return "$rc"
}

gate_tail() { tr '\n' ' ' < "$1" | tail -c 500; }

parse_bugs() {  # $1=review output file -> bug count or "parse-fail"
    [ -f "$1" ] || { printf 'parse-fail'; return; }
    local last
    last="$(grep -an 'BUGS:' "$1" | tail -1 | sed -E 's/.*BUGS:[[:space:]]*([0-9]+).*/\1/')"
    case "$last" in
        ''|*[!0-9]*) printf 'parse-fail' ;;
        *) printf '%s' "$last" ;;
    esac
}

review_run() {  # $1=task text $2=outfile -> bug count / "parse-fail" / "timeout"
    local out="$2" instrfile="$2.instr" rpid waited=0 bugs
    : > "$out"
    instr="你是独立代码审查员, 与实现者是两个互不相干的会话。本任务目标: $1 。请先用 git status --short 和 git diff HEAD 查看当前仓库的全部未提交改动, 再阅读相关文件。只报告真实的 bug(错误行为/数据损坏/安全问题/明确的逻辑错误), 忽略风格和主观建议。先列出发现的问题(文件:行号 + 一句话说明), 最后一行必须是 BUGS: <数量>; 没有问题就写 无问题 并输出 BUGS: 0。"
    printf '%s' "$instr" > "$instrfile"
    if [ -n "${CODEXC_REVIEW_CMD:-}" ]; then
        ( eval "$CODEXC_REVIEW_CMD" ) < "$instrfile" > "$out" 2>&1 &
    else
        ( codex exec --ephemeral -s read-only - ) < "$instrfile" > "$out" 2>&1 &
    fi
    rpid=$!
    while kill -0 "$rpid" 2>/dev/null; do
        if [ "$waited" -ge "$CODEXC_REVIEW_TIMEOUT" ]; then
            kill_tree "$rpid"
            wait "$rpid" 2>/dev/null
            printf '\n[review timed out after %ss]\n' "$CODEXC_REVIEW_TIMEOUT" >> "$out"
            rm -f "$instrfile"
            printf 'timeout'
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    wait "$rpid" 2>/dev/null
    rm -f "$instrfile"
    LC_ALL=C tr -d '\000' < "$out" > "$out.n" && mv "$out.n" "$out"
    parse_bugs "$out"
}

review_tail() { LC_ALL=C tr -d '\000' < "$1" | tr '\n' ' ' | tail -c 600; }

result_marker() {  # $1=stdout file -> DONE / BLOCKED / none
    [ -s "$1" ] || { printf 'none'; return; }
    line="$(grep -ioE 'TASK_RESULT:[[:space:]]*(DONE|BLOCKED)' "$1" | tail -1 | tr '[:upper:]' '[:lower:]')"
    case "$line" in
        *done*)    printf 'DONE' ;;
        *blocked*) printf 'BLOCKED' ;;
        *)         printf 'none' ;;
    esac
}

# one-time state-dir migration (v2.0: .codexc -> .codingkeeper). Runs before
# anything creates the new dir; if a fresh scaffold already exists, the old
# authoritative files (journal/queue/halt/sessions) override it.
migrate_state_dir() {
    [ -d .codexc ] || return 0
    if [ ! -d .codingkeeper ]; then
        mv .codexc .codingkeeper 2>/dev/null
        log "state dir migrated: .codexc -> .codingkeeper (journal/queue preserved)"
        return 0
    fi
    ( shopt -s dotglob; cd .codexc 2>/dev/null && mv -f * ../.codingkeeper/ 2>/dev/null )
    rmdir .codexc 2>/dev/null
    log "state dir merged: .codexc contents -> .codingkeeper"
}

status_write() {  # $1=状态文本 $2=工具名 $3=active(1/0) $4=started_at epoch(0=未知)
    local pdir=".codingkeeper"
    python3 - "$pdir" "$PWD" "$1" "${2:-}" "${3:-0}" "${4:-0}" <<'PYEOF'
import json, os, sys
pdir, project, task = sys.argv[1], sys.argv[2], sys.argv[3]
task = " ".join(str(task).split())
if len(task) > 32:
    task = task[:30].rstrip() + "…"
tool, active, started_at = sys.argv[4], sys.argv[5] == "1", int(sys.argv[6] or 0)
parked = os.path.exists(os.path.join(pdir, "loop.halt"))
snap = {"project": project, "task": task, "phase": task, "parked": parked,
        "tool": tool, "active": active, "started_at": started_at,
        "ready": sum(1 for l in open(os.path.join(pdir, "queue.md"), encoding="utf-8") if l.startswith("- [ ]")) if os.path.exists(os.path.join(pdir, "queue.md")) else 0,
        "ts": int(__import__("time").time())}
# 原子替换: 桌面面板每 2s 轮询本文件, 非原子写会被读到半截 JSON
tmp = os.path.join(pdir, "status.json.codingkeeper-tmp")
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(snap, fh, ensure_ascii=False)
os.replace(tmp, os.path.join(pdir, "status.json"))
PYEOF
    return 0
}

register_project() {
    # /tmp 下的测试世界不注册 — 集成测试会污染真实注册表 (悬浮条/ck status)
    case "$PWD" in /tmp/*|/private/tmp/*|"$TMPDIR"*) return 0 ;; esac
    mkdir -p "$HOME/.codingkeeper" 2>/dev/null
    local reg="$HOME/.codingkeeper/projects"
    grep -qxF "$PWD" "$reg" 2>/dev/null || printf '%s\n' "$PWD" >> "$reg"
    return 0
}

usage() {
    awk 'NR == 1 { next } /^set -u/ { exit } { sub(/^# ?/, ""); print }' "$0"
}
