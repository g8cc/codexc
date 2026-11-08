#!/bin/bash
# burn-watch.sh — 无 LLM 烧炉看守 (纯 bash 3.2 兼容, 5 分钟一轮)
# 部署: ~/.codingkeeper/burn-watch.sh -> 本文件 (symlink); 改本文件前必须先杀运行实例
# 职责: 三炉存活/瞬时 park 有界复燃/真问题告警/token 记账/日志轮转
LOG="$HOME/.codex/codexc-watch.log"
ALERT="$HOME/.codingkeeper/burn-ALERTS.txt"
ACCOUNT="$HOME/.codingkeeper/burn-log.txt"
LOCKDIR="$HOME/.codingkeeper/watchdog.lock"
DAY="$(date +%F)"
GREP=/usr/bin/grep
ZCJS=/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs
# This watchdog serves ZCode only. Empty/unset configuration permits 24/7;
# an explicit availability policy is forwarded unchanged to every restart.
CODEXC_ACTIVE_WINDOW="${CODEXC_ACTIVE_WINDOW:-}"   # 默认不限制 (全天燃烧)
CODEXC_ACTIVE_TZ="${CODEXC_ACTIVE_TZ:-Asia/Shanghai}"
WATCH_DIR="$(python3 -c 'import os, sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "${BASH_SOURCE[0]:-$0}" 2>/dev/null)"

watch_window_open() {
    local result allowed deadline next_open reason extra
    [ -n "$WATCH_DIR" ] && [ -f "$WATCH_DIR/ck-window.py" ] || return 125
    result="$(CODEXC_ACTIVE_WINDOW="$CODEXC_ACTIVE_WINDOW" CODEXC_ACTIVE_TZ="$CODEXC_ACTIVE_TZ" \
        python3 "$WATCH_DIR/ck-window.py" --format tsv 2>/dev/null)" || return 125
    IFS=$'\t' read -r allowed deadline next_open reason extra <<< "$result"
    [ "$allowed" = 1 ] && [ -z "$extra" ] || return 125
    case "$result" in *$'\n'*) return 125 ;; esac
    case "$deadline:$next_open" in *[!0-9:]*|:*|*:) return 125 ;; esac
    case "$reason" in
        disabled) [ -z "$CODEXC_ACTIVE_WINDOW" ] && [ "$deadline:$next_open" = 0:0 ] || return 125 ;;
        allowed) [ "$deadline" -gt 0 ] 2>/dev/null || return 125 ;;
        *) return 125 ;;
    esac
    return 0
}

proj_alive() {  # $1=project dir — pid 文件或 cwd 扫描 (双侧物理路径归一), 0=活
    local d="$1" pid rpid rcwd dreal
    pid="$(cat "$d/.codingkeeper/loop.pid" 2>/dev/null)"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && return 0
    dreal="$(cd "$d" 2>/dev/null && pwd -P)" || dreal="$d"
    for rpid in $(pgrep -f 'codexc-headless run' 2>/dev/null); do
        rcwd="$(lsof -a -p "$rpid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
        rcwd="$(cd "$rcwd" 2>/dev/null && pwd -P)" || rcwd="$rcwd"
        [ "$rcwd" = "$dreal" ] && return 0
    done
    return 1
}

rotate_log() {  # $1=文件 $2=保留行数 — >1MB 或 >2000 行时归档旧内容 (gz, 90 天)
    local f="$1" keep="$2" total old
    [ -f "$f" ] || return 0
    total=$($GREP -c . "$f" 2>/dev/null); total=${total:-0}
    [ "$(stat -f '%z' "$f" 2>/dev/null || echo 0)" -lt 1048576 ] && [ "$total" -le 2000 ] && return 0
    old=$((total - keep)); [ "$old" -le 0 ] && return 0
    head -n "$old" "$f" | gzip >> "${f%.txt}-$(date +%Y%m).txt.gz"
    tail -n "$keep" "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    find "$(dirname "$f")" -name "$(basename "${f%.txt}")-*.txt.gz" -mtime +90 -delete 2>/dev/null
}

alert() {  # $1=proj $2=text — 同因当日去重 (动态变量, bash 3.2 兼容)
    local var last text esc
    var="seen_$(echo "$1" | tr -c 'a-zA-Z0-9' '_')"
    eval "last=\${$var:-}"
    [ "$last" = "$DAY" ] && return 0
    eval "$var=\$DAY"
    echo "$(date '+%F %T') | $1 | $2" >> "$ALERT"
    if [ "${BURN_WATCH_NOTIFY:-1}" = "1" ]; then
        text="$1: $2"
        esc="${text//\\/\\\\}"; esc="${esc//\"/\\\"}"
        osascript -e "display notification \"$esc\" with title \"burn-watch\"" 2>/dev/null
    fi
    return 0
}

PROBE_TTL=1800   # 探测失败后 30 分钟内不再建新探测会话 (39 个 replyOK 堆积教训)
cli_alive() {  # 双探重试 (间隔 5s): 单发会撞网关抖动窗口误判"凭证真死"
    local out try ok failts now
    # TTL: 刚探测失败过 → 沿用失败结论, 不再建新探测会话
    failts="$(cat "$HOME/.codingkeeper/cli-probe-fail-ts" 2>/dev/null || echo 0)"
    now="$(date +%s)"
    if [ "${failts:-0}" -gt 0 ] && [ $((now - failts)) -lt "$PROBE_TTL" ]; then
        return 1
    fi
    watch_window_open || return 125
    out="$(mktemp "${TMPDIR:-/tmp}/watch-probe.XXXXXX")" || return 1
    ok=0
    for try in 1 2; do
        # Retry sleep may cross 09:00. Recheck immediately before every probe.
        watch_window_open || { rm -f "$out"; return 125; }
        "$ZCJS" --prompt replyOK --cwd "$HOME/.codingkeeper/probe-cwd" --json --no-color > "$out" 2>/dev/null
        $GREP -q response "$out" && { ok=1; break; }
        [ "$try" = 2 ] || sleep 5
    done
    # 自清理: 探测会话用完即删 (只删形如 sess_* 的 id, 防注入)
    psid="$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8', errors='replace'))
    sid = d.get('sessionId', '')
    print(sid if sid.startswith('sess_') else '')
except Exception:
    print('')
" "$out" 2>/dev/null)"
    case "$psid" in
        sess_*) sqlite3 "$HOME/.zcode/cli/db/db.sqlite" "DELETE FROM session WHERE id='$psid'" 2>/dev/null
                sqlite3 "$HOME/.zcode/v2/tasks-index.sqlite" "DELETE FROM tasks WHERE task_id='$psid'" 2>/dev/null ;;
    esac
    rm -f "$out"
    if [ "$ok" = "1" ]; then
        rm -f "$HOME/.codingkeeper/cli-probe-fail-ts"
        return 0
    fi
    date +%s > "$HOME/.codingkeeper/cli-probe-fail-ts"
    return 1
}

revive() {  # $1=proj — 有界、保留 halt 的 nohup 复燃
    local d="$HOME/Documents/work/code/AI/AIworkspace/$1"
    watch_window_open || return 125
    # A halt belongs to this project/operator; never clear it from global logs.
    [ ! -e "$d/.codingkeeper/loop.halt" ] || return 1
    [ -d "$d" ] || return 1
    ( cd "$d" || exit 1
      # The resumed runner enforces the same policy for the full child lifetime.
      CODEXC_ACTIVE_WINDOW="$CODEXC_ACTIVE_WINDOW" CODEXC_ACTIVE_TZ="$CODEXC_ACTIVE_TZ" \
      CODEXC_REVIEW_CMD="$d/.codingkeeper/review-leaf.sh" nohup zcodec run >> "$LOG" 2>&1 & )
}

# 探测会话自动清理: 看门狗的健康探测 (replyOK) 会在 zcode db 留会话行,
# 1 小时后自动删除 — 界面不再堆积 (级联清理消息与用量记录)
cleanup_probe_sessions() {
    # 自动化通道会话行 (探测/审核/worker 废弃链) 1 小时后清除, 界面零堆积。
    # worker 活链指针 (各项目 zcode-session-id) 无论多久都不清: 超长轮次
    # 中途行不刷新, 按时间判死会误杀; 真废弃链由 worker 端 heal 在 resume
    # 失败时自清 sid 文件换新链。
    local cutoff=$(( $(date +%s) - 3600 ))000
    local live sid excludes="" chain_clause=""
    for live in "$HOME"/Documents/work/code/AI/AIworkspace/*/.codingkeeper/zcode-session-id \
                "$HOME"/Documents/work/code/AI/AIworkspace/*/.codingkeeper/zcode-session-id.retry; do
        [ -f "$live" ] || continue
        sid="$(head -c 64 "$live" 2>/dev/null | tr -cd 'A-Za-z0-9_-')"
        case "$sid" in sess_*) excludes="$excludes '$sid'," ;; esac
    done
    excludes="${excludes%,}"
    [ -n "$excludes" ] && chain_clause="AND id NOT IN ($excludes)"
    sqlite3 "$HOME/.zcode/cli/db/db.sqlite" \
      "DELETE FROM session WHERE time_updated < $cutoff AND (
         title IN ('replyOK','Reply with exactly: OK')
         OR title LIKE 'Review the single leaf%'
         OR title LIKE '你是独立%'
         OR (title LIKE '[codexc-headless]%' $chain_clause))" 2>/dev/null
    # 桌面侧栏的 tasks-index 是独立库, 同步清扫 (列名 task_id)
    [ -n "$excludes" ] && chain_clause="AND task_id NOT IN ($excludes)"
    sqlite3 "$HOME/.zcode/v2/tasks-index.sqlite" \
      "DELETE FROM tasks WHERE updated_at < $cutoff AND (
         title IN ('replyOK','Reply with exactly: OK')
         OR title LIKE 'Review the single leaf%'
         OR title LIKE '你是独立%'
         OR (title LIKE '[codexc-headless]%' $chain_clause))" 2>/dev/null
    return 0
}

patrol_once() {
    local proj d pid alive halted reason rcount tok fp_j sp_j s2_j
    DAY="$(date +%F)"   # long-running watchdogs must roll over at midnight
    for proj in fingerprint sale soul2soul wechatflow; do
        d="$HOME/Documents/work/code/AI/AIworkspace/$proj"
        [ -d "$d" ] || continue
        halted=0; [ -f "$d/.codingkeeper/loop.halt" ] && halted=1
        if [ "$halted" = 1 ]; then
            halt_reason="$(head -c 200 "$d/.codingkeeper/loop.halt" 2>/dev/null)"
            case "$halt_reason" in
                *"review rounds exhausted"*|*"review output unparseable"*)
                    # 审核类 park 有界自动复燃: 夜间不再整夜停摆。
                    # 预算与退出类复燃共用 2/日; 超限 = 同一叶子反复被拒, 留档待人。
                    rcount="$(awk -v day="$DAY" -v key="复燃#$proj#" 'index($0, day " ") == 1 && index($0, key) { n++ } END { print n+0 }' "$ALERT" 2>/dev/null)"
                    rcount=${rcount:-0}
                    if [ "$rcount" -ge 2 ]; then
                        alert "$proj" "复燃超限(2) — 审核 park 留档待人 (最后park: ${halt_reason:0:40})"
                        continue
                    fi
                    rm -f "$d/.codingkeeper/loop.halt"
                    if revive "$proj"; then
                        echo "$(date '+%F %T') | $proj | 复燃#$proj#$rcount (审核park自愈: ${halt_reason:0:40})" >> "$ALERT"
                    fi
                    continue ;;
                *)
                    alert "$proj" "项目已暂停 — 保留 loop.halt，等待 runner 有界恢复或人工处理"
                    continue ;;
            esac
        fi
        # Check each project, not only each five-minute patrol: a previous
        # project can finish just as the permitted interval closes.
        watch_window_open || continue
        proj_alive "$d" && continue
        reason="runner exited without a halt"
        # 统一有界复燃: 每项目每日 2 次 (不依赖全局日志归因, 对一切 park 类生效);
        # 超限 = 同一问题反复出现, 真问题留档待人, 防坏叶无限烧
        rcount="$(awk -v day="$DAY" -v key="复燃#$proj#" 'index($0, day " ") == 1 && index($0, key) { n++ } END { print n+0 }' "$ALERT" 2>/dev/null)"
        rcount=${rcount:-0}
        if [ "$rcount" -ge 2 ]; then
            alert "$proj" "复燃超限(2) — 真问题留档待人 (最后park: ${reason:0:40})"
            continue
        fi
        if revive "$proj"; then
            echo "$(date '+%F %T') | $proj | 复燃#$proj#$rcount (${reason:0:50})" >> "$ALERT"
        fi
    done
    cleanup_probe_sessions
    local day0
    day0="$(date -j -f '%F %T' "$(date +%F) 00:00:00" +%s)000"
    tok="$(sqlite3 -readonly "$HOME/.zcode/cli/db/db.sqlite" "SELECT printf('%.1fM',sum(input_tokens+output_tokens)/1e6) FROM model_usage WHERE started_at>=$day0" 2>/dev/null)"
    # 质量退化遥测: 审核轮数/gate 重试抬头 → alert (文本固定, alert 按日去重)
    for qproj in fingerprint sale soul2soul wechatflow; do
        qjournal="$HOME/Documents/work/code/AI/AIworkspace/$qproj/.codingkeeper/journal"
        [ -f "$qjournal" ] || continue
        qtrend="$(python3 "$HOME/Documents/work/code/AI/AIworkspace/codexc/ck-quality-trend.py" "$qjournal" "$HOME/Documents/work/code/AI/AIworkspace/$qproj/.codingkeeper/parks.log" 2>/dev/null)" || continue
        echo "quality-trend $qproj: $qtrend"
        case "$qtrend" in
            *'"verdict": "alert"'*)
                alert "$qproj" "质量趋势预警 — 审核轮数/gate 重试抬头, 详情看 burn-watch.log 的 quality-trend 行" ;;
        esac
    done
    fp_j="$(wc -l < "$HOME/Documents/work/code/AI/AIworkspace/fingerprint/.codingkeeper/journal" 2>/dev/null | xargs)"
    sp_j="$(wc -l < "$HOME/Documents/work/code/AI/AIworkspace/sale/.codingkeeper/journal" 2>/dev/null | xargs)"
    s2_j="$(wc -l < "$HOME/Documents/work/code/AI/AIworkspace/soul2soul/.codingkeeper/journal" 2>/dev/null | xargs)"
    wf_j="$(wc -l < "$HOME/Documents/work/code/AI/AIworkspace/wechatflow/.codingkeeper/journal" 2>/dev/null | xargs)"
    echo "$(date '+%F %T') | fp_journal=$fp_j | sale_journal=$sp_j | s2_journal=$s2_j | wf_journal=$wf_j | 今日token=$tok" >> "$ACCOUNT"
}

# A kernel lock survives script crashes without a stale mkdir/PID race. The
# lock inode is never removed. Descriptor 9 belongs only to the watchdog;
# patrol/rotation/sleep close it for their child commands (notably nohup).
watchdog_lock_exec() {
    exec python3 - "${LOCKDIR}.flock" "$1" <<'PYLOCK'
import fcntl, os, sys
path, script = sys.argv[1:]
try:
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("watchdog 已在运行 — 退出", file=sys.stderr)
        raise SystemExit(1)
    os.fchmod(fd, 0o600)
    os.ftruncate(fd, 0)
    os.write(fd, (str(os.getpid()) + "\n").encode())
    if fd != 9:
        os.dup2(fd, 9)
        os.close(fd)
    os.set_inheritable(9, True)
    os.execv("/bin/bash", ["/bin/bash", os.path.realpath(script), "__locked-run"])
except OSError as exc:
    print("watchdog: cannot acquire lock: " + str(exc), file=sys.stderr)
    raise SystemExit(1)
PYLOCK
}

watchdog_lock_valid() {
    # macOS /dev/fd exposes a synthetic st_dev, so shell `-ef` compares it
    # incorrectly even when fd 9 is the inherited, locked regular file.
    # fstat checks the real descriptor; flock also rejects a supplied unlocked
    # descriptor when a different watchdog owns this inode.
    python3 - "${LOCKDIR}.flock" <<'PYLOCKCHECK'
import fcntl, os, stat, sys
try:
    inherited = os.fstat(9)
    current = os.lstat(sys.argv[1])
    if (not stat.S_ISREG(inherited.st_mode) or not stat.S_ISREG(current.st_mode)
            or inherited.st_uid != os.geteuid()
            or (inherited.st_dev, inherited.st_ino) != (current.st_dev, current.st_ino)):
        raise ValueError("wrong lock descriptor")
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (OSError, ValueError):
    raise SystemExit(1)
PYLOCKCHECK
}

cmd_selftest_watch() {
    local fails=0 T
    BURN_WATCH_NOTIFY=0   # selftest 不触发真实通知 (osascript 可能阻塞在权限交互)
    T="$(mktemp -d "${TMPDIR:-/tmp}/watch-selftest.XXXXXX")"
    echo "== cli_alive 成功语义 (2026-11-04 auth 误报回归锁: return 0=真) =="
    local ZCJS="$T/fake-zcjs" GREP=/usr/bin/grep
    printf '#!/bin/bash\necho '\''{"response":"ok","sessionId":"sess_x"}'\''\n' > "$ZCJS"
    chmod +x "$ZCJS"
    local out; out="$(mktemp)"
    "$ZCJS" > "$out" 2>/dev/null
    if $GREP -q response "$out"; then echo "  ok: 成功输出可检测"; else echo "  FAIL: 成功输出未命中"; fails=$((fails+1)); fi
    rm -f "$out"
    echo "== alert 同因当日去重 =="
    local ALERT_BAK="$ALERT"
    ALERT="$T/alerts.txt"
    alert fp "测试告警A"
    alert fp "测试告警A"
    local n; n=$($GREP -c "测试告警A" "$ALERT" 2>/dev/null || true)
    [ "$n" = "1" ] && echo "  ok: 同因去重 (1 条)" || { echo "  FAIL: 重复告警 ($n 条)"; fails=$((fails+1)); }
    ALERT="$ALERT_BAK"
    echo "== rotate_log 裁剪 =="
    local big="$T/big.log"
    for i in $(seq 1 3000); do printf 'line %04d %2000s\n' "$i" "x" >> "$big"; done
    rotate_log "$big" 1000
    local rn; rn=$(wc -l < "$big" | xargs)
    [ "$rn" = "1000" ] && echo "  ok: 裁剪至 1000 行" || { echo "  FAIL: 裁剪后 $rn 行"; fails=$((fails+1)); }
    ls "${big%.txt}"-*.txt.gz >/dev/null 2>&1 && echo "  ok: 归档存在" || { echo "  FAIL: 无归档"; fails=$((fails+1)); }
    echo "== proj_alive 判活 (cwd 扫描 + 物理归一回归锁) =="
    local fdir="$T/fakerun"
    mkdir -p "$fdir"
    ( cd "$fdir" && exec -a "codexc-headless run selftest-fake" sleep 300 ) &
    local fakepid=$!
    sleep 1
    if proj_alive "$fdir"; then echo "  ok: 活 runner 被 cwd 扫描识别"; else echo "  FAIL: 活 runner 未识别"; fails=$((fails+1)); fi
    kill "$fakepid" 2>/dev/null
    if proj_alive "$T/emptydir"; then echo "  FAIL: 空目录误判为活"; fails=$((fails+1)); else echo "  ok: 空目录不误判"; fi
    rm -rf "$T"
    if [ "$fails" = "0" ]; then echo "WATCHDOG SELFTEST PASS"; return 0; fi
    echo "WATCHDOG SELFTEST FAILED ($fails)"; return 1
}

case "${1:-}" in
    selftest) cmd_selftest_watch; exit $? ;;
    run|"") watchdog_lock_exec "$0" ;;
    __locked-run)
        watchdog_lock_valid || { echo "watchdog: missing lock" >&2; exit 1; } ;;
    *) echo "usage: burn-watch.sh [run|selftest]" >&2; exit 1 ;;
esac

sleeper=""
trap 'exit 130' INT
trap 'exit 143' TERM
trap '[ -z "$sleeper" ] || kill "$sleeper" 2>/dev/null' EXIT
while :; do
    patrol_once 9>&- >> "$ALERT" 2>&1
    rotate_log "$ACCOUNT" 1000 9>&-
    rotate_log "$ALERT" 300 9>&-
    sleep 300 9>&- & sleeper=$!
    wait "$sleeper"
    sleeper=""
done
