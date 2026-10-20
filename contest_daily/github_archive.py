"""将已发布的日报归档至 GitHub；独立重试，不调用采集 API。"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from html import escape
from datetime import date, datetime
from pathlib import Path

from .core import CST, load_json, save_json
from .runtime import RunLock

REPOSITORY = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+')
PENDING_LIMIT = 32 * 1024 * 1024


def archive_path(day):
    value = date.fromisoformat(day)
    return f'{value.year}/{value.month:02d}/Week-{value.isocalendar().week:02d}/{day}'


def queue_reports(root, public):
    """仅暂存已验收且有 PDF 的公开日报；优先硬链接避免重复占用。"""
    pending = root/'data/github/pending'
    pending.mkdir(parents=True, exist_ok=True)
    for meta in sorted(public.glob('????-??-??.json')):
        report = load_json(meta, {})
        day = meta.stem
        if report.get('date') != day or not report.get('run_quality', {}).get('passed') or report.get('partial_scan'):
            continue
        sources = [public/(day+suffix) for suffix in ('.html', '.pdf')]
        if not report.get('pdf_available') or not all(path.is_file() for path in sources):
            continue
        # 无需为已经同步且内容未改变的日报重新创建队列。
        import hashlib
        digest = hashlib.sha256(b''.join(path.read_bytes() for path in sources)).hexdigest()
        receipts = load_json(root/'data/github/receipts.json', {})
        if receipts.get(day) == digest:
            continue
        size = sum(path.stat().st_size for path in pending.rglob('*') if path.is_file())
        existing = pending/day
        extra = sum(path.stat().st_size for path in sources)
        if size+extra > PENDING_LIMIT:
            raise RuntimeError('GitHub 待同步队列已达 32 MiB，请检查授权或网络；未删除待同步日报')
        with tempfile.TemporaryDirectory(prefix='.queue-', dir=pending) as staging:
            stage = Path(staging)
            for source in sources:
                target = stage/source.name
                try:
                    os.link(source, target)
                except OSError:
                    shutil.copyfile(source, target)
            save_json(stage/'receipt.json', {'digest': digest})
            existing.mkdir(exist_ok=True)
            for item in stage.iterdir():
                item.replace(existing/item.name)
    return pending


def readme(paths, repository='oliverli1701-eng/competitor-daily'):
    days = sorted({Path(path).parent.as_posix() for path in paths if re.fullmatch(r'\d{4}/\d{2}/Week-\d{2}/\d{4}-\d{2}-\d{2}/index.html', path)}, reverse=True)
    lines = ['# Competitor Daily', '', '兰州大学信息科学与工程学院竞赛清单的每日情报归档。', '',
             '[查看最新日报](https://cuiying42.com/competitor/)', '',
             '每天北京时间 08:00 发布后自动归档。目录按年 / 月 / ISO 周（周一至周日）/ 日期组织；跨月周分别归入日报所属月份。', '',
             '历史日报支持在线阅读和 PDF 下载；PDF 也保存在对应日期目录中。', '']
    month = None
    for folder in days:
        parts = folder.split('/')
        if parts[:2] != month:
            month = parts[:2]
            lines += [f'## {month[0]} 年 {int(month[1])} 月', '', '| 日期 | 周 | 网页 | PDF |', '| --- | --- | --- | --- |']
        day = parts[-1]
        owner, name = repository.split('/')
        online = f'https://{owner}.github.io/{name}/{folder}'
        lines.append(f'| {day} | {parts[2]} | [在线阅读]({online}/) · [HTML]({folder}/index.html) | [下载 PDF]({online}/{day}.pdf) |')
    return '\n'.join(lines)+'\n'


def archive_index(paths, prefix=''):
    days = sorted({Path(path).parent.as_posix() for path in paths if re.fullmatch(r'\d{4}/\d{2}/Week-\d{2}/\d{4}-\d{2}-\d{2}/index.html', path)}, reverse=True)
    rows = ''.join(f'<li><a class="day" href="{escape(prefix+folder)}/"><time>{folder.split("/")[-1]}</time><span>{folder.split("/")[2]}</span><b>阅读日报 ↗</b></a><a class="pdf" href="{escape(prefix+folder)}/{folder.split("/")[-1]}.pdf" download>下载 PDF ↓</a></li>' for folder in days)
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>历史归档 · Competitor Daily</title>
<style>:root{color-scheme:light dark;--bg:#f6f4ef;--fg:#242c29;--muted:#69736d;--line:#d9ddd4;--accent:#21775b}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif}main{max-width:850px;margin:70px auto;padding:0 24px}.eyebrow{font-size:12px;letter-spacing:.18em;color:var(--accent)}h1{font-size:clamp(34px,7vw,56px);line-height:1.2;letter-spacing:-.04em;margin:20px 0}p{color:var(--muted)}a{color:inherit;text-decoration:none}a:focus-visible{outline:3px solid var(--accent);outline-offset:4px}.latest{display:inline-block;border-bottom:1px solid var(--accent);color:var(--accent);margin:12px 0 35px}ul{padding:0;list-style:none}li{display:flex;align-items:center;border-top:1px solid var(--line);gap:24px}.day{display:flex;flex:1;align-items:center;gap:26px;padding:23px 0}.day time{font-size:19px;font-variant-numeric:tabular-nums;font-weight:600}.day span,.pdf{color:var(--muted);font-size:13px}.day b{margin-left:auto;font-size:13px;font-weight:500}.day:hover,.pdf:hover{color:var(--accent)}footer{margin-top:40px;font-size:12px;color:var(--muted)}@media(max-width:600px){main{margin-top:40px}.day{gap:12px;flex-wrap:wrap}.day b{display:none}li{gap:12px}}@media(prefers-color-scheme:dark){:root{--bg:#151d1a;--fg:#e5e9e4;--muted:#99aaa0;--line:#344138;--accent:#86cfac}}</style>
<main><div class="eyebrow">COMPETITOR DAILY / ARCHIVE</div><h1>每日竞赛，逐日留存。</h1><p>按年、月、ISO 周与日期归档。每天北京时间 08:00 发布后同步。</p><a class="latest" href="https://cuiying42.com/competitor/">查看最新日报 ↗</a><ul>'''+rows+'''</ul><footer>兰州大学信息科学与工程学院 · 学科竞赛情报</footer></main></html>'''


def git(args, cwd, env):
    result = subprocess.run(['git', *args], cwd=cwd, env=env, text=True, encoding='utf-8',
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    if result.returncode:
        raise RuntimeError(f'git {args[0]} 失败：{result.stderr[-1200:].strip()}')
    return result.stdout.strip()


def synchronize(root, public):
    config = load_json(root/'data/github/config.json', {})
    if not config.get('enabled'):
        return {'status': 'disabled'}
    repository = config.get('repository', '')
    if not REPOSITORY.fullmatch(repository):
        raise ValueError('GitHub 仓库必须为 owner/name')
    private = root/'data/github'
    key, hosts = private/'id_ed25519', private/'known_hosts'
    if not key.is_file() or not hosts.is_file():
        raise ValueError('缺少 GitHub 专用部署密钥或受信任主机指纹')
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0',
           'GIT_SSH_COMMAND': f'ssh -i {shlex.quote(str(key))} -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile={shlex.quote(str(hosts))} -o ConnectTimeout=15'}
    with RunLock(root, 'github.lock'):
        pending = queue_reports(root, public)
        jobs = sorted(path for path in pending.iterdir() if path.is_dir() and re.fullmatch(r'\d{4}-\d{2}-\d{2}', path.name))
        if not jobs:
            return {'status': 'up_to_date', 'checked_at': datetime.now(CST).isoformat()}
        # 不检出历史日报内容；同步结束即移除浅克隆，服务器不常驻完整仓库。
        with tempfile.TemporaryDirectory(prefix='checkout-', dir=private) as temporary:
            checkout = Path(temporary)
            git(['clone', '--depth=1', '--filter=blob:none', '--no-checkout', '--branch', 'main',
                 f'git@github.com:{repository}.git', str(checkout)], private, env)
            git(['sparse-checkout', 'set', '--no-cone', '/README.md'], checkout, env)
            git(['checkout', 'main'], checkout, env)
            git(['config', 'user.name', 'Competitor Daily'], checkout, env)
            git(['config', 'user.email', 'competitor-daily@users.noreply.github.com'], checkout, env)
            product_home = '<!-- competitor-daily:product-home -->' in (checkout/'README.md').read_text(encoding='utf-8')
            receipts = load_json(private/'receipts.json', {})
            published = []
            for job in jobs:
                day = job.name
                folder = archive_path(day)
                target = checkout/folder
                target.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(job/(day+'.html'), target/'index.html')
                shutil.copyfile(job/(day+'.pdf'), target/(day+'.pdf'))
                # 归档页无需请求当前网站的状态接口；保留正确的同目录 PDF 下载地址。
                html = (target/'index.html').read_text(encoding='utf-8')
                html = html.replace("fetch('status.json',{cache:'no-store'})", "Promise.resolve({ok:false})")
                (target/'index.html').write_text(html, encoding='utf-8')
                git(['add', '--sparse', '--', folder], checkout, env)
                names = git(['ls-files'], checkout, env).splitlines()
                if product_home:
                    history = checkout/'archive'
                    history.mkdir(exist_ok=True)
                    (history/'index.html').write_text(archive_index(names, '../'), encoding='utf-8')
                    # README links are relative to its own directory.
                    (history/'README.md').write_text(readme(names, repository).replace('](202', '](../202'), encoding='utf-8')
                    index_paths = ['archive']
                else:
                    (checkout/'README.md').write_text(readme(names, repository), encoding='utf-8')
                    (checkout/'index.html').write_text(archive_index(names), encoding='utf-8')
                    index_paths = ['README.md', 'index.html']
                (checkout/'.nojekyll').touch()
                git(['add', '--sparse', *index_paths, '.nojekyll'], checkout, env)
                if git(['diff', '--cached', '--name-only'], checkout, env):
                    git(['commit', '-m', f'daily: {day}'], checkout, env)
                receipts[day] = load_json(job/'receipt.json')['digest']
                published.append(day)
            git(['push', 'origin', 'HEAD:main'], checkout, env)
            commit = git(['rev-parse', 'HEAD'], checkout, env)
        # 仅在远端确认成功后清理队列；凭据和日志均不会进入仓库。
        save_json(private/'receipts.json', dict(sorted(receipts.items())[-14:]))
        for job in jobs:
            shutil.rmtree(job)
        return {'status': 'synced', 'repository': repository, 'dates': published, 'commit': commit,
                'updated_at': datetime.now(CST).isoformat()}


def sync_safely(root, public):
    """归档失败单独记录，不能将已成功上线的网站标记为失败。"""
    try:
        result = synchronize(root, public)
    except Exception as exc:
        result = {'status': 'failed', 'updated_at': datetime.now(CST).isoformat(), 'error': str(exc)}
    if result['status'] != 'disabled':
        save_json(root/'data/state/github_sync.json', result)
        print('github archive: '+result['status'], flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--public-dir', type=Path, default=Path('/var/www/competitor'))
    args = parser.parse_args()
    result = sync_safely(args.root.resolve(), args.public_dir.resolve())
    return int(result['status'] == 'failed')


if __name__ == '__main__':
    raise SystemExit(main())
