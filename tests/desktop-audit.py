#!/usr/bin/env python3
"""Compile and exercise desktop input handling without launching the GUI."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

repo = Path(__file__).resolve().parent.parent
source = (repo / 'desktop/CodingKeeperBar.swift').read_text().split('\nlet app = NSApplication.shared\n')[0]
source += r'''
let delegate = AppDelegate()
func check(_ value: Bool, _ text: String) {
    if !value { fputs("FAIL: " + text + "\n", stderr); exit(1) }
}
switch CommandLine.arguments[1] {
case "duration":
    check(delegate.duration(1e100) == "—", "future timestamps must not overflow Int")
    check(delegate.duration(.infinity) == "—", "infinity must not overflow Int")
    check(delegate.duration(.nan) == "—", "NaN is invalid")
case "waiting_window", "waiting_quota", "backoff", "waiting_fuel":
    let status = delegate.readStatus(CommandLine.arguments[2])
    check(!status.running, "waiting phases must never count as running, even with a fresh active heartbeat")
    let message = delegate.waitingDescription(status)
    let expected = ["waiting_window": "等待", "waiting_quota": "配额耗尽", "backoff": "重试等待", "waiting_fuel": "等待新任务"][CommandLine.arguments[1]]!
    check(message.hasPrefix(expected), "waiting state must show its Chinese reason")
    if CommandLine.arguments[1] != "waiting_fuel" {
        check(message.contains(":"), "a valid next_run_at must show its local clock time")
    }
    check(delegate.waitingSummary([status]) == message, "the small banner must directly explain waiting")
    var running = AppDelegate.ProjStatus()
    running.running = true
    check(delegate.waitingSummary([status, running]).isEmpty, "mixed running tools must not claim global waiting")
case "waiting_manual_halt", "waiting_stale":
    let status = delegate.readStatus(CommandLine.arguments[2])
    check(!status.waiting && !status.running, "a manual halt or stale heartbeat must override old waiting state")
    check(delegate.waitingDescription(status).isEmpty, "a dead or halted runner cannot promise an automatic next run")
    check(delegate.waitingSummary([status]).isEmpty, "small banner must not promise a halted or stale runner will resume")
case "waiting_invalid":
    let status = delegate.readStatus(CommandLine.arguments[2])
    check(!status.running && status.nextRunAt == 0, "invalid next_run_at must not revive a waiting task")
    check(delegate.waitingDescription(status) == "等待运行时段", "invalid next time must have a useful fallback")
case "working", "halted":
    let status = delegate.readStatus(CommandLine.arguments[2])
    check(status.running == (CommandLine.arguments[1] == "working"), "running still requires no project halt")
case "lock-hold":
    let lock = KeeperInstanceLock()
    guard try lock.acquire(CommandLine.arguments[2]) else { exit(42) }
    withExtendedLifetime(lock) {
        try! "ready".write(toFile: CommandLine.arguments[3], atomically: true, encoding: .utf8)
        Thread.sleep(forTimeInterval: 60)
    }
case "lock-check":
    let lock = KeeperInstanceLock()
    do {
        guard try lock.acquire(CommandLine.arguments[2]) else { exit(42) }
    } catch { exit(43) }
case "future":
    let status = delegate.readStatus(CommandLine.arguments[2])
    check(!status.running, "a far-future heartbeat cannot keep a dead task alive")
case "large":
    let status = delegate.readStatus(CommandLine.arguments[2])
    check(status.task.isEmpty, "oversize status files must be rejected before parsing")
case "fifo":
    let status = delegate.readStatus(CommandLine.arguments[2])
    check(status.task.isEmpty, "nonregular status files must not block the panel")
case "hit":
    let view = KeeperContentView(frame: NSRect(x: 0, y: 0, width: 200, height: 200))
    view.contentRect = view.bounds
    let child = NSView(frame: NSRect(x: 0, y: 80, width: 100, height: 100))
    view.addSubview(child)
    view.setExpandedAppearance(true)
    check(view.hitTest(NSPoint(x: 20, y: 100)) === child, "expanded panel must deliver scroll/click to children")
    check(view.acceptsFirstMouse(for: nil), "inactive compact banner must accept the first click")
    view.wantsLayer = true
    view.setExpandedAppearance(false)
    check(view.hitTest(NSPoint(x: 20, y: 100)) === view, "compact labels must route the first click to the banner")
    check(view.hitTest(NSPoint(x: 190, y: 20)) === view, "compact blank pixels must remain clickable")
    check(view.hitTest(NSPoint(x: 210, y: 20)) == nil, "outside the banner must pass through")
    let alpha = view.layer!.backgroundColor!.alpha
    check(alpha > 0 && alpha <= 0.01, "compact surface needs near-transparent pixels for WindowServer mouse delivery")
    check(view.backdrop.isHidden, "compact surface must not blur menu icons")
    view.setExpandedAppearance(true)
    check(!view.backdrop.isHidden, "expanded details keep their readable backdrop")
    check(view.hitTest(NSPoint(x: 20, y: 100)) === child, "expanding must restore child input")
    view.setExpandedAppearance(false)
    check(view.backdrop.isHidden, "collapsing must remove the blur again")
default: exit(2)
}
print("PASS " + CommandLine.arguments[1])
'''
with tempfile.TemporaryDirectory(prefix='ck-desktop-test-') as temp:
    # 工具链自检: swiftc 本身损坏 (SDK/编译器错配) 时整条 desktop 检查零信号,
    # 诚实跳过而不是把环境问题当代码红灯 (与 tests/swift-gate.sh 同一规则)
    probe = subprocess.run([str(repo / 'tests/swift-gate.sh'), '--probe-only'], text=True,
                           capture_output=True, timeout=300,
                           env={**os.environ, 'SWIFT_GATE_PROBE_TIMEOUT': '120'})
    if probe.returncode == 2:
        print((probe.stdout or 'SKIP: Swift 工具链损坏 — desktop 检查本次未覆盖').strip())
        raise SystemExit(0)
    if probe.returncode != 0:
        print('FAIL 工具链探针异常退出', probe.returncode, (probe.stdout + probe.stderr)[:250])
        raise SystemExit(1)
    root = Path(temp)
    swift = root / 'main.swift'
    swift.write_text(source)
    binary = root / 'desktop-audit'
    subprocess.run(['swiftc', '-module-cache-path', os.environ.get('SWIFT_MODULECACHE_PATH', str(root / 'modules')), str(swift), '-o', str(binary)], check=True)
    failures = 0
    for mode in ('duration', 'future', 'large', 'fifo', 'hit', 'waiting_window', 'waiting_quota', 'backoff', 'waiting_fuel', 'waiting_invalid', 'working', 'halted', 'waiting_manual_halt', 'waiting_stale'):
        project = root / mode
        kd = project / '.codingkeeper'
        kd.mkdir(parents=True)
        status = kd / 'status.json'
        if mode in ('waiting_window', 'waiting_quota', 'backoff', 'waiting_fuel'):
            status.write_text(json.dumps({'phase': mode, 'active': True, 'ts': time.time(), 'next_run_at': time.time()+3600}))
        elif mode in ('waiting_manual_halt', 'waiting_stale'):
            age = 180 if mode == 'waiting_stale' else 0
            status.write_text(json.dumps({'phase': 'waiting_window', 'active': True, 'ts': time.time()-age, 'next_run_at': time.time()+3600}))
            if mode == 'waiting_manual_halt':
                (kd / 'loop.halt').touch()
        elif mode == 'waiting_invalid':
            status.write_text(json.dumps({'phase': 'waiting_window', 'active': True, 'ts': time.time(), 'next_run_at': 1e100}))
        elif mode in ('working', 'halted'):
            status.write_text(json.dumps({'phase': 'working', 'active': True, 'ts': time.time()}))
            if mode == 'halted':
                (kd / 'loop.halt').touch()
        elif mode == 'future':
            status.write_text(json.dumps({'active': True, 'ts': 1e100, 'started_at': 1e100}))
        elif mode == 'large':
            status.write_text(json.dumps({'task': 'x' * (1024 * 1024), 'active': True}))
        elif mode == 'fifo':
            os.mkfifo(status)
        try:
            result = subprocess.run([str(binary), mode, str(project)], text=True, capture_output=True, timeout=5)
            if result.returncode:
                print('FAIL', mode, result.stderr[:250])
                failures += 1
            else:
                print(result.stdout.strip())
        except subprocess.TimeoutExpired:
            print('FAIL', mode, 'blocked on status input')
            failures += 1
    # Two real test processes contend for one temporary lock; no NSApplication
    # is created. A forced holder exit must release the lock without stale PIDs.
    lock_path = root / 'desktop.lock'
    ready = root / 'lock-ready'
    holder = subprocess.Popen([str(binary), 'lock-hold', str(lock_path), str(ready)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not ready.exists() and holder.poll() is None:
            time.sleep(.05)
        if not ready.exists():
            raise AssertionError('lock holder did not start')
        other = subprocess.run([str(binary), 'lock-check', str(lock_path)], capture_output=True, timeout=5)
        if other.returncode != 42:
            raise AssertionError('second panel instance acquired the same lock')
        holder.kill()
        holder.wait(timeout=5)
        recovered = subprocess.run([str(binary), 'lock-check', str(lock_path)], capture_output=True, timeout=5)
        if recovered.returncode != 0:
            raise AssertionError('lock was not released after holder death')
        victim = root / 'victim'
        victim.write_text('keep')
        link = root / 'lock-link'
        link.symlink_to(victim)
        refused = subprocess.run([str(binary), 'lock-check', str(link)], capture_output=True, timeout=5)
        if refused.returncode != 43 or victim.read_text() != 'keep':
            raise AssertionError('lock followed or modified a symbolic link')
        print('PASS single-instance contention, crash recovery and symlink rejection')
    except (AssertionError, subprocess.TimeoutExpired) as exc:
        print('FAIL single-instance', exc)
        failures += 1
    finally:
        if holder.poll() is None:
            holder.kill()
        holder.communicate(timeout=5)
    raise SystemExit(bool(failures))
