from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
DATE_FIELDS = ("registration_start", "registration_end", "competition_start", "competition_end", "submission_deadline")
FACT_FIELDS = (*DATE_FIELDS, "participation_mode", "mode_details", "eligibility", "deliverables", "milestones", "entry_url", "fees", "current_phase", "phase_period", "track_requirements")
LIFECYCLES = {"active", "canceled", "postponed", "registration_closed"}
CONTROL_FIELDS = {"lifecycle", "cleared_fields", "track_id"}
CLEARABLE_FIELDS = frozenset((*FACT_FIELDS, "registration_open_confirmed", "status_as_of"))
STATUS_LABELS = {"registration_open": "报名中", "registration_closed": "报名已截止（赛程另见通知）", "in_progress": "比赛进行中", "upcoming": "已预告", "closed": "本阶段已结束", "canceled": "已取消", "postponed": "已延期（报名暂停）", "unknown": "待核实"}
MODE_LABELS = {"online": "线上", "offline": "线下", "hybrid": "线上+线下", "unknown": "官方暂未明确"}


def load_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_catalog(root: Path) -> list[dict]:
    from .workspace import confirmed_catalog
    source = confirmed_catalog(root)
    if source is None:
        source = load_json(root / "兰州大学信息学院学生学科竞赛分级列表.json")
    if not source:
        raise ValueError("缺少学院竞赛清单；请先 import-catalog，再核对并 confirm-catalog")
    grouped = {}
    for row in source["records"]:
        entry = grouped.setdefault(row["name"], {"name": row["name"], "ids": [], "levels": [], "conflict": False})
        entry["ids"].append(row["id"])
        if row["suggested_level"] not in entry["levels"]:
            entry["levels"].append(row["suggested_level"])
        entry["conflict"] |= row.get("requires_confirmation", False)
    return list(grouped.values())


def parse_at(value, end=False) -> datetime | None:
    """无时刻的截止日按北京时间当日结束；不补猜缺失的日期。"""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("日期必须是 ISO 字符串")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return datetime.combine(date.fromisoformat(value), time.max if end else time.min, CST)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=CST) if parsed.tzinfo is None else parsed.astimezone(CST)


def normalize_identity_text(value: str) -> str:
    """仅归一书写形式；保留数字、括号、范围和加号等有区分意义的字符。"""
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    value = value.translate(str.maketrans({"‐":"-", "‑":"-", "–":"-", "—":"-", "−":"-", "•":"·", "・":"·", "‧":"·", "、":",", "“":'"', "”":'"', "‘":"'", "’":"'"}))
    return re.sub(r"\s+", "", value).strip('"\'')


def edition_identity(event: dict) -> str:
    years = list(dict.fromkeys(re.findall(r"20\d{2}", event["edition"])))
    return "-".join(years[:2]) if years else normalize_identity_text(event["edition"])


def verified_controls(event: dict) -> set[str]:
    marker = event.get("verified_control_fields", [])
    return set(marker) & CONTROL_FIELDS if isinstance(marker, list) and all(isinstance(field, str) for field in marker) else set()


def effective_lifecycle(event: dict) -> str:
    return event.get("lifecycle", "active") if "lifecycle" in verified_controls(event) else "active"


def event_key(event: dict) -> str:
    # 标题/抓取时间变动不会导致同届同一赛道被当作新赛事。
    edition = edition_identity(event)
    track = "id=" + normalize_identity_text(event["track_id"]) if "track_id" in verified_controls(event) and event.get("track_id") else event.get("track", "主赛").strip()
    return "-".join(map(str, sorted(event["competition_ids"]))) + ":" + edition + ":" + track


def fact_value(value):
    """列表顺序和无意义空白变化不构成赛事事实更新。"""
    if isinstance(value, dict):
        return {key:fact_value(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return sorted((fact_value(item) for item in value), key=lambda item:json.dumps(item, ensure_ascii=False, sort_keys=True))
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return value


def factual_fingerprint(event: dict) -> str:
    body = {key:fact_value(event.get(key)) for key in FACT_FIELDS}
    body["lifecycle"] = effective_lifecycle(event)
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_event(raw: dict, known_ids: set[int], as_of: datetime) -> dict:
    event = dict(raw)
    if not isinstance(event.get("competition_ids"), list) or not event["competition_ids"]:
        raise ValueError("缺少赛事编号")
    if any(type(i) is not int or i not in known_ids for i in event["competition_ids"]):
        raise ValueError("未知赛事编号")
    for field in ("edition", "title"):
        if not isinstance(event.get(field), str) or not event[field].strip():
            raise ValueError(f"缺少 {field}")
    event.setdefault("track", "主赛")
    if not isinstance(event["track"], str) or not event["track"].strip():
        raise ValueError("track 必须是非空字符串")
    controls = verified_controls(event)
    event["verified_control_fields"] = sorted(controls)
    for field in CONTROL_FIELDS - controls:
        event.pop(field, None)
    if "lifecycle" in controls and event.get("lifecycle") not in LIFECYCLES:
        raise ValueError("未知赛事生命周期")
    if "track_id" in controls and (not isinstance(event.get("track_id"), str) or not event["track_id"].strip()):
        raise ValueError("track_id 必须是有官方证据的非空字符串")
    if "cleared_fields" in controls:
        fields = event.get("cleared_fields")
        if not isinstance(fields, list) or any(not isinstance(field, str) or field not in CLEARABLE_FIELDS for field in fields):
            raise ValueError("cleared_fields 包含不允许清空的字段")
        event["cleared_fields"] = list(dict.fromkeys(fields))
    if event.get("participation_mode", "unknown") not in MODE_LABELS:
        raise ValueError("未知参赛形式")
    event.setdefault("participation_mode", "unknown")
    for field in DATE_FIELDS:
        event.setdefault(field, None)
        parse_at(event[field])
    for start, end in (("registration_start", "registration_end"), ("competition_start", "competition_end")):
        if event[start] and event[end] and parse_at(event[start]) > parse_at(event[end], end=True):
            raise ValueError(f"日期顺序错误：{start} > {end}")
    if event.get('track_requirements') is None:
        event['track_requirements'] = []
    for field in ("eligibility", "deliverables", "milestones", "notes", "sources", "track_requirements"):
        if not isinstance(event.get(field, []), list):
            raise ValueError(f"{field} 必须是列表")
        event.setdefault(field, [])
    if not event["sources"]:
        raise ValueError("没有可追溯来源")
    for source in event["sources"]:
        if not re.match(r"^https?://", source.get("url", "")):
            raise ValueError("来源链接无效")
        published = parse_at(source.get("published_date"))
        if published and published > as_of:
            raise ValueError("来源发布时间晚于日报日期")
    for milestone in event["milestones"]:
        parse_at(milestone.get("date"))
    if event.get("phase_period"):
        phase = event["phase_period"]
        if not isinstance(phase, dict) or any(not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", phase.get(k, "")) for k in ("start", "end")) or phase["start"] > phase["end"]:
            raise ValueError("阶段月份范围无效")
    event.setdefault("mode_details", "")
    event.setdefault("fees", None)
    event.setdefault("entry_url", None)
    event.setdefault("verification", "partial")
    event["key"] = event_key(event)
    return event


def derive_status(event: dict, now: datetime) -> str:
    lifecycle = effective_lifecycle(event)
    if lifecycle in ("canceled", "postponed"):
        return lifecycle
    begin, end = (parse_at(event.get("competition_" + field), end=field == "end") for field in ("start", "end"))
    # 只有开始和结束都明确时，才把整个阶段称为“正在进行”。
    if begin and end and begin <= now <= end:
        return "in_progress"
    # 官方只给月份时保留月份精度；不伪造月初/月末为正式赛程日期。
    phase = event.get("phase_period") or {}
    month = now.strftime("%Y-%m")
    if (re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", phase.get("start", ""))
            and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", phase.get("end", ""))
            and phase["start"] <= month <= phase["end"]):
        return "in_progress"
    if lifecycle == "registration_closed":
        return "registration_closed"
    reg_begin = parse_at(event.get("registration_start"))
    reg_end = parse_at(event.get("registration_end"), end=True)
    if reg_begin and reg_end and reg_begin <= now <= reg_end:
        return "registration_open"
    if event.get("registration_open_confirmed") and event.get("status_as_of") == now.date().isoformat() and reg_end and now <= reg_end:
        return "registration_open"
    if (reg_begin and reg_begin > now) or (begin and begin > now):
        return "upcoming"
    if end and now > end:
        return "closed"
    if reg_end and now > reg_end:
        # 已截止报名并不证明比赛已经结束。
        return "registration_closed"
    return "unknown"


def upcoming_deadlines(event: dict, now: datetime, days=7) -> list[dict]:
    if effective_lifecycle(event) == "canceled":
        return []
    found = []
    for field, name in (("registration_end", event.get("registration_deadline_label", "报名截止")), ("submission_deadline", "材料/作品提交截止")):
        if field == "registration_end" and effective_lifecycle(event) in ("postponed", "registration_closed"):
            continue
        value = event.get(field)
        parsed = parse_at(value, end=True)
        if parsed and now <= parsed and 0 <= (parsed.date() - now.date()).days <= days:
            found.append({"name": name, "date": value, "days_left": (parsed.date() - now.date()).days})
    return found


def build_report(events: list[dict], coverage: list[dict], catalog: list[dict], as_of: datetime,
                 previous: dict | None, window=7, acquisition="manual_verified") -> dict:
    # 空对象也表示已有历史快照；只有 None 表示首次运行。
    bootstrap = previous is None
    older = (previous or {}).get("events", {})
    groups = {"new_registration": [], "updates": [], "deadlines": [], "ongoing": []}
    enriched = []
    for original in events:
        event = dict(original)
        event["status"] = derive_status(event, as_of)
        reg_start, reg_end = parse_at(event.get("registration_start")), parse_at(event.get("registration_end"), end=True)
        event["accepting_registration"] = bool(effective_lifecycle(event) == "active" and reg_end and as_of <= reg_end and ((reg_start and reg_start <= as_of) or (event.get("registration_open_confirmed") and event.get("status_as_of") == as_of.date().isoformat())))
        event["deadlines"] = upcoming_deadlines(event, as_of, window)
        matching = [item for item in catalog if set(item["ids"]) & set(event["competition_ids"])]
        event["catalog_names"] = [item["name"] for item in matching]
        event["levels"] = sorted({level for item in matching for level in item["levels"]})
        event["level_conflict"] = any(item["conflict"] for item in matching)
        event["name_mapping_unconfirmed"] = any("映射" in note or "认定" in note or "更名" in note for note in event.get("notes", []))
        prior = older.get(event["key"])
        event.pop("changed_fields", None)
        event["change"] = "stale" if event.get("stale") else "baseline" if bootstrap else ("first_seen" if not prior else "updated" if factual_fingerprint(event) != factual_fingerprint(prior) else "unchanged")
        # 首次发现一条旧通知，不等于今天新开放报名。
        reg_start = parse_at(event.get("registration_start"))
        if not event.get("stale") and event["accepting_registration"] and reg_start and reg_start.date() == as_of.date() and event["status"] in ("registration_open", "in_progress"):
            groups["new_registration"].append(event["key"])
        if prior and event["change"] == "updated" and not event.get("stale"):
            event["changed_fields"] = [field for field in FACT_FIELDS if fact_value(event.get(field)) != fact_value(prior.get(field))]
            if effective_lifecycle(event) != effective_lifecycle(prior):
                event["changed_fields"].append("lifecycle")
            if event["changed_fields"]:
                groups["updates"].append(event["key"])
        # 首日也能展示今天发布的官方通知，但不冒充历史差异。
        if not event.get("stale") and any(parse_at(s.get("published_date")) and parse_at(s.get("published_date")).date() == as_of.date() for s in event["sources"]):
            if event["key"] not in groups["updates"]:
                groups["updates"].append(event["key"])
            event["notes"] = list(dict.fromkeys([*event.get("notes", []), "包含今日发布的官方通知；此标记不表示已完成跨日差异比对。"] ))
        if event["deadlines"]:
            groups["deadlines"].append(event["key"])
        if event["status"] in ("in_progress", "registration_open"):
            groups["ongoing"].append(event["key"])
        enriched.append(event)
    statuses = {}
    for item in coverage:
        statuses[item["competition_id"]] = item
    covered = sum(item["result"] != "not_checked" for item in statuses.values())
    return {"schema_version": 1, "date": as_of.date().isoformat(), "as_of": as_of.isoformat(), "timezone": "Asia/Shanghai",
            "bootstrap": bootstrap, "acquisition": acquisition, "catalog_records": sum(len(c["ids"]) for c in catalog),
            "catalog_unique": len(catalog), "coverage_checked_records": covered, "deadline_window_days": window,
            "groups": groups, "events": enriched, "coverage": list(statuses.values())}
