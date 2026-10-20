import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from contest_daily.core import CST
from contest_daily.scanner import scan_live, checkpoint_signature


class ScannerRuntimeTests(unittest.TestCase):
    def test_local_notices_with_same_track_keep_their_institution_scope(self):
        urls=['https://one.example/notice','https://two.example/notice']
        events=[{'competition_ids':[21],'edition':'2026','title':'校内选拔通知','track':'主赛','sources':[{'url':u}]} for u in urls]
        class Web:
            def search(self,q):return []
            def document(self,u):return {'url':u,'text':'校内选拔通知正文'*10,'links':[],'link_details':[]}
        class Client:
            def extract(self,*args):return copy.deepcopy(events)
        config={'trusted_domains':['one.example','two.example'],'urls':urls,'source_scopes':dict(zip(urls,['甲校选拔','乙校选拔']))}
        with tempfile.TemporaryDirectory() as folder:
            found,coverage=scan_live(Path(folder),[{'ids':[21],'name':'学创杯'}],datetime(2026,10,17,tzinfo=CST),{'21':config},Client(),Web(),quiet=True)
        self.assertEqual(len({e['key'] for e in found}),2)
        self.assertEqual({e['source_scope'] for e in found},{'甲校选拔','乙校选拔'})
        self.assertEqual(coverage[0]['accepted_records'],2)

    def test_checkpoint_reuse_requires_same_model_and_extraction_profile(self):
        day=datetime(2026,10,17,tzinfo=CST)
        client=SimpleNamespace(base='https://api.example',model='model-a',reasoning_effort='low',max_tokens=24000)
        baseline=checkpoint_signature({},4,day,client)
        client.model='model-b'
        self.assertNotEqual(baseline,checkpoint_signature({},4,day,client))
        client.model='model-a';client.reasoning_effort='high'
        self.assertNotEqual(baseline,checkpoint_signature({},4,day,client))

    def test_all_explicit_priority_notices_are_read_before_the_first_notices_attachments(self):
        a,b,pdf='https://one.example/a','https://one.example/b','https://one.example/attachment.pdf'
        visited=[]
        class Web:
            def search(self,q):return []
            def document(self,u):
                visited.append(u)
                return {'url':u,'text':'官方报名通知正文'*10,'links':[],'link_details':[{'url':pdf,'title':'竞赛规则'}] if u==a else []}
        class Client:
            def extract(self,*args):return []
        with tempfile.TemporaryDirectory() as folder:
            scan_live(Path(folder),[{'ids':[1],'name':'竞赛'}],datetime(2026,10,17,tzinfo=CST),{'1':{'trusted_domains':['one.example'],'urls':[a],'priority_urls':[a,b]}},Client(),Web(),2,quiet=True)
        self.assertEqual(visited,[a,b])


if __name__=='__main__':unittest.main()
