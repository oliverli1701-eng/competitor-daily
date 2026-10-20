import copy
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

from contest_daily.__main__ import scan_live
from contest_daily.core import CST


class FakeWeb:
    """Return local fixtures while recording every requested page."""

    def __init__(self, search_results=()):
        self.search_results = list(search_results)
        self.requested = []

    def search(self, query):
        return copy.deepcopy(self.search_results)

    def document(self, url):
        self.requested.append(url)
        return {
            "url": url,
            "text": "报名自2026年10月1日开始，2026年10月20日截止。",
            "links": [],
            "sha256": "fixture",
            "content_type": "text/html",
        }


class FakeClient:
    def __init__(self, candidates=()):
        self.candidates = list(candidates)
        self.documents = []

    def extract(self, competition, documents, as_of):
        self.documents = copy.deepcopy(documents)
        return copy.deepcopy(self.candidates)


class ScanLiveTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 15, 21, 30, tzinfo=CST)
        self.competition = {
            "name": "测试竞赛",
            "ids": [1],
            "levels": ["A类"],
            "conflict": False,
        }
        self.seed = "https://official.example/seed"
        self.valid = {
            "competition_ids": [1],
            "edition": "2026",
            "track": "有效赛道",
            "title": "测试竞赛报名通知",
            "registration_start": "2026-10-01",
            "registration_end": "2026-10-20",
            "sources": [{
                "url": self.seed,
                "title": "官方报名通知",
                "published_date": "2026-10-01",
            }],
        }

    def scan(self, registry, client, web):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            return scan_live(
                Path(folder), [self.competition], self.now,
                {"1": registry}, client, web, max_pages=4,
            )

    def test_bad_record_does_not_discard_valid_sibling_and_is_reported(self):
        bad = copy.deepcopy(self.valid)
        bad.update(track="日期无效赛道", registration_end="not-a-date")
        client = FakeClient([self.valid, bad])

        events, coverage = self.scan(
            {"trusted_domains": ["official.example"], "urls": [self.seed]},
            client, FakeWeb(),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["track"], "有效赛道")
        self.assertEqual(events[0]["registration_end"], "2026-10-20")
        self.assertEqual(events[0]["verified_as_of"], self.now.isoformat())
        self.assertEqual(len(coverage), 1)
        self.assertEqual(coverage[0]["competition_id"], 1)
        self.assertEqual(coverage[0]["result"], "verified_event")
        self.assertIn("未采用", coverage[0]["note"])
        self.assertIn("not-a-date", coverage[0]["note"])

    def test_new_search_notice_is_fetched_even_when_four_seeds_fill_page_budget(self):
        seeds = [f"https://official.example/old-{number}" for number in range(4)]
        new_notice = "https://official.example/new-notice"
        web = FakeWeb([{"url": new_notice, "title": "今日新报名通知"}])
        client = FakeClient()

        _, coverage = self.scan(
            {"trusted_domains": ["official.example"], "urls": seeds},
            client, web,
        )

        self.assertIn(new_notice, web.requested)
        self.assertIn(new_notice, [document["url"] for document in client.documents])
        self.assertIn(new_notice, coverage[0]["urls"])
        self.assertTrue(set(seeds) & set(web.requested))
        self.assertLessEqual(len(web.requested), 4)

    def test_official_rule_attachment_is_read_before_older_news(self):
        rules = 'https://official.example/rules.pdf'
        class RuleWeb(FakeWeb):
            def document(inner, url):
                result = super().document(url)
                if url == self.seed:
                    result['link_details'] = [{'url': rules, 'title': '附件1：参赛指南'}]
                return result
        web = RuleWeb()
        client = FakeClient()
        self.scan({'trusted_domains':['official.example'], 'urls':[self.seed] + [f'https://official.example/old-{i}' for i in range(4)]}, client, web)
        self.assertEqual(web.requested[:2], [self.seed, rules])
        self.assertIn(rules, [d['url'] for d in client.documents])


if __name__ == "__main__":
    unittest.main()
