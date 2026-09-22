import unittest
from performance_reconciliation import build_report

def fixture():
    records=[dict(id='deposit',status='SETTLED',currency='EUR',lastEventAt='2026-01-01',cash={'amount':'100'}),dict(id='dividend',status='SETTLED',currency='EUR',lastEventAt='2026-01-02',cash={'amount':'8'}),dict(id='sell',status='SETTLED',currency='EUR',lastEventAt='2026-01-03',security={'amount':'10'})]
    snapshot=dict(capturedAt='test',transactions={'transactions':records},overview={'valuation':{'total':'110'},'performance':[{'timeframe':'MAX','simpleAbsoluteReturn':'11'}]})
    details=[{'result':{'transaction':t}} for t in [dict(id='deposit',cash={'transactionType':'DEPOSIT','amount':'100'}),dict(id='dividend',cash={'transactionType':'DISTRIBUTION','amount':'8','taxDetails':{'grossAmount':'10','taxAmount':'2'}}),dict(id='sell',securityTrade={'side':'SELL','totalAmount':'10','tradeTransactionAmounts':{'marketValuation':'10','transactionFee':'1','taxAmount':'-1'},'taxes':'-1','fee':'1'})]]
    return snapshot,details

class PerformanceTests(unittest.TestCase):
    def test_signed_tax_and_no_duplicate_fees(self):
        r=build_report(*fixture())
        self.assertEqual(r['status'],'reconciled')
        self.assertEqual(r['net_tax'],'1')
        self.assertEqual(r['fees_already_in_cashflows'],'1')
    def test_missing_detail(self):
        s,d=fixture()
        self.assertEqual(build_report(s,d[:-1])['status'],'unresolved')
    def test_bad_gross_net(self):
        s,d=fixture();d[1]['result']['transaction']['cash']['taxDetails']['grossAmount']='11'
        self.assertEqual(build_report(s,d)['status'],'unresolved')
    def test_duplicate_detail(self):
        s,d=fixture()
        with self.assertRaises(ValueError):build_report(s,d+[d[0]])

if __name__=='__main__':unittest.main()
