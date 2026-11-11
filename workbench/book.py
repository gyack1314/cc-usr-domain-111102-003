import contextlib
import json
import sqlite3
from pathlib import Path
from .domain import balance,integer,plan
from .io import canonical

class ConflictError(ValueError):
    """相同单号或请求号携带了不同内容。"""

SCHEMA=[
'CREATE TABLE IF NOT EXISTS sales(store TEXT NOT NULL,sale_id TEXT NOT NULL,payload BLOB NOT NULL,receipt BLOB NOT NULL,currency TEXT NOT NULL,gross INTEGER NOT NULL,discount INTEGER NOT NULL,cash INTEGER NOT NULL,tax INTEGER NOT NULL,entry_id INTEGER NOT NULL,PRIMARY KEY(store,sale_id))',
'CREATE TABLE IF NOT EXISTS sale_lines(store TEXT NOT NULL,sale_id TEXT NOT NULL,line_id TEXT NOT NULL,gross INTEGER NOT NULL,share INTEGER NOT NULL,net INTEGER NOT NULL,tax INTEGER NOT NULL,quantity INTEGER NOT NULL,PRIMARY KEY(store,sale_id,line_id))',
'CREATE TABLE IF NOT EXISTS units(store TEXT NOT NULL,sale_id TEXT NOT NULL,line_id TEXT NOT NULL,unit_no INTEGER NOT NULL,net INTEGER NOT NULL,tax INTEGER NOT NULL,status TEXT NOT NULL,return_entry_id INTEGER,PRIMARY KEY(store,sale_id,line_id,unit_no))',
'CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,store TEXT NOT NULL,sale_id TEXT NOT NULL,request_id TEXT,reverses INTEGER REFERENCES entries(id))',
'CREATE UNIQUE INDEX IF NOT EXISTS entries_reverses ON entries(reverses) WHERE reverses IS NOT NULL',
'CREATE TABLE IF NOT EXISTS entry_lines(entry_id INTEGER NOT NULL REFERENCES entries(id),account TEXT NOT NULL,side TEXT NOT NULL,currency TEXT NOT NULL,amount INTEGER NOT NULL)',
'CREATE TABLE IF NOT EXISTS entry_units(entry_id INTEGER NOT NULL REFERENCES entries(id),store TEXT NOT NULL,sale_id TEXT NOT NULL,line_id TEXT NOT NULL,unit_no INTEGER NOT NULL,net INTEGER NOT NULL,tax INTEGER NOT NULL)',
'CREATE TABLE IF NOT EXISTS requests(request_id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload BLOB NOT NULL,entry_id INTEGER NOT NULL,receipt BLOB NOT NULL)']

class Book:
    def __init__(self,path,timeout=30,initialize=True):
        self.path=Path(path);self.timeout=timeout
        if initialize:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self._tx() as conn:
                for statement in SCHEMA:conn.execute(statement)
    def _connect(self):
        conn=sqlite3.connect(self.path,timeout=self.timeout,isolation_level=None)
        conn.execute('PRAGMA foreign_keys=ON')
        return conn
    @contextlib.contextmanager
    def _tx(self):
        conn=self._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            try:yield conn
            except BaseException:
                if conn.in_transaction:conn.execute('ROLLBACK')
                raise
            else:conn.execute('COMMIT')
        finally:conn.close()
    @contextlib.contextmanager
    def _read(self):
        conn=self._connect()
        try:
            conn.execute('BEGIN')
            try:yield conn
            finally:
                if conn.in_transaction:conn.execute('ROLLBACK')
        finally:conn.close()
    @staticmethod
    def _line(conn,entry_id,account,side,currency,amount):
        conn.execute('INSERT INTO entry_lines VALUES(?,?,?,?,?)',(entry_id,account,side,currency,amount))
    def _locate(self,conn,request):
        sale_id=str(request['sale_id'])
        if request.get('store') is not None:
            store=str(request['store'])
            if not conn.execute('SELECT 1 FROM sales WHERE store=? AND sale_id=?',(store,sale_id)).fetchone():raise ValueError('销售单不存在')
            return store,sale_id
        rows=conn.execute('SELECT store FROM sales WHERE sale_id=?',(sale_id,)).fetchall()
        if not rows:raise ValueError('销售单不存在')
        if len(rows)>1:raise ValueError('销售单归属门店不明确')
        return rows[0][0],sale_id
    def _replay(self,conn,request_id,payload):
        row=conn.execute('SELECT payload,receipt FROM requests WHERE request_id=?',(request_id,)).fetchone()
        if not row:return None
        if row[0]!=payload:raise ConflictError('相同请求号内容冲突')
        return json.loads(row[1])
    def post_sale(self,order):
        allocation=plan(order)
        store=str(order['store']);sale_id=str(order['id']);payload=canonical(order)
        with self._tx() as conn:
            row=conn.execute('SELECT payload,receipt FROM sales WHERE store=? AND sale_id=?',(store,sale_id)).fetchone()
            if row:
                if row[0]!=payload:raise ConflictError('相同销售单号内容冲突')
                return json.loads(row[1])
            entry_id=conn.execute("INSERT INTO entries(kind,store,sale_id) VALUES('sale',?,?)",(store,sale_id)).lastrowid
            currency=allocation['currency'];cash=allocation['cash'];tax=allocation['tax']
            for account,side,amount in (('cash','debit',cash),('revenue','credit',cash-tax),('tax_payable','credit',tax)):
                if amount:self._line(conn,entry_id,account,side,currency,amount)
            lines=[]
            for item in allocation['lines']:
                conn.execute('INSERT INTO sale_lines VALUES(?,?,?,?,?,?,?,?)',(store,sale_id,item['line_id'],item['gross'],item['share'],item['net'],item['tax'],item['quantity']))
                for unit in item['units']:
                    conn.execute("INSERT INTO units VALUES(?,?,?,?,?,?,'sold',NULL)",(store,sale_id,item['line_id'],unit['unit_no'],unit['net'],unit['tax']))
                lines.append({'line_id':item['line_id'],'gross':item['gross'],'share':item['share'],'net':item['net'],'tax':item['tax'],'units':item['units']})
            receipt={'kind':'sale','store':store,'sale_id':sale_id,'entry_id':entry_id,'currency':currency,'gross':allocation['gross'],'discount':allocation['discount'],'cash':cash,'tax':tax,'lines':lines}
            conn.execute('INSERT INTO sales VALUES(?,?,?,?,?,?,?,?,?,?)',(store,sale_id,payload,canonical(receipt),currency,allocation['gross'],allocation['discount'],cash,tax,entry_id))
            return receipt
    def _picks(self,conn,request,store,sale_id,line_id,delta):
        if request.get('unit_no') is not None:
            chosen=request['unit_no']
            if not isinstance(chosen,list):raise ValueError('退货单位编号应为数组')
            picks=[integer(u) for u in chosen]
            if len(picks)!=delta or len(set(picks))!=delta or any(u<1 for u in picks):raise ValueError('退货单位编号与数量不符')
            return sorted(picks)
        rows=conn.execute("SELECT unit_no FROM units WHERE store=? AND sale_id=? AND line_id=? AND status='sold' ORDER BY unit_no LIMIT ?",(store,sale_id,line_id,delta)).fetchall()
        if len(rows)<delta:raise ValueError('可退数量不足')
        return [r[0] for r in rows]
    def apply_return(self,request):
        request_id=str(request['request_id']);payload=canonical(request)
        with self._tx() as conn:
            replay=self._replay(conn,request_id,payload)
            if replay is not None:return replay
            store,sale_id=self._locate(conn,request)
            line_id=str(request['line_id']);target=integer(request['quantity'])
            line=conn.execute('SELECT quantity FROM sale_lines WHERE store=? AND sale_id=? AND line_id=?',(store,sale_id,line_id)).fetchone()
            if not line:raise ValueError('商品行不存在')
            current=conn.execute("SELECT count(*) FROM units WHERE store=? AND sale_id=? AND line_id=? AND status='returned'",(store,sale_id,line_id)).fetchone()[0]
            if target<current:raise ValueError('累计退货数量不能小于已入账数量')
            if target==current:raise ValueError('退货数量未增加')
            if target>line[0]:raise ValueError('可退数量不足')
            picks=self._picks(conn,request,store,sale_id,line_id,target-current)
            entry_id=conn.execute("INSERT INTO entries(kind,store,sale_id,request_id) VALUES('return',?,?,?)",(store,sale_id,request_id)).lastrowid
            grabbed=[]
            for unit_no in picks:
                cur=conn.execute("UPDATE units SET status='returned',return_entry_id=? WHERE store=? AND sale_id=? AND line_id=? AND unit_no=? AND status='sold'",(entry_id,store,sale_id,line_id,unit_no))
                if cur.rowcount!=1:raise ValueError('退货单位不可用')
                net,tax=conn.execute('SELECT net,tax FROM units WHERE store=? AND sale_id=? AND line_id=? AND unit_no=?',(store,sale_id,line_id,unit_no)).fetchone()
                conn.execute('INSERT INTO entry_units VALUES(?,?,?,?,?,?,?)',(entry_id,store,sale_id,line_id,unit_no,net,tax))
                grabbed.append({'unit_no':unit_no,'net':net,'tax':tax})
            refund=sum(u['net'] for u in grabbed);tax=sum(u['tax'] for u in grabbed)
            currency=conn.execute('SELECT currency FROM sales WHERE store=? AND sale_id=?',(store,sale_id)).fetchone()[0]
            for account,side,amount in (('cash','credit',refund),('revenue','debit',refund-tax),('tax_payable','debit',tax)):
                if amount:self._line(conn,entry_id,account,side,currency,amount)
            receipt={'kind':'return','request_id':request_id,'store':store,'sale_id':sale_id,'line_id':line_id,'entry_id':entry_id,'currency':currency,'cumulative':target,'units':grabbed,'refund':refund,'tax':tax}
            conn.execute('INSERT INTO requests VALUES(?,?,?,?,?)',(request_id,'return',payload,entry_id,canonical(receipt)))
            return receipt
    def apply_reversal(self,request):
        request_id=str(request['request_id']);payload=canonical(request)
        with self._tx() as conn:
            replay=self._replay(conn,request_id,payload)
            if replay is not None:return replay
            target=str(request['target'])
            original=conn.execute("SELECT entry_id FROM requests WHERE request_id=? AND kind='return'",(target,)).fetchone()
            if not original:raise ValueError('原退货请求不存在')
            original_id=original[0]
            store,sale_id=conn.execute("SELECT store,sale_id FROM entries WHERE id=? AND kind='return'",(original_id,)).fetchone()
            if conn.execute('SELECT 1 FROM entries WHERE reverses=?',(original_id,)).fetchone():raise ValueError('原分录已被冲正')
            try:
                entry_id=conn.execute("INSERT INTO entries(kind,store,sale_id,request_id,reverses) VALUES('reversal',?,?,?,?)",(store,sale_id,request_id,original_id)).lastrowid
            except sqlite3.IntegrityError:raise ValueError('原分录已被冲正')
            for account,side,currency,amount in conn.execute('SELECT account,side,currency,amount FROM entry_lines WHERE entry_id=?',(original_id,)).fetchall():
                self._line(conn,entry_id,account,{'debit':'credit','credit':'debit'}[side],currency,amount)
            released=[]
            for line_id,unit_no in conn.execute('SELECT line_id,unit_no FROM entry_units WHERE entry_id=? ORDER BY line_id,unit_no',(original_id,)).fetchall():
                cur=conn.execute("UPDATE units SET status='sold',return_entry_id=NULL WHERE store=? AND sale_id=? AND line_id=? AND unit_no=? AND status='returned' AND return_entry_id=?",(store,sale_id,line_id,unit_no,original_id))
                if cur.rowcount!=1:raise ValueError('退货单位状态异常')
                released.append({'line_id':line_id,'unit_no':unit_no})
            receipt={'kind':'reversal','request_id':request_id,'target':target,'store':store,'sale_id':sale_id,'entry_id':entry_id,'reverses':original_id,'released':released}
            conn.execute('INSERT INTO requests VALUES(?,?,?,?,?)',(request_id,'reversal',payload,entry_id,canonical(receipt)))
            return receipt
    def entry(self,entry_id):
        with self._read() as conn:
            row=conn.execute('SELECT id,kind,store,sale_id,request_id,reverses FROM entries WHERE id=?',(entry_id,)).fetchone()
            if not row:raise ValueError('分录不存在')
            lines=[{'account':a,'side':s,'currency':c,'amount':m} for a,s,c,m in conn.execute('SELECT account,side,currency,amount FROM entry_lines WHERE entry_id=? ORDER BY rowid',(entry_id,))]
            units=[{'line_id':l,'unit_no':u,'net':n,'tax':t} for l,u,n,t in conn.execute('SELECT line_id,unit_no,net,tax FROM entry_units WHERE entry_id=? ORDER BY line_id,unit_no',(entry_id,))]
            return {'id':row[0],'kind':row[1],'store':row[2],'sale_id':row[3],'request_id':row[4],'reverses':row[5],'lines':lines,'units':units}
    def reconcile(self):
        problems=[]
        with self._read() as conn:
            reversed_ids={r[0] for r in conn.execute('SELECT reverses FROM entries WHERE reverses IS NOT NULL')}
            entries={r[0]:r[1:] for r in conn.execute('SELECT id,kind,store,sale_id,request_id,reverses FROM entries ORDER BY id')}
            for eid,(kind,store,sale_id,request_id,reverses) in entries.items():
                lines=conn.execute('SELECT account,side,currency,amount FROM entry_lines WHERE entry_id=?',(eid,)).fetchall()
                for currency,total in balance([{'currency':c,'side':s,'amount':a} for _,s,c,a in lines]).items():
                    if total!=0:problems.append(f'分录{eid}币种{currency}借贷差额{total}')
                if len({c for _,_,c,_ in lines})>1:problems.append(f'分录{eid}混入多个币种')
                if kind=='reversal':
                    original=entries.get(reverses)
                    if not original or original[0]!='return':problems.append(f'冲正分录{eid}未引用退货分录')
                    elif original[1:3]!=(store,sale_id):problems.append(f'冲正分录{eid}与原分录单据不符')
            sales=conn.execute('SELECT store,sale_id,currency,gross,discount,cash,tax,entry_id FROM sales ORDER BY store,sale_id').fetchall()
            for store,sale_id,currency,gross,discount,cash,tax,entry_id in sales:
                lines=conn.execute('SELECT line_id,gross,share,net,tax,quantity FROM sale_lines WHERE store=? AND sale_id=?',(store,sale_id)).fetchall()
                if sum(l[1] for l in lines)!=gross:problems.append(f'销售单{sale_id}行金额合不回原单')
                if sum(l[2] for l in lines)!=discount:problems.append(f'销售单{sale_id}优惠分摊合不回原单优惠')
                if sum(l[3] for l in lines)!=cash:problems.append(f'销售单{sale_id}行实收合不回原单实收')
                if sum(l[4] for l in lines)!=tax:problems.append(f'销售单{sale_id}行税额合不回原单税款')
                for line_id,lgross,share,net,ltax,quantity in lines:
                    if lgross-share!=net:problems.append(f'销售单{sale_id}行{line_id}分摊勾稽不符')
                    if net<ltax:problems.append(f'销售单{sale_id}行{line_id}实收低于税额')
                    count,unet,utax=conn.execute('SELECT count(*),COALESCE(sum(net),0),COALESCE(sum(tax),0) FROM units WHERE store=? AND sale_id=? AND line_id=?',(store,sale_id,line_id)).fetchone()
                    if (count,unet,utax)!=(quantity,net,ltax):problems.append(f'销售单{sale_id}行{line_id}单位分摊合不回行金额')
                original=entries.get(entry_id)
                if not original or original[0]!='sale':problems.append(f'销售单{sale_id}入账分录缺失')
            for store,sale_id,line_id,unit_no,net,tax,status,return_entry_id in conn.execute('SELECT store,sale_id,line_id,unit_no,net,tax,status,return_entry_id FROM units'):
                covering=[r for r in conn.execute("SELECT eu.entry_id,eu.net,eu.tax FROM entry_units eu JOIN entries e ON e.id=eu.entry_id WHERE eu.store=? AND eu.sale_id=? AND eu.line_id=? AND eu.unit_no=? AND e.kind='return'",(store,sale_id,line_id,unit_no)) if r[0] not in reversed_ids]
                if status=='returned':
                    if len(covering)!=1 or covering[0][0]!=return_entry_id or covering[0][1]!=net or covering[0][2]!=tax:problems.append(f'单位{sale_id}/{line_id}/{unit_no}权益占用与退货分录不符')
                elif covering or return_entry_id is not None:problems.append(f'单位{sale_id}/{line_id}/{unit_no}已释放仍被退货分录占用')
            balances={}
            for currency,account,side,amount in conn.execute('SELECT currency,account,side,amount FROM entry_lines'):
                key=(currency,account);balances[key]=balances.get(key,0)+(amount if side=='debit' else -amount)
            outstanding={}
            for currency,net,tax in conn.execute("SELECT s.currency,u.net,u.tax FROM units u JOIN sales s ON s.store=u.store AND s.sale_id=u.sale_id WHERE u.status='sold'"):
                n,t=outstanding.get(currency,(0,0));outstanding[currency]=(n+net,t+tax)
            currencies={}
            for currency in sorted({c for c,_ in balances}|set(outstanding)):
                net,tax=outstanding.get(currency,(0,0))
                cash=balances.get((currency,'cash'),0);revenue=-balances.get((currency,'revenue'),0);payable=-balances.get((currency,'tax_payable'),0)
                if cash!=net:problems.append(f'币种{currency}现金余额{cash}与未退实收{net}不符')
                if payable!=tax:problems.append(f'币种{currency}销项税余额{payable}与未退税额{tax}不符')
                if revenue!=net-tax:problems.append(f'币种{currency}收入余额{revenue}与未退净额{net-tax}不符')
                currencies[currency]={'cash':cash,'revenue':revenue,'tax_payable':payable,'outstanding_net':net,'outstanding_tax':tax}
            requests=conn.execute('SELECT request_id,kind,entry_id FROM requests').fetchall()
            for request_id,kind,entry_id in requests:
                original=entries.get(entry_id)
                if not original or original[0]!=kind or original[3]!=request_id:problems.append(f'请求{request_id}与分录链断裂')
            counts={'sold':0,'returned':0}
            for status,n in conn.execute('SELECT status,count(*) FROM units GROUP BY status'):counts[status]=n
        return {'ok':not problems,'problems':problems,'currencies':currencies,'entries':len(entries),'requests':len(requests),'sales':len(sales),'units':counts}
