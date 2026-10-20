import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from pypdf import PdfReader
from contest_daily.core import CST,validate_event,build_report
from contest_daily.render import write_report
from contest_daily.server import publish


class PdfTests(unittest.TestCase):
    def test_pdf_contains_chinese_embedded_font_and_official_clickable_source(self):
        day=datetime(2026,10,19,9,tzinfo=CST)
        event=validate_event({'competition_ids':[1],'edition':'2026','track':'线上赛','title':'测试竞赛','eligibility':['在校大学生'],'deliverables':['作品说明书 PDF'],'registration_end':'2026-10-23','sources':[{'url':'https://official.example/notice','title':'官方通知'}]}, {1},day)
        report=build_report([event],[],[{'ids':[1],'name':'测试竞赛','levels':['A类'],'conflict':False}],day,None)
        with tempfile.TemporaryDirectory() as folder:
            stem=write_report(Path(folder),report);pdf=PdfReader(stem.with_suffix('.pdf'))
            self.assertIn('竞赛日报',pdf.pages[0].extract_text())
            self.assertIn('作品说明书',''.join(p.extract_text() for p in pdf.pages))
            fonts=[font.get_object() for p in pdf.pages for font in p['/Resources']['/Font'].get_object().values()]
            self.assertTrue(any('/FontFile2' in font['/FontDescriptor'].get_object() for font in fonts if '/FontDescriptor' in font))
            self.assertTrue(any(p.get('/Annots') for p in pdf.pages))
            self.assertIn('2026-10-19.pdf',stem.with_suffix('.html').read_text(encoding='utf-8'))
            self.assertTrue(json.loads(stem.with_suffix('.json').read_text(encoding='utf-8'))['pdf_available'])

    def test_missing_required_pdf_preserves_public_page(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'app';public=Path(folder)/'public';public.mkdir()
            (public/'index.html').write_text('last good')
            path=root/'reports/2026';path.mkdir(parents=True)
            (path/'2026-10-19.json').write_text(json.dumps({'date':'2026-10-19','run_quality':{'passed':True},'pdf_available':True}))
            for ext in ('.html','.md'):(path/('2026-10-19'+ext)).write_text('new')
            with self.assertRaises(ValueError):publish(root,public,'2026-10-19')
            self.assertEqual((public/'index.html').read_text(),'last good')

    def test_long_track_keeps_every_fact_and_source_without_empty_tail_page(self):
        day=datetime(2026,10,20,8,tzinfo=CST)
        event=validate_event({'competition_ids':[1],'edition':'2026','track':'完整材料',
            'title':'长赛项分页测试','registration_end':'2026-10-25',
            'deliverables':[f'材料第{i}项：详细提交说明，用于检验跨页内容完整保留。'*3 for i in range(50)],
            'sources':[{'url':'https://official.example/notice','title':'末尾官方来源'}]}, {1},day)
        report=build_report([event],[],[{'ids':[1],'name':'分页验证竞赛','levels':['A类'],'conflict':False}],day,None)
        with tempfile.TemporaryDirectory() as folder:
            stem=write_report(Path(folder),report)
            pages=PdfReader(stem.with_suffix('.pdf')).pages
            text=''.join(p.extract_text() for p in pages)
            self.assertGreater(len(pages),1)
            self.assertIn('材料第49项',text)
            self.assertIn('末尾官方来源',pages[-1].extract_text())


if __name__=='__main__':unittest.main()
