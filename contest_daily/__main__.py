from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import shutil
import time as clock
import uuid
import urllib.parse
from datetime import date, datetime, time
from pathlib import Path

from .core import CST, build_report, load_catalog, load_json, save_json, validate_event
from .network import DeepSeekClient, FetchError, WebClient, load_env, trusted_url
from .render import write_report
from .runtime import RunLock, quality_check, usage_position, usage_since, publish_staged

ROOT = Path(__file__).resolve().parent.parent


def previous_snapshot(root, day):
    paths = sorted(p for p in (root / "data/state").glob("????-??-??.json") if p.stem < day)
    return next((value for path in reversed(paths) if (value := matching_snapshot(root, path))), None)


def matching_snapshot(root, path):
    from .workspace import confirmed_catalog, catalog_digest
    source = confirmed_catalog(root)
    value = load_json(path)
    if source is not None and value and value.get('catalog_sha256') != catalog_digest(source):
        return None
    return value


from .scanner import scan_live


def import_research(folder, known_ids, as_of):
    events, coverage = [], []
    paths = sorted(folder.glob("batch_*.json"))
    if not paths:
        raise ValueError("未发现 batch_*.json 核验文件")
    for path in paths:
        research = load_json(path)
        if research.get("as_of") != as_of.date().isoformat():
            raise ValueError("核验文件日期与日报日期不同：" + path.name)
        coverage.extend(research.get("coverage", []))
        for raw in research.get("events", []):
            event = validate_event(raw, known_ids, as_of)
            event["verified_as_of"] = as_of.isoformat()
            events.append(event)
    return events, coverage


from .state import merge_events, merge_catalog_events


def select_time(args):
    if args.at:
        parsed = datetime.fromisoformat(args.at)
        return parsed.replace(tzinfo=CST) if not parsed.tzinfo else parsed.astimezone(CST)
    current = datetime.now(CST)
    day = date.fromisoformat(args.date) if args.date else current.date()
    return current if day == current.date() else datetime.combine(day, time.max, CST)


def run(args):
    with RunLock(args.root.resolve()):
        try:
            return run_unlocked(args)
        except (Exception,KeyboardInterrupt) as exc:
            if getattr(args,'_run_dir',None):
                path=args._run_dir/'summary.json'
                summary=load_json(path,{})
                if summary.get('status') not in ('published','blocked','preview'):
                    summary.update(run_id=args._run_id,status='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',error=str(exc),api_usage=usage_since(args.root.resolve(),args._usage_offset),elapsed_seconds=round(clock.monotonic()-args._run_started,3))
                    save_json(path,summary)
                    print('失败运行记录：'+str(path),flush=True)
            raise


def run_unlocked(args):
    root = args.root.resolve()
    load_env(root / ".env")
    replay_path=getattr(args,'from_run',None)
    replay=load_json(replay_path.resolve()/'collected.json') if replay_path else None
    if replay_path and not replay:
        raise ValueError('指定运行目录缺少 collected.json')
    if replay_path and (args.from_research or args.ids or args.limit or args.date or args.at):
        raise ValueError('--from-run 保留原采集时刻和范围，不能与日期、筛选或人工快照选项混用')
    as_of = datetime.fromisoformat(replay['as_of']) if replay else select_time(args)
    started=clock.monotonic()
    run_id=as_of.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:10]
    run_dir=root/'data/runs'/run_id
    run_dir.mkdir(parents=True,exist_ok=True)
    offset=usage_position(root)
    args._run_dir=run_dir;args._run_id=run_id;args._usage_offset=offset;args._run_started=started
    save_json(run_dir/'summary.json',{'run_id':run_id,'as_of':as_of.isoformat(),'status':'running'})
    catalog = load_catalog(root)
    known_ids = {i for item in catalog for i in item["ids"]}
    previous = previous_snapshot(root, as_of.date().isoformat())
    same_day=matching_snapshot(root,root/'data/state'/(as_of.date().isoformat()+'.json'))
    selected=catalog
    web = WebClient(timeout=args.source_timeout)
    if replay:
        events=[validate_event(raw,known_ids,as_of) for raw in replay['events']]
        coverage=replay['coverage']
        acquisition='deepseek_replay'
    elif args.from_research:
        events, coverage = import_research(args.from_research.resolve(), known_ids, as_of)
        acquisition = "manual_verified"
    else:
        client = DeepSeekClient(root, web)
        selected = catalog
        if args.ids:
            chosen = set(map(int, args.ids.split(",")))
            if chosen-known_ids:raise ValueError('指定了清单之外的赛事编号')
            selected = [c for c in catalog if chosen & set(c["ids"])]
        if args.limit:
            selected = selected[:args.limit]
        registry = load_json(root / "config/source_registry.json", {})
        checkpoint_dir=run_dir/'checkpoints'
        if args.resume:
            origin=args.resume.resolve()/'checkpoints'
            if not origin.is_dir():
                raise ValueError('续跑目录缺少 checkpoints：'+str(origin))
            checkpoint_dir.mkdir(parents=True,exist_ok=True)
            for path in origin.glob('*.json'):
                shutil.copyfile(path,checkpoint_dir/path.name)
        events, coverage = scan_live(root, selected, as_of, registry, client, web, args.max_pages,workers=args.workers,checkpoint_dir=checkpoint_dir,resume=bool(args.resume))
        acquisition = "deepseek_live"
    for item in catalog:
        for identifier in item["ids"]:
            if not any(c["competition_id"] == identifier for c in coverage):
                coverage.append({"competition_id": identifier, "result": "not_checked", "urls": [], "note": "本轮未检查"})
    partial=len(selected)!=len(catalog)
    save_json(run_dir/'collected.json',{'as_of':as_of.isoformat(),'events':events,'coverage':coverage})
    merged, events, conflicts, coverage = merge_catalog_events(events,same_day or previous,as_of,catalog,load_json(root/'config/track_aliases.json',{}),coverage)
    quality=quality_check(events,coverage,catalog,args.min_success_ratio)
    checked=[]
    for event in merged:
        stable_key=event['key']
        event=validate_event(event,known_ids,as_of)
        event['key']=stable_key
        checked.append(event)
    merged=checked
    report = build_report(merged, coverage, catalog, as_of, previous, args.deadline_days, acquisition)
    report.update(run_id=run_id,run_quality=quality,fresh_event_count=len(events),stale_event_count=sum(bool(e.get('stale')) for e in merged),partial_scan=partial)
    report['identity_conflicts']=conflicts
    from .branding import load_profile
    report['branding']=load_profile(root)
    from .workspace import confirmed_catalog, catalog_digest
    source_catalog=confirmed_catalog(root)
    report['catalog_kind']='custom' if source_catalog else 'lzu_legacy'
    signature=catalog_digest(source_catalog) if source_catalog else None
    if signature:report['catalog_sha256']=signature
    if replay_path:
        report['source_run_id']=replay_path.name
    if args.audit_with_deepseek and quality['passed']:
        print("正在使用 DeepSeek 旗舰模型审核日报…", flush=True)
        review = DeepSeekClient(root, web).review(report)
        save_json(run_dir/'audit.json', review)
        report["audit"] = {"model": review["model"], "findings_count": len(review.get("findings", [])), "summary": review.get("summary", "")}
        if acquisition == "manual_verified":
            report["acquisition"] = "manual_plus_deepseek"
    stage_root=run_dir/'preview'
    output = write_report(stage_root, report)
    published=quality['passed'] and not partial and not args.preview
    if published:
        output=publish_staged(stage_root,root,report['date'],snapshot={"as_of":report["as_of"],"catalog_sha256":signature,"events":{event['key']:event for event in merged}})
    summary={'run_id':run_id,'as_of':as_of.isoformat(),'status':'published' if published else 'preview' if partial or quality['passed'] else 'blocked','published':published,'scope_count':len(selected),'catalog_count':len(catalog),'quality':quality,'events':len(merged),'fresh_events':len(events),'stale_events':report['stale_event_count'],'api_usage':usage_since(root,offset),'elapsed_seconds':round(clock.monotonic()-started,3),'output':str(output.with_suffix('.html')),'coverage':coverage}
    save_json(run_dir/'summary.json',summary)
    if replay_path:
        summary['source_run_id']=replay_path.name
        save_json(run_dir/'summary.json',summary)
    print('运行记录：'+str(run_dir/'summary.json'),flush=True)
    print(json.dumps({key:summary[key] for key in ('status','scope_count','fresh_events','stale_events','api_usage','elapsed_seconds')},ensure_ascii=False),flush=True)
    if not quality['passed'] and not partial:
        raise ValueError('质量门槛未通过，公开日报及历史未覆盖：'+'；'.join(quality['reasons']))
    print("日报已生成：" + str(output.with_suffix(".html")), flush=True)
    print(json.dumps({"events": len(report["events"]), "groups": {key: len(value) for key, value in report["groups"].items()}, "bootstrap": report["bootstrap"]}, ensure_ascii=False))
    if report.get("audit"):
        print("DeepSeek 审核结果见同目录 .audit.json；审核意见不会自动改写来源事实。")


def doctor(args):
    root = args.root.resolve()
    load_env(root / ".env")
    try:
        catalog = load_catalog(root)
        print(f"Python {sys.version.split()[0]}；清单 {len(catalog)} 个不同赛事")
    except ValueError as exc:
        print('清单待配置：'+str(exc))
    print("API Key：" + ("已配置" if os.environ.get("DEEPSEEK_API_KEY") else "未配置"))
    print("模型：" + os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"))
    import importlib.util
    for name in ('pypdf','reportlab'):
        print(name+'：'+('可用' if importlib.util.find_spec(name) else '未安装，请安装发行包 requirements.txt'))
    registry=load_json(root/'config/source_registry.json',{})
    print('已登记官方来源的赛事：'+str(sum(bool(value.get('trusted_domains')) for value in registry.values())))
    if args.probe_api:
        client = DeepSeekClient(root, WebClient())
        review = client.review({"as_of": datetime.now(CST).isoformat(), "bootstrap": True, "events": [], "groups": {}})
        print("API 调用成功；实际返回模型：" + review["model"])
        print("本次用量：" + json.dumps(review["usage"], ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="学院竞赛清单 → 官方来源 → DeepSeek → 可溯源日报")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help='用户独立工作目录，默认当前目录')
    sub = parser.add_subparsers(dest="command", required=True)
    initialize = sub.add_parser('init', help='建立独立工作目录和空白密钥配置，不调用 API')
    initialize.add_argument('--university', required=True)
    initialize.add_argument('--college', required=True)
    initialize.add_argument('--report-title', default='竞赛日报')
    initialize.add_argument('--accent-color', default='#1d6652')
    importer = sub.add_parser('import-catalog', help='从 PDF/Word/Excel/JSON/CSV/文本导入待核对清单')
    importer.add_argument('document', type=Path)
    importer.add_argument('--overwrite', action='store_true', help='替换现有待核对清单；旧日报保留')
    sub.add_parser('confirm-catalog', help='核对清单后明确采用，建立来源配置')
    source = sub.add_parser('sources', help='登记 Agent 已核实的官方来源')
    source.add_argument('--id', type=int, required=True)
    source.add_argument('--url', required=True)
    source.add_argument('--domain')
    sub.add_parser('demo', help='在独立目录生成虚构演示 HTML 和 PDF，不联网、不使用 Token')
    inspect = sub.add_parser("doctor", help="检查环境，不显示密钥")
    inspect.add_argument("--probe-api", action="store_true")
    execute = sub.add_parser("run", help="生成一天的 Markdown / HTML / JSON 日报")
    execute.add_argument("--date", help="北京时间日期 YYYY-MM-DD")
    execute.add_argument("--at", help="精确核验时刻，如 2026-10-15T21:30:00+08:00")
    execute.add_argument("--from-research", type=Path, help="使用有来源的人工核验快照，离线可复现")
    execute.add_argument('--from-run',type=Path,help='重建已保存的 collected.json，保留原采集时刻，不重新联网或调用 API')
    execute.add_argument("--audit-with-deepseek", action="store_true", help="额外调用旗舰模型审查日报")
    execute.add_argument("--ids", help="仅联网检查指定原序号，例如 17,24")
    execute.add_argument("--limit", type=int)
    execute.add_argument("--max-pages", type=int, default=None)
    execute.add_argument("--deadline-days", type=int, default=None)
    execute.add_argument("--allow-empty", action="store_true",help='兼容诊断选项；空采集仍受发布门槛保护')
    execute.add_argument('--preview',action='store_true',help='仅保存验收预览，不覆盖公开报告与历史快照')
    execute.add_argument('--resume',type=Path,help='从指定 data/runs/<run_id> 的成功检查点继续，失败项重新检查')
    execute.add_argument('--workers',type=int,choices=range(1,5),default=None,help='采集并行度，默认依次处理，验收可用2至4')
    execute.add_argument('--source-timeout',type=int,default=None,help='单个官方来源请求超时秒数')
    execute.add_argument('--min-success-ratio',type=float,default=None,help='全清单来源及提取成功比例发布门槛，默认0.5')
    args = parser.parse_args()
    try:
        if args.command == 'run':
            from .workspace import runtime_settings
            for key,value in runtime_settings(args.root,vars(args)).items():setattr(args,key,value)
            if args.limit is not None and args.limit<1:raise ValueError('limit 必须为正数')
        if args.command == 'init':
            from .workspace import init_workspace
            init_workspace(args.root,args.university,args.college,report_title=args.report_title,accent_color=args.accent_color)
            print('工作目录已初始化：'+str(args.root.resolve())+'；表头配置：config/profile.json')
        elif args.command == 'import-catalog':
            from .catalog_io import import_catalog
            value=import_catalog(args.document,args.root.resolve(),overwrite=args.overwrite)
            print('已导入待核对清单：'+str(args.root.resolve()/'config/catalog.json'))
            print('请核对名称、级别、重复项、官网；采用后执行 confirm-catalog')
        elif args.command == 'confirm-catalog':
            from .workspace import confirm_catalog
            value=confirm_catalog(args.root.resolve())
            print(f"已采用 {len(value['records'])} 条竞赛记录；请检查 config/source_registry.json 中的官方来源")
        elif args.command == 'sources':
            from .workspace import add_source
            add_source(args.root.resolve(),args.id,args.url,args.domain)
            print('官方来源已登记；仅登记前已由你或 Agent 核实的组织方/承办方网址')
        elif args.command == 'demo':
            from .workspace import demo
            print('离线演示已生成（虚构数据，不是实时日报）：'+str(demo(args.root).with_suffix('.html')))
        elif args.command == "doctor":
            doctor(args)
        else:
            run(args)
    except (ValueError, FetchError, KeyError, TypeError, OSError) as exc:
        print("运行失败：" + str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
