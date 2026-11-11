import multiprocessing
import tempfile
import unittest
from pathlib import Path
from workbench.book import Book,ConflictError
from workbench.demo import run as demo_run
from workbench.domain import allocate,plan
from workbench.io import read_json

ROOT=Path(__file__).resolve().parents[1]
ORDERS=read_json(ROOT/'samples/orders.json')
REQUESTS={r['request_id']:r for r in read_json(ROOT/'samples/requests.json')}

def worker(path,request):
    try:return ('ok',Book(path,initialize=False).apply_return(request))
    except ValueError as exc:return ('fail',str(exc))

class AllocationTests(unittest.TestCase):
    def test_order_level_tie_break_by_line_id(self):
        p=plan(ORDERS[0])
        self.assertEqual({l['line_id']:l['share'] for l in p['lines']},{'a':3,'b':2,'gift':0})
        self.assertEqual((p['cash'],p['tax']),(601,3))
        self.assertEqual(sum(l['share'] for l in p['lines']),5)
        self.assertEqual(sum(l['net'] for l in p['lines']),601)
        self.assertEqual(sum(u['net'] for l in p['lines'] for u in l['units']),601)
        self.assertEqual(sum(u['tax'] for l in p['lines'] for u in l['units']),3)
    def test_unit_level_split(self):
        lines={l['line_id']:l for l in plan(ORDERS[0])['lines']}
        self.assertEqual([(u['net'],u['tax']) for u in lines['a']['units']],[(100,1),(100,0),(100,0)])
        self.assertEqual([(u['net'],u['tax']) for u in lines['b']['units']],[(101,1),(100,1),(100,0)])
        self.assertEqual(lines['gift']['units'],[{'unit_no':1,'net':0,'tax':0}])
        lines={l['line_id']:l for l in plan(ORDERS[1])['lines']}
        self.assertEqual((lines['c']['share'],lines['d']['share']),(1,0))
        self.assertEqual([(u['net'],u['tax']) for u in lines['c']['units']],[(3,1),(2,0)])
        self.assertEqual([(u['net'],u['tax']) for u in lines['d']['units']],[(3,0),(3,0)])
    def test_allocate_largest_remainder(self):
        self.assertEqual(allocate(5,[('a',1),('b',1)]),{'a':3,'b':2})
        self.assertEqual(allocate(4,[('a',1),('b',3)]),{'a':1,'b':3})
        self.assertEqual(allocate(7,[('x',0),('y',10)]),{'x':0,'y':7})
        self.assertEqual(allocate(0,[('a',1)]),{'a':0})
        with self.assertRaises(ValueError):allocate(1,[('a',0)])
    def test_rejections(self):
        with self.assertRaises(ValueError):
            plan({'currency':'CNY','discount':11,'lines':[{'line_id':'a','unit_price':5,'quantity':2,'tax':0}]})
        with self.assertRaises(ValueError):
            plan({'currency':'CNY','discount':0,'lines':[{'line_id':'a','unit_price':5,'quantity':1,'tax':6}]})
        with self.assertRaises(ValueError):
            plan({'currency':'CNY','discount':1,'lines':[{'line_id':'g','unit_price':0,'quantity':1,'tax':0}]})
        with self.assertRaises(ValueError):
            plan({'currency':'CNY','discount':11,'lines':[{'line_id':'a','unit_price':10,'quantity':1,'tax':6},{'line_id':'b','unit_price':10,'quantity':1,'tax':0}]})

class BookFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'book.sqlite3'
        self.book=Book(self.path)
    def tearDown(self):self.tmp.cleanup()
    def post_samples(self):
        for order in ORDERS:self.book.post_sale(order)
    def test_sale_entry_directions(self):
        receipt=self.book.post_sale(ORDERS[0])
        entry=self.book.entry(receipt['entry_id'])
        self.assertEqual(entry['kind'],'sale')
        self.assertEqual(entry['lines'],[
            {'account':'cash','side':'debit','currency':'CNY','amount':601},
            {'account':'revenue','side':'credit','currency':'CNY','amount':598},
            {'account':'tax_payable','side':'credit','currency':'CNY','amount':3}])
        self.assertTrue(self.book.reconcile()['ok'])
    def test_return_entry_directions(self):
        self.book.post_sale(ORDERS[0])
        receipt=self.book.apply_return(REQUESTS['r1'])
        entry=self.book.entry(receipt['entry_id'])
        self.assertEqual(entry['lines'],[
            {'account':'cash','side':'credit','currency':'CNY','amount':100},
            {'account':'revenue','side':'debit','currency':'CNY','amount':99},
            {'account':'tax_payable','side':'debit','currency':'CNY','amount':1}])
        self.assertEqual(entry['units'],[{'line_id':'a','unit_no':1,'net':100,'tax':1}])
    def test_split_return_matches_whole_return(self):
        self.post_samples()
        r1=self.book.apply_return(REQUESTS['r1'])
        r2=self.book.apply_return(REQUESTS['r2'])
        self.assertEqual((r1['refund'],r1['tax']),(100,1))
        self.assertEqual((r2['refund'],r2['tax']),(100,0))
        self.assertEqual([u['unit_no'] for u in r1['units']+r2['units']],[1,2])
        twin=dict(ORDERS[0]);twin['id']='sale-a-whole'
        self.book.post_sale(twin)
        whole=self.book.apply_return({'request_id':'w1','sale_id':'sale-a-whole','line_id':'a','quantity':2})
        self.assertEqual((whole['refund'],whole['tax']),(r1['refund']+r2['refund'],r1['tax']+r2['tax']))
        r3=self.book.apply_return(REQUESTS['r3'])
        self.assertEqual((r3['refund'],r3['tax']),(3,1))
        self.assertTrue(self.book.reconcile()['ok'])
    def test_replay_and_conflict(self):
        first=self.book.post_sale(ORDERS[0])
        r2=self.book.apply_return(REQUESTS['r2'])
        self.assertEqual((r2['refund'],r2['tax']),(200,1))
        self.assertEqual(self.book.apply_return(REQUESTS['r2']),r2)
        with self.assertRaises(ConflictError):
            self.book.apply_return({'request_id':'r2','sale_id':'sale-a','line_id':'a','quantity':3})
        self.assertEqual(self.book.post_sale(ORDERS[0]),first)
        with self.assertRaises(ConflictError):
            self.book.post_sale({'id':'sale-a','store':'S1','currency':'CNY','discount':0,'lines':ORDERS[0]['lines']})
    def test_failed_return_consumes_nothing(self):
        self.book.post_sale(ORDERS[0])
        with self.assertRaises(ValueError):
            self.book.apply_return({'request_id':'r9','sale_id':'sale-a','line_id':'a','quantity':4})
        ok=self.book.apply_return({'request_id':'r9','sale_id':'sale-a','line_id':'a','quantity':3})
        self.assertEqual(ok['cumulative'],3)
        with self.assertRaises(ValueError):
            self.book.apply_return({'request_id':'r10','sale_id':'sale-a','line_id':'a','quantity':2})
        self.assertTrue(self.book.reconcile()['ok'])
    def test_reversal_releases_units_and_forbids_double(self):
        self.book.post_sale(ORDERS[0])
        r1=self.book.apply_return(REQUESTS['r1'])
        self.book.apply_return(REQUESTS['r2'])
        rev=self.book.apply_reversal({'request_id':'rv1','target':'r1'})
        self.assertEqual(rev['reverses'],r1['entry_id'])
        self.assertEqual(rev['released'],[{'line_id':'a','unit_no':1}])
        entry=self.book.entry(rev['entry_id'])
        self.assertEqual(entry['lines'],[
            {'account':'cash','side':'debit','currency':'CNY','amount':100},
            {'account':'revenue','side':'credit','currency':'CNY','amount':99},
            {'account':'tax_payable','side':'credit','currency':'CNY','amount':1}])
        again=self.book.apply_return({'request_id':'r4','sale_id':'sale-a','line_id':'a','quantity':2})
        self.assertEqual([u['unit_no'] for u in again['units']],[1])
        self.assertEqual((again['refund'],again['tax']),(100,1))
        with self.assertRaises(ValueError):
            self.book.apply_reversal({'request_id':'rv2','target':'r1'})
        with self.assertRaises(ValueError):
            self.book.apply_reversal({'request_id':'rv3','target':'nope'})
        self.assertTrue(self.book.reconcile()['ok'])
    def test_zero_price_gift_return(self):
        self.book.post_sale(ORDERS[0])
        gift=self.book.apply_return({'request_id':'g1','sale_id':'sale-a','line_id':'gift','quantity':1})
        self.assertEqual((gift['refund'],gift['tax']),(0,0))
        self.assertEqual(self.book.entry(gift['entry_id'])['lines'],[])
        self.assertTrue(self.book.reconcile()['ok'])
    def test_explicit_unit_no(self):
        self.book.post_sale(ORDERS[0])
        r=self.book.apply_return({'request_id':'u1','sale_id':'sale-a','line_id':'b','quantity':1,'unit_no':[3]})
        self.assertEqual([u['unit_no'] for u in r['units']],[3])
        self.assertEqual((r['refund'],r['tax']),(100,0))
        with self.assertRaises(ValueError):
            self.book.apply_return({'request_id':'u2','sale_id':'sale-a','line_id':'b','quantity':2,'unit_no':[3]})
        self.assertTrue(self.book.reconcile()['ok'])
    def test_unknown_sale_and_line(self):
        with self.assertRaises(ValueError):
            self.book.apply_return({'request_id':'x1','sale_id':'ghost','line_id':'a','quantity':1})
        self.book.post_sale(ORDERS[0])
        with self.assertRaises(ValueError):
            self.book.apply_return({'request_id':'x2','sale_id':'sale-a','line_id':'ghost','quantity':1})
    def test_currencies_never_mix(self):
        self.book.post_sale(ORDERS[1])
        self.book.post_sale({'id':'usd-1','store':'S2','currency':'USD','discount':0,'lines':[{'line_id':'u','unit_price':100,'quantity':1,'tax':0}]})
        self.book.apply_return(REQUESTS['r3'])
        report=self.book.reconcile()
        self.assertTrue(report['ok'],report['problems'])
        self.assertEqual(set(report['currencies']),{'CNY','USD'})
        self.assertEqual(report['currencies']['CNY'],{'cash':8,'revenue':8,'tax_payable':0,'outstanding_net':8,'outstanding_tax':0})
        self.assertEqual(report['currencies']['USD'],{'cash':100,'revenue':100,'tax_payable':0,'outstanding_net':100,'outstanding_tax':0})
    def test_reopen_keeps_books(self):
        self.book.post_sale(ORDERS[0])
        first=self.book.apply_return(REQUESTS['r1'])
        reopened=Book(self.path)
        self.assertEqual(reopened.apply_return(REQUESTS['r1']),first)
        reopened.apply_return(REQUESTS['r2'])
        report=Book(self.path).reconcile()
        self.assertTrue(report['ok'],report['problems'])
        self.assertEqual(report['currencies']['CNY']['cash'],401)

class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'book.sqlite3'
        Book(self.path).post_sale({'id':'s1','store':'S1','currency':'CNY','discount':0,'lines':[{'line_id':'x','unit_price':10,'quantity':1,'tax':1}]})
    def tearDown(self):self.tmp.cleanup()
    def test_last_unit_single_winner(self):
        reqs=[{'request_id':f'race-{i}','sale_id':'s1','line_id':'x','quantity':1} for i in range(4)]
        with multiprocessing.Pool(4) as pool:
            results=pool.starmap(worker,[(str(self.path),r) for r in reqs])
        self.assertEqual([r[0] for r in results].count('ok'),1)
        report=Book(self.path).reconcile()
        self.assertTrue(report['ok'],report['problems'])
        self.assertEqual(report['requests'],1)
    def test_same_request_id_race(self):
        req={'request_id':'same','sale_id':'s1','line_id':'x','quantity':1}
        with multiprocessing.Pool(2) as pool:
            results=pool.starmap(worker,[(str(self.path),req)]*2)
        self.assertEqual([r[0] for r in results],['ok','ok'])
        self.assertEqual(results[0][1],results[1][1])
        report=Book(self.path).reconcile()
        self.assertTrue(report['ok'],report['problems'])
        self.assertEqual((report['entries'],report['requests']),(2,1))

class DemoTests(unittest.TestCase):
    def test_demo_scenario_reconciles(self):
        with tempfile.TemporaryDirectory() as d:
            result=demo_run(Path(d)/'demo.sqlite3',ROOT/'samples')
        self.assertTrue(result['ok'])
        compare=[s for s in result['steps'] if s['step']=='拆退合计与整退对比'][0]
        self.assertTrue(compare['detail']['一致'])

if __name__=='__main__':unittest.main()
