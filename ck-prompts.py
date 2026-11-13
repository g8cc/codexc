#!/usr/bin/env python3
"""General/domain improvement fuel and atomic project configuration. No model calls."""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
import time

spec = importlib.util.spec_from_file_location('leaf', Path(__file__).resolve().with_name('ck-leaf.py'))
leaf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leaf)

pack_spec = importlib.util.spec_from_file_location('fuel_packs', Path(__file__).resolve().with_name('ck-fuel-packs.py'))
packs = importlib.util.module_from_spec(pack_spec)
pack_spec.loader.exec_module(packs)

CUSTOM_LIMIT = 128
CATALOG_LIMIT = 512

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
    'product-flow': ('核心产品流程', '从项目现有功能中选一条端到端用户目标，记录入口、操作步骤、结果与中断点。补齐一个能本地验证的流程缺口，减少完成目标的步骤，不凭想象新增整套产品。'),
    'onboarding': ('首次使用', '以第一次接触项目的用户身份走安装、配置、首个成功结果。用实际命令或界面复现一个阻碍，改进默认值、示例、引导或配置检查，以首次成功结果验收。'),
    'usability': ('操作效率', '检查一个高频流程的重复输入、隐含状态、命名与反馈。先记录当前步骤和结果，再实现一种符合现有交互的快捷操作、合理默认或状态提示；验收任务完成与可恢复性。'),
    'accessibility': ('无障碍', '项目存在界面时，实际检查核心流的键盘操作、焦点、可访问名称、对比度或读屏语义。修复一个明确的操作障碍，动态控件也要验证；无界面则记录不适用。'),
    'responsive': ('多设备体验', '在产品支持的屏幕、缩放、输入方式下走关键流程，复现内容溢出、不可点击或布局遮挡。只修可观察问题，保留桌面与窄屏验证；没有界面则不适用。'),
    'empty-states': ('空状态与进度', '检查首次无数据、筛选无结果、载入中、权限不足等实际状态，用户应知道原因和下一步。补足一个可达状态的有效操作和反馈，避免伪造示例数据或隐藏失败。'),
    'error-recovery': ('用户自助恢复', '故意触发一个本地可模拟错误，检查用户能否保存输入、重试、撤销或恢复。把报错变成可执行的恢复路径，验证不丢数据、不重复副作用且诊断准确。'),
    'search-discovery': ('查找与发现', '检查现有列表、历史、文档或设置中查找目标的实际成本。针对一个明确难找的对象改进检索、筛选、排序或导航，验证结果正确及无结果路径；不为不存在的数据造搜索。'),
    'data-portability': ('数据自主权', '围绕产品已有用户数据检查导出、导入、备份与恢复的缺口。在现有格式和权限边界内补齐一种可验证的迁移或恢复能力，证明往返不丢字段；不得删除真实数据。'),
    'integrations': ('集成体验', '按项目已声明的集成运行本地样例或模拟端点，检查配置、身份、错误处理和契约。修一个真实接入障碍，不申请新账号、不添加未经选择的外部供应商。'),
    'api-experience': ('开发者体验', '项目交付 API、SDK 或 CLI 时，从使用者视角运行一段最小集成，检查参数、错误信息、版本兼容和示例。交付一个能被真实调用验证的易用性改进，无该能力则不适用。'),
    'trust-privacy': ('信任与隐私', '核对产品实际采集、保存、展示和删除的数据与用户说明是否一致。修复一个隐私告知、数据最小化或权限体验缺口，不编造合规认证、不修改生产权限。'),
    'localization': ('语言与地区', '只针对项目明确支持的语言、时区、日期、数字或文本方向检查关键流。修复一个真实地区差异导致的错误或理解障碍，不批量添加无需求的新语种。'),
    'user-feedback': ('用户反馈闭环', '使用仓库中已有反馈、问题单、支持记录或可复现使用过程，找一个反复困扰用户的点并修复。缺少反馈时只做本地可验证的反馈入口或信息完整性改进，不捏造访谈。'),
    'activation': ('价值到达', '追踪用户从进入产品到获得第一项有用结果的实际过程，发现可观察的中断或不必要步骤。改进一处，让用户更快得到已有核心价值；记录前后流程，不编造激活率。'),
    'retention': ('重复使用价值', '核对现有高频工作是否需要反复设置、找回历史或重建上下文。实现一个有事实依据的状态保存、最近使用或可恢复工作能力，验证隐私与迁移，不新增骚扰通知。'),
    'conversion': ('商业转化', '核对现有介绍页、试用入口、价值展示与功能事实，找一个用户无法理解收益或行动的可观察断点。改进表达、演示或现有转化步骤；不编造客户、评价、收入与转化率，不改变线上价格。'),
    'packaging-value': ('交付与价值表达', '把一个已经可用却难以理解的能力做成可离线运行的样例、演示、模板或清晰套餐对照。所有承诺须由当前产品验证，避免虚假功能和未经决策的商业定位改写。'),
    'pricing-evidence': ('收费决策依据', '根据现有能力、配置成本和实际资源用量整理一种收费或成本假设及验证办法。需要选择价格、套餐或商业方向时用 ck propose 留决策工单，继续其他工作；不凭空给收入预测。'),
    'operating-cost': ('单位成本', '量化一个当前真实的模型调用、存储、带宽、构建或运行成本路径。保留负载与计费依据后做小范围节约，验证质量不降低；没有价格来源只报告资源量。'),
    'release-readiness': ('交付就绪', '用现有安装、构建、迁移、升级和回退流程生成一个本地交付产物，修复实际发布障碍或缺失说明。记录版本、命令与结果，不擅自发布、部署或推送。'),
    'product-discovery': ('产品机会', '结合 README、已实现能力、现有问题单和用户工作流找一个明确尚未满足的小需求。先查重复与成本，在已授权功能边界内实现可验收增量；需要产品取舍则提决策工单，不把空白当需求。'),
}
BUILTINS.update({
    'domain-fit': ('领域适用性', '阅读项目定位、现有代码、API、测试与队列，用 ck prompts packs 查看领域包。只对已交付能力和具体源码证据匹配领域，可用 ck prompts enable <包ID> 持久化启用；记录能力到包的依据与不适用项。不能按项目名字猜领域或为了烧更多启用全部包。存在业务取舍时用稳定 DECISION- ID 留决策，继续独立工作。'),
    'data-integrity': ('数据完整性', '核对一类已有持久化数据的唯一性、关联、版本、迁移与删除约定。用固定数据复现违反业务不变量的场景，修复并验证读写、恢复和派生数据同步；不改真实用户数据。'),
    'compatibility': ('版本与格式兼容', '用项目明确支持的旧数据、配置、API或客户端版本检查升级兼容。修一个真实兼容差距，保留迁移、降级说明及失败路径；不能凭空承诺未测试版本。'),
    'resource-lifecycle': ('资源生命周期', '跟踪一个现有文件、连接、进程、订阅或临时产物的创建、取消、失败与回收。复现泄漏或过早释放并修复，以实际资源与用户结果验收。'),
    'concurrency': ('并发与冲突', '对一个真实共享状态模拟同时写入、重复调用和读写交错。先证明丢更新、重复副作用或冲突处理错误，再修同类路径，验证锁和失败恢复不妨碍正常用户操作。'),
    'operability': ('运行与维护体验', '从维护者视角走现有启动、配置变更、健康核对和故障恢复。修一个能本地复现的维护阻碍，交付可执行诊断与恢复步骤；不擅自改生产服务。'),
    'product-measurement': ('产品目标可测量性', '针对已有关键用户目标核对成功、失败、耗时与中断点是否可区分。补一个最小本地可验证的测量或归因缺口，说明样本与隐私；新的线上追踪和指标取舍提决策工单。'),
    'collaboration': ('协作与交接', '项目存在团队或人机协作时，沿实际任务的所有者、输入、进度、交接与验收追踪一次。修一个信息丢失或责任不明确的流程缺口，不给单用户工具凭空新增团队系统。'),
    'user-control': ('用户控制与撤销', '检查现有重要操作的预览、取消、草稿、撤销和恢复范围。修一个用户无法控制或误操作难恢复的真实路径，证明授权、副作用和数据保留符合约定。'),
    'supportability': ('用户支持与问题复现', '故意触发一个现有失败，核对用户能否获得可理解原因、恢复步骤和安全的复现资料。修一处诊断或支持入口缺口，验证不泄露秘密，不把未知根因写成定论。'),
    'information-architecture': ('信息组织与导航', '从实际用户目标核对已有对象、分类、导航、设置与历史是否容易找到。复现一处结构性理解或查找障碍，改进入口与关联，以找到正确对象验收，避免仅做重命名。'),
    'experiment-design': ('产品假设与验证', '针对有现有证据的产品假设明确用户、差距、候选、成本和可判失败的验证。实现可逆的本地原型或评测，记录结果与局限；没有用户数据不宣称转化或留存提升，业务选择提决策。'),
})

CONTRACT = ('每轮围绕一个真实用户目标交付一张改进工单。先读项目约定、产品定位、已有改动、测试与队列，'
            '确认适用性、当前差距、用户或商业收益和可判失败的验收；同一根因不重复开工。'
            '保留既有用户改动，在当前项目已授权范围内自主实现可逆的产品、体验和工程改进。'
            'bug 先复现再修复并补回归，运行适当实际检查；测试绿不等于用户目标已实现。'
            '不编造用户反馈、需求、指标、收入或验证结果，不为继续运行制造无价值的改动。'
            '额度失败、时段中断和交互让位不是任务完成或无事可做，应保留当前燃料供下一次续做。'
            '涉及价格、产品方向、生产权限、对外沟通、部署或发布的取舍，使用 ck propose --file <决策稿> '
            '写入 review-needed；包含稳定ID、证据、候选、推荐、收益、代价与验收。'
            '不因一个待决策事项把整个项目 BLOCKED，先完成独立可做的部分，继续其他燃料。'
            '领域包以现有能力为依据，启用只调整燃料，不代表授权新增业务；同一个 DECISION- ID不得重复提案。'
            '不要直接改写 ready/done 或自行验收；若有代码改动按项目规范小步提交。'
            '最终消息包含一行 证据: <实际依据>，最后一行 TASK_RESULT: DONE；无可证明改进则 '
            'TASK_RESULT: DONE (idle)。只有当前工作确实无法继续且无独立成果时才 TASK_RESULT: BLOCKED: 原因。')
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


def project_prompts():
    result = {}
    directory = leaf.STATE / 'prompts'
    if directory.is_symlink():
        raise ValueError('project prompt directory must not be a symlink')
    if directory.exists():
        for path in sorted(directory.glob('*.md')):
            if not NAME.fullmatch(path.stem):
                raise ValueError('invalid prompt id: ' + path.stem)
            result[path.stem] = (path.stem, bounded(path), 'project')
            if len(result) > CUSTOM_LIMIT:
                raise ValueError('project exceeds 128 custom prompts')
    return result


def profile_value():
    profile = leaf.STATE / 'fuel-packs.json'
    if not profile.exists() and not profile.is_symlink():
        return {'version': 1, 'enabled': []}
    value = json.loads(bounded(profile))
    packs.validate_profile(value)
    return value


def configured_packs():
    return profile_value()['enabled']


def enabled_packs():
    configured = configured_packs()  # malformed stored profiles remain visible
    if 'CODEXC_FUEL_PACKS' not in os.environ:
        return configured
    raw = os.environ['CODEXC_FUEL_PACKS']
    names = [] if raw == '' else [name.strip() for name in raw.split(',')]
    return packs.validate_profile({'version': 1, 'enabled': names})


def pack_recipes(names):
    result = {}
    for name in names:
        title, fit, recipes = packs.PACKS[name]
        for ident, (recipe_title, body) in recipes.items():
            if ident in BUILTINS or ident in result:
                raise ValueError('duplicate domain recipe ID: ' + ident)
            result[ident] = (recipe_title, '[领域: ' + name + ' / ' + title + ']\n适用条件: ' + fit + '\n' + body,
                             'domain:' + name)
    return result


def catalog(all_recipes=False):
    custom = project_prompts()
    core = {key: (title, body, 'built-in') for key, (title, body) in BUILTINS.items()}
    if all_recipes:
        result = {**core, **pack_recipes(packs.PACKS), **custom}
    else:
        result = {**core, **pack_recipes(enabled_packs()), **custom}
        selected = os.environ.get('CODEXC_PROMPT_IDS', '')
        if selected:
            names = [name.strip() for name in selected.split(',')]
            available = {**core, **pack_recipes(packs.PACKS), **custom}
            if (len(names) > CATALOG_LIMIT or len(set(names)) != len(names)
                    or any(name not in available for name in names)):
                raise ValueError('CODEXC_PROMPT_IDS must contain distinct known prompt IDs')
            # An explicit recipe selection also authorizes its domain recipe;
            # inspection and custom additions never depend on this filter.
            result = {name: available[name] for name in names}
    if len(result) > CATALOG_LIMIT:
        raise ValueError('catalog exceeds 512 prompts')
    return result


def change_packs(names, enable):
    packs.validate_profile({'version': 1, 'enabled': names})
    result = []
    def change():
        nonlocal result
        value = profile_value()
        before = value['enabled']
        result = list(dict.fromkeys(before + names)) if enable else [name for name in before if name not in names]
        if result != before:
            leaf.atomic(leaf.STATE / 'fuel-packs.json', leaf.encode({**value, 'enabled': result}))
    leaf.locked(change)
    return result


def add_prompt(ident, text):
    def add():
        current = project_prompts()
        if ident in current:
            raise ValueError('project prompt already exists: ' + ident)
        if len(current) >= CUSTOM_LIMIT:
            raise ValueError('project exceeds 128 custom prompts')
        directory = leaf.STATE / 'prompts'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (ident + '.md')
        fd, temporary = tempfile.mkstemp(prefix='.prompt-', dir=directory)
        try:
            with os.fdopen(fd, 'w') as out:
                out.write(text + '\n'); out.flush(); os.fsync(out.fileno())
            os.link(temporary, path)
            leaf.sync_dir(directory)
        finally:
            os.unlink(temporary)
    leaf.locked(add)


def catalog_signature(prompts):
    # Rotation order is part of the contract; sorted JSON object keys lose it.
    return leaf.digest(leaf.encode([list(prompts.items()), CONTRACT]))


def read_cursor():
    path = leaf.STATE / 'burn-cursor.json'
    if not path.exists() and not path.is_symlink():
        return None
    value = json.loads(bounded(path))
    position = value.get('next') if isinstance(value, dict) else None
    if type(position) is not int or not 0 <= position <= 2**63:
        raise ValueError('invalid burn cursor; inspect burn-cursor.json')
    for key in ('catalog', 'checked_catalog'):
        if key in value and (not isinstance(value[key], str) or not re.fullmatch(r'[0-9a-f]{64}', value[key])):
            raise ValueError('invalid burn cursor catalog signature')
    pending = value.get('pending')
    if pending is not None:
        if (not isinstance(pending, dict) or not NAME.fullmatch(str(pending.get('id', '')))
                or not isinstance(pending.get('token'), str) or not re.fullmatch(r'[0-9a-f]{32}', pending['token'])
                or type(pending.get('next')) is not int or not 0 <= pending['next'] <= CATALOG_LIMIT):
            raise ValueError('invalid pending fuel; inspect burn-cursor.json')
    completed = value.get('completed')
    if completed is not None and (not isinstance(completed, str) or not re.fullmatch(r'[0-9a-f]{32}', completed)):
        raise ValueError('invalid completed fuel token')
    return value


def render(ident, prompts):
    if ident not in prompts:
        raise ValueError('unknown prompt: ' + ident)
    title, body, _ = prompts[ident]
    return '[CodingKeeper 燃料: ' + ident + ' / ' + title + ']\n' + body + '\n' + CONTRACT


def next_prompt(reserve=False):
    result = {}
    def advance():
        prompts = catalog()
        signature = catalog_signature(prompts)
        keys = list(prompts)
        value = read_cursor() or {'next': 0}
        position = value['next']
        if value.get('catalog', signature) != signature:
            position = 0
            value = {key: item for key, item in value.items() if key != 'pending'}
        pending = value.get('pending')
        checked = value.get('checked_catalog', value.get('catalog', signature))
        if pending:
            if pending['id'] not in prompts:
                raise ValueError('pending fuel is not in the active catalog')
            ident = pending['id']
            result.update(token=pending['token'])
        else:
            ident = keys[position % len(keys)]
            if reserve:
                pending = {'id': ident, 'token': secrets.token_hex(16), 'next': (position + 1) % len(keys)}
                result.update(token=pending['token'])
            else:
                position = (position + 1) % len(keys)
        result.update(id=ident, count=len(keys), prompt=render(ident, prompts))
        after = {**value, 'next': position, 'catalog': signature, 'checked_catalog': checked}
        if pending:
            after['pending'] = pending
        leaf.atomic(leaf.STATE / 'burn-cursor.json', leaf.encode(after))
    leaf.locked(advance)
    return result


def complete_prompt(token):
    if not re.fullmatch(r'[0-9a-f]{32}', token):
        raise ValueError('invalid fuel completion token')
    def complete():
        value = read_cursor()
        if value and value.get('completed') == token:
            return
        pending = value.get('pending') if value else None
        if not pending or pending['token'] != token:
            raise ValueError('fuel completion does not match the pending direction')
        after = {key: item for key, item in value.items() if key != 'pending'}
        after.update(next=pending['next'], completed=token)
        leaf.atomic(leaf.STATE / 'burn-cursor.json', leaf.encode(after))
    leaf.locked(complete)


def source_revision():
    if leaf.git('rev-parse', '--show-toplevel', optional=True) is None:
        return None
    names = leaf.git('ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0')
    entries = []
    for raw in sorted(set(names)):
        name = os.fsdecode(raw)
        if not name or name.startswith(('.codingkeeper/', '.codexc/')):
            continue
        try:
            info = Path(name).lstat()
            entries.append((name, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
        except FileNotFoundError:
            entries.append((name, 'missing'))
    head = leaf.git('rev-parse', '--verify', 'HEAD', optional=True)
    return leaf.digest(leaf.encode([head.decode().strip() if head else None, entries]))


def fuel_state(exhaust=False):
    interval = os.environ.get('CODEXC_FUEL_RECHECK', '3600')
    if not re.fullmatch(r'[0-9]{1,6}', interval) or int(interval) > 604800:
        raise ValueError('CODEXC_FUEL_RECHECK must be 0..604800 seconds')
    interval = int(interval)
    now = int(time.time())
    marker = leaf.STATE / 'burn-exhausted.json'
    result = 'ready'

    def check():
        nonlocal result
        signature = catalog_signature(catalog())
        cursor = read_cursor()
        changed = cursor is not None and cursor.get('checked_catalog', cursor.get('catalog', signature)) != signature
        if exhaust:
            leaf.atomic(marker, leaf.encode({'catalog': signature, 'checked_at': now, 'source': source_revision()}))
            result = 'waiting'
        elif marker.exists() or marker.is_symlink():
            value = json.loads(bounded(marker))
            if not isinstance(value, dict) or not isinstance(value.get('catalog'), str):
                raise ValueError('invalid burn exhaustion state')
            checked = value.get('checked_at', int(marker.stat().st_mtime))
            if type(checked) is not int or checked < 0:
                raise ValueError('invalid fuel rescan timestamp')
            same_source = value.get('source') == source_revision()
            due = interval > 0 and now - checked >= interval
            if changed:
                # Validate the complete marker before acknowledging a new sweep.
                leaf.atomic(leaf.STATE / 'burn-cursor.json', leaf.encode({**cursor, 'checked_catalog': signature}))
            if value['catalog'] == signature and same_source and not due and not changed:
                result = 'waiting'
            else:
                marker.unlink()
                leaf.sync_dir(leaf.STATE)
                result = 'renewed'
        elif changed:
            leaf.atomic(leaf.STATE / 'burn-cursor.json', leaf.encode({**cursor, 'checked_catalog': signature}))
            result = 'renewed'

    leaf.locked(check)
    return result


def enqueue(text, section='ready'):
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
        if any(task == text and pending and area == section for _, task, pending, area in leaf.queue_items(before)):
            if section == 'review-needed':
                return
            raise ValueError('identical task is already ready')
        ident = re.match(r'^(DECISION-[A-Z0-9]+(?:-[A-Z0-9]+)*)\b', text, re.I)
        if section == 'review-needed' and ident:
            for _, task, pending, area in leaf.queue_items(before):
                other = re.match(r'^(DECISION-[A-Z0-9]+(?:-[A-Z0-9]+)*)\b', task, re.I)
                if pending and area == section and other and other[1].upper() == ident[1].upper():
                    raise ValueError('decision ID already pending; reconcile existing proposal: ' + ident[1])
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
                if heading[1].strip().lower() == section:
                    start = i
        if start is None:
            if section != 'review-needed':
                raise ValueError('queue has no ' + section + ' section')
            lines.append('\n## review-needed\n')
            start = len(lines) - 1
        end = len(lines) if end is None else end
        parts = text.splitlines()
        inserted = '- [ ] ' + parts[0] + '\n' + ''.join('  ' + line + '\n' for line in parts[1:])
        prefix = ''.join(lines[:end])
        if not prefix.endswith('\n'):
            prefix += '\n'
        after = (prefix + inserted + ''.join(lines[end:])).encode()
        if not any(task == text and pending and area == section for _, task, pending, area in leaf.queue_items(after)):
            raise ValueError('new task did not roundtrip through the queue parser; queue unchanged')
        leaf.atomic(queue, after, stat.S_IMODE(queue.stat().st_mode) if queue.exists() else 0o600)

    leaf.locked(append)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    listing = sub.add_parser('list'); listing.add_argument('--all', action='store_true', help='include inactive domain recipes')
    listing_packs = sub.add_parser('packs', help='inspect domain packs'); listing_packs.add_argument('id', nargs='?'); listing_packs.add_argument('--json', action='store_true')
    enable = sub.add_parser('enable', help='persist domain packs for this project'); enable.add_argument('ids', nargs='+')
    disable = sub.add_parser('disable', help='disable project domain packs'); disable.add_argument('ids', nargs='+')
    show = sub.add_parser('show'); show.add_argument('id')
    next_cmd = sub.add_parser('next'); next_cmd.add_argument('--format', choices=('json', 'tsv'), default='json')
    next_cmd.add_argument('--reserve', action='store_true', help='retain this direction until completion')
    completion = sub.add_parser('complete'); completion.add_argument('token')
    sub.add_parser('available')
    sub.add_parser('exhaust')
    add = sub.add_parser('add'); add.add_argument('id'); add.add_argument('--file', required=True)
    queue = sub.add_parser('enqueue')
    sources = queue.add_mutually_exclusive_group(required=True)
    sources.add_argument('text', nargs='?'); sources.add_argument('--file'); sources.add_argument('--prompt')
    proposal = sub.add_parser('propose', help='record a decision for human review')
    sources = proposal.add_mutually_exclusive_group(required=True)
    sources.add_argument('text', nargs='?'); sources.add_argument('--file')
    args = parser.parse_args()
    try:
        if args.command == 'list':
            for ident, (title, _, source) in catalog(all_recipes=args.all).items():
                print(ident + '\t' + title + '\t' + source)
        elif args.command == 'show':
            print(render(args.id, catalog(all_recipes=True)))
        elif args.command == 'next':
            result = next_prompt(reserve=args.reserve)
            if args.format == 'tsv':
                print(result['id'] + '\t' + str(result['count']) + '\t' + base64.b64encode(result['prompt'].encode()).decode()
                      + ('\t' + result['token'] if 'token' in result else ''))
            else:
                print(json.dumps(result, ensure_ascii=True))
        elif args.command == 'complete':
            complete_prompt(args.token)
            print('fuel completed')
        elif args.command in ('available', 'exhaust'):
            print(fuel_state(exhaust=args.command == 'exhaust'))
        elif args.command == 'packs':
            if args.id and args.id not in packs.PACKS:
                raise ValueError('unknown domain pack: ' + args.id)
            active = enabled_packs()
            names = [args.id] if args.id else list(packs.PACKS)
            entries = [{'id': name, 'title': packs.PACKS[name][0], 'fit': packs.PACKS[name][1],
                        'enabled': name in active, 'recipes': list(packs.PACKS[name][2])} for name in names]
            if args.json:
                print(json.dumps({'core_count': len(BUILTINS), 'domain_count': sum(len(item[2]) for item in packs.PACKS.values()),
                                  'configured_packs': configured_packs(), 'active_packs': active,
                                  'environment_override': 'CODEXC_FUEL_PACKS' in os.environ, 'packs': entries}, ensure_ascii=False))
            else:
                for item in entries:
                    print(item['id'] + '\t' + item['title'] + '\t' + str(len(item['recipes'])) + '\t' + ('enabled' if item['enabled'] else 'inactive'))
                    print('  适用: ' + item['fit'])
                    if args.id:
                        for ident in item['recipes']:
                            print('  ' + ident + '\t' + packs.PACKS[item['id']][2][ident][0])
        elif args.command in ('enable', 'disable'):
            enabled = change_packs(args.ids, args.command == 'enable')
            print('configured domain packs: ' + (','.join(enabled) or '(none)'))
            if 'CODEXC_FUEL_PACKS' in os.environ:
                print('CODEXC_FUEL_PACKS overrides this saved profile for the current process', file=sys.stderr)
        elif args.command == 'add':
            if not NAME.fullmatch(args.id):
                raise ValueError('prompt id must contain lowercase letters, digits and hyphens')
            add_prompt(args.id, bounded(args.file))
            print('added prompt: ' + args.id)
        elif args.command == 'propose':
            text = bounded(args.file) if args.file else args.text
            enqueue(text, 'review-needed')
            print('decision recorded in .codingkeeper/queue.md review-needed')
        else:
            text = bounded(args.file) if args.file else render(args.prompt, catalog(all_recipes=True)) if args.prompt else args.text
            enqueue(text)
            print('queued in .codingkeeper/queue.md')
    except (OSError, ValueError, UnicodeError) as error:
        parser.exit(2, 'prompt fuel: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
