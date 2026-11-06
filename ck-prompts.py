#!/usr/bin/env python3
"""Engineering prompt fuel and atomic queue additions. No model calls."""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

spec = importlib.util.spec_from_file_location('leaf', Path(__file__).resolve().with_name('ck-leaf.py'))
leaf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leaf)

# Each recipe has a concrete search scope and asks for demonstrated fixes.
BUILTINS = {
    'correctness': ('正确性', '沿用户最常用的一条业务链追踪输入到结果，核对状态转换、数据计算及错误分支。选一个能复现的错误，先写失败回归，再定位根因和修复同类路径。'),
    'reliability': ('可靠性', '检查进程退出、服务断连、超时、重试与重启恢复。用本地故障注入复现一个状态丢失、重复执行或无限重试问题，修复后证明恢复有界且不丢数据。'),
    'security': ('安全', '追踪一个真实外部输入到文件、命令、数据库或权限边界，检查注入、路径越界和敏感数据泄露。只针对可复现问题修复；禁止读取真实密钥、攻击外部服务或变更生产权限。'),
    'edge-cases': ('边界条件', '检查空值、极大值、Unicode、特殊字符路径、损坏输入和并发调用。选一条现有功能，用最小回归证明其边界错误，修复根因并扫描相邻分支。'),
    'test-coverage': ('行为测试', '找到一条尚无可信回归保护的关键用户行为。添加会在真实错误下失败的测试，禁止仅检查源码字符串或重复实现逻辑；已有断言不应为了变绿而削弱。'),
    'performance': ('性能', '测量一条重复执行或慢路径，保留输入、基线耗时和结果正确性。仅在数据证明瓶颈后做小范围优化，并以相同输入验证结果与耗时；无测量不宣称加速。'),
    'observability': ('可观测性', '检查一个实际失败能否从状态、退出码和日志定位。复现不可见或误报的故障，补足必要诊断及回归；避免记录凭证、无限日志或制造额外通知。'),
    'dependencies': ('依赖健康', '核对依赖声明、锁文件、平台/版本要求和实际启动路径。优先修复可复现的兼容或依赖缺失问题；升级需最小范围和完整验证，不批量追新版本。'),
    'maintainability': ('可维护性', '检查跨入口重复实现且已经出现行为漂移的一类逻辑。先证明漂移，集中维护公共语义，保留入口差异并验证兼容。不要只为代码美观重构。'),
    'documentation': ('文档一致性', '逐条核对一个用户工作流的说明、默认值、命令和实际行为，运行离线示例复现不一致，修正文档或实现并给出验证证据，不编造运行结果。'),
}
CONTRACT = ('限定在当前项目已授权范围内，每轮只交付一个可验证的小改进。先读项目约定、已有改动和测试；'
            '保留既有用户改动。发现 bug 必须先复现再修复并补回归，执行适当的实际测试。'
            '不要为继续运行虚构工作，不擅自部署、推送或扩大业务范围。若有代码改动请做小步提交。'
            '最终消息说明证据，最后一行 TASK_RESULT: DONE；当前范围确实没有改进时用 TASK_RESULT: DONE (idle)，'
            '缺少必要外部条件时用 TASK_RESULT: BLOCKED: 原因。')
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
LIMIT = 60 * 1024


def bounded(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError('prompt must be a regular file')
        data = f.read(LIMIT + 1)
    if len(data) > LIMIT or b'\0' in data:
        raise ValueError('prompt exceeds 60 KiB or contains NUL')
    text = data.decode('utf-8').strip()
    if not text:
        raise ValueError('prompt is empty')
    return text


def catalog():
    result = {key: (title, body, 'built-in') for key, (title, body) in BUILTINS.items()}
    directory = leaf.STATE / 'prompts'
    if directory.is_symlink():
        raise ValueError('project prompt directory must not be a symlink')
    if directory.exists():
        for path in sorted(directory.glob('*.md')):
            if not NAME.fullmatch(path.stem):
                raise ValueError('invalid prompt id: ' + path.stem)
            result[path.stem] = (path.stem, bounded(path), 'project')
            if len(result) > 64:
                raise ValueError('catalog exceeds 64 prompts')
    return result


def render(ident, prompts):
    if ident not in prompts:
        raise ValueError('unknown prompt: ' + ident)
    title, body, _ = prompts[ident]
    return '[CodingKeeper 燃料: ' + ident + ' / ' + title + ']\n' + body + '\n' + CONTRACT


def next_prompt():
    prompts = catalog()
    keys = list(prompts)
    cursor = leaf.STATE / 'burn-cursor.json'
    result = {}

    def advance():
        if cursor.exists():
            value = json.loads(bounded(cursor))
            position = value.get('next') if isinstance(value, dict) else None
            if type(position) is not int or not 0 <= position <= 2**63:
                raise ValueError('invalid burn cursor; inspect burn-cursor.json')
        else:
            position = 0
        ident = keys[position % len(keys)]
        result.update(id=ident, count=len(keys), prompt=render(ident, prompts))
        leaf.atomic(cursor, leaf.encode({'next': (position + 1) % len(keys)}))

    leaf.locked(advance)
    return result


def fuel_state(exhaust=False):
    signature = leaf.digest(leaf.encode(catalog()))
    marker = leaf.STATE / 'burn-exhausted.json'
    result = 'ready'

    def check():
        nonlocal result
        if exhaust:
            leaf.atomic(marker, leaf.encode({'catalog': signature}))
            result = 'waiting'
        elif marker.exists():
            value = json.loads(bounded(marker))
            if not isinstance(value, dict) or not isinstance(value.get('catalog'), str):
                raise ValueError('invalid burn exhaustion state')
            if value['catalog'] == signature:
                result = 'waiting'
            else:
                marker.unlink()
                leaf.sync_dir(leaf.STATE)
                result = 'renewed'

    leaf.locked(check)
    return result


def enqueue(text):
    text = text.strip()
    if not text or '\0' in text or len(text.encode()) > LIMIT:
        raise ValueError('task must be nonempty UTF-8 without NUL, up to 60 KiB')
    queue = leaf.STATE / 'queue.md'

    def append():
        if not queue.exists() and (Path('.codexc') / 'queue.md').exists():
            raise ValueError('legacy .codexc queue exists; migrate it before adding tasks')
        if (leaf.STATE / 'acceptance.pending.json').exists():
            raise ValueError('recover acceptance.pending.json before adding tasks')
        before = leaf.read_queue(queue) if queue.exists() else b'## ready\n\n## review-needed\n\n## done\n'
        if any(task == text for _, task in leaf.queue_entries(before)):
            raise ValueError('identical task is already ready')
        lines = before.decode('utf-8').splitlines(keepends=True)
        # Locate only real headings outside fences, using the same fence rules.
        fence = None
        start = end = None
        task_lines = {i for i, _, _, _ in leaf.queue_items(before)}
        consumed = -1
        for i, line in enumerate(lines):
            if i <= consumed:
                continue
            if i in task_lines:
                indent = len(line) - len(line.lstrip())
                for j in range(i + 1, len(lines)):
                    following = lines[j]
                    if not following.strip():
                        continue
                    if len(following) - len(following.lstrip()) <= indent:
                        break
                    consumed = j
                continue
            token = re.match(r'^(`{3,}|~{3,})', line.strip())
            if token:
                marker = token[1]
                if fence is None:
                    fence = marker
                elif marker[0] == fence[0] and len(marker) >= len(fence) and not line.strip()[len(marker):].strip():
                    fence = None
                continue
            if fence:
                continue
            heading = re.match(r'^##\s+(.+?)\s*#*\s*$', line)
            if heading:
                if start is not None:
                    end = i
                    break
                if heading[1].strip().lower() == 'ready':
                    start = i
        if start is None:
            raise ValueError('queue has no ready section')
        end = len(lines) if end is None else end
        parts = text.splitlines()
        inserted = '- [ ] ' + parts[0] + '\n' + ''.join('  ' + line + '\n' for line in parts[1:])
        prefix = ''.join(lines[:end])
        if not prefix.endswith('\n'):
            prefix += '\n'
        after = (prefix + inserted + ''.join(lines[end:])).encode()
        if not any(task == text for _, task in leaf.queue_entries(after)):
            raise ValueError('new task did not roundtrip through the queue parser; queue unchanged')
        leaf.atomic(queue, after, stat.S_IMODE(queue.stat().st_mode) if queue.exists() else 0o600)

    leaf.locked(append)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    show = sub.add_parser('show'); show.add_argument('id')
    next_cmd = sub.add_parser('next'); next_cmd.add_argument('--format', choices=('json', 'tsv'), default='json')
    sub.add_parser('available')
    sub.add_parser('exhaust')
    add = sub.add_parser('add'); add.add_argument('id'); add.add_argument('--file', required=True)
    queue = sub.add_parser('enqueue')
    sources = queue.add_mutually_exclusive_group(required=True)
    sources.add_argument('text', nargs='?'); sources.add_argument('--file'); sources.add_argument('--prompt')
    args = parser.parse_args()
    try:
        if args.command == 'list':
            for ident, (title, _, source) in catalog().items():
                print(ident + '\t' + title + '\t' + source)
        elif args.command == 'show':
            print(render(args.id, catalog()))
        elif args.command == 'next':
            result = next_prompt()
            if args.format == 'tsv':
                print(result['id'] + '\t' + str(result['count']) + '\t' + base64.b64encode(result['prompt'].encode()).decode())
            else:
                print(json.dumps(result, ensure_ascii=True))
        elif args.command in ('available', 'exhaust'):
            print(fuel_state(exhaust=args.command == 'exhaust'))
        elif args.command == 'add':
            if not NAME.fullmatch(args.id):
                raise ValueError('prompt id must contain lowercase letters, digits and hyphens')
            text = bounded(args.file)
            current = catalog()  # Validate existing files before extending them.
            if args.id not in current and len(current) >= 64:
                raise ValueError('catalog exceeds 64 prompts')
            directory = leaf.STATE / 'prompts'
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / (args.id + '.md')
            # Publish complete files, atomically and without replacing another writer.
            fd, temporary = tempfile.mkstemp(prefix='.prompt-', dir=directory)
            try:
                with os.fdopen(fd, 'w') as out:
                    out.write(text + '\n'); out.flush(); os.fsync(out.fileno())
                os.link(temporary, path)
                leaf.sync_dir(directory)
            finally:
                os.unlink(temporary)
            print('added prompt: ' + args.id)
        else:
            text = bounded(args.file) if args.file else render(args.prompt, catalog()) if args.prompt else args.text
            enqueue(text)
            print('queued in .codingkeeper/queue.md')
    except (OSError, ValueError, UnicodeError) as error:
        parser.exit(2, 'prompt fuel: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
