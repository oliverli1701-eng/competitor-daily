import copy
import unittest
from datetime import datetime

from contest_daily.core import CST, build_report, derive_status, factual_fingerprint, validate_event
from contest_daily.state import merge_events


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.day1 = datetime(2026, 10, 15, 20, tzinfo=CST)
        self.day2 = datetime(2026, 10, 16, 20, tzinfo=CST)
        self.catalog = [{"ids":[24], "name":"测试竞赛", "levels":["A类"], "conflict":False}]
        self.base = {"competition_ids":[24], "edition":"2026", "title":"测试竞赛报名通知", "track":"实践赛", "registration_start":"2026-10-01", "registration_end":"2026-10-31", "eligibility":["同校3人组队"], "deliverables":["作品说明书 PDF"], "current_phase":"省赛阶段", "phase_period":{"start":"2026-10", "end":"2026-11"}, "milestones":[{"name":"省赛开始", "date":"2026-10-20"}], "sources":[{"url":"https://official.example/notice", "title":"报名通知", "published_date":"2026-10-01"}]}

    def event(self, changes=None, day=None, partial=False):
        raw = {"competition_ids":[24], "edition":"2026", "title":"测试竞赛后续通知", "track":"实践赛", "sources":copy.deepcopy(self.base["sources"])} if partial else copy.deepcopy(self.base)
        raw.update(changes or {})
        return validate_event(raw, {24}, day or self.day2)

    def snapshot(self, *events):
        return {"as_of":self.day1.isoformat(), "events":{event["key"]:copy.deepcopy(event) for event in events}}

    def test_explicit_edition_alias_preserves_official_display_and_stable_key(self):
        old = self.event()
        fresh = self.event({'edition':'第十一届'})
        merged = merge_events([fresh], self.snapshot(old), self.day2, {'edition_aliases':{'24':{'第十一届':'2026'}}})
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['key'], old['key'])
        self.assertEqual(merged[0]['edition'], '第十一届')

    def test_combined_baseline_retired_only_when_all_replacements_are_fresh(self):
        old = self.event({'track':'实践赛、创新赛'})
        a, b = self.event({'track':'实践赛'}), self.event({'track':'创新赛'})
        aliases = {'supersedes':{old['key']:[a['key'], b['key']]}}
        partial = merge_events([a], self.snapshot(old), self.day2, aliases)
        self.assertIn(old['key'], {e['key'] for e in partial})
        complete = merge_events([a,b], self.snapshot(old), self.day2, aliases)
        self.assertEqual({e['key'] for e in complete}, {a['key'],b['key']})
        self.assertTrue(all(old['key'] in e['superseded_keys'] for e in complete))

    def test_model_cannot_spoof_internal_alias_to_merge_unrelated_track(self):
        old = self.event()
        fresh = self.event({'track':'另一个赛道', 'track_aliases':['实践赛'], 'identity_aliases':[old['key']]})
        self.assertEqual(len(merge_events([fresh], self.snapshot(old), self.day2)), 2)

    def test_new_track_does_not_merge_merely_for_sharing_a_source(self):
        old = self.event(day=self.day1)
        fresh = self.event({"track":"挑战赛"})
        merged = merge_events([fresh], self.snapshot(old), self.day2)
        self.assertEqual(len(merged), 2)
        self.assertEqual({event["track"] for event in merged}, {"实践赛", "挑战赛"})
        self.assertTrue(next(event for event in merged if event["track"] == "实践赛")["stale"])

    def test_same_batch_later_dated_partial_notice_updates_entry_and_keeps_requirements(self):
        old=self.event({'entry_url':'https://official.example/old','sources':[{'url':'https://official.example/a','published_date':'2026-10-01'}]})
        new=self.event({'entry_url':'https://official.example/new','sources':[{'url':'https://official.example/b','published_date':'2026-10-02'}]},partial=True)
        merged=merge_events([new,old],None,self.day2)
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['entry_url'],'https://official.example/new')
        self.assertEqual(merged[0]['deliverables'],old['deliverables'])

    def test_punctuation_and_whitespace_variants_reuse_key(self):
        old = self.event({"track":"实践赛（本科组）"}, self.day1)
        fresh = self.event({"track":" 实践赛 ( 本科组 ) "})
        merged = merge_events([fresh], self.snapshot(old), self.day2)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["key"], old["key"])
        self.assertIn(fresh["key"], merged[0]["identity_aliases"])

    def test_explicit_label_alias_and_same_day_rerun_are_idempotent(self):
        old = self.event(day=self.day1)
        fresh = self.event({"track":"实践竞赛"})
        aliases = {"24":{"实践竞赛":"实践赛"}}
        first = merge_events([fresh], self.snapshot(old), self.day2, aliases)
        second = merge_events([fresh], self.snapshot(*first), self.day2, aliases)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["key"], old["key"])

    def test_official_track_id_survives_name_change_but_distinguishes_siblings(self):
        old = self.event({"track_id":"TASK-01", "verified_control_fields":["track_id"]}, self.day1)
        renamed = self.event({"track":"新的官方赛项名", "track_id":"TASK-01", "verified_control_fields":["track_id"]})
        distinct = self.event({"track":"实践赛", "track_id":"TASK-02", "verified_control_fields":["track_id"]})
        merged = merge_events([renamed, distinct], self.snapshot(old), self.day2)
        self.assertEqual(len(merged), 2)
        self.assertEqual(next(event for event in merged if event["track_id"] == "TASK-01")["key"], old["key"])

    def test_range_punctuation_is_not_erased_from_identity(self):
        old = self.event({"track":"赛题1-2"}, self.day1)
        fresh = self.event({"track":"赛题12"})
        self.assertEqual(len(merge_events([fresh], self.snapshot(old), self.day2)), 2)

    def test_identical_duplicate_is_idempotent_but_distinct_clear_operations_are_not_discarded(self):
        fresh = self.event(partial=True)
        self.assertEqual(len(merge_events([fresh, copy.deepcopy(fresh)], None, self.day2)), 1)
        clearing = self.event({"cleared_fields":["submission_deadline"], "verified_control_fields":["cleared_fields"]}, partial=True)
        with self.assertRaisesRegex(ValueError, "冲突"):
            merge_events([fresh, clearing], None, self.day2)

    def test_ambiguous_name_match_requires_an_explicit_key_alias(self):
        first = self.event({"track":"实践 赛"}, self.day1)
        second = self.event({"track":"实践赛"}, self.day1)
        fresh = self.event({"track":"实践　赛"})
        with self.assertRaisesRegex(ValueError, "歧义"):
            merge_events([fresh], self.snapshot(first, second), self.day2)
        merged = merge_events([fresh], self.snapshot(first, second), self.day2, {fresh["key"]:second["key"]})
        self.assertFalse(next(event for event in merged if event["key"] == second["key"])["stale"])

    def test_partial_notice_keeps_known_phase_and_updates_named_milestone(self):
        old = self.event(day=self.day1)
        fresh = self.event({"deliverables":["作品说明书 PDF，新增盖章页"], "milestones":[{"name":"省赛结束", "date":"2026-11-15"}]}, partial=True)
        current = merge_events([fresh], self.snapshot(old), self.day2)[0]
        self.assertEqual(current["current_phase"], old["current_phase"])
        self.assertEqual(current["phase_period"], old["phase_period"])
        self.assertEqual(current["eligibility"], old["eligibility"])
        self.assertEqual({item["name"] for item in current["milestones"]}, {"省赛开始", "省赛结束"})
        self.assertIn("新增盖章页", current["deliverables"][0])

    def test_verified_explicit_clear_prevents_carrying_the_old_deadline(self):
        old = self.event({"submission_deadline":"2026-10-25"}, self.day1)
        fresh = self.event({"cleared_fields":["submission_deadline"], "verified_control_fields":["cleared_fields"]}, partial=True)
        current = merge_events([fresh], self.snapshot(old), self.day2)[0]
        self.assertIsNone(current["submission_deadline"])
        self.assertIn("submission_deadline", current["cleared_fields_applied"])
        again = merge_events([self.event(partial=True)], self.snapshot(current), self.day2)[0]
        self.assertIsNone(again["submission_deadline"])

    def test_unverified_control_fields_cannot_cancel_clear_or_create_an_id(self):
        old = self.event({"submission_deadline":"2026-10-25"}, self.day1)
        fresh = self.event({"lifecycle":"canceled", "cleared_fields":["submission_deadline"], "track_id":"GUESS"}, partial=True)
        self.assertNotIn("lifecycle", fresh)
        self.assertNotIn("track_id", fresh)
        current = merge_events([fresh], self.snapshot(old), self.day2)[0]
        self.assertEqual(current["submission_deadline"], "2026-10-25")
        self.assertNotEqual(derive_status(current, self.day2), "canceled")

    def test_cancellation_removes_all_action_nodes_and_stays_canceled_until_verified_resume(self):
        old = self.event(day=self.day1)
        cancel = self.event({"lifecycle":"canceled", "verified_control_fields":["lifecycle"]}, partial=True)
        canceled = merge_events([cancel], self.snapshot(old), self.day2)[0]
        for field in ("registration_start", "registration_end", "competition_start", "competition_end", "submission_deadline", "phase_period", "entry_url"):
            self.assertIsNone(canceled[field])
        self.assertEqual(canceled["milestones"], [])
        self.assertEqual(derive_status(canceled, self.day2), "canceled")
        unconfirmed_resume = merge_events([self.event()], self.snapshot(canceled), self.day2)[0]
        self.assertEqual(derive_status(unconfirmed_resume, self.day2), "canceled")
        self.assertIsNone(unconfirmed_resume["registration_end"])
        resumed = merge_events([self.event({"lifecycle":"active", "verified_control_fields":["lifecycle"]})], self.snapshot(canceled), self.day2)[0]
        report = build_report([resumed], [], self.catalog, self.day2, self.snapshot(canceled))
        self.assertTrue(report["events"][0]["accepting_registration"])
        self.assertIn("lifecycle", report["events"][0]["changed_fields"])

    def test_postponed_without_new_dates_does_not_invent_a_replacement(self):
        old = self.event(day=self.day1)
        fresh = self.event({"lifecycle":"postponed", "verified_control_fields":["lifecycle"], "current_phase":"赛程延期，新日期另行通知"}, partial=True)
        current = merge_events([fresh], self.snapshot(old), self.day2)[0]
        self.assertEqual(derive_status(current, self.day2), "postponed")
        self.assertIsNone(current["registration_end"])
        self.assertIsNone(current["phase_period"])
        self.assertEqual(current["milestones"], [])
        report = build_report([current], [], self.catalog, self.day2, self.snapshot(old))
        self.assertFalse(report["events"][0]["accepting_registration"])
        self.assertEqual(report["groups"]["ongoing"], [])

    def test_postponement_preserves_only_explicit_new_nodes_and_still_pauses_registration(self):
        old = self.event(day=self.day1)
        fresh = self.event({"lifecycle":"postponed", "verified_control_fields":["lifecycle"], "competition_start":"2026-11-20"}, partial=True)
        current = merge_events([fresh], self.snapshot(old), self.day2)[0]
        self.assertEqual(current["competition_start"], "2026-11-20")
        self.assertIsNone(current["registration_end"])
        subsequent = merge_events([self.event(partial=True)], self.snapshot(current), self.day2)[0]
        self.assertEqual(subsequent["competition_start"], "2026-11-20")
        self.assertFalse(build_report([subsequent], [], self.catalog, self.day2, self.snapshot(current))["events"][0]["accepting_registration"])

    def test_explicit_registration_close_keeps_a_running_competition(self):
        old = self.event({"competition_start":"2026-10-10", "competition_end":"2026-11-20"}, self.day1)
        fresh = self.event({"lifecycle":"registration_closed", "verified_control_fields":["lifecycle"]}, partial=True)
        current = merge_events([fresh], self.snapshot(old), self.day2)[0]
        report = build_report([current], [], self.catalog, self.day2, self.snapshot(old))
        self.assertEqual(report["events"][0]["status"], "in_progress")
        self.assertFalse(report["events"][0]["accepting_registration"])
        self.assertEqual(report["groups"]["ongoing"], [current["key"]])

    def test_failed_refresh_preserves_history_without_new_or_update_announcements(self):
        old = self.event({"registration_start":"2026-10-16", "sources":[{"url":"https://official.example/notice", "published_date":"2026-10-16"}]}, self.day2)
        previous = self.snapshot(old)
        stale = merge_events([], previous, self.day2)
        report = build_report(stale, [], self.catalog, self.day2, previous)
        self.assertEqual(len(report["events"]), 1)
        self.assertTrue(report["events"][0]["stale"])
        self.assertEqual(report["events"][0]["change"], "stale")
        self.assertEqual(report["groups"]["new_registration"], [])
        self.assertEqual(report["groups"]["updates"], [])

    def test_reordered_requirements_are_not_important_factual_updates(self):
        old = self.event({"eligibility":["同校3人组队", "本科生"]}, self.day1)
        fresh = self.event({"eligibility":["本科生", "同校3人组队"], "title":"同赛事不同通知标题"})
        self.assertEqual(factual_fingerprint(old), factual_fingerprint(fresh))
        current = merge_events([fresh], self.snapshot(old), self.day2)[0]
        report = build_report([current], [], self.catalog, self.day2, self.snapshot(old))
        self.assertEqual(report["groups"]["updates"], [])


if __name__ == "__main__":
    unittest.main()
