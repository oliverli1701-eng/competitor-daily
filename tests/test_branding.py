import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from contest_daily.branding import DEFAULT_PROFILE, load_profile, normalize_profile, profile_css
from contest_daily.core import CST, build_report, validate_event
from contest_daily.render import markdown, to_html, write_report


class BrandingTests(unittest.TestCase):
    def report(self):
        now = datetime(2026, 10, 20, 8, tzinfo=CST)
        event = validate_event({
            'competition_ids': [1], 'edition': '2026', 'track': '线上赛',
            'title': '演示竞赛', 'registration_end': '2026-10-25',
            'deliverables': ['作品说明书'],
            'sources': [{'url': 'https://official.example/notice', 'title': '官方通知'}],
        }, {1}, now)
        return build_report([event], [], [{'ids': [1], 'name': '演示竞赛', 'levels': ['A类'], 'conflict': False}], now, None)

    def test_legacy_workspace_keeps_original_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(load_profile(Path(folder)), DEFAULT_PROFILE)
        page = to_html('', self.report())
        self.assertIn('兰州大学信息科学与工程学院 · 学科竞赛追踪', page)
        self.assertIn('<title>竞赛日报 · 2026-10-20</title>', page)

    def test_profile_rejects_unsafe_css_or_unsupported_schema(self):
        for invalid in ({'accent_color': '#123456;}</style><script>x</script>'}, {'schema_version': 2}, {'schema_version': True}, {'report_title': ''}, {'college': 3}, {'website_url': 'javascript:alert(1)'}):
            with self.subTest(profile=invalid), self.assertRaises(ValueError):
                normalize_profile(invalid)
        result = normalize_profile({'accent_color': '#3B5CC4', 'custom_plugin': {'enabled': True}})
        self.assertEqual(result['accent_color'], '#3b5cc4')
        self.assertTrue(result['custom_plugin']['enabled'])
        self.assertIn("[data-theme='dark']", profile_css(result))

    def test_html_escapes_all_user_identity_fields(self):
        report = self.report()
        report['branding'] = {'university': '示例大学', 'college': '<script>bad</script>学院', 'report_title': '竞赛<快报>', 'brand_name': '情报&专刊', 'english_title': 'BRIEF <test>', 'subtitle': '学院"精选', 'footer_text': '我的<页脚>'}
        page = to_html('', report)
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;学院', page)
        self.assertIn('<title>竞赛&lt;快报&gt; · 2026-10-20</title>', page)
        self.assertIn('BRIEF &lt;test&gt;', page)
        self.assertIn('我的&lt;页脚&gt;', page)
        self.assertNotIn('<script>bad</script>', page)
        self.assertNotIn('兰州大学', page)

    def test_workspace_profile_is_included_in_all_outputs_with_demo_label(self):
        report = self.report()
        report['demo'] = True
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config').mkdir()
            (root / 'config/profile.json').write_text(json.dumps({
                'university': '示例大学', 'college': '人工智能学院',
                'report_title': '学院竞赛快报', 'brand_name': '竞赛雷达',
                'accent_color': '#315b82', 'footer_text': '自己的学院日报',
            }, ensure_ascii=False), encoding='utf-8')
            with patch.dict(os.environ, {'REPORT_PDF_EXPORT': '1'}):
                stem = write_report(root, report)
            self.assertNotIn('branding', report, 'Rendering must not mutate caller-owned report')
            html = stem.with_suffix('.html').read_text(encoding='utf-8')
            saved = json.loads(stem.with_suffix('.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['branding']['college'], '人工智能学院')
            self.assertIn('示例大学人工智能学院', html)
            self.assertIn('DEMO / 演示日报', html)
            self.assertIn('--accent:#315b82', html)
            self.assertIn('非实时赛事资讯', stem.with_suffix('.md').read_text(encoding='utf-8'))
            reader = PdfReader(stem.with_suffix('.pdf'))
            pdf_text = ''.join(page.extract_text() for page in reader.pages)
            for phrase in ('示例大学人工智能学院', '学院竞赛快报', '非实时赛事资讯', '自己的学院日报'):
                self.assertIn(phrase, pdf_text)
            self.assertNotIn('cuiying42.com', pdf_text)
            self.assertNotIn('兰州大学', pdf_text)
            self.assertEqual(reader.metadata.title, '学院竞赛快报 · 2026-10-20')

    def test_report_branding_takes_precedence_over_render_stage_root(self):
        report = self.report()
        report['branding'] = {'university': '我校', 'college': '我的学院'}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'REPORT_PDF_EXPORT': '0'}):
            stem = write_report(Path(folder), report)
            self.assertIn('我校我的学院', stem.with_suffix('.html').read_text(encoding='utf-8'))
        self.assertIn('我校我的学院', markdown(report))


if __name__ == '__main__':
    unittest.main()
