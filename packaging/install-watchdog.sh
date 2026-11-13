#!/bin/bash
# Deploy self-contained runtime scripts, then verify launchd's loaded arguments.
# Documents access still requires the host's existing Full Disk Access grant.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
bin_dir="$HOME/.codingkeeper/bin"
agents="$HOME/Library/LaunchAgents"
domain="gui/$(id -u)"
mkdir -p "$bin_dir" "$agents"

atomic_copy() {
    local source="$1" target="$2" temporary
    temporary="$(mktemp "$target.new.XXXXXX")"
    cp -p "$source" "$temporary" || { rm -f "$temporary"; return 1; }
    mv -f "$temporary" "$target"
}

# Old Bash processes retain their inode. Shared helpers must travel with the
# daily runtime copy; a bin-only daily previously could not source ck-common.
atomic_copy "$repo/burn-watch.sh" "$bin_dir/burn-watch.sh"
atomic_copy "$repo/codexc-daily" "$bin_dir/codexc-daily"
atomic_copy "$repo/ck-watchdog-alive.sh" "$bin_dir/ck-watchdog-alive.sh"
for helper in "$repo"/ck-*.py "$repo"/ck-*.sh; do
    atomic_copy "$helper" "$bin_dir/${helper##*/}"
done
ln -sfn "$repo/burn-watch.sh" "$HOME/.codingkeeper/burn-watch.sh"

for label in com.codingkeeper.watchdog com.codexc.daily com.codingkeeper.watchdog-alive; do
    plist="$agents/$label.plist"
    python3 - "$here/$label.plist" "$plist" "$HOME" <<'PYPLIST'
import os, plistlib, sys, tempfile
source, target, home = sys.argv[1:]
with open(source, 'rb') as stream: value = plistlib.load(stream)
def relocate(item):
    if isinstance(item, str): return item.replace('/Users/wardonguo', home)
    if isinstance(item, list): return [relocate(v) for v in item]
    if isinstance(item, dict): return {k: relocate(v) for k, v in item.items()}
    return item
value = relocate(value)
fd, temporary = tempfile.mkstemp(prefix='.launchd-', dir=os.path.dirname(target))
try:
    with os.fdopen(fd, 'wb') as stream: plistlib.dump(value, stream)
    os.replace(temporary, target)
finally:
    if os.path.exists(temporary): os.unlink(temporary)
PYPLIST
    if launchctl print "$domain/$label" >/dev/null 2>&1; then
        if ! launchctl bootout "$domain/$label"; then
            sleep 1
            if launchctl print "$domain/$label" >/dev/null 2>&1; then
                launchctl bootout "$domain/$label" || {
                    echo "✗ $label bootout failed; old job is still loaded" >&2
                    exit 1
                }
            fi
        fi
    fi
    launchctl bootstrap "$domain" "$plist" || {
        echo "✗ $label bootstrap failed" >&2
        exit 1
    }
    loaded="$(mktemp "$bin_dir/.launchd-loaded.XXXXXX")"
    if ! launchctl print "$domain/$label" > "$loaded"; then
        rm -f "$loaded"
        echo "✗ $label missing after bootstrap" >&2
        exit 1
    fi
    if ! python3 - "$plist" "$loaded" "$label" <<'PYCHECK'
import plistlib, re, sys
with open(sys.argv[1], 'rb') as stream: expected = plistlib.load(stream)['ProgramArguments']
with open(sys.argv[2]) as stream: output = stream.read()
program = re.search(r'^\s*program = (.+)$', output, re.M)
arguments = re.search(r'arguments = \{\s*\n(.*?)\n\s*\}', output, re.S)
actual = [line.strip().strip('"') for line in arguments[1].splitlines() if line.strip()] if arguments else []
if not program or program[1].strip().strip('"') != expected[0] or actual != expected:
    sys.exit('✗ ' + sys.argv[3] + ': loaded program/arguments differ from runtime plist')
PYCHECK
    then
        rm -f "$loaded"
        exit 1
    fi
    rm -f "$loaded"
    echo "✓ $label loaded arguments verified"
done
echo "✓ 三个 launchd 作业路径已核验；心跳 $HOME/.codingkeeper/watchdog.heartbeat"
