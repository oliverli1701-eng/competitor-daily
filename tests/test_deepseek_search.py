import json
import os
import unittest
from unittest.mock import patch
from contest_daily.network import WebClient,FetchError


class DeepSeekSearchTests(unittest.TestCase):
    def test_new_search_endpoint_keeps_bearer_key_out_of_url_and_returns_candidates(self):
        result={'results':[{'url':'https://official.example/new','title':'报名通知','content':'not used as verified evidence'}]}
        with patch.dict(os.environ,{'SEARCH_PROVIDER':'deepseek','DEEPSEEK_API_KEY':'fixture-secret','DEEPSEEK_BASE_URL':'https://api.deepseek.com'}),patch.object(WebClient,'request',return_value=(json.dumps(result).encode(),{},'')) as request:
            found=WebClient().search('竞赛 报名',3)
        self.assertEqual(found,[{'url':'https://official.example/new','title':'报名通知'}])
        args=request.call_args.args
        self.assertEqual(args[0],'https://api.deepseek.com/v1/tools/search')
        self.assertNotIn('fixture-secret',args[0])
        self.assertFalse(json.loads(args[1])['need_content'])
        self.assertEqual(args[2]['Authorization'],'Bearer fixture-secret')

    def test_malformed_search_response_is_not_claimed_to_be_no_matches(self):
        with patch.dict(os.environ,{'SEARCH_PROVIDER':'deepseek','DEEPSEEK_API_KEY':'fixture'}),patch.object(WebClient,'request',return_value=(b'{"error":"denied"}',{},'')):
            with self.assertRaises(FetchError):WebClient().search('竞赛')


if __name__=='__main__':unittest.main()
