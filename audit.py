"""Reproducible, offline audit of a saved Scalable MCP snapshot (stdlib only)."""
import json
import html
import hashlib
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
D = lambda x: Decimal(str(x))

def reconcile(transactions, holdings):
    quantities = defaultdict(Decimal)
    cash = Decimal(0)
    excluded, unresolved = [], []
    seen = set()
    for t in transactions:
        if t['id'] in seen:
            raise ValueError('Duplicate transaction ID')
        seen.add(t['id'])
        if t.get('isCancellation'):
            unresolved.append(t['id'])
            continue
        if t['status'] == 'CANCELLED':
            excluded.append(t['id'])
            continue
        if t['status'] != 'SETTLED' or t['currency'] != 'EUR':
            unresolved.append(t['id'])
            continue
        s = t.get('security')
        c = t.get('cash')
        if s and s.get('side') in ('BUY', 'SELL') and s.get('quantity') is not None and s.get('amount') is not None:
            quantities[s['isin']] += D(s['quantity']) * (1 if s['side'] == 'BUY' else -1)
            cash += D(s['amount'])
        elif c and c.get('amount') is not None:
            cash += D(c['amount'])
        else:
            unresolved.append(t['id'])
    current = {h['isin']: D(h['position']['filled']) for h in holdings if h.get('position')}
    comparisons = [dict(isin=i, ledger=str(quantities[i]), current=str(current.get(i, 0)), difference=str(quantities[i]-current.get(i, 0))) for i in sorted(set(current)|set(quantities))]
    return dict(implied_cash=str(cash), positions=comparisons, excluded=excluded, unresolved=unresolved)

def coverage(chart):
    data = chart.get('result', {})
    points = data.get('dataPoints', [])
    valid = sorted((p['timestampUtc'], p['midPrice']) for p in points if p.get('timestampUtc') and p.get('midPrice') is not None)
    dates = sorted(set(t[:10] for t, _ in valid))
    gaps = [(datetime.fromisoformat(b)-datetime.fromisoformat(a)).days for a,b in zip(dates, dates[1:])]
    return dict(isin=chart.get('isin'), name=chart.get('name'), points=len(points), unique_dates=len(dates), first=dates[0] if dates else None, last=dates[-1] if dates else None, median_gap_days=median(gaps) if gaps else None, currency=data.get('currency'), nonpositive=sum(p<=0 for _,p in valid), missing=len(points)-len(valid), error=data.get('error'), adjustment_status='undocumented; not approved for total-return modelling')

def main():
    raw = ROOT/'data/raw/snapshot.json'
    b = json.loads(raw.read_text(encoding='utf-8'))
    details = json.loads((ROOT/'data/raw/transaction_details.json').read_text(encoding='utf-8'))
    tx = b['transactions']['transactions']
    holdings = b['holdings']['holdings']
    r = reconcile(tx, holdings)
    r['reported_cash'] = str(b['cash']['cash']['cashBalance'])
    r['cash_difference'] = str(D(r['implied_cash'])-D(r['reported_cash']))
    r['cash_matches_at_cent_precision'] = D(r['implied_cash']).quantize(D('0.01')) == D(r['reported_cash'])
    values = [dict(isin=h['isin'], name=h['name'], quantity=h['position']['filled'], value=float(D(h['position']['filled'])*D(h['currentQuote']['midPrice']))) for h in holdings]
    r['quote_valuation'] = str(sum((D(v['value']) for v in values), Decimal(0)))
    r['reported_securities'] = str(b['overview']['valuation']['securities'])
    r['quote_valuation_difference'] = str(D(r['quote_valuation'])-D(r['reported_securities']))
    r['overview_identity_difference'] = str(D(b['overview']['valuation']['total'])-D(r['reported_securities'])-D(b['overview']['valuation']['crypto'])-D(r['reported_cash']))
    external_types = {'DEPOSIT','WITHDRAWAL','CASH_TRANSFER_IN','CASH_TRANSFER_OUT'}
    external = sum((D(t['cash']['amount']) for t in tx if t.get('cash') and t['cash']['transactionType'] in external_types and t['status']=='SETTLED'), Decimal(0))
    r['net_external_flows_broker_boundary'] = str(external)
    r['ending_value_minus_flows_assuming_zero_opening'] = str(D(b['overview']['valuation']['total'])-external)
    reported_gain = next(p['simpleAbsoluteReturn'] for p in b['overview']['performance'] if p['timeframe']=='MAX')
    r['broker_reported_gain'] = str(reported_gain)
    r['broker_gain_minus_cashflow_gain'] = str(D(reported_gain)-D(r['ending_value_minus_flows_assuming_zero_opening']))
    historical = {t['security']['isin'] for t in tx if t.get('security')}
    cover = [coverage(c) for c in b['charts']]
    year_cover = [coverage(c) for c in json.loads((ROOT/'data/raw/one_year_charts.json').read_text(encoding='utf-8'))]
    result = dict(captured_at=b['capturedAt'], snapshot_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(), transaction_count=len(tx), transaction_start=min(t['lastEventAt'] for t in tx), transaction_end=max(t['lastEventAt'] for t in tx), pagination_exhausted=b['transactions']['page']['nextCursor'] is None, statuses=dict(Counter(t['status'] for t in tx)), transaction_types=dict(Counter((t.get('security') or t.get('cash') or {}).get('transactionType','UNKNOWN') for t in tx)), detail_count=len(details), current_holdings=len(holdings), historical_instruments=len(historical), closed_instruments=sorted(historical-{h['isin'] for h in holdings}), reconciliation=r, coverage=cover, model_ready=False)
    out=ROOT/'reports'
    out.mkdir(exist_ok=True)
    result['one_year_coverage'] = year_cover
    (out/'audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    def table(rows, columns):
        return '<table><thead><tr>'+''.join('<th>'+html.escape(k)+'</th>' for k in columns)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(row.get(k,'')))+'</td>' for k in columns)+'</tr>' for row in rows)+'</tbody></table>'
    mismatch=sum(D(p['difference'])!=0 for p in r['positions'])
    body=f'''<h1>Portfolio Risk Lab</h1><p>Data audit · snapshot {html.escape(b['capturedAt'])} · EUR · read-only import</p>
    <div class="cards"><section><small>Current holdings</small><strong>{len(holdings)}</strong></section><section><small>Activity records</small><strong>{len(tx)}</strong></section><section><small>Quantity mismatches</small><strong>{mismatch}</strong></section><section><small>Cash residual</small><strong>€{D(r['cash_difference']):.4f}</strong></section></div>
    <div class="notice">Research gate: daily Monte Carlo and performance attribution are not yet enabled. Chart sampling and return adjustments have not passed validation.</div>
    <h2>Reconciliation</h2><p>Transaction range: {result['transaction_start'][:10]} to {result['transaction_end'][:10]}. All returned pages exhausted; this does not establish history before the earliest record. Assumed opening holdings and cash: zero.</p>
    {table([{'check':k,'value':v} for k,v in r.items() if not isinstance(v,list)],['check','value'])}
    <p>Quote-based valuations use asynchronous mid-prices; a discrepancy against the broker valuation is not automatically an accounting error. Internal transfers are external flows at the broker-portfolio boundary, but may be internal at the whole-account boundary.</p>
    <h2>Holdings</h2>{table(sorted(values,key=lambda v:-v['value']),['name','isin','quantity','value'])}
    <h2>Quantity reconstruction, including exited positions</h2>{table(r['positions'],['isin','ledger','current','difference'])}
    <h2>Historical chart coverage</h2>{table(cover,['name','points','first','last','median_gap_days','missing','nonpositive'])}
    <h2>One-year chart sampling</h2>{table(year_cover,['name','points','first','last','median_gap_days'])}
    <h2>Data interpretation</h2><ul><li>Cancelled unfilled orders are excluded. Unknown statuses and reversals require explicit treatment.</li><li>Dividends and their reinvestment purchases are separate ledger events; reinvestment is not an external contribution.</li><li>List timestamps describe last activity, not necessarily execution. Detail history includes timestamps without time-zone offsets; their timezone needs verification.</li><li>Price adjustment conventions are undocumented in the chart responses. Do not assume split-adjusted or dividend-adjusted prices.</li><li>Historical attribution also needs prices for the four exited instruments; current holdings alone would introduce survivorship bias.</li></ul>
    <h2>Next research milestone</h2><ol><li>Cash matches at displayed cent precision. Explain the difference between the broker's gain metric and the gain implied by external flows, checking fee and tax conventions.</li><li>Acquire and validate daily price, distribution and corporate-action histories for all historical instruments, plus the benchmark.</li><li>Build daily portfolio accounting and validate cash-flow timing.</li><li>Implement shrinkage covariance, block bootstrap and contribution-policy comparisons with saved experiment metadata.</li></ol>'''
    page='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Portfolio Risk Lab — Data Audit</title><style>body{font:16px system-ui;background:#101723;color:#e1e8f1;max-width:1200px;margin:40px auto;padding:0 24px}h1{font-size:36px}h2{margin-top:40px}p,li{line-height:1.6;color:#bcc9da}.cards{display:flex;gap:16px;flex-wrap:wrap}section{background:#1c293a;padding:22px;flex:1;min-width:160px;border-radius:12px}small,strong{display:block}strong{font-size:30px;margin-top:10px}.notice{padding:20px;background:#40341c;margin-top:24px;border-radius:10px}table{border-collapse:collapse;width:100%;font-size:13px;display:block;overflow:auto}td,th{padding:10px;text-align:left;border-bottom:1px solid #334155}th{color:#65d6bd}td{font-variant-numeric:tabular-nums}</style>'+body+'</html>'
    (out/'audit.html').write_text(page,encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('coverage','reconciliation')},indent=2))
    print(json.dumps(r,indent=2))

if __name__=='__main__': main()
