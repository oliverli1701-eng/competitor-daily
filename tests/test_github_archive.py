import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contest_daily.core import save_json
from contest_daily.github_archive import archive_path, queue_reports, readme, synchronize, sync_safely


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base/'app'
        self.root.mkdir()
        self.public = self.base/'public'
        self.public.mkdir()
        self.private = self.root/'data/github'
        self.private.mkdir(parents=True)
        save_json(self.private/'config.json', {'enabled': True, 'repository': 'owner/competitor-daily'})
        for name in ('id_ed25519', 'known_hosts'):
            (self.private/name).write_text('test only')
        self.day = '2026-10-20'
        self.report(self.day)

    def report(self, day):
        save_json(self.public/(day+'.json'), {'date': day, 'run_quality': {'passed': True}, 'pdf_available': True})
        (self.public/(day+'.html')).write_text(f'<a href="{day}.pdf">PDF</a>')
        (self.public/(day+'.pdf')).write_bytes(b'%PDF-test')

    def command(self, args, cwd=None):
        result = subprocess.run(['git', *args], cwd=cwd or self.base, check=True, capture_output=True,
                                text=True, encoding='utf-8')
        return result.stdout.strip()

    def remote(self):
        remote = self.base/'remote.git'
        self.command(['init', '--bare', '--initial-branch=main', str(remote)])
        seed = self.base/'seed'
        self.command(['clone', str(remote), str(seed)])
        self.command(['config', 'user.name', 'Test'], seed)
        self.command(['config', 'user.email', 'test@example.com'], seed)
        (seed/'README.md').write_text('start')
        self.command(['add', 'README.md'], seed)
        self.command(['commit', '-m', 'init'], seed)
        self.command(['push', 'origin', 'main'], seed)
        return remote

    def test_iso_week_uses_report_calendar_month_at_year_boundary(self):
        self.assertEqual(archive_path(self.day), '2026/10/Week-43/2026-10-20')
        self.assertEqual(archive_path('2027-01-01'), '2027/01/Week-53/2027-01-01')
        with self.assertRaises(ValueError): archive_path('../../etc')

    def test_queue_retains_unpublished_jobs_and_ignores_failed_or_missing_pdf(self):
        pending = queue_reports(self.root, self.public)
        self.assertTrue((pending/self.day/(self.day+'.pdf')).exists())
        (self.public/(self.day+'.pdf')).unlink()
        queue_reports(self.root, self.public)
        self.assertTrue((pending/self.day/(self.day+'.pdf')).exists())
        self.report('2026-10-19')
        save_json(self.public/'2026-10-19.json', {'date': '2026-10-19', 'run_quality': {'passed': False}})
        queue_reports(self.root, self.public)
        self.assertFalse((pending/'2026-10-19').exists())

    @unittest.skipUnless(shutil.which('git'), 'requires Git')
    def test_real_git_push_download_link_index_idempotence_and_no_history_checkout(self):
        remote = self.remote()
        from contest_daily.github_archive import git as actual_git
        def local_git(args, cwd, env):
            if args[0] == 'clone':
                args = [*args]
                args[-2] = str(remote)
            return actual_git(args, cwd, env)
        (self.root/'.env').write_text('SECRET_MUST_STAY_PRIVATE')
        with patch('contest_daily.github_archive.git', side_effect=local_git):
            result = synchronize(self.root, self.public)
            self.assertEqual(result['status'], 'synced')
            self.assertEqual(synchronize(self.root, self.public)['status'], 'up_to_date')
            self.report('2026-10-21')
            synchronize(self.root, self.public)
        files = self.command(['--git-dir='+str(remote), 'ls-tree', '-r', '--name-only', 'main']).splitlines()
        self.assertEqual(len(files), 7)
        self.assertFalse(any('.env' in path or '.json' in path for path in files))
        text = self.command(['--git-dir='+str(remote), 'show', 'main:README.md'])
        self.assertIn('2026-10-20.pdf', text)
        self.assertIn('2026-10-21.pdf', text)
        html = self.command(['--git-dir='+str(remote), 'show', 'main:'+archive_path(self.day)+'/index.html'])
        self.assertIn('href="2026-10-20.pdf"', html)
        self.assertFalse(list(self.private.glob('checkout-*')))
        self.assertFalse(list((self.private/'pending').iterdir()))

    def test_failed_push_keeps_pending_and_does_not_claim_synced(self):
        def fail(*args, **kwargs):
            raise RuntimeError('network unavailable')
        with patch('contest_daily.github_archive.git', side_effect=fail):
            result = sync_safely(self.root, self.public)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue((self.private/'pending'/self.day/(self.day+'.pdf')).exists())
        self.assertFalse(list(self.private.glob('checkout-*')))
        self.assertFalse((self.private/'receipts.json').exists())

    @unittest.skipUnless(shutil.which('git'), 'requires Git')
    def test_product_home_is_preserved_and_history_paths_work_after_daily_push(self):
        remote = self.remote()
        seed = self.base/'seed'
        homepage = '<!-- competitor-daily:product-home -->\n# Install the skill\n'
        (seed/'README.md').write_text(homepage, encoding='utf-8')
        (seed/'index.html').write_text('<h1>Product home</h1>', encoding='utf-8')
        self.command(['add', '.'], seed)
        self.command(['commit', '-m', 'product'], seed)
        self.command(['push', 'origin', 'main'], seed)
        from contest_daily.github_archive import git as actual_git
        def local_git(args, cwd, env):
            if args[0] == 'clone': args = [*args[:-2], str(remote), args[-1]]
            return actual_git(args, cwd, env)
        with patch('contest_daily.github_archive.git', side_effect=local_git):
            synchronize(self.root, self.public)
        self.assertEqual(self.command(['--git-dir='+str(remote), 'show', 'main:README.md']), homepage.strip())
        self.assertIn('Product home', self.command(['--git-dir='+str(remote), 'show', 'main:index.html']))
        history = self.command(['--git-dir='+str(remote), 'show', 'main:archive/index.html'])
        self.assertIn('href="../2026/10/Week-43/2026-10-20/"', history)


if __name__ == '__main__':
    unittest.main()
