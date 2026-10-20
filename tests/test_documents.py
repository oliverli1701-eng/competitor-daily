import json
import unittest
from email.message import Message
from contest_daily.network import WebClient


class FixtureWeb(WebClient):
    def __init__(self, payload):
        self.payload = payload
        self.request_headers = None

    def request(self, url, payload=None, headers=None, limit=5_000_000):
        self.request_headers = headers
        metadata = Message()
        metadata['Content-Type'] = 'application/json; charset=utf-8'
        return json.dumps(self.payload, ensure_ascii=False).encode(), metadata, url


class PublicDocumentTests(unittest.TestCase):
    def test_ican_body_and_attached_rule_are_available(self):
        web = FixtureWeb({'data':{'publishContent':'<p>队伍2至5人，复赛提交代码、技术文档和演示视频。</p>'*5, 'fileUrl':json.dumps([{'url':'https://official.example/rules.pdf'}])}})
        doc = web.document('https://api.g-ican.com/v1/api/school/informationPublish/detailInfo?informationId=253')
        self.assertIn('技术文档', doc['text'])
        self.assertIn('https://official.example/rules.pdf', doc['links'])
        self.assertEqual(web.request_headers, {'Authorization':'null'})

    def test_huawei_uses_rule_modules_and_excludes_live_counters(self):
        web = FixtureWeb({'data':{'modules':[{'context':'<p>全国总决赛线上答辩，全球总决赛现场答辩。</p>'*5}], 'participants':'DO_NOT_PUBLISH_THIS_COUNTER'}})
        doc = web.document('https://apigw-04.huawei.com/example')
        self.assertIn('线上答辩', doc['text'])
        self.assertNotIn('DO_NOT_PUBLISH_THIS_COUNTER', doc['text'])

    def test_lanqiao_news_body_and_links_are_read(self):
        web = FixtureWeb({'news':{'title':'第18届蓝桥杯', 'content':'<p>参赛学生凭学生证注册，按照赛项规则上传作品。</p>'*5+'<a href="/rules.pdf">参赛章程</a>'}})
        doc = web.document('https://www.guoxinlanqiao.com/api/web/news/selectone?nnid=1367')
        self.assertIn('学生证', doc['text'])
        self.assertTrue(any(x['title']=='参赛章程' for x in doc['link_details']))


if __name__ == '__main__':
    unittest.main()
