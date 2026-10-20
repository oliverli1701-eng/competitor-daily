"""自包含的竞赛日报产品界面 V7：动效特刊。

编辑部版式之上加入数据驱动的动效层：今日焦点实时倒计时、提醒窗口进度环、
未来 14 天节点日历带、卡片进场编排与指针微交互；仍无外部前端依赖。
"""
from __future__ import annotations

import html
import json
import math
import re
from datetime import date, datetime, timedelta

from .core import parse_at, effective_lifecycle
from .branding import institution_name, normalize_profile, profile_css
from .presentation import SECTIONS, build_cards, clean_fact, short_date


def esc(value):
    return html.escape(str(value or ''), quote=True)


ICONS = {
    'grid': '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    'search': '<circle cx="10.7" cy="10.7" r="6.7"/><path d="m16 16 4.5 4.5"/>',
    'arrow': '<path d="M5 12h14m-5-5 5 5-5 5"/>',
    'external': '<path d="M14 4h6v6m0-6-9 9M10 5H5v14h14v-5"/>',
    'down': '<path d="m8 11 4 4 4-4M12 3v12M4 17v4h16v-4"/>',
    'close': '<path d="m6 6 12 12M6 18 18 6"/>',
    'list': '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="5.2" cy="6" r="1.15"/><circle cx="5.2" cy="12" r="1.15"/><circle cx="5.2" cy="18" r="1.15"/>',
    'timeline': '<path d="M7 3.5v17"/><circle cx="7" cy="8" r="2.3"/><circle cx="7" cy="16.5" r="2.3"/><path d="M12.5 8H19M12.5 16.5H19"/>',
}


def icon(name, css=''):
    return f'<svg class="icon {css}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>'


# 头部启动脚本：在样式应用前恢复上次的配色选择，避免深色用户看到浅色闪烁。
THEME_BOOT = "<script>try{var themeChoice=localStorage.getItem('cb-theme');if(themeChoice){document.documentElement.dataset.theme=themeChoice}}catch(error){}</script>"


def node_key(node):
    if not node:
        return (2, float('inf'))
    return (0 if node['kind'] in ('registration_end', 'submission_deadline') else 1, node['at'])


def ui_variant(event, name, year, variant_renderer, now, window=7):
    variant = variant_renderer(event, name)
    variant.update(status=event.get('status', ''), key=event['key'], label=event['view_track'] or event.get('edition') or event['title'], levels=event.get('levels', []))
    variant['entry_url'] = event.get('entry_url') if re.match(r'^https?://', event.get('entry_url') or '') else ''
    def describe(point, label, value, kind):
        days = (point.date()-now.date()).days
        deadline = kind in ('registration_end', 'submission_deadline')
        # 紧迫分级：今日、1–3 天、提醒窗口内其余，仅报名/作品截止参与分级。
        urgency = ('today' if days == 0 else 'soon' if days <= 3 else 'week') if deadline and 0 <= days <= window else ''
        kind_label = {'registration_end':'报名截止', 'submission_deadline':'作品截止', 'competition_start':'比赛开始', 'milestone':'赛程节点'}[kind]
        relative = ('今日' if days == 0 else f'{days} 天后') + ('截止' if deadline else '开赛' if kind == 'competition_start' else '')
        clock = point.strftime('%H:%M') + (point.strftime(':%S') if point.second else '') if 'T' in value else ''
        return {'at':point.timestamp(), 'label':label, 'value':short_date(value, year), 'kind':kind, 'kind_label':kind_label, 'days':days, 'urgent':deadline and 0<=days<=window, 'urgency':urgency, 'window':window, 'date_main':(f'{point.year}年' if point.year!=year else '')+f'{point.month}月{point.day}日', 'clock':clock, 'datetime':point.isoformat() if 'T' in value else point.date().isoformat(), 'relative':relative, 'track':variant['label'], 'weekday':'周'+'一二三四五六日'[point.weekday()]}
    deadlines = []
    for field, label in (('registration_end', event.get('registration_deadline_label', '报名截止')), ('submission_deadline', '作品提交')):
        if effective_lifecycle(event) == 'canceled' or (field == 'registration_end' and effective_lifecycle(event) in ('postponed', 'registration_closed')):
            continue
        point = parse_at(event.get(field), end=True)
        if point and point >= now:
            deadlines.append(describe(point, label, event[field], field))
    deadline = min(deadlines, key=lambda node:node['at']) if deadlines else None
    if len(deadlines)==2 and deadlines[0]['at']==deadlines[1]['at']:
        deadline['kind_label'] = '报名 / 作品截止'
        if deadline['label']=='报名截止':
            deadline['label'] = '报名 / 作品截止'
    fallback = event.get('view_next')
    variant['deadline'] = deadline
    variant['node'] = deadline or (describe(*fallback) if fallback else None)
    return variant


def state_label(variants):
    multiple = len(variants)>1
    if any(v['open'] for v in variants):
        return ('含可报名赛项' if multiple else '报名中', '')
    if any(v['status']=='in_progress' for v in variants):
        return ('含进行中赛项' if multiple else '比赛进行中', ' competing')
    labels = {'upcoming':'赛程预告', 'registration_closed':'报名已截止', 'closed':'本阶段结束', 'canceled':'已取消', 'postponed':'已延期 · 报名暂停'}
    text = next((labels[v['status']] for v in variants if v['status'] in labels), '')
    return (('含'+text+'赛项') if multiple and text else text, ' upcoming')


def mode_label(variants):
    modes = sorted({mode for variant in variants for mode in variant['modes']})
    if len(modes)>1:
        return '线上 / 线下（分赛项）'
    label = {'online':'线上', 'offline':'线下', 'hybrid':'线上 + 线下'}.get(modes[0], '') if modes else ''
    return '含'+label+'赛项' if label and len(variants)>1 else label


def card_html(card, year, detail_renderer, variant_renderer, now=None, window=7, stagger=0):
    if now is None:
        now = parse_at(card['events'][0]['verified_as_of'])
    events = card['events']
    variants = [ui_variant(event, card['name'], year, variant_renderer, now, window) for event in events]
    featured = min(variants, key=lambda variant:node_key(variant['node']))
    node = featured['node']
    urgency = node['urgency'] if node else ''
    grade = ' / '.join('学院 '+level.replace('类', ' 类') for level in card['levels'])
    recognition = '<span class="recognition-tag" title="原清单等级或现名称映射需按学院口径核对">认定提示</span>' if card.get('conflict') or card.get('mapped') else ''
    edition = ' / '.join(dict.fromkeys(re.findall(r'20\d{2}(?:-20\d{2})?', ' '.join(event.get('edition', '') for event in events))))
    state, tone = state_label(variants)
    mode = mode_label(variants)
    briefs = []
    for event, variant in zip(events, variants):
        fields = []
        for label, values in (('参赛对象', event['view_eligibility']), ('提交内容', event['view_deliverables'])):
            if values:
                fields.append(f'<div class="brief-line"><div><span>{label}</span><p>{esc("；".join(values[:2]))}</p></div></div>')
        if not fields:
            phase = clean_fact(event.get('current_phase')) or next(iter(event['view_notes']), '')
            if phase:
                fields.append(f'<div class="brief-line"><div><span>已知进展</span><p>{esc(phase)}</p></div></div>')
        if event.get('stale'):
            fields.append(f'<p class="verification-note">沿用上次核验 · {esc((event.get("verified_as_of") or "")[:10])}</p>')
        briefs.append(f'<div class="track-brief" data-key="{esc(variant["key"])}" data-variant="{esc(json.dumps(variant, ensure_ascii=False))}" {"hidden" if variant is not featured else ""}>{"".join(fields)}</div>')
    source_body = ''.join(detail_renderer(event, year, card['name']) for event in events)
    if card.get('conflict'):
        source_body = '<p class="recognition">原清单同名赛事有 A / B 等级冲突，请按学院认定口径核对。</p>'+source_body
    elif card.get('mapped'):
        source_body = '<p class="recognition">等级沿用学院原清单；现名称或子赛道的认定需按学院口径核对。</p>'+source_body
    entry = featured['entry_url'] if featured['open'] else ''
    note = node['label'] if node and node['label'] not in (node['kind_label'], '作品提交', '作品截止') else ''
    badge_text = ''
    if urgency and node:
        badge_text = '今日截止' if node['days'] == 0 else f'剩 {node["days"]} 天'
    badge_class = f' {urgency}' if urgency else ''
    relative_hidden = '' if (node and not urgency) else ' hidden'
    relative_text = esc(node['relative']) if (node and not urgency) else ''
    if urgency and node:
        fraction = max(0.0, min(1.0, (window - node['days']) / window))
        progress_html = f'<span class="action-progress" aria-hidden="true"><i style="width:{fraction * 100:.0f}%"></i></span>'
    else:
        progress_html = '<span class="action-progress" hidden aria-hidden="true"><i></i></span>'
    action_urgency = f' data-urgency="{esc(urgency)}"' if urgency else ''
    return f'''<article class="contest-card" id="{card['key']}" style="--reveal-delay:{stagger}ms" data-name="{esc(card['name'])}" data-featured="{esc(featured['key'])}" data-urgent="{str(bool(node and node['urgent'])).lower()}" data-urgency="{esc(urgency)}" data-variants="{esc(json.dumps(variants, ensure_ascii=False))}"><div class="card-inner">
      <div class="card-identity"><div class="card-classification"><span class="grade-tag">{esc(grade)}</span>{recognition}<span class="edition">{esc(edition)}</span></div><h3>{esc(card['name'])}</h3><div class="card-tags"><span class="state-tag{tone}"{" hidden" if not state else ""}><i></i><span class="state-label">{esc(state)}</span></span><span class="mode-tag"{" hidden" if not mode else ""}>{esc(mode)}</span></div><p class="track-count">共 {len(events)} 条赛项记录</p></div>
      <div class="card-brief">{''.join(briefs)}</div>
      <div class="action-node" data-kind="{esc(node['kind'] if node else '')}"{action_urgency}{" hidden" if not node else ""}><span class="action-kind">{esc(node['kind_label'] if node else '')}</span><time class="action-time" datetime="{esc(node['datetime'] if node else '')}"><b class="action-date-value">{esc(node['date_main'] if node else '')}</b><span class="action-clock"{" hidden" if not node or not node['clock'] else ""}>{esc(node['clock'] if node else '')}</span></time>{progress_html}<span class="action-badge{badge_class}"{" hidden" if not urgency else ""}>{esc(badge_text)}</span><span class="action-relative"{relative_hidden}>{relative_text}</span><p class="action-date-label"{" hidden" if not note else ""}>{esc(note)}</p><p class="action-track">{esc('对应赛项 · '+featured['label'] if node else '')}</p></div>
      <div class="card-actions"><details class="rules"><summary class="detail-trigger"><span class="detail-trigger-label">查看赛项与官方来源</span>{icon('arrow')}</summary><div class="rules-body">{source_body}</div></details><a class="entry-link" href="{esc(entry or '#')}" target="_blank" rel="noopener noreferrer"{" hidden" if not entry else ""}>当前赛项报名{icon('external')}</a></div>
    </div></article>'''


SECTION_INDEX = {'new_registration': '壹', 'updates': '贰', 'deadlines': '叁', 'ongoing': '肆'}
URGENCY_ORDER = {'today': 0, 'soon': 1, 'week': 2, '': 3}


def focus_panel_html(cards, year, now, window, variant_renderer):
    """今日焦点（全局最紧迫节点）+ 未来 14 天关键节点日历带，均为日报时点的静态事实。"""
    if not cards:
        return ''
    best_card = best_node = None
    buckets = {}
    for card in cards:
        variants = [ui_variant(event, card['name'], year, variant_renderer, now, window) for event in card['events']]
        featured = min(variants, key=lambda variant: node_key(variant['node']))
        if featured['node'] and (best_node is None or node_key(featured['node']) < node_key(best_node)):
            best_card, best_node = card, featured['node']
        for variant in variants:
            node = variant['node']
            if not node:
                continue
            offset = (datetime.fromtimestamp(node['at'], tz=now.tzinfo).date() - now.date()).days
            if 0 <= offset < 14:
                bucket = buckets.setdefault(offset, {'count': 0, 'urgency': '', 'date_main': node['date_main']})
                bucket['count'] += 1
                if URGENCY_ORDER.get(node['urgency'], 3) < URGENCY_ORDER.get(bucket['urgency'], 3):
                    bucket['urgency'] = node['urgency']
    if best_card is None or best_node is None:
        return ''
    node = best_node
    urgency = node['urgency']
    remaining = max(0.0, node['at'] - now.timestamp())
    units = ((int(remaining // 86400), 'days', '天'), (int(remaining % 86400 // 3600), 'hours', '时'), (int(remaining % 3600 // 60), 'minutes', '分'), (int(remaining % 60), 'seconds', '秒'))
    cells = ''.join(f'<span class="cd-cell" data-cell="{unit}"><b class="cd-num" data-unit="{unit}">{value:02d}</b><span class="cd-label">{label}</span></span>' for value, unit, label in units)
    circumference = 2 * math.pi * 52
    if node['urgent']:
        fraction = max(0.0, min(1.0, (window - node['days']) / window))
        ring_html = f'<div class="hero-ring"><svg viewBox="0 0 120 120" aria-hidden="true"><circle class="ring-track" cx="60" cy="60" r="52"/><circle class="ring-value" data-full="{circumference:.1f}" cx="60" cy="60" r="52" style="stroke-dasharray:{circumference:.1f};stroke-dashoffset:{circumference * (1 - fraction):.1f}"/></svg><div class="ring-center"><b>{node["days"]}</b><span>天后截止</span></div></div>'
    else:
        ring_html = f'<div class="hero-ring" hidden><svg viewBox="0 0 120 120" aria-hidden="true"><circle class="ring-track" cx="60" cy="60" r="52"/><circle class="ring-value" data-full="{circumference:.1f}" cx="60" cy="60" r="52" style="stroke-dasharray:{circumference:.1f};stroke-dashoffset:{circumference:.1f}"/></svg><div class="ring-center"><b></b><span>天后截止</span></div></div>'
    sub_parts = [part for part in (node['track'], node['kind_label']) if part]
    if node['label'] and node['label'] not in (node['kind_label'], '作品提交', '作品截止'):
        sub_parts.append(node['label'])
    horizon_cells = []
    for offset in range(14):
        day = now.date() + timedelta(days=offset)
        bucket = buckets.get(offset)
        count = bucket['count'] if bucket else 0
        classes = ['hz-cell']
        if bucket and bucket['urgency']:
            classes.append('hz-' + bucket['urgency'])
        if offset == 0:
            classes.append('hz-issue')
        bars = '<span class="hz-bars" aria-hidden="true">' + ''.join('<i></i>' for _ in range(min(count, 4))) + '</span>'
        count_label = f'<span class="hz-count">{count}</span>' if count else '<span class="hz-count">·</span>'
        flag = '<span class="hz-flag" aria-hidden="true">刊</span>' if offset == 0 else ''
        date_attr = f' data-date="{esc(bucket["date_main"])}"' if bucket else ''
        disabled = '' if bucket else ' disabled'
        title = f'{bucket["date_main"]} · {count} 个关键节点' if bucket else f'{day.month}月{day.day}日 · 暂无关键节点'
        horizon_cells.append(f'<button type="button" class="{" ".join(classes)}" style="--i:{offset}"{date_attr}{disabled} title="{esc(title)}"><span class="hz-week">周{"一二三四五六日"[day.weekday()]}</span><span class="hz-day">{day.day}</span>{bars}{count_label}{flag}</button>')
    return f'''<section class="focus-panel" data-urgency="{esc(urgency)}" aria-label="今日焦点与未来十四天关键节点">
      <div class="focus-hero" id="focus-hero"><div class="hero-main"><p class="hero-eyebrow"><i class="hero-live-dot" aria-hidden="true"></i>今日焦点 · 实时倒计时</p><button type="button" class="hero-title" id="hero-title" data-card="{esc(best_card['key'])}">{esc(best_card['name'])}</button><p class="hero-sub" id="hero-sub">{esc(' · '.join(sub_parts))}</p><div class="hero-countdown" id="hero-countdown" role="timer" aria-label="距该节点的实时剩余时间">{cells}</div><p class="hero-expired" id="hero-expired" hidden>该节点时刻已到 · 后续安排以官方通知为准</p></div>{ring_html}</div>
      <div class="horizon" aria-label="未来十四天关键节点日历"><p class="horizon-title">未来 14 天关键节点 · 按日统计</p><div class="horizon-cells">{''.join(horizon_cells)}</div></div>
    </section>'''


def render_html(report, detail_renderer, variant_renderer):
    profile = normalize_profile(report.get('branding'))
    cards = build_cards(report)
    year = int(report['date'][:4])
    now = parse_at(report['as_of'])
    window = report.get('deadline_window_days', 7)
    def card_key(card):
        return min((node_key(ui_variant(event, card['name'], year, variant_renderer, now, window)['node']) for event in card['events']))
    cards.sort(key=card_key)
    counts = {key:sum(key in card['sections'] for card in cards) for key, _ in SECTIONS}
    tabs = [('all', '全部赛事', len(cards)), ('new_registration', '新开放报名', counts['new_registration']), ('updates', '赛事重要更新', counts['updates']), ('deadlines', '临近截止提醒', counts['deadlines']), ('ongoing', '正在进行的比赛', counts['ongoing'])]
    def tab_markup(key, label, count):
        index = f'<span class="tab-index" aria-hidden="true">{SECTION_INDEX[key]}</span>' if key in SECTION_INDEX else ''
        return f'<button class="tab {"active" if key == "all" else ""}" data-section="{key}" aria-pressed="{str(key == "all").lower()}">{index}<span class="tab-name">{label}</span><span class="tab-count">{count} 项</span></button>'
    navigation = ''.join(tab_markup(key, label, count) for key, label, count in tabs)
    issue = date.fromisoformat(report['date'])
    weekday = '星期' + '一二三四五六日'[issue.weekday()]
    issue_date = f'{issue.year} 年 {issue.month} 月 {issue.day} 日'
    stamp = report['as_of'][:16].replace('T', ' ')
    rechecks = sorted({event.get('content_rechecked_on') for event in report['events'] if event.get('content_rechecked_on')})
    audit_stamp = f' · {rechecks[-1]} 补充核对' if rechecks else ''
    records = sum(len(card['events']) for card in cards)
    covered = report.get('coverage_checked_records', 0)
    catalog_records = report.get('catalog_records', 0)
    quality=report.get('run_quality') or {}
    outcomes=quality.get('results',{})
    successful=sum(outcomes.get(k,0) for k in ('verified_event','no_current_notice','no_verified_event'))
    quality_note=f' · 有效提取 {successful}/{quality["competition_count"]} 项赛事' if quality.get('competition_count') else ''
    levels = sorted({level for card in cards for level in card['levels']})
    grade_options = ''.join(f'<option value="{esc(level)}">{esc(level.replace("类", " 类"))}</option>' for level in levels)
    masthead_title = ''.join(f'<span class="title-char" style="--i:{index}">{esc(character)}</span>' for index, character in enumerate(profile['report_title']))
    eyebrow = ' · '.join(filter(None, [institution_name(profile), profile['subtitle']]))
    brand_style = profile_css(profile)
    if len(profile['report_title']) > 8:
        brand_style += '.nameplate h1{font-size:clamp(24px,5vw,48px);letter-spacing:.08em;text-indent:.08em;overflow-wrap:anywhere}'
    demo_banner = ''
    if report.get('demo'):
        demo_banner = '<aside class="demo-banner" aria-label="演示日报"><span>DEMO / 演示日报</span><p>非实时赛事资讯 · 这是版式与功能预览，导入你的学院清单后即可生成专属日报。</p></aside>'
        brand_style += '.demo-banner{display:flex;align-items:center;gap:20px;padding:16px 20px;margin:0 0 24px;border:1px solid var(--accent-line);background:var(--accent-soft);color:var(--ink-soft)}.demo-banner>span{flex-shrink:0;color:var(--accent);font:650 11px/1.5 var(--sans);letter-spacing:.12em}.demo-banner p{margin:0;font-size:12px;line-height:1.8}@media(max-width:640px){.demo-banner{display:block}.demo-banner p{margin-top:6px}}'
    focus_panel = focus_panel_html(cards, year, now, window, variant_renderer)
    card_list = ''.join(card_html(card, year, detail_renderer, variant_renderer, now, window, min(position, 7) * 45) for position, card in enumerate(cards))
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#f6f4ee"><title>{esc(profile['report_title'])} · {report['date']}</title>{THEME_BOOT}<style>{CSS}{brand_style}</style></head>
    <body><div id="scroll-progress" aria-hidden="true"></div><div class="daily-shell" id="top" data-as-of="{now.timestamp():.3f}"><header class="masthead"><div class="utility-bar"><a class="brand" href="#top"><span class="brand-seal" aria-hidden="true">竞</span><span class="brand-copy"><b>{esc(profile['brand_name'])}</b><small>{esc(profile['english_title'])}</small></span></a><div class="utility-actions"><div class="theme-switch" role="group" aria-label="配色模式"><button type="button" data-theme-set="auto">自动</button><button type="button" data-theme-set="light">浅色</button><button type="button" data-theme-set="dark">深色</button></div><a class="export-button" href="{report['date']}.{'pdf' if report.get('pdf_available') else 'md'}" download>{icon('down')}{'下载 PDF' if report.get('pdf_available') else '导出日报'}</a></div></div><div class="nameplate"><p class="masthead-eyebrow">{esc(eyebrow)}</p><h1 aria-label="{esc(profile['report_title'])}">{masthead_title}</h1><p class="dateline"><time datetime="{report['date']}">{issue_date}</time><span class="dateline-sep">·</span><span>{weekday}</span><span class="dateline-sep">·</span><span>信息截至 {stamp}（北京时间）</span></p></div><p class="issue-meta"><span><b data-countup="{len(cards)}">{len(cards)}</b> 项赛事</span><span class="meta-sep">／</span><span><b data-countup="{records}">{records}</b> 条赛项记录</span><span class="meta-sep">／</span><span>已检查 {covered} / {catalog_records} 条清单记录{esc(quality_note)}</span><span class="meta-sep">／</span><span>截止提醒窗口 {window} 天</span></p></header>
    <main>{demo_banner}<p id="daily-status" class="daily-status" role="status" hidden></p>{focus_panel}<section class="section-nav" aria-label="日报栏目"><nav class="section-tabs">{navigation}</nav><p class="section-help">栏目可重叠，数量按赛事去重；“正在进行”包含报名与竞赛阶段。临近截止范围为 {window} 天。</p></section>
    <div class="filters"><label class="search">{icon('search')}<input id="search" type="search" placeholder="搜索赛事、赛项、材料或要求" aria-label="搜索赛事、赛项、材料或要求"></label><div class="filter-options"><label class="open-toggle"><input id="open-only" type="checkbox"><span class="toggle-track" aria-hidden="true"></span>仅可报名</label><label class="select-field"><span>参赛形式</span><select id="mode-filter"><option value="all">不限形式</option><option value="online">线上（含混合）</option><option value="offline">线下（含混合）</option><option value="hybrid">线上 + 线下</option></select></label><label class="select-field"><span>学院分级</span><select id="grade-filter"><option value="all">全部等级</option>{grade_options}</select></label></div></div>
    <div id="active-filters" class="active-filters" role="group" aria-label="已启用的筛选条件" hidden></div><section class="discovery" data-view="list" aria-labelledby="section-title"><div class="list-heading"><h2 id="section-title">全部赛事</h2><div class="results-meta"><span id="result-count" role="status" aria-live="polite">截止优先，其次赛程</span><div class="view-toggle" role="group" aria-label="阅读视图"><button type="button" data-view="list" class="active" aria-pressed="true">{icon('list')}<span>列表</span></button><button type="button" data-view="timeline" aria-pressed="false">{icon('timeline')}<span>时间线</span></button></div><button id="reset-filters" hidden>清除条件 ×</button></div></div><div class="list-column-labels" aria-hidden="true"><span>赛事 / 学院分级</span><span>对应赛项 · 资格与提交内容</span><span>关键日期 · 北京时间</span></div><div class="card-list">{card_list}</div><section id="timeline-view" class="timeline-view" hidden aria-label="按日期排列的关键节点时间线"></section><div id="empty-state" hidden><span class="empty-icon">{icon('search')}</span><h3>没有符合条件的赛事</h3><p>可以换个关键词，或重置筛选。</p><button id="empty-reset">查看全部赛事{icon('arrow')}</button></div></section>
    <footer class="page-footer"><span>{esc(profile['footer_text'] or profile['brand_name'])} · 每日竞赛情报机 V7 生成</span><span>卡片与徽章按 {issue_date} 日报时点计算；焦点倒计时按阅读时刻实时计算 · 北京时间</span><span>信息截至 {stamp}{audit_stamp}</span><span class="kbd-hint">快捷键 <kbd>/</kbd> 搜索 · <kbd>T</kbd> 切换视图 · <kbd>D</kbd> 切换配色</span><a href="{report['date']}.json">结构化数据与检索记录{icon('external')}</a></footer></main></div>
    <dialog id="detail-dialog" aria-labelledby="detail-title"><div class="drawer-header"><div><span class="drawer-eyebrow">参赛细则 / 官方来源</span><h2 id="detail-title">赛事细则</h2><p>按当前筛选展示匹配赛项，日期均为北京时间。</p></div><button id="close-detail" class="icon-button" autofocus aria-label="关闭赛事细则">{icon('close')}</button></div><div id="detail-body" class="drawer-body"></div></dialog><script>{SCRIPT}</script></body></html>'''


SCRIPT = r"""
(() => {
  const dailyStatus=document.querySelector('#daily-status');
  if(dailyStatus&&typeof fetch==='function'){
    fetch('status.json',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(data=>{
      if(!data)return;
      const text=data.status==='running'?'今日日报正在采集，完成后将自动发布。':data.status==='ready'?'今日日报已生成，08:00 发布。':data.status==='failed'?'本轮更新未完成，当前展示 '+(data.report_date||'最近一次')+' 的成功日报。':'';
      dailyStatus.textContent=text;dailyStatus.hidden=!text;
    }).catch(()=>{});
  }
  document.documentElement.dataset.reveal = 'on';
  const cards = [...document.querySelectorAll('.contest-card')];
  const tabs = [...document.querySelectorAll('.tab')];
  const search = document.querySelector('#search');
  const openOnly = document.querySelector('#open-only');
  const mode = document.querySelector('#mode-filter');
  const grade = document.querySelector('#grade-filter');
  const reset = document.querySelector('#reset-filters');
  const dialog = document.querySelector('#detail-dialog');
  const body = document.querySelector('#detail-body');
  const close = document.querySelector('#close-detail');
  const chips = document.querySelector('#active-filters');
  const discovery = document.querySelector('.discovery');
  const timelineView = document.querySelector('#timeline-view');
  const viewButtons = [...document.querySelectorAll('.view-toggle button')];
  const themeButtons = [...document.querySelectorAll('.theme-switch button')];
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  const shell = document.querySelector('.daily-shell');
  const asOfMs = (parseFloat(shell && shell.dataset.asOf) || 0) * 1000;
  const heroPanel = document.querySelector('.focus-panel');
  const heroBlock = document.querySelector('#focus-hero');
  const heroTitle = document.querySelector('#hero-title');
  const heroSub = document.querySelector('#hero-sub');
  const heroCountdown = document.querySelector('#hero-countdown');
  const heroExpired = document.querySelector('#hero-expired');
  const names = {all:'全部赛事', new_registration:'新开放报名', updates:'赛事重要更新', deadlines:'临近截止提醒', ongoing:'正在进行的比赛'};
  const kindLabels = {registration_end:'报名截止',submission_deadline:'作品截止',competition_start:'比赛开始',milestone:'赛程节点'};
  const urgencyOrder = {today:0, soon:1, week:2, '':3};
  const rank = node => !node ? 2 : ['registration_end','submission_deadline'].includes(node.kind) ? 0 : 1;
  const compare = (a,b) => rank(a)-rank(b) || (a?.at??Infinity)-(b?.at??Infinity) || 0;
  const urgencyOf = node => !node || !['registration_end','submission_deadline'].includes(node.kind) ? '' : node.days===0 ? 'today' : node.days<=3 ? 'soon' : node.urgent ? 'week' : '';
  const badgeText = node => node.days===0 ? '今日截止' : '剩 '+node.days+' 天';
  let section='all', view='list', opener=null, detailCard=null;
  let closeMotion=null;
  const cardMotions=new Map();
  const media=typeof window!=='undefined'&&typeof window.matchMedia==='function'?window.matchMedia('(prefers-reduced-motion: reduce)'):null;
  const scheme=typeof window!=='undefined'&&typeof window.matchMedia==='function'?window.matchMedia('(prefers-color-scheme: dark)'):null;
  const motionAllowed=()=>!!media&&!media.matches;
  const safeRun = task => { try { task(); } catch (error) { /* 单个动效子系统失败不拖垮整页 */ } };

  /* 配色：默认跟随系统；手动选择记入 localStorage，头部启动脚本已先行应用避免闪烁。 */
  function applyThemeMeta(){
    const choice=document.documentElement.dataset.theme||'auto';
    const dark=choice==='dark'||(choice!=='light'&&!!(scheme&&scheme.matches));
    if(themeMeta)themeMeta.setAttribute('content',dark?'#151310':'#f6f4ee');
  }
  function selectTheme(value){
    document.documentElement.dataset.theme=value;
    try{localStorage.setItem('cb-theme',value);}catch{}
    for(const button of themeButtons){
      const active=button.dataset.themeSet===value;
      button.classList.toggle('active',active);
      button.setAttribute('aria-pressed',String(active));
    }
    applyThemeMeta();
  }
  for(const button of themeButtons)button.addEventListener('click',()=>selectTheme(button.dataset.themeSet));
  selectTheme(document.documentElement.dataset.theme||'auto');
  if(scheme&&scheme.addEventListener)scheme.addEventListener('change',applyThemeMeta);

  /* 视图：列表为默认阅读轴；时间线按日期纵排关键节点，点击条目直达细则面板。 */
  function selectView(value){
    view=value;
    if(discovery)discovery.dataset.view=value;
    for(const button of viewButtons){
      const active=button.dataset.view===value;
      button.classList.toggle('active',active);
      button.setAttribute('aria-pressed',String(active));
    }
  }
  for(const button of viewButtons)button.addEventListener('click',()=>{if(view!==button.dataset.view){selectView(button.dataset.view);update();}});

  function animate(element,frames,options){
    if(!motionAllowed()||typeof element?.animate!=='function')return null;
    try{return element.animate(frames,{easing:'cubic-bezier(.2,.75,.2,1)',fill:'none',...options});}catch{return null;}
  }
  function captureCards(){
    const boxes=new Map();
    if(motionAllowed())for(const card of cards){
      if(!card.hidden&&typeof card.getBoundingClientRect==='function')boxes.set(card,card.getBoundingClientRect());
    }
    return boxes;
  }
  function animateCards(before,changed){
    const viewport=typeof window!=='undefined'?window.innerHeight||1000:1000;
    for(const animation of cardMotions.values())animation.cancel();cardMotions.clear();
    if(!motionAllowed())return;
    const targets=[];
    for(const card of cards){
      if(card.hidden||typeof card.getBoundingClientRect!=='function')continue;
      const next=card.getBoundingClientRect();
      if(!next.width||next.bottom<0||next.top>viewport+40)continue;
      targets.push({card,next});
    }
    for(const {card,next} of targets){
      const previous=before.get(card);
      const dx=previous?previous.left-next.left:0,dy=previous?previous.top-next.top:8;
      if(previous&&Math.abs(dx)<1&&Math.abs(dy)<1&&!changed.has(card))continue;
      const far=Math.abs(dy)>120||Math.abs(dx)>120;
      const animation=animate(card,[{transform:`translate(${far?0:dx}px, ${far?8:dy}px)`,opacity:previous&&!far ? 0.75 : 0},{transform:'translate(0, 0)',opacity:1}],{duration:240});
      if(animation){
        cardMotions.set(card,animation);
        const done=()=>{if(cardMotions.get(card)===animation)cardMotions.delete(card);};
        animation.finished?.then(done,done);
      }
    }
  }
  function selectSection(value){
    section=value;
    for(const tab of tabs){tab.classList.toggle('active',tab.dataset.section===section);tab.setAttribute('aria-pressed',String(tab.dataset.section===section));}
  }
  function renderChips(){
    if(!chips||typeof document.createElement!=='function')return;
    const specs=[];
    if(section!=='all')specs.push(['section',names[section]]);
    if(search.value.trim())specs.push(['search','关键词：'+search.value.trim()]);
    if(openOnly.checked)specs.push(['open','仅可报名']);
    if(mode.value!=='all')specs.push(['mode','形式：'+({online:'线上（含混合）',offline:'线下（含混合）',hybrid:'线上 + 线下'}[mode.value])]);
    if(grade&&grade.value!=='all')specs.push(['grade','学院：'+grade.value.replace('类',' 类')]);
    const buttons=specs.map(([key,label])=>{
      const button=document.createElement('button');button.type='button';button.classList.add('filter-chip');button.dataset.filter=key;
      button.setAttribute('aria-label','移除条件：'+label);button.setAttribute('title',label);
      const text=document.createElement('span');text.textContent=label;
      const cross=document.createElement('span');cross.classList.add('chip-close');cross.textContent='×';cross.setAttribute('aria-hidden','true');button.append(text,cross);
      button.addEventListener('click',()=>{
        let target=search;
        if(key==='section'){selectSection('all');target=tabs.find(tab=>tab.dataset.section==='all')||search;}
        if(key==='search')search.value='';
        if(key==='open'){openOnly.checked=false;target=openOnly;}
        if(key==='mode'){mode.value='all';target=mode;}
        if(key==='grade'){grade.value='all';target=grade;}
        update();target.focus();
      });return button;
    });
    chips.replaceChildren(...buttons);chips.hidden=!buttons.length;
  }
  function renderTimeline(entries){
    if(!timelineView||typeof document.createElement!=='function')return;
    const groups=new Map();
    const ordered=[...entries].sort((a,b)=>a.node.at-b.node.at||a.contest.localeCompare(b.contest,'zh')||a.track.localeCompare(b.track,'zh'));
    for(const entry of ordered){
      const node=entry.node;
      if(!groups.has(node.date_main))groups.set(node.date_main,{weekday:node.weekday||'',urgency:'',entries:[]});
      const group=groups.get(node.date_main);
      group.entries.push(entry);
      const urgency=urgencyOf(node);
      if(urgencyOrder[urgency]<urgencyOrder[group.urgency])group.urgency=urgency;
    }
    const fragment=document.createDocumentFragment();
    for(const [label,group] of groups){
      const day=document.createElement('div');
      day.className='timeline-day';
      day.dataset.date=label;
      if(group.urgency)day.dataset.urgency=group.urgency;
      const rail=document.createElement('div');
      rail.className='timeline-rail';
      const time=document.createElement('time');
      time.textContent=label;
      rail.append(time);
      if(group.weekday){
        const weekday=document.createElement('span');
        weekday.className='rail-weekday';
        weekday.textContent=group.weekday;
        rail.append(weekday);
      }
      if(group.urgency){
        const badge=document.createElement('span');
        badge.className='timeline-badge '+group.urgency;
        badge.textContent=group.urgency==='today'?'今日截止':'临近截止';
        rail.append(badge);
      }
      const list=document.createElement('div');
      list.className='timeline-entries';
      for(const entry of group.entries){
        const node=entry.node;
        const item=document.createElement('button');
        item.type='button';
        item.className='timeline-entry';
        item.dataset.kind=node.kind;
        const kind=document.createElement('span');
        kind.className='entry-kind';
        kind.textContent=node.kind_label||kindLabels[node.kind]||'赛程节点';
        const main=document.createElement('span');
        main.className='entry-main';
        const contest=document.createElement('span');
        contest.className='entry-contest';
        contest.textContent=entry.contest;
        main.append(contest);
        if(entry.track){
          const track=document.createElement('span');
          track.className='entry-track';
          track.textContent='赛项 · '+entry.track;
          main.append(track);
        }
        const tail=document.createElement('span');
        tail.className='entry-tail';
        if(node.clock){
          const clock=document.createElement('span');
          clock.className='entry-clock';
          clock.textContent=node.clock;
          tail.append(clock);
        }
        const urgency=urgencyOf(node);
        if(urgency){
          const badge=document.createElement('span');
          badge.className='action-badge '+urgency;
          badge.textContent=badgeText(node);
          tail.append(badge);
        } else if(node.relative){
          const relative=document.createElement('span');
          relative.className='entry-relative';
          relative.textContent=node.relative;
          tail.append(relative);
        }
        item.append(kind,main,tail);
        item.addEventListener('click',()=>{openDetails(entry.card,item);});
        list.append(item);
      }
      day.append(rail,list);
      fragment.append(day);
    }
    timelineView.replaceChildren(fragment);
  }

  /* 今日焦点：全局最紧迫节点的实时倒计时，随筛选结果切换；过期即明示，不装作还在倒计时。 */
  let heroTarget=null, heroTimer=null;
  function heroFromCards(){
    for(const card of document.querySelectorAll('.card-list .contest-card')){
      if(card.hidden)continue;
      const variants=JSON.parse(card.dataset.variants||'[]');
      const featured=variants.find(variant=>variant.key===card.dataset.featured);
      if(featured&&featured.node)return{card,node:featured.node};
    }
    return{card:null,node:null};
  }
  function setCountdownCell(unit,value){
    if(!heroCountdown)return;
    const cell=heroCountdown.querySelector('[data-unit="'+unit+'"]');
    if(!cell)return;
    const text=String(value).padStart(2,'0');
    if(cell.textContent===text)return;
    cell.textContent=text;
    if(motionAllowed()&&typeof cell.animate==='function'){
      try{cell.animate([{transform:'translateY(-55%)',opacity:.15},{transform:'none',opacity:1}],{duration:260,easing:'cubic-bezier(.2,.75,.2,1)'});}catch{}
    }
  }
  function stopTicker(){if(heroTimer){clearInterval(heroTimer);heroTimer=null;}}
  function tickHero(){
    if(heroTarget==null||!heroCountdown||!heroExpired)return;
    if(Date.now()>=heroTarget){
      if(!heroExpired.hidden)return;
      heroCountdown.hidden=true;heroExpired.hidden=false;stopTicker();
      return;
    }
    let rest=Math.max(0,heroTarget-Math.max(Date.now(),asOfMs||Date.now()));
    const days=Math.floor(rest/86400000);rest-=days*86400000;
    const hours=Math.floor(rest/3600000);rest-=hours*3600000;
    const minutes=Math.floor(rest/60000);rest-=minutes*60000;
    const seconds=Math.floor(rest/1000);
    setCountdownCell('days',days);setCountdownCell('hours',hours);setCountdownCell('minutes',minutes);setCountdownCell('seconds',seconds);
  }
  function startTicker(){
    stopTicker();
    tickHero();
    if(heroTarget!=null&&heroCountdown&&!heroCountdown.hidden&&Date.now()<heroTarget)heroTimer=setInterval(()=>{if(!document.hidden)tickHero();},1000);
  }
  function renderHero(pick){
    if(!heroPanel||!heroBlock)return;
    if(!pick.card||!pick.node){heroBlock.hidden=true;heroTarget=null;stopTicker();return;}
    heroBlock.hidden=false;
    if(pick.node.urgency)heroPanel.dataset.urgency=pick.node.urgency;else delete heroPanel.dataset.urgency;
    if(heroTitle){heroTitle.textContent=pick.card.dataset.name;heroTitle.dataset.card=pick.card.id;}
    if(heroSub){
      const parts=[pick.node.track,pick.node.kind_label].filter(Boolean);
      if(pick.node.label&&![pick.node.kind_label,'作品提交','作品截止'].includes(pick.node.label))parts.push(pick.node.label);
      heroSub.textContent=parts.join(' · ');
    }
    const ring=heroPanel.querySelector('.hero-ring');
    if(ring){
      if(pick.node.urgent&&pick.node.window){
        ring.hidden=false;
        const value=ring.querySelector('.ring-value');
        if(value){
          const full=parseFloat(value.dataset.full)||326.7;
          const fraction=Math.max(0,Math.min(1,(pick.node.window-pick.node.days)/pick.node.window));
          value.style.strokeDashoffset=(full*(1-fraction)).toFixed(1);
        }
        const days=ring.querySelector('.ring-center b');
        if(days)days.textContent=String(pick.node.days);
      } else ring.hidden=true;
    }
    if(heroCountdown&&heroExpired){heroCountdown.hidden=false;heroExpired.hidden=true;}
    heroTarget=pick.node.at*1000;
    startTicker();
  }
  function primeRing(){
    const ring=document.querySelector('.focus-panel .ring-value');
    if(!ring||!motionAllowed())return;
    const finalValue=ring.style.strokeDashoffset;
    if(!finalValue)return;
    ring.style.transition='none';
    ring.style.strokeDashoffset=ring.dataset.full||'326.7';
    requestAnimationFrame(()=>requestAnimationFrame(()=>{
      ring.style.transition='';
      ring.style.strokeDashoffset=finalValue;
    }));
  }

  function update() {
    const before=captureCards(),changed=new Set();
    const term=search.value.trim().toLocaleLowerCase();
    const filtered=section!=='all'||!!term||openOnly.checked||mode.value!=='all'||(grade&&grade.value!=='all');
    const matches=v => (section==='all'||v.sections.includes(section)) && (!term||v.search.includes(term)) && (!openOnly.checked||v.open) && (mode.value==='all'||v.modes.includes(mode.value)||(mode.value!=='hybrid'&&v.modes.includes('hybrid'))) && (!grade||grade.value==='all'||(v.levels||[]).includes(grade.value));
    let count=0, records=0;
    const nodes=new Map();
    const timelineEntries=[];
    for(const card of cards){
      const variants=JSON.parse(card.dataset.variants||'[]');
      const selected=variants.filter(matches);
      const featured=[...selected].sort((a,b)=>compare(a.node,b.node))[0];
      const node=featured?.node;
      if(card.dataset.featured!==(featured?.key||''))changed.add(card);
      card.dataset.featured=featured?.key||'';
      nodes.set(card,node);
      card.hidden=!selected.length;
      if(!card.hidden){
        count++;records+=selected.length;
        for(const variant of selected)if(variant.node)timelineEntries.push({node:variant.node,contest:card.dataset.name,track:variant.label,card});
      }
      card.dataset.urgent=String(!!node?.urgent);
      card.dataset.urgency=urgencyOf(node);
      for(const row of card.querySelectorAll('.track-detail')) row.hidden=!matches(JSON.parse(row.dataset.variant));
      for(const row of card.querySelectorAll('.track-brief')) row.hidden=!featured||row.dataset.key!==featured.key;
      const trackCount=card.querySelector('.track-count');
      if(trackCount)trackCount.textContent=selected.length===variants.length?'共 '+variants.length+' 条赛项记录':'匹配 '+selected.length+' / '+variants.length+' 条赛项记录';
      const state=card.querySelector('.state-tag');
      if(state){
        const isOpen=selected.some(v=>v.open), isActive=selected.some(v=>v.status==='in_progress'), multiple=selected.length>1;
        const labels={upcoming:'赛程预告',registration_closed:'报名已截止',closed:'本阶段结束',canceled:'已取消',postponed:'已延期 · 报名暂停'};
        const other=selected.map(v=>labels[v.status]).find(Boolean)||'';
        const label=isOpen?(multiple?'含可报名赛项':'报名中'):isActive?(multiple?'含进行中赛项':'比赛进行中'):multiple&&other?'含'+other+'赛项':other;
        state.hidden=!label;
        state.querySelector('.state-label').textContent=label;
        state.classList.toggle('competing',!isOpen&&isActive);
        state.classList.toggle('upcoming',!isOpen&&!isActive);
      }
      const modeTag=card.querySelector('.mode-tag, .badge.mode');
      if(modeTag){
        const modes=[...new Set(selected.flatMap(v=>v.modes))];
        const labels={online:'线上',offline:'线下',hybrid:'线上 + 线下'};
        modeTag.hidden=!modes.length;
        modeTag.textContent=modes.length>1?'线上 / 线下（分赛项）':modes.length?(selected.length>1?'含'+labels[modes[0]]+'赛项':labels[modes[0]]):'';
      }
      const action=card.querySelector('.action-node');
      if(action){
        action.hidden=!node;
        if(node){
          action.dataset.kind=node.kind;
          const urgency=urgencyOf(node);
          if(urgency)action.dataset.urgency=urgency;else delete action.dataset.urgency;
          const type=node.kind_label||kindLabels[node.kind]||'赛程节点';
          action.querySelector('.action-kind').textContent=type;
          action.querySelector('.action-date-value').textContent=node.date_main||node.value;
          const clock=action.querySelector('.action-clock');
          clock.hidden=!node.clock;clock.textContent=node.clock||'';
          const time=action.querySelector('.action-time');
          if(time)time.setAttribute('datetime',node.datetime||'');
          const progress=action.querySelector('.action-progress');
          if(progress){
            const fraction=urgency&&node.window?Math.max(0,Math.min(1,(node.window-node.days)/node.window)):0;
            progress.hidden=!urgency;
            const fill=progress.firstElementChild;
            if(fill)fill.style.width=(fraction*100).toFixed(0)+'%';
          }
          const badge=action.querySelector('.action-badge');
          if(badge){
            badge.hidden=!urgency;
            badge.className='action-badge'+(urgency?' '+urgency:'');
            badge.textContent=urgency?badgeText(node):'';
          }
          const relative=action.querySelector('.action-relative');
          if(relative){
            relative.hidden=!node.relative||!!urgency;
            relative.textContent=node.relative||(node.days===0?'今日':node.days+' 天后');
          }
          const note=action.querySelector('.action-date-label');
          note.hidden=!node.label||[type,'作品提交','作品截止'].includes(node.label);note.textContent=node.label||'';
          action.querySelector('.action-track').textContent='对应赛项 · '+(node.track||featured.label||'');
        }
      }
      const entry=card.querySelector('.entry-link');
      if(entry){
        const url=featured?.open&&/^https?:\/\//.test(featured.entry_url||'')?featured.entry_url:'';
        entry.hidden=!url;entry.setAttribute('href',url||'#');
      }
      const triggerLabel=card.querySelector('.detail-trigger-label');
      if(triggerLabel)triggerLabel.textContent=selected.length<variants.length?'查看匹配赛项与官方来源':'查看赛项与官方来源';
    }
    const list=document.querySelector('.card-list');
    let ordered=[...cards];
    if(list){ordered=[...cards].sort((a,b)=>compare(nodes.get(a),nodes.get(b))||cards.indexOf(a)-cards.indexOf(b));ordered.forEach(card=>list.appendChild(card));}
    document.querySelector('#result-count').textContent=filtered?'匹配 '+count+' 项赛事 / '+records+' 条赛项记录':'截止优先，其次赛程';
    document.querySelector('#empty-state').hidden=count!==0;
    if(reset)reset.hidden=!filtered;
    const title=document.querySelector('#section-title');
    if(title)title.textContent=names[section];
    renderChips();animateCards(before,changed);
    if(timelineView){timelineView.hidden=view!=='timeline';if(view==='timeline')renderTimeline(timelineEntries);}
    renderHero(heroFromCards());
    if(dialog&&dialog.open&&detailCard){
      if(detailCard.hidden)dialog.close();
      else{const clone=detailCard.querySelector('.rules-body').cloneNode(true);clone.classList.add('drawer-content');body.replaceChildren(clone);}
    }
  }
  for(const tab of tabs)tab.addEventListener('click',()=>{
    selectSection(tab.dataset.section);
    update();
  });
  search.addEventListener('input',update);
  openOnly.addEventListener('change',update);
  mode.addEventListener('change',update);
  if(grade)grade.addEventListener('change',update);
  function clear(){
    selectSection('all');search.value='';openOnly.checked=false;mode.value='all';if(grade)grade.value='all';
    update();search.focus();
  }
  if(reset)reset.addEventListener('click',clear);
  const emptyReset=document.querySelector('#empty-reset');
  if(emptyReset)emptyReset.addEventListener('click',clear);
  function openDetails(card,trigger){
    if(!dialog||typeof dialog.showModal!=='function'||!card||card.hidden)return false;
    const source=card.querySelector('.rules-body');if(!source)return false;
    clearCloseMotion();
    opener=trigger;detailCard=card;
    const clone=source.cloneNode(true);clone.classList.add('drawer-content');body.replaceChildren(clone);
    document.querySelector('#detail-title').textContent=card.dataset.name;
    if(!dialog.open)dialog.showModal();body.scrollTop=0;close.focus();return true;
  }
  for(const trigger of document.querySelectorAll('.detail-trigger'))trigger.addEventListener('click',event=>{if(openDetails(trigger.closest('.contest-card'),trigger))event.preventDefault();});
  function clearCloseMotion(){
    const animation=closeMotion;closeMotion=null;
    if(dialog)delete dialog.dataset.closing;
    animation?.cancel();
  }
  function requestClose(){
    if(!dialog?.open||closeMotion)return;
    const computed=typeof window!=='undefined'&&typeof window.getComputedStyle==='function'?window.getComputedStyle(dialog):null;
    const animation=animate(dialog,[{transform:computed?.transform||'translateX(0)',opacity:computed?.opacity||1},{transform:'translateX(32px)',opacity:0}],{duration:180});
    if(!animation?.finished){dialog.close();return;}
    closeMotion=animation;dialog.dataset.closing='true';
    const done=()=>{if(closeMotion!==animation)return;closeMotion=null;delete dialog.dataset.closing;if(dialog.open)dialog.close();};
    animation.finished.then(done,done);
  }
  if(dialog&&close){
    close.addEventListener('click',requestClose);
    dialog.addEventListener('click',event=>{if(event.target===dialog)requestClose();});
    dialog.addEventListener('cancel',event=>{event.preventDefault();requestClose();});
    dialog.addEventListener('close',()=>{
      clearCloseMotion();
      body.replaceChildren();detailCard=null;
      if(opener&&opener.isConnected&&!opener.closest('[hidden]')&&opener.getClientRects().length)opener.focus();else search.focus();opener=null;
    });
  }
  media?.addEventListener?.('change',()=>{
    if(!media.matches)return;
    for(const animation of cardMotions.values())animation.cancel();cardMotions.clear();
    const closing=!!closeMotion;clearCloseMotion();if(closing&&dialog?.open)dialog.close();
  });

  /* —— V7 动效子系统：彼此独立，单个失败不影响整页 —— */

  /* 进场编排：滚动到视口逐张揭示，一次性生效。 */
  safeRun(()=>{
    if('IntersectionObserver' in window&&motionAllowed()){
      const observer=new IntersectionObserver(entries=>{
        for(const entry of entries){
          if(entry.isIntersecting){entry.target.classList.add('revealed');observer.unobserve(entry.target);}
        }
      },{rootMargin:'0px 0px -5% 0px',threshold:.06});
      for(const card of cards)observer.observe(card);
    }else{
      for(const card of cards)card.classList.add('revealed');
    }
  });

  /* 指针微交互：卡片随指针轻微倾斜，光斑跟随；仅精确指针设备且未减少动效时启用。 */
  safeRun(()=>{
    const fine=typeof window!=='undefined'&&typeof window.matchMedia==='function'?window.matchMedia('(hover: hover) and (pointer: fine)'):null;
    if(!fine||!fine.matches||!motionAllowed())return;
    for(const card of cards){
      const inner=card.querySelector('.card-inner');
      if(!inner)continue;
      card.addEventListener('pointermove',event=>{
        if(card.hidden)return;
        const rect=card.getBoundingClientRect();
        if(!rect.width||!rect.height)return;
        const x=Math.min(1,Math.max(0,(event.clientX-rect.left)/rect.width));
        const y=Math.min(1,Math.max(0,(event.clientY-rect.top)/rect.height));
        card.style.setProperty('--rx',((0.5-y)*2.4).toFixed(2)+'deg');
        card.style.setProperty('--ry',((x-0.5)*2.4).toFixed(2)+'deg');
        card.style.setProperty('--mx',(x*100).toFixed(1)+'%');
        card.style.setProperty('--my',(y*100).toFixed(1)+'%');
      });
      card.addEventListener('pointerleave',()=>{
        card.style.setProperty('--rx','0deg');
        card.style.setProperty('--ry','0deg');
      });
    }
  });

  /* 刊头统计数字滚动累加。 */
  safeRun(()=>{
    if(!motionAllowed())return;
    for(const node of document.querySelectorAll('[data-countup]')){
      const target=parseInt(node.dataset.countup,10);
      if(!Number.isFinite(target)||target<=0)continue;
      const start=performance.now();
      const duration=700;
      node.textContent='0';
      const step=now=>{
        const progress=Math.min(1,(now-start)/duration);
        node.textContent=String(Math.round(target*(1-Math.pow(1-progress,3))));
        if(progress<1)requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }
  });

  /* 阅读进度条。 */
  safeRun(()=>{
    const bar=document.querySelector('#scroll-progress');
    if(!bar)return;
    const updateBar=()=>{
      const max=document.documentElement.scrollHeight-window.innerHeight;
      bar.style.transform='scaleX('+(max>0?Math.min(1,window.scrollY/max):0)+')';
    };
    document.addEventListener('scroll',updateBar,{passive:true});
    window.addEventListener('resize',updateBar);
    updateBar();
  });

  /* 快捷键：/ 搜索、T 切换视图、D 循环配色。 */
  safeRun(()=>{
    document.addEventListener('keydown',event=>{
      if(event.ctrlKey||event.metaKey||event.altKey||event.isComposing)return;
      if(dialog&&dialog.open)return;
      const target=event.target;
      if(target&&(['INPUT','SELECT','TEXTAREA'].includes(target.tagName)||target.isContentEditable||target.closest?.('[contenteditable]')))return;
      if(event.key==='/'){event.preventDefault();search.focus();}
      else if(event.key==='t'||event.key==='T'){selectView(view==='list'?'timeline':'list');update();}
      else if(event.key==='d'||event.key==='D'){
        const order=['auto','light','dark'];
        const current=document.documentElement.dataset.theme||'auto';
        selectTheme(order[(order.indexOf(current)+1)%order.length]||'auto');
      }
    });
  });

  /* 日历带：点击有节点的日期，切到时间线并滚动定位、闪烁提示。 */
  safeRun(()=>{
    for(const cell of document.querySelectorAll('.hz-cell')){
      if(cell.disabled)continue;
      cell.addEventListener('click',()=>{
        const dateKey=cell.dataset.date;
        if(!dateKey)return;
        if(view!=='timeline'){selectView('timeline');update();}
        requestAnimationFrame(()=>{
          if(!timelineView)return;
          const day=timelineView.querySelector('[data-date="'+dateKey+'"]');
          if(!day)return;
          day.scrollIntoView({behavior:motionAllowed()?'smooth':'auto',block:'start'});
          day.classList.remove('hz-flash');
          void day.offsetWidth;
          day.classList.add('hz-flash');
          setTimeout(()=>day.classList.remove('hz-flash'),1400);
        });
      });
    }
  });

  /* 今日焦点初始化：先描环，再对上首个可见卡片并启动实时倒计时。 */
  safeRun(()=>{
    if(!heroPanel)return;
    primeRing();
    renderHero(heroFromCards());
    document.addEventListener('visibilitychange',()=>{
      if(!document.hidden&&heroTarget!=null&&heroCountdown&&!heroCountdown.hidden)tickHero();
    });
  });
  if(heroTitle)heroTitle.addEventListener('click',()=>{
    const card=document.getElementById(heroTitle.dataset.card||'');
    if(card)openDetails(card,heroTitle);
  });

  animateCards(new Map(),new Set());
})();
"""


from .ui_styles import CSS
