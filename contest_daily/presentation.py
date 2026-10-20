"""将核验记录转换为面向参赛者的阅读视图，不补写未知事实。"""
from __future__ import annotations

import re
from datetime import datetime
from .core import parse_at, effective_lifecycle

SECTIONS = (("new_registration", "新开放报名"), ("updates", "赛事重要更新"), ("deadlines", "临近截止提醒"), ("ongoing", "正在进行的比赛"))
DISPLAY_NAMES = {1: "美国大学生数学建模竞赛 · MCM/ICM", 2: "中国国际大学生创新大赛", 4: "挑战杯 · 创业计划大赛", 5: "ICPC 国际大学生程序设计竞赛", 10: "外研社杯 · 外语能力大赛", 11: "全国大学生机器人大赛", 15: "中国机器人大赛", 17: "蓝桥杯", 21: "学创杯", 24: "华为 ICT 大赛", 29: "全国大学生创新年会", 32: "iCAN 大学生创新创业大赛", 36: "ISCC 信息安全与对抗技术竞赛", 37: "全国大学生数字媒体竞赛", 38: "AIC 人工智能算法精英大赛", 39: "全国大学生数学竞赛", 49: "全国 3D 数字化创新设计大赛", 52: "计算机能力与数字素养大赛 · 传智杯"}
MISSING = re.compile(r"官方暂未明确|尚未|未明确|未核实|未获得|待核实|待公布|未公布|未标明|本轮|本次通知未|进一步核对|见来源|见原文|未在.*(?:规定|明确|说明)|暂未|无法确认|未知|缺少可核对|仍待|待.*(?:核对|确认|通知)")
PROCESS = re.compile(r"首次|首日|基线|跨日|指纹|映射|原表名称|原清单|学院认定|认定映射|包含今日发布|仅检索|抓取|本轮|本次.*核验|缺少可核对|置空字段|证据校验")


def clean_fact(value):
    if not isinstance(value, str):
        return ""
    parts = []
    for part in re.split(r"[；;。\n]", value):
        part = part.strip(" ，,；;")
        if not part:
            continue
        # 同一句里“日期已知，具体时刻未核实”只移除后半句。
        chunks = re.split(r"[，,]", part) if MISSING.search(part) else [part]
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk or MISSING.search(chunk):
                continue
            if re.match(r"(?:具体|完整|相关|其他|材料具体).*(?:以|按|见|待|另|须.*核对)", chunk):
                continue
            parts.append(chunk)
    return "；".join(parts)


def facts(values):
    return list(dict.fromkeys(text for value in (values or []) if (text := clean_fact(value))))


def short_date(value, year):
    if not value:
        return ""
    try:
        parsed = parse_at(value)
    except (ValueError, TypeError):
        return ""
    prefix = f"{parsed.year}." if parsed.year != year else ""
    label = f"{prefix}{parsed.month:02d}.{parsed.day:02d}"
    if "T" in value:
        label += f" {parsed.hour:02d}:{parsed.minute:02d}"
        if parsed.second:
            label += f":{parsed.second:02d}"
    return label


def mode_label(event):
    labels = {"online": "线上", "offline": "线下", "hybrid": "线上 + 线下"}
    if event.get("participation_mode") in labels:
        return labels[event["participation_mode"]]
    modes = sorted({r.get('mode') for r in event.get('track_requirements', []) if r.get('mode') in labels})
    return "分赛项：" + ' / '.join(labels[m] for m in modes) if modes else ""


def track_name(event):
    track = re.sub(r"（映射待确认）|\(映射待确认\)", "", event.get("track", "主赛"))
    return "" if track in ("主赛", "主体赛事", "全国主赛", "现名赛事相关通知") else track


def status_label(event):
    state = event.get("status")
    if event.get("accepting_registration"):
        return "报名中 · 比赛进行中" if state == "in_progress" else "报名中"
    return {"in_progress": "比赛进行中", "upcoming": "赛程预告", "registration_closed": "报名已截止", "closed": "本阶段结束", "canceled":"已取消", "postponed":"已延期 · 报名暂停"}.get(state, "")


def next_node(event, now):
    lifecycle = effective_lifecycle(event)
    if lifecycle == 'canceled':
        return None
    candidates = []
    for field, label in (("registration_end", event.get("registration_deadline_label", "报名截止")), ("submission_deadline", "作品提交"), ("competition_start", "比赛开始")):
        if field == 'registration_end' and lifecycle in ('postponed', 'registration_closed'):
            continue
        value = event.get(field)
        point = parse_at(value, end=field != "competition_start")
        if point and point >= now:
            candidates.append((point, label, value, field))
    for milestone in event.get("milestones", []):
        value = milestone.get("date")
        point = parse_at(value, end=True)
        if point and point >= now:
            candidates.append((point, milestone["name"], value, "milestone"))
    return min(candidates, key=lambda item: item[0]) if candidates else None


def build_cards(report):
    now = parse_at(report["as_of"])
    grouped = {}
    memberships = {key: set(values) for key, values in report["groups"].items()}
    for raw in report["events"]:
        event = dict(raw)
        event["view_eligibility"] = facts(event.get("eligibility"))
        event["view_deliverables"] = facts(event.get("deliverables"))
        event["view_notes"] = [text for note in event.get("notes", []) if not PROCESS.search(note) and (text := clean_fact(note))]
        event["view_mode_details"] = clean_fact(event.get("mode_details"))
        event["view_mode"] = mode_label(event)
        event["view_track"] = track_name(event)
        event["view_status"] = status_label(event)
        event["view_sections"] = [key for key, values in memberships.items() if event["key"] in values]
        event["view_next"] = next_node(event, now)
        if not (event["view_next"] or event["view_eligibility"] or event["view_deliverables"] or event.get("current_phase") or event["view_mode"] or event["view_notes"] or event.get('status') in ('canceled','postponed')):
            continue
        ids = tuple(sorted(event["competition_ids"]))
        name = (event.get('catalog_names') or [event['title']])[0]
        if report.get('catalog_kind') == 'lzu_legacy':
            name = DISPLAY_NAMES.get(ids[0], name)
        group = grouped.setdefault(ids, {"ids": ids, "name": name, "events": [], "sections": set()})
        group["events"].append(event)
        group["sections"].update(event["view_sections"])
    cards = []
    for group in grouped.values():
        events = group["events"]
        group["sections"] = sorted(group["sections"])
        group["active"] = any(e.get("accepting_registration") or e.get("status") == "in_progress" for e in events)
        group["open"] = any(e.get("accepting_registration") for e in events)
        group["modes"] = sorted({e["participation_mode"] for e in events if e.get('participation_mode') in ('online','offline','hybrid')} | {r['mode'] for e in events for r in e.get('track_requirements', []) if r.get('mode') in ('online', 'offline', 'hybrid')})
        group["levels"] = sorted({level for e in events for level in e.get("levels", [])})
        group["conflict"] = any(e.get("level_conflict") for e in events)
        group["mapped"] = any(e.get("name_mapping_unconfirmed") for e in events)
        group["sources"] = list({source["url"]: source for e in events for source in e["sources"]}.values())
        group["next"] = min((e["view_next"] for e in events if e["view_next"]), default=None, key=lambda item: item[0])
        group["urgent"] = bool(group["next"] and group["next"][3] in ("registration_end", "submission_deadline") and (group["next"][0].date() - now.date()).days <= report.get("deadline_window_days", 7))
        group["key"] = "contest-" + "-".join(map(str, group["ids"]))
        events.sort(key=lambda e: (e["view_next"][0] if e["view_next"] else datetime.max.replace(tzinfo=now.tzinfo), e.get("track", "")))
        cards.append(group)
    future = datetime.max.replace(tzinfo=now.tzinfo)
    cards.sort(key=lambda c: (not c["urgent"], c["next"][0] if c["urgent"] else future, not c["open"], not c["active"], c["next"][0] if c["next"] else future, c["ids"]))
    return cards
