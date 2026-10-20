import copy
import json
import unittest
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from contest_daily.core import CST, build_report, parse_at, validate_event
from contest_daily.presentation import build_cards, short_date, clean_fact
from contest_daily.product_ui import node_key, ui_variant
from contest_daily.render import to_html, markdown, event_variant


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 15, 22, tzinfo=CST)
        self.catalog = [{"ids": [24], "name": "华为ICT大赛", "levels": ["A类"], "conflict": False}]
        self.raw = {"competition_ids": [24], "edition": "2026-2027", "title": "华为ICT大赛", "track": "实践赛", "registration_start": "2026-09-01", "registration_end": "2026-10-31", "eligibility": ["3名学生和1名教师，同校组队"], "sources": [{"url": "https://official.example/notice", "title": "通知"}]}

    def make(self, extra=None):
        events = [validate_event(self.raw, {24}, self.now)]
        if extra:
            events.append(validate_event(extra, {24}, self.now))
        return build_report(events, [], self.catalog, self.now, None)

    def test_cancellation_remains_visible_without_actionable_facts(self):
        self.raw={'competition_ids':[24],'edition':'2026','title':'取消通知','track':'主赛','lifecycle':'canceled','verified_control_fields':['lifecycle'],'sources':[{'url':'https://official.example/notice'}]}
        report=self.make();cards=build_cards(report)
        self.assertEqual(len(cards),1)
        self.assertIsNone(cards[0]['next'])
        self.assertIn('已取消',to_html('',report))

    def test_stale_track_shows_original_verification_date(self):
        self.raw.update(stale=True,verified_as_of='2026-10-14T08:00:00+08:00')
        report=self.make()
        for page in (to_html('',report),markdown(report)):
            self.assertIn('2026-10-14',page)
            self.assertIn('上次核验',page)

    def test_empty_fields_and_process_notes_are_not_published(self):
        self.raw['notes'] = ['本轮未核实具体作品，请见来源通知', '每人只能加入一支队伍', '缺少可核对原文证据，已置空字段：registration_start, phase_period']
        r = self.make()
        for text in (to_html('', r), markdown(r)):
            for phrase in ('官方暂未明确', '本轮未核实', '提交材料：', '费用：', '提醒：phase_period'):
                self.assertNotIn(phrase, text)
            self.assertIn('每人只能加入一支队伍', text)

    def test_tracks_are_grouped_and_deadlines_remain_distinct(self):
        second = {**copy.deepcopy(self.raw), 'track': '挑战赛', 'registration_end': '2026-11-30'}
        r = self.make(second)
        self.assertEqual(len(build_cards(r)), 1)
        page = to_html('', r)
        self.assertEqual(page.count('<article class="contest-card"'), 1)
        self.assertIn('10.31', page)
        self.assertIn('11.30', page)
        self.assertIn('data-section="ongoing"', page)

    def test_known_mode_is_only_badged_when_supported(self):
        class ModeReader(HTMLParser):
            def __init__(self):
                super().__init__()
                self.modes = []
                self.current = None

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if tag == 'span' and 'mode-tag' in attributes.get('class', '').split():
                    self.current = {'text':'', 'hidden':'hidden' in attributes}
                    self.modes.append(self.current)

            def handle_data(self, text):
                if self.current is not None:
                    self.current['text'] += text

            def handle_endtag(self, tag):
                if tag == 'span':
                    self.current = None

        def mode_tags(report):
            reader = ModeReader()
            reader.feed(to_html('', report))
            return reader.modes

        self.assertEqual(mode_tags(self.make()), [{'text':'', 'hidden':True}])
        self.raw['participation_mode'] = 'online'
        self.assertEqual(mode_tags(self.make()), [{'text':'线上', 'hidden':False}])

    def test_seconds_and_foreign_timezone_are_preserved_for_readers(self):
        self.assertEqual(short_date('2026-10-23T23:59:59+08:00', 2026), '10.23 23:59:59')
        self.assertEqual(short_date('2027-01-28T15:00:00-05:00', 2026), '2027.01.29 04:00')

    def test_html_and_attribute_values_are_escaped(self):
        self.raw['eligibility'] = ['<img src=x onerror=alert(1)> "data-open"']
        page = to_html('', self.make())
        self.assertNotIn('<img src=x', page)
        self.assertIn('&lt;img', page)

    def test_known_months_are_kept_when_only_precise_time_is_missing(self):
        text = clean_fact('校赛5月底前、省赛6月底前、全国决赛11月前，具体终审日期未核实')
        self.assertIn('全国决赛11月前', text)
        self.assertNotIn('未核实', text)

    def test_rules_notice_remains_searchable_without_registration_dates(self):
        report = json.loads((Path(__file__).resolve().parent / 'fixtures/archived-public-report.json').read_text(encoding='utf-8'))
        cards = build_cards(report)
        rules = next(card for card in cards if card['ids'] == (11,))
        self.assertEqual(len(rules['events']), 1)
        event = rules['events'][0]
        self.assertIsNone(event['view_next'])
        self.assertIn('2027 年足式机器人挑战赛-V1.0', event['view_notes'][0])
        variant = event_variant(event, rules['name'])
        self.assertEqual(variant['key'], '11:2027:ROBOCON 2027 规则预告')
        self.assertEqual(variant['label'], 'ROBOCON 2027 规则预告')
        self.assertEqual(variant['levels'], ['A类'])
        for term in ('robocon', '2027', '足式机器人', '女娲补天'):
            self.assertIn(term, variant['search'])
        self.assertFalse(variant['open'])

    def test_overlapping_sections_and_record_total_have_distinct_units(self):
        report = json.loads((Path(__file__).resolve().parent / 'fixtures/archived-public-report.json').read_text(encoding='utf-8'))
        cards = build_cards(report)
        self.assertEqual(len(cards), 18)
        self.assertEqual(sum(len(card['events']) for card in cards), 34)
        self.assertEqual({event['key'] for card in cards for event in card['events']}, {event['key'] for event in report['events']})
        counts = {section:sum(section in card['sections'] for card in cards) for section in report['groups']}
        self.assertEqual(counts, {'new_registration':0, 'updates':2, 'deadlines':2, 'ongoing':11})
        aic = next(card for card in cards if card['ids'] == (38,))
        self.assertIn('ongoing', aic['sections'])
        self.assertIn('deadlines', aic['sections'])
        self.assertIn('registration_closed', {event['status'] for event in aic['events']})

    def test_national_registration_node_keeps_local_earlier_cutoff_notice(self):
        report = json.loads((Path(__file__).resolve().parent / 'fixtures/archived-public-report.json').read_text(encoding='utf-8'))
        card = next(card for card in build_cards(report) if card['ids'] == (39,))
        variant = ui_variant(card['events'][0], card['name'], 2026, event_variant, parse_at(report['as_of']))
        self.assertEqual(variant['node']['label'], '全国报名节点（各校/赛区可更早截止）')
        self.assertEqual(variant['node']['track'], '全国初赛')
        self.assertEqual(variant['node']['date_main'].replace(' ', ''), '10月19日')
        self.assertIn('各校/赛区可更早截止', to_html('', report))

    def test_same_instant_registration_and_submission_are_one_action(self):
        report = json.loads((Path(__file__).resolve().parent / 'fixtures/archived-public-report.json').read_text(encoding='utf-8'))
        card = next(card for card in build_cards(report) if card['ids'] == (37,))
        node = ui_variant(card['events'][0], card['name'], 2026, event_variant, parse_at(report['as_of']))['node']
        self.assertEqual(node['kind_label'], '报名 / 作品截止')
        self.assertEqual(node['label'], '报名 / 作品截止')
        self.assertEqual(node['clock'], '23:59:59')

    def test_action_dates_keep_cross_year_and_deadline_priority(self):
        report = json.loads((Path(__file__).resolve().parent / 'fixtures/archived-public-report.json').read_text(encoding='utf-8'))
        cards = build_cards(report)
        mcm = next(card for card in cards if card['ids'] == (1,))
        robot = next(card for card in cards if card['ids'] == (15,))
        now = parse_at(report['as_of'])
        future_deadline = ui_variant(mcm['events'][0], mcm['name'], 2026, event_variant, now)['node']
        near_schedule = ui_variant(robot['events'][0], robot['name'], 2026, event_variant, now)['node']
        self.assertEqual(future_deadline['date_main'].replace(' ', ''), '2027年1月29日')
        self.assertEqual(future_deadline['clock'], '04:00')
        self.assertLess(node_key(future_deadline), node_key(near_schedule))
        self.assertLess(node_key(near_schedule), node_key(None))

    def test_deadline_highlight_uses_report_window(self):
        report = json.loads((Path(__file__).resolve().parent / 'fixtures/archived-public-report.json').read_text(encoding='utf-8'))
        card = next(card for card in build_cards(report) if card['ids'] == (39,))
        now = parse_at(report['as_of'])
        self.assertFalse(ui_variant(card['events'][0], card['name'], 2026, event_variant, now, window=3)['node']['urgent'])
        self.assertTrue(ui_variant(card['events'][0], card['name'], 2026, event_variant, now, window=4)['node']['urgent'])

    def test_rendered_metadata_covers_all_known_records(self):
        class RecordReader(HTMLParser):
            def __init__(self):
                super().__init__()
                self.variants = []

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if tag == 'article' and 'contest-card' in attributes.get('class', '').split():
                    self.variants.append(json.loads(attributes['data-variants']))

        report = json.loads((Path(__file__).resolve().parent / 'fixtures/archived-public-report.json').read_text(encoding='utf-8'))
        page = to_html('', report)
        reader = RecordReader()
        reader.feed(page)
        self.assertEqual(len(reader.variants), 18)
        self.assertEqual(sum(map(len, reader.variants)), 34)
        self.assertEqual({variant['key'] for variants in reader.variants for variant in variants}, {event['key'] for event in report['events']})
        self.assertIn('学院 A 类', page)
        self.assertIn('学院 B 类', page)
        self.assertIn('栏目可重叠', page)


if __name__ == '__main__':
    unittest.main()
