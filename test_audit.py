import unittest
from audit import reconcile

def trade(id,side,quantity,amount,status='SETTLED'):
    return dict(id=id,status=status,currency='EUR',security=dict(isin='TEST',side=side,quantity=quantity,amount=amount))

class AccountingTests(unittest.TestCase):
    def test_buy_sell_and_cancelled_order(self):
        r=reconcile([trade('a','BUY','3','-30'),trade('b','SELL','1','12'),trade('c','SELL','2','0','CANCELLED')],[dict(isin='TEST',position=dict(filled=2))])
        self.assertEqual(r['implied_cash'],'-18')
        self.assertEqual(r['positions'][0]['difference'],'0')
        self.assertEqual(r['excluded'],['c'])
    def test_dividend_reinvestment_is_cash_neutral(self):
        dividend=dict(id='d',status='SETTLED',currency='EUR',cash=dict(amount='0.50',transactionType='DISTRIBUTION'))
        r=reconcile([dividend,trade('r','BUY','0.01','-0.50')],[])
        self.assertEqual(r['implied_cash'],'0.00')
    def test_duplicate_rejected(self):
        t=trade('a','BUY','1','-10')
        with self.assertRaises(ValueError): reconcile([t,t],[])
    def test_unknown_state_is_not_posted(self):
        r=reconcile([trade('a','BUY','1','-10','PENDING')],[])
        self.assertEqual(r['unresolved'],['a'])
        self.assertEqual(r['implied_cash'],'0')

if __name__=='__main__': unittest.main()
