import copy
from pathlib import Path
from .book import Book,ConflictError
from .io import read_json

def run(database,samples='samples'):
    path=Path(database)
    if path.exists():raise ValueError('演示需要新的数据库路径')
    book=Book(path)
    orders=read_json(Path(samples)/'orders.json')
    requests={r['request_id']:r for r in read_json(Path(samples)/'requests.json')}
    steps=[]
    def record(title,detail):
        steps.append({'step':title,'detail':detail});return detail
    for order in orders:record(f"销售入账{order['id']}",book.post_sale(order))
    first=record('拆退第一笔r1:行a累计1件',book.apply_return(requests['r1']))
    second=record('拆退第二笔r2:行a累计2件',book.apply_return(requests['r2']))
    record('单sale-b退货r3:行c累计1件',book.apply_return(requests['r3']))
    twin=copy.deepcopy(orders[0]);twin['id']='sale-a-whole'
    record('对照单入账(与sale-a同内容)',book.post_sale(twin))
    whole=record('对照单一次退2件w1',book.apply_return({'request_id':'w1','sale_id':'sale-a-whole','line_id':'a','quantity':2}))
    record('拆退合计与整退对比',{'拆退合计':{'refund':first['refund']+second['refund'],'tax':first['tax']+second['tax']},'整退':{'refund':whole['refund'],'tax':whole['tax']},'一致':first['refund']+second['refund']==whole['refund'] and first['tax']+second['tax']==whole['tax']})
    record('冲正r1(反向分录引用原分录)',book.apply_reversal({'request_id':'rv1','target':'r1'}))
    record('释放后再次申请r4:行a累计2件',book.apply_return({'request_id':'r4','sale_id':'sale-a','line_id':'a','quantity':2}))
    record('零价赠品退货r5',book.apply_return({'request_id':'r5','sale_id':'sale-a','line_id':'gift','quantity':1}))
    book=Book(path)
    replay=book.apply_return(requests['r2'])
    record('进程重开后重放r2',{'回执一致':replay==second,'entry_id':replay['entry_id']})
    try:book.apply_return({'request_id':'r2','sale_id':'sale-a','line_id':'a','quantity':3})
    except ConflictError as exc:record('同号不同内容r2',f'冲突被拒:{exc}')
    try:book.apply_return({'request_id':'r6','sale_id':'sale-a','line_id':'a','quantity':4})
    except ValueError as exc:record('超量退货r6',f'失败且不占用数量:{exc}')
    record('同号重试r6:行a累计3件',book.apply_return({'request_id':'r6','sale_id':'sale-a','line_id':'a','quantity':3}))
    try:book.apply_reversal({'request_id':'rv2','target':'r1'})
    except ValueError as exc:record('重复冲正rv2',f'被拒:{exc}')
    report=book.reconcile()
    record('核对',report)
    return {'ok':report['ok'],'steps':steps}
