import importlib.util,io,json,os,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('market_smoke',Path(__file__).resolve().parents[3]/'scripts/cloud_market_smoke.py')
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)

class MarketSmokeContractTests(unittest.TestCase):
    def run_case(self,closed=False,stale=False,override=None):
        now=datetime.now(timezone.utc)
        at=(now-timedelta(minutes=20 if stale else 6)).isoformat()
        data={'paper_only':True,'lifecycle_verification':{'accounting_ok':True,'stages':{},'live_e2e_complete':False},
              'services':[{'component':'monitor','status':'ok','last_success_at':now.isoformat()}],
              'market':{'is_open':not closed},
              'trades':[{'ticker':'TMO','is_shadow':1,'status':'open','last_bar_at':at,'last_price':100,'price_as_of':at,'current_price':100,
                         'opened_at':(now-timedelta(days=1)).isoformat()}]}
        data['trades'][0].update(override or {})
        paths=[]
        def get(url,**kwargs):
            paths.append(url)
            payload={'quotes':[]} if url.endswith('/quotes') else {} if url.endswith('/health') else data
            response=io.BytesIO(json.dumps(payload).encode());response.status=200
            return response
        with patch.dict(os.environ,BACKEND_URL='https://example.test'),patch.object(smoke,'urlopen',side_effect=get),patch('builtins.print') as output:
            smoke.main()
        return paths,json.loads(output.call_args.args[0])

    def test_shadow_only_ticker_uses_completed_bar_evidence(self):
        _,out=self.run_case()
        self.assertEqual(out['monitor_progress'],'PASS')
        self.assertFalse(out['live_tp_sl_complete'])

    def test_stale_shadow_still_fails(self):
        with self.assertRaises(AssertionError):self.run_case(stale=True)

    def test_closed_session_success_is_not_live_validation(self):
        paths,out=self.run_case(closed=True)
        self.assertEqual(out['live_market'],'NOT_VERIFIED_MARKET_CLOSED')
        self.assertFalse(any(p.endswith('/quotes') for p in paths))

    def test_shadow_missing_invalid_or_unfinished_mark_fails(self):
        for override in ({'last_price':None},{'last_price':0},{'last_price':float('nan')},
                         {'last_bar_at':None},
                         {'last_bar_at':datetime.now(timezone.utc).isoformat()},
                         {'opened_at':datetime.now(timezone.utc).isoformat()}):
            with self.subTest(override=override),self.assertRaises(AssertionError):
                self.run_case(override=override)
