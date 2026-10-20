import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from contest_daily.runtime import RunLock, quality_check, publish_staged


class RuntimeTests(unittest.TestCase):
    def test_all_stale_run_is_blocked_even_if_sources_answered(self):
        self.assertFalse(quality_check([], [{'competition_id':1,'result':'no_current_notice'}], [{'ids':[1]}])['passed'])

    def test_failed_source_is_not_counted_as_success(self):
        q=quality_check([{'key':'fresh'}],[{'competition_id':1,'result':'verified_event'},{'competition_id':2,'result':'failed'},{'competition_id':3,'result':'inconclusive'}],[{'ids':[1]},{'ids':[2]},{'ids':[3]}])
        self.assertFalse(q['passed']);self.assertAlmostEqual(q['successful_source_fraction'],.3333)

    def test_duplicate_catalog_ids_have_one_denominator(self):
        q=quality_check([{}],[{'competition_id':35,'result':'verified_event'},{'competition_id':40,'result':'verified_event'}],[{'ids':[35,40]}])
        self.assertEqual(q['competition_count'],1);self.assertTrue(q['passed'])

    def test_missing_scope_is_blocked(self):
        self.assertFalse(quality_check([{}],[],[{'ids':[1]}])['passed'])

    def test_incomplete_stage_cannot_overwrite_last_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);public=root/'reports/2026';public.mkdir(parents=True)
            old=public/'2026-10-16.html';old.write_text('LAST SUCCESS')
            stage=root/'stage/reports/2026';stage.mkdir(parents=True);(stage/'2026-10-16.html').write_text('incomplete')
            with self.assertRaises(ValueError):publish_staged(root/'stage',root,'2026-10-16')
            self.assertEqual(old.read_text(),'LAST SUCCESS')

    def test_runtime_lock_released_for_next_run(self):
        with tempfile.TemporaryDirectory() as folder:
            with RunLock(Path(folder)):
                with self.assertRaises(ValueError):
                    with RunLock(Path(folder)):pass
            with RunLock(Path(folder)):pass

    def test_replace_failure_rolls_back_reports_and_snapshot(self):
        for fail_at in (2, 4):
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); stage=root/'stage'; day='2026-10-17'
                for suffix in ('md','html','json'):
                    p=root/'reports/2026'/f'{day}.{suffix}';p.parent.mkdir(parents=True,exist_ok=True);p.write_text('old-'+suffix)
                    p=stage/'reports/2026'/f'{day}.{suffix}';p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}' if suffix=='json' else 'new-'+suffix)
                state=root/'data/state'/f'{day}.json';state.parent.mkdir(parents=True);state.write_text('old-state')
                original=Path.replace;calls=[]
                def fail_once(source,target):
                    if source.suffix=='.publishing':
                        calls.append(source)
                        if len(calls)==fail_at:raise OSError('injected storage failure')
                    return original(source,target)
                with patch.object(Path,'replace',fail_once), self.assertRaises(OSError):
                    publish_staged(stage,root,day,snapshot={'events':{}})
                for suffix in ('md','html','json'):
                    self.assertEqual((root/'reports/2026'/f'{day}.{suffix}').read_text(),'old-'+suffix)
                self.assertEqual(state.read_text(),'old-state')
                self.assertEqual(list(root.rglob('*.publishing')),[])
