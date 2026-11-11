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
