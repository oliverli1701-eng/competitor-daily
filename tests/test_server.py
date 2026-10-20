import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contest_daily.core import save_json
from contest_daily.server import publish, maintain, remove_owned, publication_delay
from datetime import datetime
from contest_daily.core import CST


class ServerTests(unittest.TestCase):
    def test_prepared_report_waits_until_0800_but_manual_late_run_does_not_wait(self):
        self.assertEqual(publication_delay(datetime(2026,10,20,7,45,tzinfo=CST),'08:00'),900)
        self.assertEqual(publication_delay(datetime(2026,10,20,8,10,tzinfo=CST),'08:00'),0)
        with self.assertRaises(ValueError):publication_delay(datetime.now(CST),'25:00')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'app';self.root.mkdir()
        self.public=Path(self.tmp.name)/'public';self.public.mkdir()
        self.day='2026-10-17';self.source=self.root/'reports/2026';self.source.mkdir(parents=True)
        save_json(self.source/(self.day+'.json'),{'date':self.day,'run_quality':{'passed':True}})
        for ext in ('.html','.md'):(self.source/(self.day+ext)).write_text('new'+ext)

    def test_index_shares_html_storage_and_relative_downloads_exist(self):
        publish(self.root,self.public,self.day)
        self.assertTrue(os.path.samefile(self.public/'index.html',self.public/(self.day+'.html')))
        self.assertTrue((self.public/(self.day+'.md')).is_file())
        self.assertEqual(list(self.public.glob('.*deploying')),[])

    def test_failed_quality_cannot_replace_live_index(self):
        (self.public/'index.html').write_text('last good')
        save_json(self.source/(self.day+'.json'),{'date':self.day,'run_quality':{'passed':False}})
        with self.assertRaises(ValueError):publish(self.root,self.public,self.day)
        self.assertEqual((self.public/'index.html').read_text(),'last good')

    def test_interrupted_copy_removes_partial_temporary_file(self):
        (self.public/'index.html').write_text('last good')
        def fail(src,dest):
            dest.write_bytes(b'partial')
            raise OSError('disk write failed')
        with patch('contest_daily.server.shutil.copyfile',side_effect=fail),self.assertRaises(OSError):publish(self.root,self.public,self.day)
        self.assertEqual(list(self.public.glob('.*deploying')),[])
        self.assertEqual((self.public/'index.html').read_text(),'last good')

    def test_failed_index_switch_rolls_back_same_day_files_without_backup_files(self):
        for ext in ('.html','.md','.json'):(self.public/(self.day+ext)).write_text('old'+ext)
        (self.public/'index.html').write_text('old index')
        original=Path.replace
        def fail(source,target):
            if source.name=='.index.deploying':raise OSError('injected failure')
            return original(source,target)
        with patch.object(Path,'replace',fail),self.assertRaises(OSError):publish(self.root,self.public,self.day)
        self.assertEqual((self.public/'index.html').read_text(),'old index')
        for ext in ('.html','.md','.json'):self.assertEqual((self.public/(self.day+ext)).read_text(),'old'+ext)
        self.assertEqual(list(self.public.glob('.*deploying')),[])
        self.assertEqual(list(self.public.glob('.*recovering')),[])

    def test_maintenance_bounds_history_cache_and_keeps_only_failed_checkpoints(self):
        for day in range(1,11):
            (self.public/f'2026-10-{day:02d}.html').write_text('report')
            save_json(self.root/f'data/state/2026-10-{day:02d}.json',{})
        cache=self.root/'data/cache';cache.mkdir(parents=True)
        for i in range(4):(cache/f'{i}.json').write_bytes(b'x'*50)
        save_json(self.root/'data/runs/failure/checkpoints/1.json',{})
        save_json(self.root/'data/runs/failure/collected.json',{})
        save_json(self.root/'data/runs/old/summary.json',{})
        with patch('contest_daily.server.CACHE_LIMIT',100):maintain(self.root,self.public,'failure')
        self.assertEqual(len(list(self.public.glob('*.html'))),7)
        self.assertEqual(len(list((self.root/'data/state').glob('2026*.json'))),3)
        self.assertLessEqual(sum(p.stat().st_size for p in cache.glob('*')),100)
        self.assertTrue((self.root/'data/runs/failure/checkpoints/1.json').exists())
        self.assertFalse((self.root/'data/runs/failure/collected.json').exists())
        self.assertFalse((self.root/'data/runs/old').exists())
        self.assertFalse(self.source.exists())

    def test_cleanup_refuses_files_outside_application(self):
        other=Path(self.tmp.name)/'other';other.write_text('unrelated')
        with self.assertRaises(ValueError):remove_owned(other,self.root)
        self.assertTrue(other.exists())


if __name__=='__main__':unittest.main()
