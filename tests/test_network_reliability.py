import copy
import json
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from contest_daily.network import (DeepSeekClient, ExtractionError, FetchError, WebClient,
                                   extraction_fingerprint)


URL = "https://official.example/notice"
COMPETITION = {"ids": [1], "name": "测试竞赛"}
TEXT = "2026年10月15日发布。测试竞赛现接受报名，报名截止2026年10月20日。比赛原定2026年11月1日。"


def raw_event(text=TEXT):
    return {"competition_ids": [1], "edition": "2026", "track": "主赛", "title": "测试竞赛报名通知",
            "registration_end": "2026-10-20", "registration_open_confirmed": True, "status_as_of": "2026-10-15",
            "sources": [{"url": URL, "published_date": "2026-10-15"}],
            "evidence": [{"field": "registration_end", "url": URL, "quote": "报名截止2026年10月20日"},
                         {"field": "registration_open_confirmed", "url": URL, "quote": "现接受报名，报名截止2026年10月20日"},
                         {"field": "published_date", "url": URL, "quote": "2026年10月15日发布"}]}


def response(events):
    return json.dumps({"model": "fixture-model", "usage": {"prompt_tokens": 10, "completion_tokens": 10},
                       "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"events": events}, ensure_ascii=False)}}]}).encode(), Message(), "https://api.deepseek.com/chat/completions"


class IncrementalCacheTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key-never-written", "DEEPSEEK_MODEL": "fixture-model"})
        self.env.start()
        self.client = DeepSeekClient(Path(self.folder.name), WebClient())
        self.docs = [{"url": URL, "text": TEXT}]

    def tearDown(self):
        self.env.stop()
        self.folder.cleanup()

    def test_identical_body_reuses_cache_across_days_without_refreshing_confirmation(self):
        with patch.object(WebClient, "request", return_value=response([raw_event()])) as request:
            first = self.client.extract(COMPETITION, self.docs, "2026-10-15T20:00:00+08:00")
            second = self.client.extract(COMPETITION, self.docs, "2026-10-16T20:00:00+08:00")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(first[0]["status_as_of"], "2026-10-15")
        self.assertEqual(second[0]["status_as_of"], "2026-10-15")
        self.assertTrue(self.client.last_extraction["cache_hit"])
        files = list(Path(self.folder.name).rglob("*.json"))
        self.assertTrue(files)
        self.assertNotIn("test-key-never-written", "".join(p.read_text(encoding="utf-8") for p in files))

    def test_expired_confirmation_is_removed_on_cache_hit(self):
        with patch.object(WebClient, "request", return_value=response([raw_event()])) as request:
            self.client.extract(COMPETITION, self.docs, "2026-10-15T20:00:00+08:00")
            expired = self.client.extract(COMPETITION, self.docs, "2026-10-21T20:00:00+08:00")
        self.assertEqual(request.call_count, 1)
        self.assertFalse(expired[0]["registration_open_confirmed"])
        self.assertIsNone(expired[0]["status_as_of"])

    def test_body_model_or_competition_change_invalidates_cache(self):
        base = extraction_fingerprint(COMPETITION, self.docs, "m1")[0]
        for competition, docs, model in [({"ids": [2], "name": "另一竞赛"}, self.docs, "m1"),
                                          (COMPETITION, [{"url": URL, "text": TEXT + "报名延期。"}], "m1"),
                                          (COMPETITION, self.docs, "m2")]:
            self.assertNotEqual(base, extraction_fingerprint(competition, docs, model)[0])
        # Whitespace-only formatting has no effect on semantic body cache identity.
        self.assertEqual(extraction_fingerprint(COMPETITION, [{"url": URL, "text": "some  content"}], "m1")[0],
                         extraction_fingerprint(COMPETITION, [{"url": URL, "text": "some\ncontent"}], "m1")[0])

    def test_future_notice_waits_until_publish_date_without_another_model_call(self):
        docs = [{"url": URL, "text": TEXT, "published_date": "2026-10-17"}]
        with patch.object(WebClient, "request", return_value=response([raw_event()])) as request:
            future = self.client.extract(COMPETITION, docs, "2026-10-16T20:00:00+08:00")
            current = self.client.extract(COMPETITION, docs, "2026-10-17T20:00:00+08:00")
        self.assertEqual(future, [])
        self.assertEqual(len(current), 1)
        self.assertFalse(current[0]["registration_open_confirmed"])
        self.assertEqual(request.call_count, 1)

    def test_cache_made_later_cannot_publish_future_source_on_historical_run(self):
        docs = [{"url": URL, "text": TEXT, "published_date": "2026-10-15"}]
        with patch.object(WebClient, "request", return_value=response([raw_event()])) as request:
            self.client.extract(COMPETITION, docs, "2026-10-16T20:00:00+08:00")
            historical = self.client.extract(COMPETITION, docs, "2026-10-14T20:00:00+08:00")
        self.assertEqual(historical, [])
        self.assertEqual(request.call_count, 1)

    def test_valid_empty_result_differs_from_bad_json(self):
        with patch.object(WebClient, "request", return_value=response([])):
            self.assertEqual(self.client.extract(COMPETITION, self.docs, "2026-10-15"), [])
        self.assertEqual(self.client.last_extraction["status"], "no_current_notice")
        changed = [{"url": URL, "text": TEXT + "后续公告。"}]
        bad = json.dumps({"choices": [{"message": {"content": "<html>error</html>"}, "finish_reason": "stop"}]}).encode(), Message(), URL
        with patch.object(WebClient, "request", return_value=bad):
            with self.assertRaisesRegex(ExtractionError, "不能据此认定"):
                self.client.extract(COMPETITION, changed, "2026-10-15")

    def test_later_observation_of_undated_notice_is_not_historical_evidence(self):
        event = raw_event()
        event["sources"][0]["published_date"] = None
        event["evidence"] = [p for p in event["evidence"] if p["field"] != "published_date"]
        with patch.object(WebClient, "request", return_value=response([event])) as request:
            self.client.extract(COMPETITION, self.docs, "2026-10-16T20:00:00+08:00")
            historical = self.client.extract(COMPETITION, self.docs, "2026-10-15T20:00:00+08:00")
        self.assertEqual(historical, [])
        self.assertEqual(request.call_count, 1)

    def test_reasoning_and_output_policy_are_part_of_cache_identity(self):
        base = extraction_fingerprint(COMPETITION, self.docs, "m", "low", 24000)[0]
        self.assertNotEqual(base, extraction_fingerprint(COMPETITION, self.docs, "m", "high", 24000)[0])
        self.assertNotEqual(base, extraction_fingerprint(COMPETITION, self.docs, "m", "low", 32000)[0])

    def test_extraction_payload_uses_configured_effort_and_budget(self):
        with patch.dict(os.environ, {"DEEPSEEK_REASONING_EFFORT": "low", "DEEPSEEK_MAX_TOKENS": "24000"}):
            client = DeepSeekClient(Path(self.folder.name), WebClient())
        with patch.object(WebClient, "request", return_value=response([raw_event()])) as request:
            client.extract(COMPETITION, self.docs, "2026-10-15")
        payload = json.loads(request.call_args.args[1])
        self.assertEqual(payload["model"], "fixture-model")
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["max_tokens"], 24000)

    def test_review_effort_is_independent_from_extraction(self):
        with patch.dict(os.environ, {"DEEPSEEK_REASONING_EFFORT": "low", "DEEPSEEK_REVIEW_REASONING_EFFORT": "max"}):
            client = DeepSeekClient(Path(self.folder.name), WebClient())
        review_response = json.dumps({"choices": [{"message": {"content": '{"findings":[],"summary":"ok"}'}, "finish_reason": "stop"}]}).encode(), Message(), URL
        with patch.object(WebClient, "request", return_value=review_response) as request:
            client.review({"events": []})
        self.assertEqual(json.loads(request.call_args.args[1])["reasoning_effort"], "max")

    def test_invalid_effort_or_budget_fails_before_any_request(self):
        for settings in ({"DEEPSEEK_REASONING_EFFORT": "medium"}, {"DEEPSEEK_REVIEW_REASONING_EFFORT": "invalid"},
                         {"DEEPSEEK_MAX_TOKENS": "bad"}, {"DEEPSEEK_MAX_TOKENS": "0"}):
            with patch.dict(os.environ, settings), patch.object(WebClient, "request") as request:
                with self.assertRaises(ValueError):
                    DeepSeekClient(Path(self.folder.name), WebClient())
                request.assert_not_called()

    def test_truncation_is_logged_not_cached_and_not_retried(self):
        truncated, headers, url = response([])
        body = json.loads(truncated)
        body["choices"][0]["finish_reason"] = "length"
        with patch.object(WebClient, "request", return_value=(json.dumps(body).encode(), headers, url)) as request:
            with self.assertRaisesRegex(ExtractionError, "未完整结束"):
                self.client.extract(COMPETITION, self.docs, "2026-10-15")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.client.last_extraction["status"], "failed")
        self.assertEqual(self.client.last_extraction["reason"], "truncated")
        self.assertIn("elapsed_seconds", self.client.last_extraction)
        self.assertEqual(list((Path(self.folder.name) / "data/cache/llm").glob("*.json")), [])
        usage = [json.loads(line) for line in (Path(self.folder.name) / "data/state/api_usage.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(usage[0]["finish_reason"], "length")
        self.assertEqual(usage[0]["usage"]["completion_tokens"], 10)
        self.assertEqual(usage[0]["operation"], "extract")


class LifecycleEvidenceTests(unittest.TestCase):
    def checked(self, event, text):
        return DeepSeekClient.validate_evidence({"events": [event]}, [{"url": URL, "text": text}], COMPETITION)[0]

    def test_est_pm_time_remains_precise_and_displays_on_correct_beijing_day(self):
        from contest_daily.core import parse_at
        event=raw_event();event['registration_end']='2027-01-28T15:00:00-05:00'
        quote='Registration Deadline: Before 3:00 p.m. EST on Thursday, January 28, 2027.'
        event['evidence']=[{'field':'registration_end','url':URL,'quote':quote}]
        result=self.checked(event,quote)
        self.assertEqual(result['registration_end'],event['registration_end'])
        self.assertEqual(parse_at(result['registration_end']).isoformat(),'2027-01-29T04:00:00+08:00')

    def test_unread_source_cannot_support_a_fact_when_other_sources_are_valid(self):
        event=raw_event();other='https://unread.example/notice'
        event['sources'].append({'url':other})
        event['deliverables']=['虚构作品文件']
        event['evidence'].append({'field':'deliverables','url':other,'quote':'虚构作品文件'})
        result=self.checked(event,TEXT)
        self.assertEqual(result['deliverables'],[])
        self.assertEqual(result['sources'][0]['url'],URL)
        self.assertEqual(result['discarded_source_count'],1)

    def test_chinese_mode_is_normalized_but_still_requires_actual_mode_evidence(self):
        event=raw_event();event['participation_mode']='线下'
        event['evidence'].append({'field':'participation_mode','url':URL,'quote':'比赛采用线下现场考试'})
        self.assertEqual(self.checked(event,TEXT+'比赛采用线下现场考试')['participation_mode'],'offline')
        self.assertEqual(self.checked(event,TEXT)['participation_mode'],'unknown')

    def test_partial_month_range_is_discarded_without_losing_valid_deadline(self):
        event=raw_event();event['phase_period']={'start':None,'end':'2026-10-20T23:59:59+08:00'}
        event['evidence'].append({'field':'phase_period','url':URL,'quote':'报名截止2026年10月20日'})
        result=self.checked(event,TEXT)
        self.assertIsNone(result['phase_period'])
        self.assertEqual(result['registration_end'],'2026-10-20')

    def test_model_cannot_self_authorize_lifecycle_clears_or_track_identity(self):
        event = raw_event()
        event.update(lifecycle="canceled", cleared_fields=["registration_end"], track_id="fake-1",
                     verified_control_fields=["lifecycle", "cleared_fields", "track_id"])
        result = self.checked(event, TEXT)
        for key in ("lifecycle", "cleared_fields", "track_id", "verified_control_fields"):
            self.assertNotIn(key, result)

    def test_quoted_unrelated_text_cannot_authorize_controls(self):
        event = raw_event()
        event.update(lifecycle="canceled", cleared_fields=["registration_end"])
        event["evidence"].extend([{"field": "lifecycle", "url": URL, "quote": "报名截止2026年10月20日"},
                                  {"field": "cleared_fields.registration_end", "url": URL, "quote": "报名截止2026年10月20日"}])
        result = self.checked(event, TEXT)
        self.assertNotIn("verified_control_fields", result)

    def test_explicit_cancellation_and_specific_deadline_clear_are_authorized(self):
        text = TEXT + "本届竞赛取消。原报名截止日期作废，作品提交截止日期仍然有效。"
        event = raw_event()
        event.update(lifecycle="canceled", cleared_fields=["registration_end", "submission_deadline"])
        event["evidence"].extend([{"field": "lifecycle", "url": URL, "quote": "本届竞赛取消"},
                                  {"field": "cleared_fields", "url": URL, "quote": "原报名截止日期作废"}])
        result = self.checked(event, text)
        self.assertEqual(result["lifecycle"], "canceled")
        self.assertEqual(result["cleared_fields"], ["registration_end"])
        self.assertEqual(result["verified_control_fields"], ["lifecycle", "cleared_fields"])

    def test_negated_cancellation_does_not_cancel(self):
        text = TEXT + "本届竞赛不会取消，按原计划正常举行。"
        event = raw_event()
        event["lifecycle"] = "canceled"
        event["evidence"].append({"field": "lifecycle", "url": URL, "quote": "本届竞赛不会取消"})
        self.assertNotIn("lifecycle", self.checked(event, text))

    def test_clear_cannot_borrow_revocation_from_another_clause(self):
        quote = "原报名截止日期作废，作品提交截止日期仍然有效"
        event = raw_event()
        event["cleared_fields"] = ["registration_end", "submission_deadline"]
        event["evidence"].append({"field": "cleared_fields", "url": URL, "quote": quote})
        self.assertEqual(self.checked(event, TEXT + quote)["cleared_fields"], ["registration_end"])

    def test_revocation_of_cancellation_is_not_a_new_cancellation(self):
        quote = "本届竞赛取消通知现已作废"
        event = raw_event()
        event["lifecycle"] = "canceled"
        event["evidence"].append({"field": "lifecycle", "url": URL, "quote": quote})
        self.assertNotIn("lifecycle", self.checked(event, TEXT + quote))

    def test_postponement_and_restoration_require_their_own_semantics(self):
        for lifecycle, quote in [("postponed", "本届比赛延期，赛程时间另行通知"), ("active", "本届竞赛恢复正常举行")]:
            event = raw_event()
            event["lifecycle"] = lifecycle
            event["evidence"].append({"field": "lifecycle", "url": URL, "quote": quote})
            self.assertEqual(self.checked(event, TEXT + quote)["lifecycle"], lifecycle)
        event = raw_event()
        event["lifecycle"] = "active"
        event["evidence"].append({"field": "lifecycle", "url": URL, "quote": "现接受报名，报名截止2026年10月20日"})
        self.assertNotIn("lifecycle", self.checked(event, TEXT))

    def test_track_id_requires_explicit_source_identifier(self):
        text = TEXT + "赛题编号：AI-03，名称：智能分析。"
        event = raw_event()
        event["track_id"] = "AI-03"
        event["evidence"].append({"field": "track_id", "url": URL, "quote": "赛题编号：AI-03"})
        result = self.checked(event, text)
        self.assertEqual(result["track_id"], "AI-03")
        self.assertIn("track_id", result["verified_control_fields"])

    def test_validation_does_not_mutate_raw_cache_contents(self):
        event = raw_event()
        event["sources"][0]["published_date"] = "2027-01-01"
        original = copy.deepcopy(event)
        self.checked(event, TEXT)
        self.assertEqual(event, original)

    def test_model_notes_need_their_own_literal_evidence(self):
        supported = "参赛队伍需要提交原创作品"
        event = raw_event()
        event["notes"] = [supported, "预计本校学生都可免费参赛", "更短的总结"]
        event["evidence"].append({"field": "notes", "url": URL, "quote": supported})
        result = self.checked(event, TEXT + supported)
        self.assertEqual(result["notes"], [supported])

    def test_ungrounded_notes_in_old_raw_cache_are_revalidated(self):
        event = raw_event()
        event["notes"] = ["全国总决赛线上举办，报名费全免"]
        self.assertEqual(self.checked(event, TEXT)["notes"], [])


class DocumentFailureTests(unittest.TestCase):
    def fixture(self, payload):
        message = Message()
        message["Content-Type"] = "application/json; charset=utf-8"
        return patch.object(WebClient, "request", return_value=(json.dumps(payload, ensure_ascii=False).encode(), message, URL))

    def test_json_error_is_not_readable_notice(self):
        with self.fixture({"code": 403, "message": "请登录后重试。" * 20}):
            with self.assertRaisesRegex(FetchError, "未返回可读取通知正文"):
                WebClient().document(URL)

    def test_publication_metadata_is_retained_without_dynamic_counters(self):
        with self.fixture({"data": {"title": "报名通知", "publishTime": "2026-10-17 10:00:00", "content": "<p>报名需提交技术报告。</p>" * 10, "viewCount": 999999}}):
            doc = WebClient().document(URL)
        self.assertEqual(doc["published_date"], "2026-10-17")
        self.assertNotIn("999999", doc["text"])
        self.assertIn("报名通知", doc["text"])


if __name__ == "__main__":
    unittest.main()
