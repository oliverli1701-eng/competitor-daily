import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from contest_daily.core import load_catalog, save_json
from contest_daily.catalog_io import import_catalog
from contest_daily.workspace import init_workspace, confirm_catalog, confirmed_catalog, catalog_digest, add_source, runtime_settings, demo
from contest_daily.__main__ import previous_snapshot


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'my-college'
        init_workspace(self.root, '测试大学', '设计学院')

    def import_one(self, **changes):
        source = Path(self.temp.name)/'list.json'
        row = {'id': 17, 'name': '自主创意赛', 'suggested_level': '校级重点'}
        row.update(changes)
        save_json(source, {'records': [row]})
        import_catalog(source, self.root)

    def test_init_keeps_identity_editable_and_never_copies_real_key(self):
        value = json.loads((self.root/'config/profile.json').read_text(encoding='utf-8'))
        self.assertEqual(value['university'], '测试大学')
        self.assertEqual(value['college'], '设计学院')
        self.assertEqual(value['website_url'], '')
        self.assertIn('DEEPSEEK_API_KEY=\n', (self.root/'.env').read_text(encoding='utf-8'))
        with self.assertRaises(ValueError): init_workspace(self.root, '其他', '学院')

    def test_pending_or_edited_catalog_cannot_run_and_confirm_builds_sources(self):
        self.import_one(official_urls=['https://organizer.example/'])
        with self.assertRaises(ValueError): load_catalog(self.root)
        confirm_catalog(self.root)
        self.assertEqual(load_catalog(self.root)[0]['levels'], ['校级重点'])
        self.assertFalse(load_catalog(self.root)[0]['conflict'])
        registry = json.loads((self.root/'config/source_registry.json').read_text(encoding='utf-8'))
        self.assertEqual(registry['17']['trusted_domains'], ['organizer.example'])
        value = confirmed_catalog(self.root)
        value['records'][0]['name'] = '另一比赛'
        save_json(self.root/'config/catalog.json', value)
        with self.assertRaises(ValueError): confirmed_catalog(self.root)

    def test_source_presets_match_names_and_never_old_school_ids(self):
        self.import_one()
        presets = {'其他学院比赛': {'trusted_domains':['wrong.example']}}
        with patch('contest_daily.workspace.source_presets', return_value=presets):
            confirm_catalog(self.root)
        registry = json.loads((self.root/'config/source_registry.json').read_text(encoding='utf-8'))
        self.assertNotIn('trusted_domains', registry['17'])

    def test_changed_catalog_cannot_inherit_wrong_competition_history(self):
        self.import_one()
        confirm_catalog(self.root)
        save_json(self.root/'data/state/2026-10-19.json', {'events':{'old-id':{}}, 'catalog_sha256':'other-school'})
        self.assertIsNone(previous_snapshot(self.root,'2026-10-20'))
        save_json(self.root/'data/state/2026-10-19.json', {'events':{}, 'catalog_sha256':catalog_digest(confirmed_catalog(self.root))})
        self.assertIsNotNone(previous_snapshot(self.root,'2026-10-20'))

    def test_settings_cli_override_validation_and_source_registration(self):
        save_json(self.root/'config/runtime.json', {'workers':2, 'deadline_days':14})
        self.assertEqual(runtime_settings(self.root, {'workers':1})['workers'], 1)
        self.assertEqual(runtime_settings(self.root, {})['deadline_days'], 14)
        with self.assertRaises(ValueError): runtime_settings(self.root, {'workers':10})
        self.import_one()
        confirm_catalog(self.root)
        add_source(self.root,17,'https://news.organizer.example/notice','organizer.example')
        with self.assertRaises(ValueError): add_source(self.root,17,'https://other.example/','organizer.example')

    def test_offline_demo_never_calls_api_or_creates_real_catalog_or_history(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('demo must be offline')):
            output = demo(self.root)
        self.assertTrue(output.with_suffix('.html').is_file())
        self.assertTrue(output.with_suffix('.pdf').is_file())
        text = output.with_suffix('.html').read_text(encoding='utf-8')
        self.assertIn('测试大学设计学院', text)
        self.assertIn('DEMO / 演示日报', text)
        self.assertIn('校园创新应用挑战赛（演示）', text)
        self.assertNotIn('美国大学生数学建模竞赛', text)
        self.assertFalse((self.root/'config/catalog.json').exists())
        self.assertFalse((self.root/'data/state').exists())
        with self.assertRaises(ValueError): demo(self.root)


if __name__ == '__main__': unittest.main()
