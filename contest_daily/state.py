"""按保守身份匹配合并官方局部公告；缺省、撤销和生命周期具有不同语义。"""
from __future__ import annotations

import copy

from .core import (CLEARABLE_FIELDS, DATE_FIELDS, FACT_FIELDS, effective_lifecycle,
                   edition_identity, event_key, factual_fingerprint,
                   normalize_identity_text, verified_controls)
from .core import parse_at


EMPTY = (None, "", [], "unknown")
ACTION_FIELDS = (*DATE_FIELDS, "milestones", "phase_period", "current_phase", "entry_url", "registration_open_confirmed", "status_as_of")
REGISTRATION_FIELDS = ("registration_start", "registration_end", "entry_url", "registration_open_confirmed", "status_as_of")


def merge_catalog_events(fresh, previous, as_of, catalog, aliases, coverage):
    """单个赛事身份冲突只隔离该赛事，其他赛事仍经过原有发布门槛。"""
    merged, accepted, conflicts = [], [], []
    coverage = copy.deepcopy(coverage)
    for competition in catalog:
        ids=set(competition['ids'])
        current=[e for e in fresh if ids.intersection(e['competition_ids'])]
        history={k:e for k,e in (previous or {}).get('events',{}).items() if ids.intersection(e['competition_ids'])}
        prior={'events':history} if previous is not None else None
        try:
            records=merge_events(current,prior,as_of,aliases)
        except ValueError as exc:
            conflicts.append({'competition_ids':competition['ids'],'name':competition['name'],'error':str(exc)})
            records=merge_events([],prior,as_of,aliases)
            for row in coverage:
                if row['competition_id'] in ids:
                    row.update(result='failed',failed_stage='identity',note='赛项身份存在冲突，本轮隔离并沿用上次核验信息：'+str(exc))
        else:
            accepted.extend(current)
        merged.extend(records)
    return merged, accepted, conflicts, coverage


def _scope(event, aliases=None):
    identifiers = tuple(sorted(event["competition_ids"]))
    edition = edition_identity(event)
    configurations = (aliases or {}).get("edition_aliases", {}) if isinstance(aliases, dict) else {}
    mapping = configurations.get("-".join(map(str, identifiers)), {}) if isinstance(configurations, dict) else {}
    if isinstance(mapping, dict):
        normalized = {normalize_identity_text(key):edition_identity({"edition":value}) for key, value in mapping.items() if isinstance(key, str) and isinstance(value, str)}
        seen = set()
        while edition in normalized and edition not in seen:
            seen.add(edition)
            edition = normalized[edition]
    return (identifiers, edition)


def _track_id(event):
    return normalize_identity_text(event["track_id"]) if "track_id" in verified_controls(event) and event.get("track_id") else ""


def _names(event):
    return {normalize_identity_text(name) for name in [event.get("track", "主赛"), *event.get("track_aliases", [])] if isinstance(name, str)}


def _aliases(event, aliases):
    """支持显式完整key映射、track标签映射及按竞赛编号分组的标签映射。"""
    if not isinstance(aliases, dict):
        return set()
    mappings = dict(aliases)
    scoped = aliases.get("-".join(map(str, sorted(event["competition_ids"]))))
    if isinstance(scoped, dict):
        mappings.update(scoped)
    found = set()
    for start in (event["key"], event.get("track", "主赛")):
        value = start
        seen = set()
        while value not in seen and isinstance(mappings.get(value), str):
            seen.add(value)
            value = mappings[value]
            found.add(value)
    return found


def _resolve(event, history, aliases):
    scope, official_id = _scope(event, aliases), _track_id(event)
    candidates = [(key, prior) for key, prior in history.items() if _scope(prior, aliases) == scope]
    def compatible(prior):
        return not (official_id and _track_id(prior) and official_id != _track_id(prior))
    if official_id:
        matches = [key for key, prior in candidates if _track_id(prior) == official_id]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError("同一官方 track_id 对应多个历史赛项，请先消歧")
    explicit = _aliases(event, aliases)
    explicit_matches = [key for key, prior in candidates if compatible(prior) and (key in explicit or set(prior.get("identity_aliases", [])).intersection(explicit))]
    if len(explicit_matches) == 1:
        return explicit_matches[0]
    if len(explicit_matches) > 1:
        raise ValueError("显式 aliases 对应多个历史赛项，请先消歧")
    if event["key"] in history and _scope(history[event["key"]], aliases) == scope and compatible(history[event["key"]]):
        return event["key"]
    names = _names(event) | {normalize_identity_text(value) for value in explicit if ":" not in value}
    keys = {event["key"], *explicit}
    matches = []
    for key, prior in candidates:
        if not compatible(prior):
            continue
        if key in keys or keys.intersection(prior.get("identity_aliases", [])) or names.intersection(_names(prior)):
            matches.append(key)
    if len(matches) > 1:
        raise ValueError("赛项身份匹配存在歧义，请在 aliases 中明确对应历史 key")
    return matches[0] if matches else None


def _empty(field):
    if field in ("eligibility", "deliverables", "milestones", "track_requirements"):
        return []
    if field == "participation_mode":
        return "unknown"
    if field == "registration_open_confirmed":
        return False
    return None


def _sources(prior, current):
    sources = {source["url"]:copy.deepcopy(source) for source in prior.get("sources", [])}
    for source in current.get("sources", []):
        sources[source["url"]] = {**sources.get(source["url"], {}), **copy.deepcopy(source)}
    return list(sources.values())


def _milestones(prior, current):
    values = {normalize_identity_text(item.get("name", "")):copy.deepcopy(item) for item in prior}
    for item in current:
        values[normalize_identity_text(item.get("name", ""))] = copy.deepcopy(item)
    return list(values.values())


def merge_events(fresh, previous, as_of, aliases=None):
    """返回合并记录；aliases 只作人工明确映射，来源重叠不参与身份判断。

    lifecycle、cleared_fields、track_id 仅信任 validate_evidence 生成的
    verified_control_fields 标记。省略生命周期会保留历史已核验的取消/暂停。
    """
    merged = {}
    for key, original in (previous or {}).get("events", {}).items():
        prior = copy.deepcopy(original)
        prior["key"] = key
        prior["stale"] = True
        prior.setdefault("stale_since", as_of.isoformat())
        merged[key] = prior
    seen, raw_to_stable = {}, {}
    def notice_order(event):
        dates=[parse_at(source.get('published_date')) for source in event.get('sources',[])]
        return max((point.timestamp() for point in dates if point),default=float('inf'))
    for original in sorted(fresh,key=notice_order):
        current = copy.deepcopy(original)
        # 这些是本模块产生的内部身份历史，不能让模型自行声明别名来合并赛项。
        for field in ("identity_aliases", "track_aliases", "superseded_keys", "cleared_fields_applied", "carried_forward_fields"):
            current.pop(field, None)
        controls = verified_controls(current)
        for field in ("lifecycle", "cleared_fields", "track_id"):
            if field not in controls:
                current.pop(field, None)
        current["verified_control_fields"] = sorted(controls)
        current.setdefault("key", event_key(current))
        incoming_key = current["key"]
        matched = _resolve(current, merged, aliases)
        key = matched or incoming_key
        raw_to_stable[incoming_key] = key
        if key in seen:
            prior_clear = set(seen[key].get("cleared_fields", [])) if "cleared_fields" in verified_controls(seen[key]) else set()
            current_clear = set(current.get("cleared_fields", [])) if "cleared_fields" in controls else set()
            if factual_fingerprint(seen[key]) == factual_fingerprint(current) and prior_clear == current_clear:
                merged[key]["sources"] = _sources(merged[key], current)
                continue
            earlier=[parse_at(s.get('published_date')) for s in seen[key].get('sources',[])]
            later=[parse_at(s.get('published_date')) for s in current.get('sources',[])]
            if not earlier or not later or any(p is None for p in earlier+later) or min(later)<=max(earlier):
                raise ValueError("同届同赛项出现多条冲突记录：" + key)
            # 同批抓到前后两份有明确发布时间的公告，按时间应用局部更新。
        seen[key] = copy.deepcopy(current)
        prior = merged.get(key)
        clear = set(current.get("cleared_fields", [])) & CLEARABLE_FIELDS if "cleared_fields" in controls else set()
        incoming_lifecycle = current.get("lifecycle") if "lifecycle" in controls else None
        # 延期公告撤销原节点，仅保留该通知明确给出的新日期/节点，不猜复赛时间。
        reset_old = set(ACTION_FIELDS) if incoming_lifecycle == "postponed" else set()
        carried = []
        if prior:
            for field in (*FACT_FIELDS, "registration_open_confirmed", "status_as_of", "registration_deadline_label"):
                if field not in clear and field not in reset_old and current.get(field) in EMPTY and prior.get(field) not in EMPTY:
                    current[field] = copy.deepcopy(prior[field])
                    carried.append(field)
            if "milestones" not in clear and "milestones" not in reset_old and current.get("milestones") and prior.get("milestones"):
                current["milestones"] = _milestones(prior["milestones"], current["milestones"])
            if not current.get("notes"):
                current["notes"] = copy.deepcopy(prior.get("notes", []))
            current["sources"] = _sources(prior, current)
            if incoming_lifecycle is None and "lifecycle" in verified_controls(prior):
                current["lifecycle"] = prior["lifecycle"]
                controls.add("lifecycle")
            if not _track_id(current) and _track_id(prior):
                current["track_id"] = prior["track_id"]
                controls.add("track_id")
            current["identity_aliases"] = list(dict.fromkeys([*prior.get("identity_aliases", []), *current.get("identity_aliases", []), incoming_key]))
            current["identity_aliases"] = [alias for alias in current["identity_aliases"] if alias != key]
            current["track_aliases"] = list(dict.fromkeys([*prior.get("track_aliases", []), prior.get("track", "主赛"), current.get("track", "主赛")]))
            if prior.get("superseded_keys"):
                current["superseded_keys"] = copy.deepcopy(prior["superseded_keys"])
        current.setdefault("identity_aliases", [])
        current.setdefault("track_aliases", [current.get("track", "主赛")])
        current["verified_control_fields"] = sorted(controls)
        lifecycle = effective_lifecycle(current)
        if lifecycle == "canceled":
            clear.update(ACTION_FIELDS)
        elif lifecycle == "registration_closed":
            clear.update(REGISTRATION_FIELDS)
        elif incoming_lifecycle == "postponed":
            for field in reset_old:
                if current.get(field) in EMPTY or field == "registration_open_confirmed":
                    clear.add(field)
        for field in clear:
            current[field] = _empty(field)
        current["cleared_fields_applied"] = sorted(clear | {field for field in (prior or {}).get("cleared_fields_applied", []) if current.get(field) in EMPTY or current.get(field) is False})
        current["carried_forward_fields"] = sorted(field for field in carried if field not in clear)
        current["key"] = key
        current["stale"] = False
        current.pop("stale_since", None)
        current.setdefault("verified_as_of", as_of.isoformat())
        merged[key] = current
    # 明确的一对多基线替代：所有替代项必须在本轮取得，任何缺项都保留历史项。
    supersedes = aliases.get("supersedes", {}) if isinstance(aliases, dict) else {}
    for old_key, replacements in supersedes.items() if isinstance(supersedes, dict) else []:
        if old_key not in (previous or {}).get("events", {}) or old_key not in merged:
            continue
        if not isinstance(replacements, list) or not replacements or any(not isinstance(key, str) for key in replacements):
            continue
        if len(set(replacements)) != len(replacements) or not all(key in raw_to_stable for key in replacements):
            continue
        new_keys = [raw_to_stable[key] for key in replacements]
        if len(set(new_keys)) != len(new_keys) or old_key in new_keys:
            continue
        old_scope = _scope(merged[old_key], aliases)
        if any(key not in merged or _scope(merged[key], aliases) != old_scope for key in new_keys):
            continue
        del merged[old_key]
        for key in new_keys:
            merged[key]["superseded_keys"] = list(dict.fromkeys([*merged[key].get("superseded_keys", []), old_key]))
    return list(merged.values())
