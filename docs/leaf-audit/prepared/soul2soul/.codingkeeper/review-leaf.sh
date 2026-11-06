#!/bin/bash
# Shared leaf reviewer: exact candidate evidence, bounded parser, no paid probes.
set -eu
cd "$(dirname "$0")/.."
exec python3 "/Users/wardonguo/Documents/work/code/AI/AIworkspace/codexc/codexc-review-leaf" "$@"
