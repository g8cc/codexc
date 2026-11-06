#!/bin/bash
# Tool-specific watchdogs. Sourced by codexc; never launches a worker or a runner.
# Snapshot protocol: state<TAB>event identity<TAB>base64(final/error text).
ck_tool_snapshot() {
    python3 - "$1" "$2" "${OPENCODE_DIR:-}" <<'PY'
import base64, hashlib, json, os, sqlite3, sys
from pathlib import Path
tool, source, oc = sys.argv[1:]
state, token, text = "none", "0", ""
try:
    if tool == "opencode":
        with sqlite3.connect(Path(oc + "/opencode.db").resolve().as_uri() + "?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT type,seq,data FROM session_message WHERE session_id=? ORDER BY seq DESC LIMIT 1", (source,)).fetchone()
        if row:
            kind, seq, raw = row
            token = hashlib.sha256((str(seq) + raw).encode()).hexdigest()
            item = json.loads(raw)
            if kind == "assistant" and isinstance(item, dict):
                if item.get("error") or item.get("finish") == "error":
                    state, text = "error", json.dumps(item.get("error") or item, ensure_ascii=False)
                    error_data = item.get("error")
                    if isinstance(error_data, dict):
                        detail = error_data.get("data", error_data)
                        if isinstance(detail, dict):
                            code = str(detail.get("statusCode") or detail.get("status") or "")
                            if code == "429":
                                text = "Too Many Requests: " + text
                            elif code in ("500", "502", "503", "504"):
                                text = "server error: " + text
                elif item.get("finish") == "stop":
                    state = "clean"
                    content = item.get("content")
                    if isinstance(content, list):
                        text = "".join(b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    elif source and os.path.isfile(source):
        with open(source, "rb") as fh:
            end = fh.seek(0, os.SEEK_END)
            position, chunks, lines = end, [], 0
            while position > 0 and lines < 400 and end - position < 4 * 1024 * 1024:
                size = min(position, 65536)
                position -= size
                fh.seek(position)
                chunk = fh.read(size)
                chunks.append(chunk)
                lines += chunk.count(b"\n")
        raw = b"".join(reversed(chunks))
        if position:
            boundary = raw.find(b"\n") + 1
            position += boundary
            raw = raw[boundary:]
        events = []
        for line in raw.splitlines(keepends=True):
            position += len(line)
            try:
                item = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(item, dict):
                events.append((item, position))
        for item, offset in reversed(events):
            if tool == "claude":
                if item.get("isSidechain"):
                    continue
                kind = item.get("type")
                if kind not in ("user", "assistant"):
                    continue
                token = str(offset)
                if kind == "user":
                    break
                message = item.get("message")
                message = message if isinstance(message, dict) else {}
                content = message.get("content")
                content = content if isinstance(content, list) else []
                text = "".join(b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
                if item.get("isApiErrorMessage"):
                    state = "error"
                    if item.get("apiErrorStatus") == 429:
                        text = "Too Many Requests: " + text
                elif message.get("stop_reason") in ("end_turn", "stop_sequence") and not any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content):
                    state = "clean"
                break
            else:
                if item.get("type") != "message":
                    continue
                message = item.get("message")
                if not isinstance(message, dict) or message.get("role") not in ("user", "assistant"):
                    continue
                token = str(offset)
                if message.get("role") == "user":
                    break
                content = message.get("content")
                content = content if isinstance(content, list) else []
                text = "".join(b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
                if message.get("stopReason") == "error":
                    state = "error"
                    text += " " + str(message.get("errorMessage") or message.get("error") or "")
                elif message.get("stopReason") == "stop":
                    state = "clean"
                break
except (OSError, sqlite3.Error, ValueError, TypeError):
    state, token, text = "none", "0", ""
print(state + "\t" + token + "\t" + base64.b64encode(text[:16384].encode("utf-8", "replace")).decode())
PY
}

watch_and_run_tool() (  # subshell keeps the loop library's globals private
    local tool="$1" follow_pid="$2" pane="$3" root_notify="${CODEXC_NOTIFY:-1}"
    local snapshot state token payload error last_path last_token rollout count=0 last_send=0 now
    local retry_re="$TRANSIENT_RE" extra="" active=0 started=0 heartbeat=0
    local notify_secs="${CODEXC_NOTIFY_SECS:-120}"
    case "$follow_pid" in ''|*[!0-9]*) return 1 ;; esac
    [ "$follow_pid" -gt 1 ] || return 1
    CODEXC_TOOL="$tool"
    CODEXC_LOOP_LIB_ONLY=1 . "$SCRIPT_DIR/codexc-loop" || return 1
    CODEXC_LOOP_NOTIFY="$root_notify"
    CK_LANE=codexc; CK_TAG="watcher-$tool"
    if declare -F load_extra_patterns >/dev/null; then extra="$(load_extra_patterns)"; fi
    [ -z "$extra" ] || retry_re="$retry_re|$extra"
    last_path="$(find_rollout "$pane")"
    snapshot="$(ck_tool_snapshot "$tool" "$last_path")"
    last_token="${snapshot#*$TAB}"; last_token="${last_token%%$TAB*}"
    log "watcher armed on pane $pane (historical events skipped)"
    while kill -0 "$follow_pid" 2>/dev/null && pane_alive "$pane"; do
        sleep "$CODEXC_POLL"
        kill -0 "$follow_pid" 2>/dev/null && pane_alive "$pane" || break
        rollout="$(find_rollout "$pane")"
        [ -n "$rollout" ] || continue
        now=$(date +%s)
        if pane_busy "$pane"; then
            if [ "$active" = "0" ]; then active=1; started="$now"; heartbeat=0; fi
            if [ $((now - heartbeat)) -ge 30 ] && declare -F write_status >/dev/null; then
                write_status "执行中" 1 "$started"
                heartbeat="$now"
            fi
            continue
        fi
        snapshot="$(ck_tool_snapshot "$tool" "$rollout")"
        state="${snapshot%%$TAB*}"
        payload="${snapshot#*$TAB}"; token="${payload%%$TAB*}"; payload="${payload#*$TAB}"
        if [ "$rollout" != "$last_path" ] && [ -n "$last_path" ]; then
            last_path="$rollout"; last_token="$token"
            continue  # a resumed session's historical error is not new work
        fi
        last_path="$rollout"
        [ "$token" != "$last_token" ] || continue
        [ "$state" != "none" ] || { last_token="$token"; continue; }
        pane_busy "$pane" && continue
        error="$(python3 -c 'import base64,sys; print(base64.b64decode(sys.argv[1]).decode("utf-8","replace"))' "$payload")"
        if [ "$state" = "clean" ]; then
            last_token="$token"
            if declare -F write_status >/dev/null; then write_status "$error" 0 "$started"; fi
            if [ "$root_notify" = "1" ] && [ "$started" -gt 0 ] && [ $((now - started)) -ge "$notify_secs" ]; then
                notify "任务回合已完成 ($tool)"
            fi
            active=0; started=0
            continue
        fi
        if printf '%s\n' "$error" | grep -Eiq -- "$BLOCK_RE"; then
            last_token="$token"
            log "quota/subscription limit; auto-continue suppressed"
            continue
        fi
        if ! printf '%s\n' "$error" | grep -Eiq -- "$retry_re"; then
            last_token="$token"
            continue
        fi
        if [ "$count" -ge "$CODEXC_MAX_CONTINUES" ]; then
            log "auto-continue limit reached ($count/$CODEXC_MAX_CONTINUES)"
            [ "$root_notify" != "1" ] || notify "自动续命已达上限 ($tool)"
            break
        fi
        now=$(date +%s)
        [ $((now - last_send)) -ge "$CODEXC_COOLDOWN" ] || continue
        # Recheck ownership/liveness immediately before both keyboard writes.
        kill -0 "$follow_pid" 2>/dev/null && pane_alive "$pane" || break
        pane_busy "$pane" && continue
        tmux send-keys -t "$pane" -l -- "$CODEXC_MESSAGE" || break
        sleep 0.4
        kill -0 "$follow_pid" 2>/dev/null && pane_alive "$pane" || break
        tmux send-keys -t "$pane" Enter || break
        last_token="$token"; last_send="$now"; count=$((count + 1))
        log "auto-continue sent ($count/$CODEXC_MAX_CONTINUES)"
    done
)

watch_and_run_claude() { watch_and_run_tool claude "$@"; }
watch_and_run_pi() { watch_and_run_tool pi "$@"; }
watch_and_run_opencode() { watch_and_run_tool opencode "$@"; }
