"""Exercise the real CLI publishing path with local scan fixtures only."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from contest_daily import __main__ as cli
from contest_daily.core import CST, save_json, validate_event
from contest_daily.scanner import scan_live
from contest_daily.network import FetchError


class CliRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.now = datetime(2026, 10, 17, 8, tzinfo=CST)
        self.day = self.now.date().isoformat()
        save_json(self.root / '兰州大学信息学院学生学科竞赛分级列表.json', {'records':[
            {'id':101, 'name':'测试实践竞赛', 'suggested_level':'A类'},
            {'id':102, 'name':'测试另一竞赛', 'suggested_level':'B类'},
        ]})
        self.old = self.event(deliverables=['既有作品 PDF'])
        self.fresh = self.event(deliverables=['新要求：作品 PDF 和盖章报名表'])
        for day in ('2026-10-16', self.day):
            save_json(self.root / 'data/state' / (day + '.json'), {'as_of':day+'T07:00:00+08:00', 'events':{self.old['key']:self.old}})
        self.public = self.root / 'reports/2026'
        self.public.mkdir(parents=True)
        for suffix in ('.html', '.md', '.json'):
            (self.public / (self.day+suffix)).write_text('LAST GOOD PUBLICATION '+suffix, encoding='utf-8')

    def event(self, **changes):
        raw = {'competition_ids':[101], 'edition':'2026', 'title':'实践赛报名通知', 'track':'实践赛',
               'registration_start':'2026-10-01', 'registration_end':'2026-10-25',
               'eligibility':['在校大学生'], 'sources':[{'url':'https://official.example/notice', 'title':'官方通知', 'published_date':'2026-10-16'}]}
        raw.update(changes)
        return validate_event(raw, {101,102}, self.now)

    def args(self, **changes):
        values = dict(root=self.root, at=self.now.isoformat(), date=None, from_research=None,
                      ids=None, limit=None, max_pages=4, workers=1, resume=None,
                      source_timeout=1, min_success_ratio=.5, deadline_days=7,
                      audit_with_deepseek=False, preview=False, allow_empty=False)
        values.update(changes)
        return SimpleNamespace(**values)

    def public_and_state_bytes(self):
        paths = [*self.public.glob(self.day+'.*'), *self.root.joinpath('data/state').glob('????-??-??.json')]
        return {str(path.relative_to(self.root)):path.read_bytes() for path in paths}

    def invoke(self, events, coverage, scan_error=None, **options):
        # No key loading, request, search, model call or billable operation.
        with mock.patch.object(cli, 'load_env'), mock.patch.object(cli, 'WebClient', return_value=object()), mock.patch.object(cli, 'DeepSeekClient', return_value=object()), mock.patch.object(cli, 'scan_live', side_effect=scan_error, return_value=(copy.deepcopy(events), copy.deepcopy(coverage))), redirect_stdout(io.StringIO()):
            return cli.run(self.args(**options))

    def summaries(self):
        return [json.loads(path.read_text(encoding='utf-8')) for path in self.root.glob('data/runs/*/summary.json')]

    def test_saved_run_can_be_rebuilt_without_network_and_without_redating_facts(self):
        origin=self.root/'data/runs/source-run'
        save_json(origin/'collected.json',{'as_of':self.now.isoformat(),'events':[self.fresh],'coverage':[{'competition_id':101,'result':'verified_event'},{'competition_id':102,'result':'no_current_notice'}]})
        with mock.patch.object(cli,'load_env'), mock.patch.object(cli,'scan_live',side_effect=AssertionError('must not rescan')), mock.patch.object(cli,'DeepSeekClient',side_effect=AssertionError('must not call model')), redirect_stdout(io.StringIO()):
            cli.run(self.args(from_run=origin,at=None))
        summary=self.summaries()[0]
        self.assertEqual(summary['status'],'published')
        self.assertEqual(summary['api_usage']['calls'],0)
        self.assertEqual(summary['as_of'],self.now.isoformat())
        self.assertEqual(summary['source_run_id'],'source-run')

    def test_complete_source_failure_preserves_publication_and_both_snapshots(self):
        protected = self.public_and_state_bytes()
        with self.assertRaisesRegex(ValueError, '质量门槛未通过'):
            self.invoke([], [{'competition_id':i, 'result':'failed', 'urls':[], 'note':'source fixture failed'} for i in (101,102)])
        self.assertEqual(self.public_and_state_bytes(), protected)
        summary = self.summaries()[0]
        self.assertEqual(summary['status'], 'blocked')
        self.assertFalse(summary['published'])
        self.assertEqual(summary['fresh_events'], 0)
        self.assertEqual(summary['stale_events'], 1)
        staged = Path(summary['output'])
        self.assertTrue(staged.is_file())
        self.assertIn('preview', staged.parts)

    def test_partial_scan_is_preview_and_cannot_replace_publication_or_state(self):
        protected = self.public_and_state_bytes()
        self.invoke([self.fresh], [{'competition_id':101, 'result':'verified_event', 'urls':['https://official.example/notice']}], ids='101')
        self.assertEqual(self.public_and_state_bytes(), protected)
        summary = self.summaries()[0]
        self.assertEqual(summary['status'], 'preview')
        self.assertFalse(summary['published'])
        self.assertEqual(summary['scope_count'], 1)
        self.assertEqual(summary['quality']['results']['not_checked'], 1)

    def test_successful_full_scan_publishes_exact_staged_files_then_current_snapshot(self):
        prior_day = (self.root / 'data/state/2026-10-16.json').read_bytes()
        self.invoke([self.fresh], [{'competition_id':101, 'result':'verified_event'}, {'competition_id':102, 'result':'no_current_notice'}])
        summary = self.summaries()[0]
        self.assertEqual(summary['status'], 'published')
        self.assertTrue(summary['published'])
        self.assertTrue(summary['quality']['passed'])
        self.assertEqual(Path(summary['output']), self.public / (self.day+'.html'))
        run_dir = next(self.root.glob('data/runs/*/summary.json')).parent
        for suffix in ('.md', '.html', '.json'):
            self.assertEqual((self.public/(self.day+suffix)).read_bytes(), (run_dir/'preview/reports/2026'/(self.day+suffix)).read_bytes())
        snapshot = json.loads((self.root/'data/state'/(self.day+'.json')).read_text(encoding='utf-8'))
        self.assertEqual(snapshot['events'][self.fresh['key']]['deliverables'], self.fresh['deliverables'])
        self.assertFalse(snapshot['events'][self.fresh['key']]['stale'])
        self.assertEqual((self.root / 'data/state/2026-10-16.json').read_bytes(), prior_day)

    def test_explicit_preview_preserves_publication_even_when_quality_passes(self):
        protected = self.public_and_state_bytes()
        self.invoke([self.fresh], [{'competition_id':101, 'result':'verified_event'}, {'competition_id':102, 'result':'no_current_notice'}], preview=True)
        self.assertEqual(self.public_and_state_bytes(), protected)
        summary = self.summaries()[0]
        self.assertTrue(summary['quality']['passed'])
        self.assertEqual(summary['status'], 'preview')
        self.assertFalse(summary['published'])

    def test_same_day_successful_rerun_keeps_one_stable_record_and_unchanged_snapshot(self):
        coverage = [{'competition_id':101, 'result':'verified_event'}, {'competition_id':102, 'result':'no_current_notice'}]
        self.invoke([self.fresh], coverage)
        first = (self.root/'data/state'/(self.day+'.json')).read_bytes()
        self.invoke([self.fresh], coverage)
        self.assertEqual((self.root/'data/state'/(self.day+'.json')).read_bytes(), first)
        summaries = self.summaries()
        self.assertEqual(len(summaries), 2, 'same --at and process must still retain two independent run records')
        self.assertEqual(len({summary['run_id'] for summary in summaries}), 2)
        snapshot = json.loads(first)
        self.assertEqual(list(snapshot['events']), [self.fresh['key']])
        report = json.loads((self.public/(self.day+'.json')).read_text(encoding='utf-8'))
        self.assertEqual(len(report['events']), 1)
        self.assertEqual(report['events'][0]['key'], self.fresh['key'])

    def test_model_records_rejected_by_core_are_failures_not_no_current_notice(self):
        bad = {**self.fresh, 'registration_end':'not-a-date'}
        class LocalWeb:
            def search(self, query):
                return []

            def document(self, url):
                return {'url':url, 'text':'Official fixture, registration date is deliberately invalid in the model candidate.', 'links':[], 'link_details':[], 'sha256':'fixture'}

        class LocalClient:
            def extract(self, competition, documents, as_of):
                return [bad]

        catalog = [{'ids':[101], 'name':'测试实践竞赛', 'levels':['A类'], 'conflict':False}]
        registry = {'101':{'trusted_domains':['official.example'], 'urls':['https://official.example/notice']}}
        with redirect_stdout(io.StringIO()):
            events, coverage = scan_live(self.root, catalog, self.now, registry, LocalClient(), LocalWeb())
        self.assertEqual(events, [])
        self.assertEqual(coverage[0]['result'], 'failed')
        self.assertEqual(coverage[0]['failed_stage'], 'extraction')

    def test_scan_exception_retains_failure_summary_and_releases_run_lock(self):
        protected = self.public_and_state_bytes()
        with self.assertRaisesRegex(FetchError, 'fixture scan aborted'):
            self.invoke([], [], scan_error=FetchError('fixture scan aborted'))
        self.assertEqual(self.public_and_state_bytes(), protected)
        summary = self.summaries()[0]
        self.assertEqual(summary['status'], 'failed')
        self.assertIn('fixture scan aborted', summary['error'])
        self.assertEqual(summary['api_usage']['calls'], 0)
        # The failure must not leave the lock held for a later successful run.
        self.invoke([self.fresh], [{'competition_id':101, 'result':'verified_event'}, {'competition_id':102, 'result':'no_current_notice'}], preview=True)
        self.assertEqual({summary['status'] for summary in self.summaries()}, {'failed', 'preview'})

    def test_merge_conflict_records_failure_without_publishing_a_partial_report(self):
        protected = self.public_and_state_bytes()
        conflict = self.event(deliverables=['与同批另一记录冲突的作品要求'])
        with self.assertRaisesRegex(ValueError, '质量门槛'):
            self.invoke([self.fresh, conflict], [{'competition_id':101, 'result':'verified_event'}, {'competition_id':102, 'result':'no_current_notice'}])
        self.assertEqual(self.public_and_state_bytes(), protected)
        summary = self.summaries()[0]
        self.assertEqual(summary['status'], 'blocked')
        self.assertEqual(summary['coverage'][0]['failed_stage'],'identity')

    def test_one_identity_conflict_is_quarantined_while_other_competition_publishes(self):
        conflict=self.event(deliverables=['同一时间的矛盾要求'])
        other=validate_event({**self.fresh,'competition_ids':[102],'title':'另一赛事'}, {101,102},self.now)
        self.invoke([self.fresh,conflict,other],[{'competition_id':101,'result':'verified_event'},{'competition_id':102,'result':'verified_event'}])
        report=json.loads((self.public/(self.day+'.json')).read_text(encoding='utf-8'))
        self.assertTrue(report['run_quality']['passed'])
        self.assertEqual(len(report['identity_conflicts']),1)
        old=next(e for e in report['events'] if 101 in e['competition_ids'])
        self.assertTrue(old['stale'])
        self.assertEqual(report['coverage'][0]['failed_stage'],'identity')
        self.assertTrue(any(102 in e['competition_ids'] and not e['stale'] for e in report['events']))


if __name__ == '__main__':
    unittest.main()
