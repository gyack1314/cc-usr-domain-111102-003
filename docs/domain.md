# 领域数据约定

CNY金额单位为分。line.gross=unit_price*quantity，tax是已包含在gross中的整行税额。订单优惠减少商品收入，不改变原行冻结的税额；要求优惠后实收>=总tax，且各行分摊后也须满足net>=tax，否则整单拒绝。销售分录借cash=实收，贷revenue=实收-tax、tax_payable=tax；退货方向相反，冲正逐项反向。unit_no从1开始。所有请求ID全局唯一，原始订单ID各店内唯一。

全部资料为本地合成。samples保留来源状态，读取和存档不等于业务验证通过；异常记录不被自动修改。workbench/domain.py中的现有函数可独立调用，tests/domain_checks.py演示其行为。allocate按最大余数法分摊（余数相同按键升序），plan给出整单分摊方案：订单优惠按行优惠前金额比例分摊，行实收与行税额独立分到unit_no单位，零价行不承接优惠，分摊后行net<tax或优惠无可分金额则整单拒绝。
