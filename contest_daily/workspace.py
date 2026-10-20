"""Portable workspaces: configuration, catalog adoption, sources and offline demo."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

from .core import CST, load_json, save_json

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def catalog_digest(document):
    return hashlib.sha256(json.dumps(document.get('records', []), sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def confirmed_catalog(root):
    source = load_json(root/'config/catalog.json')
    if source is None:
        return None
    review = source.get('review', {})
    if review.get('status') != 'confirmed' or review.get('catalog_sha256') != catalog_digest(source):
        raise ValueError('竞赛清单尚未核对，或核对后已被编辑；请查看 config/catalog.json 后执行 confirm-catalog')
    return source


def init_workspace(root, university, college, *, report_title='竞赛日报', accent_color='#1d6652'):
    from .branding import normalize_profile
    root = Path(root).resolve()
    if not university.strip() or not college.strip():
        raise ValueError('请填写大学和学院名称')
    profile = normalize_profile({'schema_version': 1, 'university': university, 'college': college,
                                 'report_title': report_title, 'brand_name': '竞赛情报',
                                 'english_title': 'COMPETITOR DAILY', 'subtitle': '学科竞赛追踪',
                                 'accent_color': accent_color, 'site_url': '', 'footer_text': 'Competitor Daily · 以官方通知为准'})
    if (root/'config/profile.json').exists() or (root/'config/catalog.json').exists() or (root/'data/state').exists():
        raise ValueError('该目录已有日报机配置或历史，请使用新的独立目录；已有表头可直接编辑 config/profile.json')
    root.mkdir(parents=True, exist_ok=True)
    save_json(root/'config/profile.json', profile)
    save_json(root/'config/source_registry.json', {})
    save_json(root/'config/track_aliases.json', {})
    save_json(root/'config/runtime.json', {'schema_version': 1, 'deadline_days': 7, 'max_pages': 4,
                                          'workers': 1, 'source_timeout': 15, 'min_success_ratio': .5})
    (root/'inputs').mkdir(exist_ok=True)
    (root/'assets').mkdir(exist_ok=True)
    for name in ('ReportSans.ttc', 'FONT-LICENSE.txt'):
        origin = PACKAGE_ROOT/'assets'/name
        if origin.is_file():
            shutil.copyfile(origin, root/'assets'/name)
    example = PACKAGE_ROOT/'.env.example'
    content = example.read_text(encoding='utf-8') if example.exists() else 'DEEPSEEK_API_KEY=\nDEEPSEEK_MODEL=deepseek-flash\nSEARCH_PROVIDER=deepseek\n'
    # Always create blank credentials; never inherit the author's actual .env.
    content = re.sub(r'(?m)^DEEPSEEK_API_KEY=.*$', 'DEEPSEEK_API_KEY=', content)
    if not (root/'.env').exists():
        (root/'.env').write_text(content, encoding='utf-8')
        (root/'.env').chmod(0o600)
    (root/'.gitignore').write_text('.env\n.env.*\n!.env.example\ndata/\n__pycache__/\n', encoding='utf-8')
    return profile


def source_presets():
    return load_json(PACKAGE_ROOT/'presets/sources.json', {})


def confirm_catalog(root):
    from .catalog_io import validate_catalog
    target = root/'config/catalog.json'
    document = load_json(target)
    if not document:
        raise ValueError('先用 import-catalog 导入竞赛清单')
    document['records'] = validate_catalog(document)
    if not document.get('records'):
        raise ValueError('未提取到赛事，不能采用空清单；请由 Agent 依据原件整理 records 后再核对')
    presets = source_presets()
    registry = load_json(root/'config/source_registry.json', {})
    # Source identity follows the normalized competition name, never an old school's numeric ID.
    for record in document['records']:
        identifier = str(record['id'])
        config = registry.get(identifier)
        if config and config.get('name') not in (None, record['name']):
            config = None
        if config is None:
            config = dict(presets.get(record['name'], {}))
        urls = record.get('official_urls', [])
        if urls:
            for url in urls:
                parsed = urllib.parse.urlsplit(url)
                if parsed.scheme not in ('http', 'https') or not parsed.hostname:
                    raise ValueError('official_urls 必须是完整 HTTP(S) 官方网址')
                config.setdefault('urls', [])
                config.setdefault('trusted_domains', [])
                if url not in config['urls']: config['urls'].append(url)
                if parsed.hostname not in config['trusted_domains']: config['trusted_domains'].append(parsed.hostname)
        config['name'] = record['name']
        registry[identifier] = config
    current_ids = {str(row['id']) for row in document['records']}
    registry = {key: value for key, value in registry.items() if key in current_ids}
    # Review status is separate from a genuine disagreement between duplicate recognition levels.
    for record in document['records']:
        record['requires_confirmation'] = len({other['suggested_level'] for other in document['records'] if other['name'] == record['name']}) > 1
    document['review'] = {'status': 'confirmed', 'catalog_sha256': catalog_digest(document), 'confirmed_at': datetime.now(CST).isoformat()}
    document['requires_confirmation'] = False
    save_json(target, document)
    save_json(root/'config/source_registry.json', registry)
    return document


def add_source(root, identifier, url, domain=None):
    document = confirmed_catalog(root)
    if not document or identifier not in {row['id'] for row in document['records']}:
        raise ValueError('赛事编号不在已核对的竞赛清单中')
    parsed = urllib.parse.urlsplit(url)
    domain = domain or parsed.hostname
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or not domain or not (parsed.hostname == domain or parsed.hostname.endswith('.'+domain)):
        raise ValueError('来源 URL 必须为 HTTP(S)，且属于所登记域名')
    registry = load_json(root/'config/source_registry.json', {})
    entry = registry.setdefault(str(identifier), {})
    for field, value in (('urls', url), ('trusted_domains', domain)):
        if value not in entry.setdefault(field, []): entry[field].append(value)
    save_json(root/'config/source_registry.json', registry)
    return entry


def runtime_settings(root, overrides):
    defaults = {'max_pages': 4, 'workers': 1, 'source_timeout': 15, 'min_success_ratio': .5, 'deadline_days': 7}
    value = load_json(Path(root)/'config/runtime.json', {})
    if not isinstance(value, dict) or value.get('schema_version', 1) != 1:
        raise ValueError('runtime.json 必须为 schema_version=1 的配置对象')
    result = {key: overrides.get(key) if overrides.get(key) is not None else value.get(key, default) for key, default in defaults.items()}
    for key in ('max_pages', 'workers', 'source_timeout', 'deadline_days'):
        if type(result[key]) is not int or not 1 <= result[key] <= {'max_pages': 30, 'workers': 4, 'source_timeout': 120, 'deadline_days': 90}[key]:
            raise ValueError(f'runtime.{key} 超出有效范围')
    if type(result['min_success_ratio']) not in (int, float) or not 0 <= result['min_success_ratio'] <= 1:
        raise ValueError('runtime.min_success_ratio 必须为 0 到 1 之间的数字')
    return result


def demo(root):
    """Fictional data, offline only. Never write a demo into a real user's history."""
    from .branding import load_profile
    from .core import build_report, validate_event
    from .render import write_report
    root = Path(root).resolve()
    if (root/'config/catalog.json').exists() or (root/'data/state').exists() or (root/'reports').exists():
        raise ValueError('演示请使用独立新目录，不覆盖实际清单、历史或日报')
    if not (root/'config/profile.json').exists():
        init_workspace(root, '示例大学', '计算机与人工智能学院')
    now = datetime(2026, 10, 20, 8, tzinfo=CST)
    catalog = [
        {'ids':[1], 'name':'校园创新应用挑战赛（演示）', 'levels':['学院 A 类'], 'conflict':False},
        {'ids':[2], 'name':'开放数据可视化赛（演示）', 'levels':['学院 B 类'], 'conflict':False},
        {'ids':[3], 'name':'智能系统设计赛（演示）', 'levels':['学院 A 类'], 'conflict':False},
    ]
    raw = [
        {'competition_ids':[1], 'track':'软件创新', 'title':'校园创新应用挑战赛报名通知（虚构演示）', 'registration_start':'2026-10-20', 'registration_end':'2026-11-05', 'submission_deadline':'2026-11-12T18:00:00+08:00', 'participation_mode':'online', 'eligibility':['本科生、研究生均可参加', '1–3 人组队，允许跨院系'], 'deliverables':['项目说明书 PDF', '可运行的作品或代码仓库', '3 分钟演示视频']},
        {'competition_ids':[2], 'track':'数据叙事', 'title':'开放数据可视化赛作品提交安排（虚构演示）', 'registration_start':'2026-10-01', 'registration_end':'2026-10-23T23:59:00+08:00', 'submission_deadline':'2026-10-25T18:00:00+08:00', 'participation_mode':'online', 'eligibility':['在校学生', '个人或 2 人组队'], 'deliverables':['交互式可视化 HTML', '数据来源与处理说明', '作品截图 PNG']},
        {'competition_ids':[3], 'track':'智能硬件', 'title':'智能系统设计赛线下展示安排（虚构演示）', 'registration_start':'2026-09-01', 'registration_end':'2026-10-10', 'competition_start':'2026-10-18', 'competition_end':'2026-11-08', 'participation_mode':'hybrid', 'mode_details':'线上提交技术文档，入围队伍参加线下展示', 'eligibility':['2–4 人组队', '至少一名成员负责硬件实现'], 'deliverables':['技术报告 PDF', '原型演示视频', '入围后携带硬件原型'], 'current_phase':'作品开发与线上材料提交'},
    ]
    events = []
    for item in raw:
        item.update(edition='2026', notes=['虚构示例，仅展示产品能力，不是真实赛事通知。'], sources=[{'url':'https://example.org/competitor-daily-demo', 'title':'虚构演示来源（不作为真实通知）', 'published_date':'2026-10-20'}])
        events.append(validate_event(item, {1,2,3}, now))
    coverage = [{'competition_id': i, 'result':'verified_event', 'urls':[], 'note':'虚构演示，未发起网络请求'} for i in (1,2,3)]
    report = build_report(events, coverage, catalog, now, None)
    report.update(branding=load_profile(root), demo=True, acquisition='offline_demo', partial_scan=False,
                  run_quality={'passed': True, 'competition_count':3, 'results':{'verified_event':3}})
    # Demo facts are never persisted as a real scan/snapshot or sent to any API.
    return write_report(root, report)
