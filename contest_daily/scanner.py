from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .core import save_json, load_json, validate_event
from .network import DeepSeekClient, FetchError, trusted_url

def checkpoint_signature(config, max_pages, as_of, client):
    profile=(getattr(client,'base',None),getattr(client,'model',None),getattr(client,'reasoning_effort',None),getattr(client,'max_tokens',None))
    return hashlib.sha256(repr(('validated-v2',config,max_pages,as_of.date().isoformat(),profile)).encode()).hexdigest()

def scan_live(root, catalog, as_of, registry, client, web, max_pages=4, *, workers=1, checkpoint_dir=None, resume=False, quiet=False):
    if workers>1 and len(catalog)>1:
        ordered={}
        def one(competition):
            worker_client=DeepSeekClient(root,web)
            return scan_live(root,[competition],as_of,registry,worker_client,web,max_pages,checkpoint_dir=checkpoint_dir,resume=resume,quiet=True)
        with ThreadPoolExecutor(max_workers=min(workers,4)) as executor:
            pending={executor.submit(one,competition):index for index,competition in enumerate(catalog)}
            for future in as_completed(pending):
                index=pending[future]
                ordered[index]=future.result()
                print(f"[{len(ordered)}/{len(catalog)}] {catalog[index]['name']} · {ordered[index][1][0]['result']}",flush=True)
        return ([event for index in sorted(ordered) for event in ordered[index][0]], [item for index in sorted(ordered) for item in ordered[index][1]])
    events, coverage = [], []
    requested_max_pages=max_pages
    requested_max_tokens=getattr(client,'max_tokens',None)
    for index, competition in enumerate(catalog, 1):
        started=time.monotonic()
        if not quiet:print(f"[{index}/{len(catalog)}] {competition['name']}", flush=True)
        config = registry.get(str(competition["ids"][0]), {})
        if requested_max_tokens is not None:
            client.max_tokens=int(config.get('max_tokens',requested_max_tokens))
            if not 1024<=client.max_tokens<=262144:raise ValueError('赛事 max_tokens 超出有效范围')
        max_pages=min(requested_max_pages,int(config.get('page_budget',4)))
        signature=checkpoint_signature(config,max_pages,as_of,client)
        checkpoint=Path(checkpoint_dir)/('-'.join(map(str,competition['ids']))+'.json') if checkpoint_dir else None
        cached=load_json(checkpoint) if checkpoint and resume else None
        if cached and cached.get('signature')==signature and all(item['result'] in ('verified_event','no_current_notice') for item in cached.get('coverage',[])):
            events.extend(cached['events']);coverage.extend([{**item,'checkpoint_reused':True} for item in cached['coverage']]);continue
        domains = config.get("trusted_domains", [])
        seeds = list(config.get("urls", []))
        discovered = []
        query = '"' + config.get("search_name", competition["name"]) + f'" {as_of.year} 报名 通知'
        errors, untrusted = [], []
        try:
            for item in web.search(query):
                if trusted_url(item["url"], domains):
                    discovered.append(item["url"])
                else:
                    untrusted.append(item)
        except (FetchError, ValueError) as exc:
            errors.append(str(exc))
        docs, visited = [], set()
        # 注册的官方公告入口独立于搜索服务；抓首页/栏目页的最新相关链接。
        index_candidates = []
        for index_url in config.get("index_urls", [])[:2]:
            if not trusted_url(index_url, domains):
                continue
            try:
                listing = web.document(index_url)
                for detail in listing.get("link_details", []):
                    label = detail.get("title", "")
                    if trusted_url(detail["url"], domains) and re.search(r"通知|公告|报名|竞赛|contest|registration", label, re.I):
                        score = 3 * bool(re.search(str(as_of.year) + "|" + str(as_of.year + 1), label)) + 2 * ("报名" in label) + ("通知" in label)
                        index_candidates.append((score, detail["url"]))
            except (FetchError, ValueError) as exc:
                errors.append("官方公告入口：" + str(exc))
        index_candidates.sort(key=lambda pair: pair[0], reverse=True)
        # 新检索通知优先，至少留一个来源位给已登记官方入口。
        priority=list(config.get('priority_urls',[]))
        primary=priority or seeds[:1]
        discovery=list(dict.fromkeys(discovered+[url for _,url in index_candidates]))
        urls = list(dict.fromkeys(primary+discovery[:1]+seeds+discovery[1:]))
        # 若搜索不可用，仍沿官方入口发现新公告，避免永远只盯着旧文章。
        cursor = 0
        while cursor < len(urls):
            url = urls[cursor]
            cursor += 1
            if len(docs) >= max_pages or len(visited) >= max_pages * 3:
                break
            if url in visited:
                continue
            visited.add(url)
            if not trusted_url(url, domains):
                errors.append("官方域名未登记，暂不采用该候选来源")
                continue
            try:
                document = web.document(url)
                if not trusted_url(document["url"], domains):
                    raise FetchError("重定向超出已登记官方域名")
                docs.append(document)
                # 优先跟进正文中的章程、赛题、参赛指南和材料附件。
                # 不只读报名概述，也不让旧新闻耗尽全部页面预算。
                rules = []
                for detail in document.get("link_details", []):
                    target = detail.get("url", "")
                    if (trusted_url(target, domains) and target not in visited
                            and re.search(r"章程|规程|规则|赛规|参赛指南|附件|赛题|提交流程|报名指南", detail.get("title", ""))):
                        rules.append(target)
                insertion=cursor+int(cursor<len(urls) and urls[cursor] in discovery and urls[cursor] not in visited)
                # 明确配置的多份关键通知先读完，不能被第一份公告的附件挤掉。
                insertion=max([insertion]+[i+1 for i in range(cursor,len(urls)) if urls[i] in primary])
                for target in reversed(list(dict.fromkeys(rules))):
                    if target in urls[cursor:]:
                        urls.remove(target)
                    urls.insert(insertion, target)
                for link in document["links"]:
                    if trusted_url(link, domains) and link not in urls and not link.lower().endswith((".jpg", ".png", ".css", ".js")):
                        # 只展开入口页的一级链接；实际归属和年份由模型根据正文验证。
                        path = urllib.parse.urlsplit(url).path
                        if path in ("", "/") or any(token in path.lower() for token in ("notice", "news", "tongzhi", "list")):
                            urls.append(link)
                cache_path = root / "data/cache/pages" / (hashlib.sha256(document["url"].encode()).hexdigest() + ".json")
                save_json(cache_path, {**document, "retrieved_at": as_of.isoformat()})
            except (FetchError, ValueError) as exc:
                errors.append(str(exc))
        extracted = []
        extraction_failed=False
        rejected_records=0
        if docs:
            try:
                candidates = client.extract(competition, docs, as_of.isoformat())
            except (ValueError, KeyError, TypeError, FetchError) as exc:
                errors.append(str(exc))
                extraction_failed=True
                candidates = []
            for raw in candidates:
                try:
                    raw=dict(raw)
                    raw.pop('source_scope',None)
                    scopes=config.get('source_scopes',{})
                    source_scopes={scopes.get(source.get('url')) for source in raw.get('sources',[])}
                    if len(source_scopes)==1 and None not in source_scopes:
                        scope=next(iter(source_scopes))
                        raw['source_scope']=scope
                        if scope not in raw.get('track','主赛'):
                            raw['track']=scope+' · '+raw.get('track','主赛')
                    event = validate_event(raw, set(competition["ids"]), as_of)
                    event["verified_as_of"] = as_of.isoformat()
                    extracted.append(event)
                except (ValueError, KeyError, TypeError) as exc:
                    rejected_records+=1
                    errors.append("一条赛道记录未采用：" + str(exc))
            if candidates and not extracted:
                extraction_failed=True
            events.extend(extracted)
        result = "verified_event" if extracted else "failed" if extraction_failed or not docs and errors else "no_current_notice" if docs else "inconclusive"
        if not domains:
            result = "inconclusive"
            errors.append("尚未登记可核验官方来源；候选网址需确认后加入 source_registry.json")
        current_coverage=[]
        for competition_id in competition["ids"]:
            current_coverage.append({"competition_id": competition_id, "query": query, "result": result,
                             "urls": [d["url"] for d in docs], "note": "；".join(errors) or "已检查官方来源，未以搜索摘要代替正文。",
                             "untrusted_candidates": untrusted[:5], 'documents_read':len(docs), 'url_attempts':len(visited),
                             'elapsed_seconds':round(time.monotonic()-started,3), 'extraction':getattr(client,'last_extraction',{}),
                             'accepted_records':len(extracted), 'rejected_records':rejected_records,
                             'failed_stage':'extraction' if extraction_failed else 'source' if not docs else None})
        coverage.extend(current_coverage)
        if checkpoint:save_json(checkpoint,{'signature':signature,'as_of':as_of.isoformat(),'events':extracted,'coverage':current_coverage})
    return events, coverage

