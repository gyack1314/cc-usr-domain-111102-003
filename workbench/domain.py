def integer(value):
    if type(value) is not int or value<0:raise ValueError('金额或数量必须是非负整数')
    return value
def gross(line):
    amount=integer(line['unit_price'])*integer(line['quantity'])
    if line['quantity']==0 or integer(line['tax'])>amount:raise ValueError('行数量或税额无效')
    return amount
def quote(order):
    ids=[x['line_id'] for x in order['lines']]
    if not ids or len(ids)!=len(set(ids)):raise ValueError('商品行ID无效')
    total=sum(gross(x) for x in order['lines']);discount=integer(order['discount']);tax=sum(x['tax'] for x in order['lines'])
    if discount>total or total-discount<tax:raise ValueError('优惠不合法')
    return {'currency':order['currency'],'gross':total,'discount':discount,'cash':total-discount,'tax':tax}
def balance(entries):
    totals={}
    for e in entries:
        if e['side'] not in ['debit','credit']:raise ValueError('借贷方向无效')
        sign=1 if e['side']=='debit' else -1
        totals[e['currency']]=totals.get(e['currency'],0)+sign*integer(e['amount'])
    return totals
def allocate(total,weights):
    integer(total);shares={};pool=[]
    for key,weight in weights:
        w=integer(weight);shares[key]=0
        if w>0:pool.append((key,w))
    if total==0:return shares
    if not pool:raise ValueError('优惠超出合法可分金额')
    base=sum(w for _,w in pool);rest=total
    for key,w in pool:
        share=total*w//base;shares[key]=share;rest-=share
    for key,_ in sorted(pool,key=lambda item:(-(total*item[1]%base),item[0]))[:rest]:shares[key]+=1
    return shares
def plan(order):
    q=quote(order)
    shares=allocate(q['discount'],[(x['line_id'],gross(x)) for x in order['lines']])
    lines=[]
    for x in order['lines']:
        g=gross(x);share=shares[x['line_id']];net=g-share;tax=integer(x['tax'])
        if net<tax:raise ValueError('行分摊后实收低于税额')
        units=range(1,integer(x['quantity'])+1)
        nets=allocate(net,[(u,1) for u in units]);taxes=allocate(tax,[(u,1) for u in units])
        lines.append({'line_id':x['line_id'],'gross':g,'share':share,'net':net,'tax':tax,'quantity':x['quantity'],'units':[{'unit_no':u,'net':nets[u],'tax':taxes[u]} for u in units]})
    return {'currency':q['currency'],'gross':q['gross'],'discount':q['discount'],'cash':q['cash'],'tax':q['tax'],'lines':lines}
