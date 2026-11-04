#!/bin/bash
# burn-watch.sh — 无 LLM 烧炉看守 v2 (纯 bash 3.2 兼容, 5 分钟一轮, nohup 常驻)
# 职责: 双炉存活/瞬时 park 复燃/真问题告警/token 记账/日志轮转。真问题绝不强推。
LOG="$HOME/.codex/codexc-watch.log"
ALERT="$HOME/.codingkeeper/burn-ALERTS.txt"
ACCOUNT="$HOME/.codingkeeper/burn-log.txt"
DAY="$(date +%D)"
GREP=/usr/bin/grep
ZCJS=/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs

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

alert() {  # $1=proj $2=text — 同因当日去重 (bash 3.2 兼容, 动态变量)
    local var last
    var="seen_$(echo "$1" | tr -c 'a-zA-Z0-9' '_')"
    eval "last=\${$var:-}"
    [ "$last" = "$DAY" ] && return 0
    eval "$var=\$DAY"
    echo "$(date '+%F %T') | $1 | $2" >> "$ALERT"
    osascript -e "display notification \"$1: $2\" with title \"burn-watch\"" 2>/dev/null
    return 0
}

# zcode CLI 探测: 输出含 "response" = 凭证/网关活着
cli_alive() {
    local out try ok
    out="$(mktemp "${TMPDIR:-/tmp}/watch-probe.XXXXXX")"
    # 两次探测 (间隔 5s): 单发会撞网关抖动窗口误判"凭证真死"
    ok=0
    for try in 1 2; do
        "$ZCJS" --prompt replyOK --json --no-color > "$out" 2>/dev/null
        $GREP -q response "$out" && { ok=1; break; }
        sleep 5
    done
    rm -f "$out"
    # bash 约定 return 0=成功: ok=1(活) 必须映射为 return 0 — 此前语义反转,
    # 探测成功却被调用者判为"凭证真死" (所有 auth 误报的唯一根因)
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
    local proj d pid alive halted reason
    for proj in fingerprint sale; do
        d="$HOME/Documents/work/code/AI/AIworkspace/$proj"
        [ -d "$d" ] || continue
        pid="$(cat "$d/.codingkeeper/loop.pid" 2>/dev/null)"
        alive=0; [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && alive=1
        # pid 文件可能失真 (竞态写入/残留) — cwd 扫描兜底: 该目录有活 runner 即活着
        if [ "$alive" = 0 ]; then
            for rpid in $(pgrep -f 'codexc-headless run' 2>/dev/null); do
                rcwd="$(lsof -a -p "$rpid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
                [ "$rcwd" = "$d" ] && { alive=1; break; }
            done
        fi
        halted=0; [ -f "$d/.codingkeeper/loop.halt" ] && halted=1
        [ "$alive" = 1 ] && continue            # 燃烧中或 auto-resume 休眠中 — 健康
        reason="$($GREP -a 'parked:' "$LOG" 2>/dev/null | tail -1 | sed 's/.*parked: //')"
        case "$reason" in
            *"idle exhaustion"*)
                alert "$proj" "诚实熄火(队列空/burn无活) — 加任务或 rm loop.halt 复燃"
                continue ;;
            *"auth failure"*)
                if cli_alive; then
                    alert "$proj" "CLI 探测恢复 — 按瞬时复燃"
                else
                    # 不定性"真死": 每轮低频探测, 网关恢复即自动复燃 (对账可查 ALERTS)
                    echo "$(date '+%F %T') | $proj | auth park, CLI 探测仍失败 — 继续等待" >> "$ALERT"
                    continue
                fi ;;
            *"BLOCKED"*|*"gate 连续"*|*"审查轮次超过"*|*"无法解析"*|*"not found in queue"*)
                alert "$proj" "真问题 park: $reason — 不强推, 待人 (诊断: $d/.codingkeeper/.hl-*)"
                continue ;;
        esac
        revive "$proj"
        alert "$proj" "复燃 (${reason:-runner进程消失})"
    done
    local tok fp_j sp_j
    tok="$(sqlite3 "$HOME/.zcode/cli/db/db.sqlite" "SELECT printf('%.1fM',sum(input_tokens+output_tokens)/1e6) FROM model_usage WHERE started_at>=strftime('%s','now','start of day')*1000" 2>/dev/null)"
    fp_j="$(wc -l < "$HOME/Documents/work/code/AI/AIworkspace/fingerprint/.codingkeeper/journal" 2>/dev/null | xargs)"
    sp_j="$(wc -l < "$HOME/Documents/work/code/AI/AIworkspace/sale/.codingkeeper/journal" 2>/dev/null | xargs)"
    ghost=$(sqlite3 "$HOME/.zcode/cli/db/db.sqlite" "SELECT count(*) FROM session WHERE time_updated > (strftime('%s','now')-86400)*1000" 2>/dev/null)
    echo "$(date '+%F %T') | fp_journal=$fp_j | sale_journal=$sp_j | 今日token=$tok | 近24h活跃zcode会话=$ghost" >> "$ACCOUNT"
}


cmd_selftest_watch() {
    local fails=0 T
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
    local n; n=$($GREP -c "测试告警A" "$ALERT" 2>/dev/null || echo 0)
    [ "$n" = "1" ] && echo "  ok: 同因去重 (1 条)" || { echo "  FAIL: 重复告警 ($n 条)"; fails=$((fails+1)); }
    ALERT="$ALERT_BAK"
    echo "== rotate_log 裁剪 =="
    local big="$T/big.log"
    for i in $(seq 1 3000); do printf 'line %04d %2000s\n' "$i" "x" >> "$big"; done
    rotate_log "$big" 1000
    local rn; rn=$(wc -l < "$big" | xargs)
    [ "$rn" = "1000" ] && echo "  ok: 裁剪至 1000 行" || { echo "  FAIL: 裁剪后 $rn 行"; fails=$((fails+1)); }
    ls "${big%.txt}"-*.txt.gz >/dev/null 2>&1 && echo "  ok: 归档存在" || { echo "  FAIL: 无归档"; fails=$((fails+1)); }
    rm -rf "$T"
    if [ "$fails" = "0" ]; then echo "WATCHDOG SELFTEST PASS"; return 0; fi
    echo "WATCHDOG SELFTEST FAILED ($fails)"; return 1
}

case "${1:-}" in
    selftest) cmd_selftest_watch; exit $? ;;
    run|"") ;;
    *) echo "usage: burn-watch.sh [run|selftest]" >&2; exit 1 ;;
esac

while :; do
    patrol_once >> "$ALERT" 2>&1
    rotate_log "$ACCOUNT" 1000
    rotate_log "$ALERT" 300
    sleep 300
done
