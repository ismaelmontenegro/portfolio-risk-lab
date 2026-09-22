import unittest
from market_data import validate_series, instrument_universe

def sample():
    rows=[{'date':'2026-01-02','close':100,'adjusted_close':90},{'date':'2026-01-05','close':101,'adjusted_close':91}]
    metadata=dict(provider='synthetic',symbol='TEST',isin='TEST',exchange='TEST',currency='EUR',source_url='test',retrieved_at='2026-01-06',frequency='daily',adjustment='split_and_dividend',mapping_verified=True)
    return rows,metadata

class MarketDataTests(unittest.TestCase):
    def check(self,rows,meta,sessions=None):
        return validate_series(rows,meta,'2026-01-02','2026-01-05',sessions)
    def test_calendar_weekend_and_model_gate(self):
        r=self.check(*sample(),['2026-01-02','2026-01-05'])
        self.assertTrue(r['structural_checks_passed'])
        self.assertFalse(r['model_ready'])
    def test_missing_session(self):
        rows,m=sample()
        self.assertIn('missing_exchange_sessions',self.check(rows[:1],m,['2026-01-02','2026-01-05'])['blockers'])
    def test_nan_zero_duplicate(self):
        rows,m=sample();rows += [rows[0],dict(date='2026-01-03',close=0,adjusted_close=float('nan'))]
        r=self.check(rows,m)
        self.assertEqual(r['duplicate_dates'],1)
        self.assertEqual(r['invalid_rows'],[3])
    def test_unknown_adjustment_and_fx(self):
        rows,m=sample();m.update(currency='USD',adjustment='unknown')
        r=self.check(rows,m)
        self.assertIn('eur_conversion_required',r['blockers'])
        self.assertIn('total_return_adjustment_not_documented',r['blockers'])
    def test_large_move_not_silently_removed(self):
        rows,m=sample();rows[1]['adjusted_close']=10
        self.assertEqual(len(self.check(rows,m)['large_moves']),1)
    def test_exited_position_included_cancelled_excluded(self):
        tx=[dict(security={'isin':'OLD'},status='SETTLED',lastEventAt='2026-01-02',description='Exited'),dict(security={'isin':'CANCEL'},status='CANCELLED')]
        r=instrument_universe({'holdings':{'holdings':[]},'transactions':{'transactions':tx},'capturedAt':'2026-01-05'})
        self.assertEqual(len(r),1);self.assertFalse(r[0]['current'])

if __name__=='__main__':unittest.main()
