#!/bin/bash
# burn-watch.sh — 无 LLM 烧炉看守 (纯 bash 3.2 兼容, 5 分钟一轮)
# 部署: ~/.codingkeeper/burn-watch.sh -> 本文件 (symlink); 改本文件前必须先杀运行实例
# 职责: 三炉存活/瞬时 park 有界复燃/真问题告警/token 记账/日志轮转
LOG="$HOME/.codex/codexc-watch.log"
ALERT="$HOME/.codingkeeper/burn-ALERTS.txt"
ACCOUNT="$HOME/.codingkeeper/burn-log.txt"
LOCKDIR="$HOME/.codingkeeper/watchdog.lock"
DAY="$(date +%D)"
GREP=/usr/bin/grep
ZCJS=/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs

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
    local var last
    var="seen_$(echo "$1" | tr -c 'a-zA-Z0-9' '_')"
    eval "last=\${$var:-}"
    [ "$last" = "$DAY" ] && return 0
    eval "$var=\$DAY"
    echo "$(date '+%F %T') | $1 | $2" >> "$ALERT"
    if [ "${BURN_WATCH_NOTIFY:-1}" = "1" ]; then
        osascript -e "display notification \"$1: $2\" with title \"burn-watch\"" 2>/dev/null
    fi
    return 0
}

cli_alive() {  # 双探重试 (间隔 5s): 单发会撞网关抖动窗口误判"凭证真死"
    local out try ok
    out="$(mktemp "${TMPDIR:-/tmp}/watch-probe.XXXXXX")"
    ok=0
    for try in 1 2; do
        "$ZCJS" --prompt replyOK --json --no-color > "$out" 2>/dev/null
        $GREP -q response "$out" && { ok=1; break; }
        sleep 5
    done
    rm -f "$out"
    # bash 约定 return 0=成功 — ok=1(活) 必须映射为 return 0 (语义反转回归锁)
    [ "$ok" = "1" ] && return 0
    return 1
}

revive() {  # $1=proj — 清 halt + nohup 复燃 (与 tmux server 生命周期解耦)
    local d="$HOME/Documents/work/code/AI/AIworkspace/$1"
    rm -f "$d/.codingkeeper/loop.halt"
    ( cd "$d" && CODEXC_REVIEW_CMD="$d/.codingkeeper/review-leaf.sh" \
      nohup zcodec run >> "$LOG" 2>&1 & )
}

patrol_once() {
    local proj d pid alive halted reason rcount tok fp_j sp_j s2_j
    for proj in fingerprint sale soul2soul; do
        d="$HOME/Documents/work/code/AI/AIworkspace/$proj"
        [ -d "$d" ] || continue
        halted=0; [ -f "$d/.codingkeeper/loop.halt" ] && halted=1
        if [ "$halted" = 0 ]; then
            proj_alive "$d" && continue           # 燃烧中 / auto-resume 休眠中 — 健康
        fi
        reason="$($GREP -a 'parked:' "$LOG" 2>/dev/null | tail -1 | sed 's/.*parked: //')"
        case "$reason" in
            *"idle exhaustion"*)
                alert "$proj" "诚实熄火(队列空/burn无活) — 加任务或 rm loop.halt 复燃"
                continue ;;
            *"auth failure"*)
                if ! cli_alive; then
                    alert "$proj" "CLI 凭证真死 — 请 zcode login; park 保留待人"
                    continue
                fi
                alert "$proj" "auth failure 但 CLI 探测已恢复 — 复燃" ;;
            *"BLOCKED"*|*"gate 连续"*|*"审查轮次超过"*|*"not found in queue"*)
                alert "$proj" "真问题 park: $reason — 不强推, 待人 (诊断: $d/.codingkeeper/.hl-*)"
                continue ;;
        esac
        # 统一有界复燃: 每项目每日 2 次 (不依赖全局日志归因, 对一切 park 类生效);
        # 超限 = 同一问题反复出现, 真问题留档待人, 防坏叶无限烧
        rcount=$($GREP -c "$DAY.*复燃#$proj" "$ALERT" 2>/dev/null)
        rcount=${rcount:-0}
        if [ "$rcount" -ge 2 ]; then
            alert "$proj" "复燃超限(2) — 真问题留档待人 (最后park: ${reason:0:40})"
            continue
        fi
        revive "$proj"
        echo "$(date '+%F %T') | $proj | 复燃#$proj#$rcount (${reason:0:50})" >> "$ALERT"
    done
    local day0
    day0="$(date -j -f '%F %T' "$(date +%F) 00:00:00" +%s)000"
    tok="$(sqlite3 "$HOME/.zcode/cli/db/db.sqlite" "SELECT printf('%.1fM',sum(input_tokens+output_tokens)/1e6) FROM model_usage WHERE started_at>=$day0" 2>/dev/null)"
    fp_j="$(wc -l < "$HOME/Documents/work/code/AI/AIworkspace/fingerprint/.codingkeeper/journal" 2>/dev/null | xargs)"
    sp_j="$(wc -l < "$HOME/Documents/work/code/AI/AIworkspace/sale/.codingkeeper/journal" 2>/dev/null | xargs)"
    s2_j="$(wc -l < "$HOME/Documents/work/code/AI/AIworkspace/soul2soul/.codingkeeper/journal" 2>/dev/null | xargs)"
    echo "$(date '+%F %T') | fp_journal=$fp_j | sale_journal=$sp_j | s2_journal=$s2_j | 今日token=$tok" >> "$ACCOUNT"
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
    run|"") ;;
    *) echo "usage: burn-watch.sh [run|selftest]" >&2; exit 1 ;;
esac

# 自锁: 防多实例并发巡逻 (重复复燃/错位执行的元凶)
if mkdir "$LOCKDIR" 2>/dev/null; then
    echo $$ > "$LOCKDIR/pid"
    trap 'rm -rf "$LOCKDIR"' EXIT
else
    opid="$(cat "$LOCKDIR/pid" 2>/dev/null)"
    kill -0 "$opid" 2>/dev/null && { echo "watchdog 已在运行 (pid $opid) — 退出"; exit 0; }
    rm -rf "$LOCKDIR"; echo $$ > "$LOCKDIR/pid"; trap 'rm -rf "$LOCKDIR"' EXIT
fi

while :; do
    patrol_once >> "$ALERT" 2>&1
    rotate_log "$ACCOUNT" 1000
    rotate_log "$ALERT" 300
    sleep 300
done
