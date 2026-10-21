"""服务器入口：受质量门槛保护的静态发布和有界存储。"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .core import CST, load_json, save_json
from .runtime import RunLock

DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
CACHE_LIMIT = 32 * 1024 * 1024


def publication_delay(now,value):
    if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',value):raise ValueError('发布时间必须为 HH:MM')
    hour,minute=map(int,value.split(':'))
    target=now.replace(hour=hour,minute=minute,second=0,microsecond=0)
    return max(0,(target-now).total_seconds())


def write_status(public,status):
    public.mkdir(parents=True,exist_ok=True)
    days=sorted(p.stem for p in public.glob('*.json') if DAY.fullmatch(p.stem))
    temporary=public/'.status.deploying'
    import json
    temporary.write_text(json.dumps({'status':status,'updated_at':datetime.now(CST).isoformat(),'report_date':days[-1] if days else None},ensure_ascii=False),encoding='utf-8')
    temporary.chmod(0o644);temporary.replace(public/'status.json')


def remove_owned(path, base):
    base=base.resolve()
    if path == base or not path.parent.resolve().is_relative_to(base):
        raise ValueError('拒绝清理应用目录以外的路径')
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def publish(root, public, day):
    if not DAY.fullmatch(day):
        raise ValueError('无效日报日期')
    source=root/'reports'/day[:4]
    report=load_json(source/(day+'.json'))
    if not report or report.get('date')!=day or not report.get('run_quality',{}).get('passed') or report.get('partial_scan'):
        raise ValueError('日报不完整或未通过质量门槛，保留网站上一版')
    inputs=[source/(day+suffix) for suffix in ('.md','.json','.html')]
    if report.get('pdf_available'):inputs.append(source/(day+'.pdf'))
    if not all(p.is_file() for p in inputs):
        raise ValueError('日报三种格式不完整')
    public.mkdir(parents=True,exist_ok=True)
    originals={};prepared=[];committed=[]
    try:
        for src in inputs:
            dest=public/src.name
            originals[dest]=dest.read_bytes() if dest.exists() else None
            temp=public/('.'+src.name+'.deploying')
            prepared.append((temp,dest));shutil.copyfile(src,temp);temp.chmod(0o644)
        for temp,dest in prepared:
            temp.replace(dest);committed.append(dest)
        # 最后切换首页硬链接，不再复制一份相同 HTML。
        temp_index=public/'.index.deploying'
        temp_index.unlink(missing_ok=True)
        os.link(public/(day+'.html'),temp_index)
        temp_index.replace(public/'index.html')
    except OSError:
        for dest in reversed(committed):
            if originals[dest] is None:
                dest.unlink(missing_ok=True)
            else:
                temp=public/('.'+dest.name+'.recovering')
                temp.write_bytes(originals[dest]);temp.chmod(0o644);temp.replace(dest)
        raise
    finally:
        for temp,_ in prepared:temp.unlink(missing_ok=True)
        (public/'.index.deploying').unlink(missing_ok=True)
    return report


def maintain(root, public, keep_run=None):
    """只清理此应用自己的目录，不处理服务器其他网站。"""
    cache=root/'data/cache'
    now=time.time();files=[]
    if cache.exists():
        for path in cache.rglob('*'):
            if not path.is_file() or path.is_symlink():continue
            stat=path.stat()
            if now-stat.st_mtime>7*86400:remove_owned(path,cache)
            else:files.append((stat.st_mtime,stat.st_size,path))
        total=sum(item[1] for item in files)
        for _,size,path in sorted(files):
            if total<=CACHE_LIMIT:break
            remove_owned(path,cache);total-=size
    state=root/'data/state'
    snapshots=sorted((p for p in state.glob('*.json') if DAY.fullmatch(p.stem)),reverse=True)
    for path in snapshots[3:]:remove_owned(path,state)
    # 仅留用量日志末尾 128 KiB，控制常驻日志总量。
    for path in [state/'api_usage.jsonl',root/'data/logs/latest.log']:
        if path.exists() and path.stat().st_size>128*1024:
            with path.open('rb') as stream:stream.seek(-128*1024,2);tail=stream.read()
            path.write_bytes(tail.split(b'\n',1)[-1])
    runs=root/'data/runs'
    if runs.exists():
        for path in runs.iterdir():
            if path.name!=keep_run:remove_owned(path,runs)
            elif path.is_dir():
                for item in path.iterdir():
                    if item.name not in ('checkpoints','summary.json'):remove_owned(item,runs)
    # 发布完成后私有 reports 和预览副本已无用途；公开目录单独保留 7 天。
    reports=root/'reports'
    if reports.exists():
        for path in reports.iterdir():remove_owned(path,reports)
    if public.exists():
        dates=sorted({p.stem for p in public.iterdir() if DAY.fullmatch(p.stem)},reverse=True)
        for day in dates[7:]:
            for suffix in ('.html','.md','.json','.pdf'):
                p=public/(day+suffix)
                if p.exists() or p.is_symlink():remove_owned(p,public)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--public-dir',type=Path,default=Path('/var/www/competitor/lzucs'))
    parser.add_argument('--publish-existing',metavar='YYYY-MM-DD',help='仅上线已验收的现有日报，不调用 API')
    parser.add_argument('--publish-at',metavar='HH:MM',help='预采集完成后等待当日北京时间指定时刻再发布；已过时刻则立即发布')
    args=parser.parse_args();root=args.root.resolve();public=args.public_dir.resolve()
    if args.publish_at:publication_delay(datetime.now(CST),args.publish_at)
    if root==public or public.is_relative_to(root) or root.is_relative_to(public):
        raise ValueError('运行目录和公开目录必须相互独立')
    with RunLock(root,'server.lock'):
        keep=None;exit_code=0
        try:
            if args.publish_existing:
                report=publish(root,public,args.publish_existing)
                summary={'status':'published_existing','as_of':report['as_of'],'date':report['date'],'additional_api_calls':0}
            else:
                write_status(public,'running')
                # 先释放过期占用；失败时可复用本日成功检查点，避免重复付费。
                last=load_json(root/'data/state/last_run.json',{})
                resume=root/'data/runs'/str(last.get('run_id',''))
                if last.get('status')!='published' and (resume/'checkpoints').is_dir():keep=resume.name
                maintain(root,public,keep)
                before=set((root/'data/runs').glob('*/summary.json'))
                command=[sys.executable,'-m','contest_daily','--root',str(root),'run','--max-pages','8','--workers','4','--source-timeout','12']
                if keep:command+=['--resume',str(resume)]
                log=root/'data/logs/latest.log';log.parent.mkdir(parents=True,exist_ok=True)
                with log.open('w',encoding='utf-8') as stream:
                    result=subprocess.run(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1'})
                created=set((root/'data/runs').glob('*/summary.json'))-before
                summary=load_json(max(created,key=lambda p:p.stat().st_mtime)) if created else {'status':'failed','error':'采集未生成运行摘要'}
                if result.returncode or summary.get('status')!='published':
                    keep=summary.get('run_id');exit_code=1
                else:
                    day=summary['as_of'][:10]
                    if args.publish_at:
                        delay=publication_delay(datetime.now(CST),args.publish_at)
                        if delay:write_status(public,'ready')
                        while delay:
                            time.sleep(min(delay,30))
                            delay=publication_delay(datetime.now(CST),args.publish_at)
                    publish(root,public,day);keep=None
            save_json(root/'data/state/last_run.json',summary)
            write_status(public,'failed' if exit_code else 'published')
            if not exit_code:
                from .github_archive import sync_safely
                sync_safely(root, public)
            print('competitor: '+summary['status']+' · '+str(summary.get('as_of','')),flush=True)
        except Exception as exc:
            summary={'status':'failed','as_of':datetime.now(CST).isoformat(),'error':str(exc)}
            save_json(root/'data/state/last_run.json',summary)
            write_status(public,'failed')
            raise
        finally:
            maintain(root,public,keep)
        return exit_code


if __name__=='__main__':
    raise SystemExit(main())
