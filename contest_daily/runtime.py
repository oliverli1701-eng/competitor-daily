"""运行隔离、质量门槛和用量统计；失败记录不覆盖公开日报。"""
from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from pathlib import Path


class RunLock:
    def __init__(self, root, name='run.lock'):
        self.path=Path(root)/'data/state'/name
        self.stream=None

    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.stream=self.path.open('a+b')
        if self.path.stat().st_size==0:self.stream.write(b'0');self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.stream.close();self.stream=None
            raise ValueError('已有日报任务正在运行，本次退出以免重复采集或覆盖历史。') from None
        return self

    def __exit__(self,*args):
        if not self.stream:return
        self.stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.stream,fcntl.LOCK_UN)
        self.stream.close();self.stream=None


def quality_check(events,coverage,catalog,min_success_ratio=.5):
    by_id={item['competition_id']:item for item in coverage}
    results=[]
    for competition in catalog:
        entries=[by_id.get(i,{'result':'not_checked'}) for i in competition['ids']]
        result=next((e['result'] for e in entries if e['result'] in ('failed','inconclusive','not_checked')),entries[0]['result'])
        results.append(result)
    counts=dict(Counter(results))
    successful=sum(counts.get(key,0) for key in ('verified_event','no_current_notice','no_verified_event'))
    ratio=successful/len(catalog) if catalog else 0
    reasons=[]
    if not events:reasons.append('本轮没有经验证的赛事记录，禁止用全部旧数据冒充新日报')
    if counts.get('not_checked'):reasons.append('未完成全清单检查')
    if ratio<min_success_ratio:reasons.append(f'官方正文及提取成功比例 {ratio:.1%} 低于门槛 {min_success_ratio:.1%}')
    return {'passed':not reasons,'reasons':reasons,'competition_count':len(catalog),'results':counts,'successful_source_fraction':round(ratio,4),'min_success_ratio':min_success_ratio,'fresh_event_count':len(events)}


def usage_position(root):
    path=Path(root)/'data/state/api_usage.jsonl'
    return path.stat().st_size if path.exists() else 0


def usage_since(root,offset):
    path=Path(root)/'data/state/api_usage.jsonl'
    rows=[]
    if path.exists():
        with path.open('rb') as stream:
            stream.seek(offset)
            for line in stream:
                try:rows.append(json.loads(line))
                except (ValueError,UnicodeError):continue
    totals={key:sum((row.get('usage') or {}).get(key,0) or 0 for row in rows) for key in ('prompt_tokens','completion_tokens','total_tokens')}
    totals.update(calls=len(rows),models=sorted({str(row.get('model','unknown')) for row in rows}),cached_prompt_tokens=sum((row.get('usage') or {}).get('prompt_cache_hit_tokens',(row.get('usage') or {}).get('prompt_tokens_details',{}).get('cached_tokens',0)) or 0 for row in rows))
    return totals


def publish_staged(stage_root,root,day,snapshot=None):
    folder=Path('reports')/day[:4]
    target=Path(root)/folder;target.mkdir(parents=True,exist_ok=True)
    for suffix in ('.md','.html','.json'):
        source=Path(stage_root)/folder/(day+suffix)
        if not source.is_file():raise ValueError('暂存日报不完整，未发布')
    pairs=[(Path(stage_root)/folder/(day+suffix),target/(day+suffix)) for suffix in ('.md','.html','.json')]
    pdf=Path(stage_root)/folder/(day+'.pdf')
    metadata=json.loads((Path(stage_root)/folder/(day+'.json')).read_text(encoding='utf-8'))
    if metadata.get('pdf_available'):
        if not pdf.is_file():raise ValueError('暂存 PDF 缺失，未发布')
        pairs.append((pdf,target/(day+'.pdf')))
    if snapshot is not None:
        state_source=Path(stage_root)/'snapshot.json'
        state_source.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        destination=Path(root)/'data/state'/(day+'.json');destination.parent.mkdir(parents=True,exist_ok=True)
        pairs.append((state_source,destination))
    backup=Path(stage_root)/'publication_backup';backup.mkdir(exist_ok=True)
    originals={};prepared=[];committed=[]
    try:
        for index,(source,destination) in enumerate(pairs):
            temporary=destination.with_suffix(destination.suffix+'.publishing')
            prepared.append(temporary);shutil.copyfile(source,temporary)
            saved=backup/str(index)
            if destination.exists():shutil.copyfile(destination,saved);originals[destination]=saved
            else:originals[destination]=None
        for (_,destination),temporary in zip(pairs,prepared):
            temporary.replace(destination);committed.append(destination)
    except OSError:
        for destination in reversed(committed):
            saved=originals[destination]
            if saved is None:destination.unlink(missing_ok=True)
            else:
                recovery=destination.with_suffix(destination.suffix+'.recovering')
                shutil.copyfile(saved,recovery);recovery.replace(destination)
        raise
    finally:
        for temporary in prepared:temporary.unlink(missing_ok=True)
    return target/day
