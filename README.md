# codexc

Keep [Codex CLI](https://developers.openai.com/codex/) running when you can't.

`codexc` wraps `codex` in a per-project tmux session and adds three things plain Codex doesn't have:

1. **Auto-continue watchdog** — when a turn dies from a transient failure (429 rate limits, dropped streams, 5xx, network hiccups), codexc types `continue` for you and the task picks up where it stopped. Quota errors are recognized and deliberately *not* auto-continued.
2. **Scheduled & daily runs** — queue a prompt at a specific time (`codexc -t 10:00`), or register a daily job (`codexc-daily install 10:00`) that resumes your most recent session every morning — even after a restart — but politely skips if you're at the computer.
3. **Auto-yes** — Codex runs with official full-auto flags and the working directory is pre-trusted, so no approval popups or "do you trust this directory?" gates stall an unattended run.

> macOS-only (uses launchd, osascript, BSD tools). Chinese docs: [README.zh-CN.md](README.zh-CN.md)

## Requirements

- macOS
- [tmux](https://github.com/tmux/tmux) ≥ 3.5 (for CSI-u extended keys), `sqlite3`, `python3`
- [Codex CLI](https://developers.openai.com/codex/) (`npm i -g @openai/codex`) — logged in

## Quick start

```bash
git clone https://github.com/g8cc/codexc.git
cd codexc
./install.sh            # symlinks scripts into ~/.codex/bin
exec $SHELL             # reload PATH if ~/.codex/bin is not on it yet

cd ~/projects/myapp
codexc                  # codex opens in a tmux session named after this dir
```

Detach (`Ctrl-a` `d`) to leave it running; `codexc` again to reattach. All commands work from plain SSH sessions too.

## Usage

| Command | Effect |
|---|---|
| `ck <tool> [args]` | unified entry: `ck codex` / `ck claude` / `ck pi` / `ck opencode` / `ck zcode` / `ck dsh` |
| `ck status` | cross-project overview |
| `ck fuel [tool]` | fuel gauge |
| `codexc` | backward compat alias for `ck codex` |
| `codexc` | create-or-attach this directory's session — interactive by default, nothing auto-fed |
| `codexc loop` | arm the unattended delivery loop (auto-scaffolds `.codingkeeper/` on first run; `--no-loop` forces it off) |
| `codex <args>` | `codexc codex -m o3 --search` → fresh session in this dir with those codex args |
| `codexc resume --last` | continue the most recent codex session |
| `codexc resume <session-id>` | continue a specific session |
| `codexc -t 10:00 "prompt"` | queue a prompt at 10:00 (`+30m` also works) |
| `codexc loop` | same as `codexc` (kept for explicitness) |
| `codexc fuel [codex\|claude]` | boiler fuel gauge: current provider, cc-switch failover queue, today/month spend, recent relay errors |
| `codexc -T claude` | drive **Claude Code** (loop, gate, reviews all work the same) |
| `codexc -T opencode` | drive **opencode** (same pipeline; sessions read from opencode.db) |
| `ck zcode run` | drive **ZCode's CLI** on the headless lane: one blocking turn per task via `zcode --prompt --mode yolo`, session continuity persisted to `.codingkeeper/zcode-session-id`. Queue/gate auto-scaffold on first run; needs Node >= 24 and the app's `zcode.cjs` (auto-detected) |
| `zcodec` | product-name entry mirroring `codexc`: bare = wake the ZCode app (interactive, never auto-runs), `zcodec run` = the night runner, other verbs (`init`/`status`/`selftest`) or zcode CLI args pass through. **`dshc`** mirrors it for dsh (bare prints usage) |
| `ck status` | **all-projects overview**: burning/parked/queue/last-acceptance for every registered project |
| `ck fuel [tool]` | shorthand for `codexc fuel` |
| `codexc -T pi` | drive **pi** (same pipeline; auto-continue keys off `stopReason: "error"`) |
| `codexc-daily install 10:00` | daily auto-resume at 10:00 (launchd) |
| `codexc-daily` | run one daily cycle right now |
| `codexc-daily pause` / `resume` | disable / re-enable the daily job |
| `codexc-daily status` / `uninstall` | inspect / remove the daily job |

### Per-project sessions

One tmux session per working directory, named after the directory (`codexc` basename, parent names prepended on collision, `-2`/`-3` suffixes after that). Detaching keeps codex alive in the background; closing the pane's command kills the session naturally.

## Auto-continue watchdog

A watcher polls Codex's `logs_*.sqlite` store for transient turn failures (case-insensitive), enforces the configured minimum interval between sends (10 seconds by default), waits briefly for the TUI to settle, then sends `continue` + Enter. Built-in patterns cover 429 rate limits, "server error", "stream error", overloaded, connection reset, fetch failed, timeouts, and similar. After **30 auto-continues by default** it stops and notifies; set `CODEXC_MAX_CONTINUES` to change the limit (`0` disables retries).

Two safety valves:

- **Never auto-continue quota walls.** "usage limit", "upgrade to", "subscription", "plan limit" are blocklisted and checked *before* anything else.
- **Your own patterns.** One regex per line in `~/.codex/codexc.patterns`, or `CODEXC_EXTRA_RE` for a one-off.

## Scheduled & daily runs

`codexc -t 10:00 "continue"` sends a prompt at 10:00 into the live session (or cold-starts one in that directory). It's one-shot; recurring schedules are codexc-daily's job.

`codexc-daily` is a **safety net, not an interrupter**. At fire time it:

- finds the newest codex session's working directory (`session_meta.cwd` of the newest rollout file);
- if that directory's tmux session is alive — waits for an idle TUI (up to 60s for a running turn), then sends `continue`;
- if it's gone — cold-starts `codexc resume --last continue` in the original directory, watchdog armed;
- **skips entirely if the last turn completed cleanly** (`task_complete` in the rollout) — a finished task never gets a pointless "continue";
- **skips and notifies if you've used the computer in the last 30 minutes** (`CODEXC_DAILY_IDLE`, minutes; `0` disables), and never runs while paused.

## Unattended delivery loop (`codexc-loop`)

`codexc loop` arms a session with a supervised delivery pipeline: tasks are fed one at a time from a queue file, and a task is only accepted after real tests pass and two consecutive independent reviews report zero bugs.

```bash
codexc loop          # start the loop — auto-scaffolds .codingkeeper/ on first run
                     # (test commands detected from uv/pytest/package.json/go/
                     # Cargo/Flutter/Makefile; review the generated gate.sh)
codexc-loop init     # explicit scaffold (same thing, for scripted setups)
```

- `.codingkeeper/queue.md` — tasks under `## ready` are fed top-first; codex writes self-generated follow-ups to `## review-needed`, which never run until you promote them; `## done` gets checked off.
- `.codingkeeper/gate.sh` — your project's real test command. The loop runs it in the shell and only trusts its exit code; failures are fed back to codex (bounded by `CODEXC_GATE_RETRIES`).
- Each finished task is reviewed by a separate read-only `codex exec --ephemeral` reviewer context. `CODEXC_REVIEW_PASS` (default 2) consecutive zero-bug reviews accept the task; any found bug goes back to codex for fixing. Exhausted retries park the loop (touch `.codingkeeper/loop.halt` pauses; `rm` it resumes) and send a notification.
- `CODEXC_LOOP_DRY=1 codexc loop` — log every action without touching the TUI.
- **Desktop panel**: the runners publish `status.json` on every state change; the menubar app (`desktop/CodingKeeperBar.swift`, built by install) shows all projects' tasks/park state in one place. **Burn mode (default ON)**: when the queue runs dry, the loop feeds a standing improve-and-harden prompt — proceed with the worker's own stated next step, else a professional closure review (correctness, security, performance, reliability, robustness/edge-cases, maintainability, test coverage, dependency health, observability, docs consistency), fixing findings in small commits. When the worker reports genuinely nothing to do twice in a row, the boiler parks itself and notifies you. `CODEXC_LOOP_IDLE=0` disables; any other value replaces the prompt; `CODEXC_IDLE_PARK` tunes the no-op limit.
- Tool notes: `codexc-daily` cold-starts codex sessions only. Claude's watcher keys off session JSONL (`isApiErrorMessage`, post-retry-exhaustion); pi's off `stopReason: "error"`; opencode's off errored assistant rows in `opencode.db`. Reviews always run on codex so the grader is a different model than the worker. Tools without a terminal TUI run on the **headless lane** instead: `codexc-headless` runs one blocking subprocess per task with the same queue/gate/review/burn semantics. `ck zcode run` is the bridge to ZCode's CLI this way; `dsh --profile headless` works the same once its credentials are configured (`CODEXC_HEADLESS_CMD="dsh --profile headless --session-id night -" codexc-headless run`).

## Auto-yes

| `CODEXC_AUTO_YES` | Behavior |
|---|---|
| `1` (default) | Full auto: official `--dangerously-bypass-approvals-and-sandbox`, plus pre-trusting the directory in codex's config so the first-run trust prompt never appears |
| `2` | Skip approval prompts but keep the workspace sandbox (`-a never -s workspace-write`) |
| `0` | Off — native codex approval behavior |

Flags you pass explicitly (`-a`, `-s`, `--full-auto`, …) are never overridden. The bypass is codex's own supported flag, not keyboard simulation. **Read the trade-off:** mode `1` lets codex run commands on your machine without approval — that's the point for unattended runs, and it assumes you trust your tasks and have backups.

## tmux keys (with the bundled config)

| Keys | Effect |
|---|---|
| `Ctrl-a` `d` | detach — codex keeps running |
| `Ctrl-b` `d` | same (second prefix key, fully synced) |
| `Ctrl-a` `Ctrl-a` | send a real `Ctrl-a` to the program (line start in a shell) |
| `Ctrl-b` `Ctrl-b` | send a real `Ctrl-b` |

The config also makes tmux distinguish `Shift+Enter` from `Enter` (newline vs send in codex's composer) and lets the mouse wheel scroll pane history.

## Configuration reference

| Env | Meaning | Default |
|---|---|---|
| `CODEXC_SESSION` | override the tmux session name | per-directory name |
| `CODEXC_HOME` | codex home | `~/.codex` |
| `CODEXC_MESSAGE` | text codexc-daily sends at fire time | `continue` |
| `CODEXC_AT` | schedule spec, same as `-t` | — |
| `CODEXC_EXTRA_RE` | extra auto-continue regex (OR-ed with built-ins) | — |
| `CODEXC_AUTO_YES` | `1` full auto / `2` sandboxed / `0` off | `1` |
| `CODEXC_DAILY_IDLE` | daily-job idle threshold in minutes, `0` disables (range `0`–`10080`) | `30` |

## How it works

- `codexc` starts tmux (or attaches), injects codex flags + a self-healing retry config, and spawns a background watcher that polls Codex's SQLite error log; it inspects the pane to avoid typing during an active turn.
- `codexc-daily` finds sessions by parsing the JSONL rollout files under `$CODEX_HOME/sessions/`; scheduling is delegated to launchd (`com.codexc.daily`).
- The bundled `tmux.conf` links `sync-prefix2.sh`, which mirrors the `prefix` key table into tmux's otherwise-empty `prefix2` table so both prefixes behave identically.

- [处理逻辑手册](docs/OPERATIONS.md) · [架构与不变量](docs/ARCHITECTURE.md) · [工具矩阵与凭证](docs/TOOLS.md) · [商业化路线](docs/COMMERCIALIZATION.md) · [Changelog](CHANGELOG.md)

## Uninstall

```bash
codexc-daily uninstall          # remove the launchd job (if installed)
rm ~/.codex/bin/codexc ~/.codex/bin/claudec ~/.codex/bin/opencodec ~/.codex/bin/pic ~/.codex/bin/codexc-headless ~/.codex/bin/codexc-zcode-worker ~/.codex/bin/codexc-dsh-worker ~/.codex/bin/zcodec ~/.codex/bin/dshc ~/.codex/bin/codexc-daily ~/.codex/bin/codexc-loop ~/.codex/bin/sync-prefix2.sh
rm -f ~/Library/LaunchAgents/com.codexc.daily.plist
```

`install.sh` never overwrites without backing up (`*.bak.<timestamp>` next to the replaced file).

## License

[MIT](LICENSE)
