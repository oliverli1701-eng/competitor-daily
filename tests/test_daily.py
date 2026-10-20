import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from contest_daily.core import CST, build_report, derive_status, factual_fingerprint, parse_at, upcoming_deadlines, validate_event
from contest_daily.network import DeepSeekClient, PageText, trusted_url
from contest_daily.render import markdown, to_html


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 15, 21, 30, tzinfo=CST)
        self.catalog = [{"name": "测试竞赛", "ids": [35, 40], "levels": ["A类", "B类"], "conflict": True}]
        self.raw = {"competition_ids": [35, 40], "edition": "2026", "title": "测试竞赛", "registration_start": "2026-10-01",
                    "registration_end": "2026-10-20T20:00:00+08:00", "participation_mode": "unknown",
                    "sources": [{"url": "https://official.example/notice", "published_date": "2026-10-01", "title": "公告"}]}
        self.event = validate_event(self.raw, {35, 40}, self.now)

    def test_exact_deadline_has_expired(self):
        self.event["registration_end"] = "2026-10-15T20:00:00+08:00"
        self.assertEqual(derive_status(self.event, self.now), "registration_closed")
        self.assertEqual(upcoming_deadlines(self.event, self.now), [])

    def test_date_only_deadline_is_inclusive(self):
        self.event["registration_end"] = "2026-10-15"
        self.assertEqual(derive_status(self.event, self.now), "registration_open")
        self.assertEqual(upcoming_deadlines(self.event, self.now)[0]["days_left"], 0)

    def test_foreign_timezone_is_converted(self):
        self.assertEqual(parse_at("2027-01-28T15:00:00-05:00").isoformat(), "2027-01-29T04:00:00+08:00")

    def test_no_start_date_not_assumed_open(self):
        self.event["registration_start"] = None
        self.assertEqual(derive_status(self.event, self.now), "unknown")
        self.event.update(registration_open_confirmed=True, status_as_of="2026-10-15")
        self.assertEqual(derive_status(self.event, self.now), "registration_open")
        self.event["status_as_of"] = "2026-10-14"
        self.assertEqual(derive_status(self.event, self.now), "unknown")

    def test_month_precision_does_not_fabricate_days(self):
        self.event["phase_period"] = {"start": "2026-09", "end": "2026-10"}
        self.assertEqual(derive_status(self.event, self.now), "in_progress")
        self.assertIsNone(self.event["competition_start"])

    def test_explicit_null_month_period_is_allowed(self):
        self.event["phase_period"] = None
        self.assertEqual(derive_status(self.event, self.now), "registration_open")

    def test_bootstrap_is_not_new_registration(self):
        report = build_report([self.event], [], self.catalog, self.now, None)
        self.assertTrue(report["bootstrap"])
        self.assertEqual(report["groups"]["new_registration"], [])
        self.assertEqual(report["groups"]["updates"], [])
        self.assertTrue(report["events"][0]["level_conflict"])

    def test_new_opening_today_and_same_day_official_notice(self):
        self.event["registration_start"] = "2026-10-15"
        self.event["sources"][0]["published_date"] = "2026-10-15"
        report = build_report([self.event], [], self.catalog, self.now, None)
        self.assertEqual(len(report["groups"]["new_registration"]), 1)
        self.assertEqual(len(report["groups"]["updates"]), 1)

    def test_only_factual_changes_trigger_update(self):
        old = copy.deepcopy(self.event)
        previous = {"events": {old["key"]: old}}
        self.event["verified_as_of"] = "2026-10-15"
        self.event["sources"][0]["supports"] = ["抓取时的新元数据"]
        report = build_report([self.event], [], self.catalog, self.now, previous)
        self.assertEqual(report["groups"]["updates"], [])
        self.event["registration_end"] = "2026-10-21"
        report = build_report([self.event], [], self.catalog, self.now, previous)
        self.assertEqual(len(report["groups"]["updates"]), 1)

    def test_future_source_is_rejected(self):
        self.raw["sources"][0]["published_date"] = "2026-10-16"
        with self.assertRaises(ValueError):
            validate_event(self.raw, {35, 40}, self.now)

    def test_chronology_is_rejected(self):
        self.raw["registration_start"] = "2026-10-25"
        with self.assertRaises(ValueError):
            validate_event(self.raw, {35, 40}, self.now)

    def test_unseen_model_source_is_rejected(self):
        documents = [{"url": "https://official.example/notice", "text": "报名截止2026年10月20日。"}]
        raw = copy.deepcopy(self.event)
        raw["sources"] = [{"url": "https://invented.example/notice"}]
        with self.assertRaises(ValueError):
            DeepSeekClient.validate_evidence({"events": [raw]}, documents, {"ids": [35, 40]})

    def test_unsupported_model_facts_are_removed(self):
        documents = [{"url": "https://official.example/notice", "text": "报名截止2026年10月20日。"}]
        raw = copy.deepcopy(self.event)
        raw["evidence"] = [{"field": "registration_end", "url": documents[0]["url"], "quote": documents[0]["text"]}]
        result = DeepSeekClient.validate_evidence({"events": [raw]}, documents, {"ids": [35, 40]})[0]
        self.assertEqual(result["registration_end"], "2026-10-20")
        self.assertIsNone(result["registration_start"])

    def test_wrong_date_cannot_borrow_an_unrelated_quote(self):
        documents = [{"url": "https://official.example/notice", "text": "报名截止2026年10月20日。"}]
        raw = copy.deepcopy(self.event)
        raw["registration_end"] = "2027-12-31"
        raw["evidence"] = [{"field": "registration_end", "url": documents[0]["url"], "quote": documents[0]["text"]}]
        result = DeepSeekClient.validate_evidence({"events": [raw]}, documents, {"ids": [35, 40]})[0]
        self.assertIsNone(result["registration_end"])

    def test_phase_change_is_an_important_update(self):
        previous = {"events": {self.event["key"]: copy.deepcopy(self.event)}}
        self.event["phase_period"] = {"start": "2026-10", "end": "2026-11"}
        report = build_report([self.event], [], self.catalog, self.now, previous)
        self.assertEqual(len(report["groups"]["updates"]), 1)
        self.assertIn("phase_period", report["events"][0]["changed_fields"])

    def test_domains_cannot_be_spoofed(self):
        self.assertTrue(trusted_url("https://www.official.example/a", ["official.example"]))
        self.assertFalse(trusted_url("https://official.example.evil.com/a", ["official.example"]))

    def test_html_is_escaped_and_four_sections_exist(self):
        self.event["title"] = '<script>alert(1)</script>'
        report = build_report([self.event], [], self.catalog, self.now, None)
        text = markdown(report)
        page = to_html(text, report)
        self.assertNotIn("<script>alert(1)</script>", page)
        for name in ("新开放报名", "赛事重要更新", "临近截止提醒", "正在进行的比赛"):
            self.assertIn(name, page)


if __name__ == "__main__":
    unittest.main()
