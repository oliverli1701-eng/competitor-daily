from __future__ import annotations

import copy
import html
import json
import re
import os
from pathlib import Path

from . import __version__
from .core import save_json
from .branding import institution_name, load_profile, normalize_profile
from .presentation import SECTIONS, build_cards, clean_fact, short_date


def esc(value):
    return html.escape(str(value or ""), quote=True)


def link(url, label, css=""):
    if not re.match(r"^https?://", url or ""):
        return ""
    return f'<a class="{css}" href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(label)}<span aria-hidden="true"> ↗</span></a>'


def event_markdown(event):
    lines = []
    if event.get("view_status"):
        lines.append("- 状态：" + event["view_status"])
    if event.get("view_mode") or event.get("view_mode_details"):
        lines.append("- 形式：" + " · ".join(filter(None, [event["view_mode"], event["view_mode_details"]])))
    if event.get("stale"):
        lines.append("- 上次核验：" + (event.get("verified_as_of") or "")[:16].replace("T", " ") + " · 本轮未重新取得")
    for field, name in (("registration_end", "报名截止"), ("submission_deadline", "作品提交截止")):
        if event.get(field):
            lines.append(f"- {event.get('registration_deadline_label', name) if field == 'registration_end' else name}：{event[field]}")
    if event.get("competition_start") or event.get("competition_end"):
        lines.append("- 比赛：" + " → ".join(filter(None, [event.get("competition_start"), event.get("competition_end")])))
    if event["view_eligibility"]:
        lines.append("- 参赛：" + "；".join(event["view_eligibility"]))
    if event["view_deliverables"]:
        lines.append("- 提交：" + "；".join(event["view_deliverables"]))
    if clean_fact(event.get("fees")):
        lines.append("- 费用：" + clean_fact(event["fees"]))
    if clean_fact(event.get("current_phase")):
        lines.append("- 阶段：" + clean_fact(event["current_phase"]))
    for note in event["view_notes"]:
        lines.append("- 提醒：" + note)
    if event.get("entry_url"):
        lines.append(f"- [报名 / 提交入口]({event['entry_url']})")
    return lines


def markdown(report):
    profile = normalize_profile(report.get('branding'))
    cards = build_cards(report)
    year = int(report["date"][:4])
    lines = [f"# {profile['report_title']} · {report['date']}", "", institution_name(profile), "", f"{len(cards)} 项赛事 · 按下一关键节点排序 · 信息截至 {report['as_of'][:16].replace('T', ' ')}（北京时间）", ""]
    if report.get('demo'):
        lines += ["> 演示日报 · 用于预览版式与功能，非实时赛事资讯；请导入自己的竞赛清单后重新采集。", ""]
    for key, title in SECTIONS:
        selected = [c for c in cards if key in c["sections"]]
        lines += [f"## {title} · {len(selected)} 项", ""]
        if not selected:
            lines += ["本期无新增条目。", ""]
            continue
        lines += ["| 赛事 | 下一节点 |", "| --- | --- |"]
        for card in selected:
            node = card["next"]
            value = f"{short_date(node[2], year)} {node[1]}" if node else " / ".join(dict.fromkeys(e["view_status"] for e in card["events"] if e["view_status"]))
            lines.append(f"| {card['name']} | {value} |")
        lines.append("")
    lines += ["## 参赛速查", ""]
    for card in cards:
        lines += [f"### {card['name']} · {' / '.join(card['levels'])}", ""]
        for event in card["events"]:
            if len(card["events"]) > 1:
                lines += [f"**{event['view_track'] or event['edition']}**", ""]
            lines += event_markdown(event) + [""]
        lines += ["来源：" + " · ".join(f"[{s.get('title') or '官方通知'}]({s['url']})" for s in card["sources"]), ""]
    lines += [f"[结构化数据与检索记录]({report['date']}.json)", ""]
    return "\n".join(lines)


def fact_line(label, values):
    if not values:
        return ""
    return f'<div class="fact"><dt>{label}</dt><dd>' + "；".join(esc(v) for v in values) + '</dd></div>'


def event_variant(event, name=''):
    modes = {event['participation_mode']} - {'unknown'} | {r['mode'] for r in event.get('track_requirements', []) if r.get('mode') in ('online','offline','hybrid')}
    searchable = [name, event.get('title', ''), event.get('edition', ''), event['view_track'], *event['view_eligibility'], *event['view_deliverables'], *event['view_notes'], *(source.get('title', '') for source in event.get('sources', []))]
    return {'key':event.get('key', ''), 'label':event['view_track'] or event.get('edition', ''), 'levels':event.get('levels', []), 'sections':event['view_sections'], 'open':bool(event.get('accepting_registration')), 'modes':sorted(modes), 'search':(' '.join(searchable)).lower()}


def event_detail(event, year, card_name=''):
    rows = [fact_line("参赛要求", event["view_eligibility"]), fact_line("提交材料", event["view_deliverables"])]
    if event.get('stale'):
        rows.append(fact_line("上次核验", [(event.get('verified_as_of') or '')[:16].replace('T',' ') + ' · 本轮未重新取得，信息可能已变化']))
    if event.get("view_mode_details"):
        rows.append(fact_line("比赛形式", [event["view_mode_details"]]))
    for field, label in (("registration_end", event.get("registration_deadline_label", "报名截止")), ("submission_deadline", "作品截止")):
        if event.get(field):
            rows.append(fact_line(label, [short_date(event[field], year)]))
    dates = [short_date(event.get(field), year) for field in ("competition_start", "competition_end") if event.get(field)]
    if dates:
        rows.append(fact_line("比赛日期", [" → ".join(dates)]))
    if clean_fact(event.get("current_phase")):
        rows.append(fact_line("当前阶段", [clean_fact(event["current_phase"])]))
    if clean_fact(event.get("fees")):
        rows.append(fact_line("参赛费用", [clean_fact(event["fees"])]))
    rows.append(fact_line("赛程节点", [f"{m['name']} {short_date(m['date'], year)}" for m in event.get("milestones", []) if m.get("date")]))
    rows.append(fact_line("其他要求", event["view_notes"]))
    requirements = event.get("track_requirements", [])
    if requirements:
        rows.append('<div class="subtopics">' + "".join('<p><b>' + esc(r["name"]) + '</b> ' + esc("；".join(filter(None, [{"online":"线上", "offline":"线下", "hybrid":"线上 + 线下"}.get(r.get("mode")), clean_fact(r.get('mode_details')), *r.get("eligibility", []), *r.get("deliverables", [])]))) + '</p>' for r in requirements) + '</div>')
    sources = "".join(link(s["url"], s.get("title") or "赛事通知") for s in event["sources"])
    title = event["view_track"] or event.get("edition", "参赛细则")
    return f'<section class="track-detail" data-variant="{esc(json.dumps(event_variant(event,card_name),ensure_ascii=False))}" data-sections="{esc(" ".join(event["view_sections"]))}"><h4>{esc(title)}</h4><dl>{"".join(rows)}</dl><div class="track-links">{link(event.get("entry_url"), "报名 / 提交入口")}<span class="source-links">{sources}</span></div></section>'


from .product_ui import CSS, SCRIPT, card_html as product_card_html, render_html as product_render_html


def card_html(card, year):
    return product_card_html(card, year, event_detail, event_variant)


def to_html(markdown_text, report):
    return product_render_html(report, event_detail, event_variant)


def write_report(root: Path, report):
    report=dict(report)
    report['branding'] = normalize_profile(report['branding']) if 'branding' in report else load_profile(root)
    folder = root / "reports" / report["date"][:4]
    folder.mkdir(parents=True, exist_ok=True)
    stem = folder / report["date"]
    from .pdf_export import write_pdf
    font=Path(os.environ.get('REPORT_PDF_FONT',str(Path(__file__).resolve().parent.parent/'assets/ReportSans.ttc')))
    if os.environ.get('REPORT_PDF_EXPORT')=='1' and not font.is_file():
        raise ValueError('必须生成 PDF，但中文字体缺失，停止发布')
    report['pdf_available']=os.environ.get('REPORT_PDF_EXPORT','auto')!='0' and font.is_file()
    if report['pdf_available']:
        write_pdf(report,stem.with_suffix('.pdf'))
    text = markdown(report)
    stem.with_suffix(".md").write_text(text, encoding="utf-8")
    stem.with_suffix(".html").write_text(to_html(text, report), encoding="utf-8")
    public = copy.deepcopy(report)
    public['presentation_version'] = __version__
    for event in public["events"]:
        event.pop("evidence", None)
    save_json(stem.with_suffix(".json"), public)
    return stem
