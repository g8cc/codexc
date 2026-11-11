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
# 运行位副本 (bin/) 不随仓库携带 ck-window.py 等辅助脚本: 回退到 symlink
# 指向的仓库真源目录, 否则 watch_window_open 对一切炉子 return 125, 巡逻全盲
if [ ! -f "$WATCH_DIR/ck-window.py" ]; then
    bw_repo_dir="$(dirname "$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$HOME/.codingkeeper/burn-watch.sh" 2>/dev/null)" 2>/dev/null)"
    [ -n "$bw_repo_dir" ] && [ -f "$bw_repo_dir/ck-window.py" ] && WATCH_DIR="$bw_repo_dir"
fi

# 炉队发现: 注册表 ~/.codingkeeper/projects 登记且 scaffold 三件套齐全的项目才是炉子。
# 加炉 = ck-init-furnace (登记+三件套); 下架 = 注册表删行。$HOME/.codingkeeper 不受
# Documents TCC 限制, launchd 实例同样可读。缺件的已登记项目告警留档, 不盲烧。
FLEET_EXCLUDE="test"
CODEXC_FLEET_MAX="${CODEXC_FLEET_MAX:-6}"       # 并发目标: 看门狗把活炉补足到该数 (低于即复燃); 0=不限
CODEXC_DISK_MIN_GB="${CODEXC_DISK_MIN_GB:-10}"  # HOME 所在卷可用 GiB 低于此值时每日告警
# 非数字手滑兜底回默认 (否则每巡逻刷 integer expression 错误且磁盘监控静默失效)
case "${CODEXC_FLEET_MAX}" in ''|*[!0-9]*) CODEXC_FLEET_MAX=6 ;; esac
case "${CODEXC_DISK_MIN_GB}" in ''|*[!0-9]*) CODEXC_DISK_MIN_GB=10 ;; esac
fleet_furnaces() {
    local p
    [ -f "$HOME/.codingkeeper/projects" ] || return 0
    # || [ -n "$p" ]: 末行缺换行符的注册表不得丢最后一炉; CRLF/首尾空白是
    # 编辑器与外部工具的现实损坏 — 两者都表现为静默丢炉 (全盲事故类)
    while IFS= read -r p || [ -n "$p" ]; do
        p="${p%$'\r'}"
        p="${p#"${p%%[![:space:]]*}"}"; p="${p%"${p##*[![:space:]]}"}"
        p="${p%/}"
        [ -d "$p" ] || continue
        case "$p" in *[[:space:]]*) continue ;; esac
        case " $FLEET_EXCLUDE " in *" ${p##*/} "*) continue ;; esac
        [ -f "$p/.codingkeeper/queue.md" ] || continue
        if [ ! -f "$p/.codingkeeper/gate.sh" ] || [ ! -f "$p/.codingkeeper/review-leaf.sh" ]; then
            alert "${p##*/}" "scaffold 缺件 (gate.sh/review-leaf.sh) — 已登记不烧, 补齐或除名" 2>/dev/null || true
            continue
        fi
        echo "$p"
    done < "$HOME/.codingkeeper/projects"
}

fleet_trace_registry() {  # 注册表死条目/空白路径/缺 queue.md 的留档 — 必须住在主壳:
    # fleet_furnaces 每次巡逻在 4 个 <() 子壳里各跑一遍, 进程内去重随子壳消亡,
    # 会变成每 5 分钟 4 条的日志噪音; 这里一巡逻一次, alert 按条目按日去重
    local p
    [ -f "$HOME/.codingkeeper/projects" ] || return 0
    while IFS= read -r p || [ -n "$p" ]; do
        p="${p%$'\r'}"
        p="${p#"${p%%[![:space:]]*}"}"; p="${p%"${p##*[![:space:]]}"}"
        p="${p%/}"
        [ -z "$p" ] && continue                     # 空行是注册表合法语法
        case "$p" in \#*) continue ;; esac          # 注释掉条目 = 可用的暂停手段
        case " $FLEET_EXCLUDE " in *" ${p##*/} "*) continue ;; esac  # 主动除名 = 静默
        case "$p" in
            # 去重键含全路径: 共用常量键会让同日第二条空白条目永无留档
            *[[:space:]]*) alert "registry: $p" "注册表条目含空白 — 巡逻跳过 (空格路径暂不支持)" 2>/dev/null || true; continue ;;
        esac
        [ -d "$p" ] || { alert "${p##*/}" "注册表条目目录不存在 — 巡逻跳过 (除名或补目录): $p" 2>/dev/null || true; continue; }
        [ -f "$p/.codingkeeper/queue.md" ] || { alert "${p##*/}" "注册表条目缺 queue.md — 未初始化? 巡逻跳过: $p" 2>/dev/null || true; continue; }
    done < "$HOME/.codingkeeper/projects"
}

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

PROJ_ALIVE_CWDS=""   # 一次巡逻只扫一次 runner cwd (pgrep+lsof 是 O(炉数×活runner) 的重复成本)
proj_alive_scan() {  # 惰性: 首个 pid 文件未命中的炉子触发; patrol_once 入口重置 — 每周期新鲜
    local rpid rcwd
    PROJ_ALIVE_CWDS=" "
    # pgrep -f 会对含非法字节的进程 cmdline 整体报错弃扫 ("illegal byte
    # sequence", 舰队 runner 的中文任务参数即可触发) — 用 LC_ALL=C ps+awk
    # 字节透明枚举; [c] 类括号自排除, 避免匹配到枚举进程自身
    for rpid in $(LC_ALL=C ps ax -o pid=,command= 2>/dev/null | LC_ALL=C awk '/[c]odexc-headless run/ { print $1 }'); do
        rcwd="$(lsof -a -p "$rpid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
        rcwd="$(cd "$rcwd" 2>/dev/null && pwd -P)" || continue
        PROJ_ALIVE_CWDS="$PROJ_ALIVE_CWDS$rcwd "
    done
}
proj_alive() {  # $1=project dir — pid 文件 (每炉新鲜) 或 cwd 扫描 (每巡逻一次缓存), 0=活
    local d="$1" pid dreal
    pid="$(cat "$d/.codingkeeper/loop.pid" 2>/dev/null)"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && return 0
    dreal="$(cd "$d" 2>/dev/null && pwd -P)" || dreal="$d"
    [ -z "$PROJ_ALIVE_CWDS" ] && proj_alive_scan
    case "$PROJ_ALIVE_CWDS" in *" $dreal "*) return 0 ;; esac
    return 1
}

fleet_alive_count() {  # 注册炉子中活着的 runner 数 (proj_alive 走每巡逻缓存)
    local n=0 d
    while IFS= read -r d <&3; do
        proj_alive "$d" && n=$((n + 1))
    done 3< <(fleet_furnaces)
    echo "$n"
}

fleet_cap_blocks() {  # 并发闸门: 活炉数 + 本巡逻已复燃数 ≥ 上限 → block。
    # 必须加 FLEET_REVIVED 增量 — 活炉计数是巡逻开始时的缓存, 同一巡逻内
    # 连续复燃不更新, 闸门会被缓存打穿 (2026-11-11 实证一次巡逻 12 炉齐开)。
    # 只数注册炉子 (proj_alive 逐炉比对 cwd) — 与真实舰队进程天然隔离, 可测。
    [ "${CODEXC_FLEET_MAX:-5}" -gt 0 ] || return 1
    local alive rev
    alive="$(fleet_alive_count)"
    rev="${FLEET_REVIVED:-0}"
    [ "$((alive + rev))" -lt "${CODEXC_FLEET_MAX:-5}" ] && return 1
    return 0
}

disk_watch() {  # HOME 所在卷可用 GiB 低于阈值 → 每日告警一次 (key=disk)
    local free_gb
    free_gb="$(df -k "$HOME" 2>/dev/null | awk 'NR == 2 { print int($4 / 1048576) }')"
    [ -n "$free_gb" ] || return 0
    if [ "$free_gb" -lt "${CODEXC_DISK_MIN_GB:-10}" ]; then
        alert "disk" "磁盘仅剩 ${free_gb} GiB (阈值 ${CODEXC_DISK_MIN_GB:-10}) — 清理 /tmp/ck-*、.codex/sessions 或 evidence; 磁盘满曾致看门狗写入失败死亡 (2026-11-10)"
    fi
    return 0
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

revive() {  # $1=proj — 有界、保留 halt 的 nohup 复燃 (注册表驱动: 传 fleet_furnaces 的完整路径)
    local d="$1"
    watch_window_open || return 125
    # A halt belongs to this project/operator; never clear it from global logs.
    [ ! -e "$d/.codingkeeper/loop.halt" ] || return 1
    [ -d "$d" ] || return 1
    ( cd "$d" || exit 1
      # The resumed runner enforces the same policy for the full child lifetime.
      # 9-12 全关: patrol 期间 bash 把锁 fd 暂存在 10 (+1/2 的存槽), 长命 runner
      # 继承它 = 永久持锁, 看门狗死后永远重启不了 (2026-11-10 舰队扩编时实证)。
      CODEXC_ACTIVE_WINDOW="$CODEXC_ACTIVE_WINDOW" CODEXC_ACTIVE_TZ="$CODEXC_ACTIVE_TZ" \
      CODEXC_REVIEW_CMD="$d/.codingkeeper/review-leaf.sh" nohup zcodec run >> "$LOG" 2>&1 9>&- 10>&- 11>&- 12>&- & )
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
    while IFS= read -r fdir <&3; do
        for f in "$fdir/.codingkeeper/zcode-session-id" \
                 "$fdir/.codingkeeper/zcode-session-id.retry"; do
            [ -f "$f" ] || continue
            sid="$(head -c 64 "$f" 2>/dev/null | tr -cd 'A-Za-z0-9_-')"
            case "$sid" in sess_*) excludes="$excludes '$sid'," ;; esac
        done
    done 3< <(fleet_furnaces)
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
    local proj d pid alive halted reason rcount tok acc_line
    PROJ_ALIVE_CWDS=""   # 缓存按巡逻周期重置: 上周期的扫描对本周期的生死判定是陈旧数据
    FLEET_REVIVED=0       # 本巡逻已成功复燃数 — 并发闸门的增量项 (随巡逻重置)
    fleet_trace_registry   # 注册表死条目/空白/缺件留档 — 主壳一次, alert 按条目按日去重
    disk_watch             # 磁盘水位监控 — 低水位每日告警 (2026-11-10 死亡事故的诱因)
    DAY="$(date +%F)"   # long-running watchdogs must roll over at midnight
    date +%s > "$HOME/.codingkeeper/watchdog.heartbeat" 2>/dev/null || true
    # 运行位自愈: launchd 从 ~/.codingkeeper/bin/ 的副本启动 (TCC: launchd 进程读不了
    # ~/Documents), 副本漂移则从仓库真源原子刷新; 新代码由主循环的翻日 exec 加载。
    if [ "$0" = "$HOME/.codingkeeper/bin/burn-watch.sh" ]; then
        bw_repo="$(readlink "$HOME/.codingkeeper/burn-watch.sh" 2>/dev/null)"
        if [ -n "$bw_repo" ] && ! cmp -s "$0" "$bw_repo" 2>/dev/null \
                && cp "$bw_repo" "$0.new.$$" 2>/dev/null; then
            mv "$0.new.$$" "$0" && echo "$(date '+%F %T') watchdog: 运行副本已刷新自仓库真源"
        fi
    fi
    # 注册表按字面路径逐行生效: for $( ) 的词分割+glob 展开会把字面名含元字符
    # 目录的同 pattern 兄弟卷进巡逻, 绕过三件套/排除表审查 (read -r + fd3 防
    # 循环体命令吃掉炉队行)
    while IFS= read -r d <&3; do
        proj="${d##*/}"
        [ -d "$d" ] || continue
        halted=0; [ -f "$d/.codingkeeper/loop.halt" ] && halted=1
        if [ "$halted" = 1 ]; then
            halt_reason="$(head -c 200 "$d/.codingkeeper/loop.halt" 2>/dev/null)"
            case "$halt_reason" in
                *"model quota exhausted"*)
                    # 模型日额度 park: 额度按日重置 — 跨日后有界自动复燃 (1/日),
                    # 否则每晚额度刷新时整队睡死 (2026-11-11 实证 4 炉配额 park
                    # 过夜)。套餐未激活/人工类 park 仍走 *) 人工分支。
                    # awk -v 与 前缀赋值 都会对值做转义 (\b→退格) — 键必须走 ENVIRON 字面传递
                    qcount="$(day="$DAY" key="配额复燃#$proj#" awk 'index($0, ENVIRON["day"] " ") == 1 && index($0, ENVIRON["key"]) { n++ } END { print n+0 }' "$ALERT" 2>/dev/null)"
                    qcount=${qcount:-0}
                    if [ "$qcount" -ge 1 ]; then
                        alert "$proj" "配额复燃超限(1/日) — 留档待人 (最后park: ${halt_reason:0:40})"
                        continue
                    fi
                    if fleet_cap_blocks; then
                        alert "fleet" "并发已满 ${CODEXC_FLEET_MAX} — ${proj} 配额 park 保留, 空位后自动复燃"
                        continue
                    fi
                    rm -f "$d/.codingkeeper/loop.halt"
                    if revive "$d"; then
                        FLEET_REVIVED=$((FLEET_REVIVED + 1))
                        echo "$(date '+%F %T') | $proj | 配额复燃#$proj#$qcount (额度重置自愈)" >> "$ALERT"
                    else
                        alert "$proj" "复燃失败(rc=$?) — runner 未拉起 (留档按日去重)"
                    fi
                    continue ;;
                *"review rounds exhausted"*|*"review output unparseable"*)
                    # 审核类 park 有界自动复燃: 夜间不再整夜停摆。
                    # 预算与退出类复燃共用 2/日; 超限 = 同一叶子反复被拒, 留档待人。
                    rcount="$(day="$DAY" key="复燃#$proj#" awk 'index($0, ENVIRON["day"] " ") == 1 && index($0, ENVIRON["key"]) { n++ } END { print n+0 }' "$ALERT" 2>/dev/null)"
                    rcount=${rcount:-0}
                    if [ "$rcount" -ge 2 ]; then
                        alert "$proj" "复燃超限(2) — 审核 park 留档待人 (最后park: ${halt_reason:0:40})"
                        continue
                    fi
                    if fleet_cap_blocks; then
                        alert "fleet" "并发已满 ${CODEXC_FLEET_MAX} — ${proj} 审核 park 保留, 空位后自动复燃"
                        continue
                    fi
                    rm -f "$d/.codingkeeper/loop.halt"
                    if revive "$d"; then
                        FLEET_REVIVED=$((FLEET_REVIVED + 1))
                        echo "$(date '+%F %T') | $proj | 复燃#$proj#$rcount (审核park自愈: ${halt_reason:0:40})" >> "$ALERT"
                    else
                        alert "$proj" "复燃失败(rc=$?) — runner 未拉起, 每 5 分钟继续重试; 检查 zcodec/时段/TCC (留档按日去重)"
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
        rcount="$(day="$DAY" key="复燃#$proj#" awk 'index($0, ENVIRON["day"] " ") == 1 && index($0, ENVIRON["key"]) { n++ } END { print n+0 }' "$ALERT" 2>/dev/null)"
        rcount=${rcount:-0}
        if [ "$rcount" -ge 2 ]; then
            alert "$proj" "复燃超限(2) — 真问题留档待人 (最后park: ${reason:0:40})"
            continue
        fi
        if fleet_cap_blocks; then
            alert "fleet" "并发已满 ${CODEXC_FLEET_MAX} — ${proj} 等待空位后自动复燃"
            continue
        fi
        if revive "$d"; then
            FLEET_REVIVED=$((FLEET_REVIVED + 1))
            echo "$(date '+%F %T') | $proj | 复燃#$proj#$rcount (${reason:0:50})" >> "$ALERT"
        else
            alert "$proj" "复燃失败(rc=$?) — runner 未拉起, 每 5 分钟继续重试; 检查 zcodec/时段/TCC (留档按日去重)"
        fi
    done 3< <(fleet_furnaces)
    cleanup_probe_sessions
    local day0
    day0="$(date -j -f '%F %T' "$(date +%F) 00:00:00" +%s)000"
    tok="$(sqlite3 -readonly "$HOME/.zcode/cli/db/db.sqlite" "SELECT printf('%.1fM',sum(input_tokens+output_tokens)/1e6) FROM model_usage WHERE started_at>=$day0" 2>/dev/null)"
    # 质量退化遥测: 审核轮数/gate 重试抬头 → alert (文本固定, alert 按日去重)
    while IFS= read -r qdir <&3; do
        qproj="${qdir##*/}"
        qjournal="$qdir/.codingkeeper/journal"
        [ -f "$qjournal" ] || continue
        qtrend="$(python3 "$WATCH_DIR/ck-quality-trend.py" "$qjournal" "$qdir/.codingkeeper/parks.log" 2>/dev/null)"
        qtrc=$?
        # rc=1 是 alert 判定 (要照常告警), rc>=2 才是解析失败
        [ "$qtrc" -ge 2 ] && continue
        [ -n "$qtrend" ] || continue
        # 例行遥测写 watch 日志 (有界) 而非 stdout — patrol 的 stdout/stderr 全量
        # 进 300 行轮转的 ALERT, 每炉每轮一条会把真实告警几小时内挤穿
        echo "$(date '+%F %T') quality-trend $qproj: $qtrend" >> "$LOG"
        case "$qtrend" in
            *'"verdict": "alert"'*)
                alert "$qproj" "质量趋势预警 — 审核轮数/gate 重试抬头, 详情看 codexc-watch.log 的 quality-trend 行" ;;
        esac
    done 3< <(fleet_furnaces)
    local acc_line
    acc_line="$(date '+%F %T')"
    while IFS= read -r d <&3; do
        # 缺 journal 的炉子: < 重定向失败由 shell 报错, 2>/dev/null 压不住 —
        # 先验文件再重定向, 不让例行报错漏进 ALERT
        jcount=""
        [ -f "$d/.codingkeeper/journal" ] && jcount="$(wc -l < "$d/.codingkeeper/journal" | xargs)"
        acc_line="$acc_line | ${d##*/}_journal=$jcount"
    done 3< <(fleet_furnaces)
    echo "$acc_line | 今日token=$tok" >> "$ACCOUNT"
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
    # 零点翻日 = re-exec 换血: 仓库代码更新最迟一天内自动生效。
    # 必须在主循环 (fd 9 开启) 做, 不能放 patrol_once — 那里以 9>&- 运行, exec 出的
    # 新实例 fstat(9) 报 EBADF, "missing lock" 自杀 (2026-11-10 零点事故)。
    if [ -n "${WATCHDOG_DAY:-}" ] && [ "$(date +%F)" != "$WATCHDOG_DAY" ]; then
        exec /bin/bash "$0" __locked-run
    fi
    WATCHDOG_DAY="$(date +%F)"
    patrol_once 9>&- >> "$ALERT" 2>&1
    rotate_log "$ACCOUNT" 1000 9>&-
    rotate_log "$ALERT" 300 9>&-
    sleep 300 9>&- 10>&- 11>&- 12>&- & sleeper=$!
    wait "$sleeper"
    sleeper=""
done
