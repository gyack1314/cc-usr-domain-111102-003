from workbench.domain import quote,balance,integer
def check(c,root,read):
    c.assertEqual(quote(read(root/'samples/orders.json')[0])['cash'],601)
    c.assertEqual(balance([{'currency':'CNY','side':'debit','amount':4},{'currency':'CNY','side':'credit','amount':4}]),{'CNY':0})
    with c.assertRaises(ValueError):integer(True)
    with c.assertRaises(ValueError):quote({'lines':[{'line_id':'x','unit_price':1,'quantity':1,'tax':1}],'discount':1})
