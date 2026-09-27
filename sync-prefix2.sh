#!/bin/bash
# sync-prefix2.sh — make the second prefix key Ctrl+b share the exact command
# set of the primary prefix Ctrl+a.
#
# tmux's prefix2 key table is empty by default: with just `set -g prefix2 C-b`
# nothing after C-b would ever run (detach, new window, etc. all dead). This
# script copies every binding from the prefix table (Ctrl+a) into the prefix2
# table (Ctrl+b), and fixes C-b C-b to send a real Ctrl+b to the program.
#
# Invoked by run-shell in ~/.tmux.conf at config load; after changing
# prefix-table bindings re-run `tmux source-file ~/.tmux.conf` to sync.
set -u
set -o pipefail

# 1. copy all prefix-table bindings into the prefix2 table
tmpfile="$(mktemp "${TMPDIR:-/tmp}/codexc-prefix2.XXXXXX")" || exit 1
trap 'rm -f "$tmpfile"' EXIT
if ! tmux list-keys -T prefix 2>/dev/null | sed 's/-T prefix /-T prefix2 /' > "$tmpfile"; then
    exit 1
fi
tmux source-file "$tmpfile" 2>/dev/null || exit 1

# 2. fix: C-b C-b sends a real Ctrl+b (plain send-prefix would send Ctrl+a)
tmux bind-key -T prefix2 C-b send-prefix -2 2>/dev/null

# 3. also make sure prefix C-a double-press sends a real Ctrl+a
tmux bind-key -T prefix C-a send-prefix 2>/dev/null
