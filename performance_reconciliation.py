"""Trace the broker's pre-tax gain to the saved cash-flow ledger."""
import hashlib
import html
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = 'https://help.scalable.capital/en/trading-1541d52f/where-can-i-find-the-total-return-and-portfolio-value-d6877037'
D = lambda v: Decimal(str(v))

def build_report(snapshot, details):
    lookup = {}
    for entry in details:
        t = entry.get('result', {}).get('transaction')
        if not t:
            raise ValueError('Missing transaction detail')
        if t['id'] in lookup:
            raise ValueError('Duplicate detail ID')
        lookup[t['id']] = t
    rows, excluded, issues = [], [], []
    seen = set()
    flows = cash_tax = trade_tax = fees = Decimal(0)
    for record in snapshot['transactions']['transactions']:
        key = record['id']
        if key in seen:
            raise ValueError('Duplicate activity ID')
        seen.add(key)
        if record.get('status') == 'CANCELLED' and not record.get('isCancellation'):
            excluded.append(key)
            continue
        if record.get('status') != 'SETTLED' or record.get('isCancellation') or record.get('currency') != 'EUR':
            issues.append({'id': key, 'issue': 'Unsupported status, reversal or currency'})
            continue
        t = lookup.get(key)
        if t is None:
            issues.append({'id': key, 'issue': 'Missing detail'})
            continue
        c, s = t.get('cash'), t.get('securityTrade')
        row = dict(id=key, date=record['lastEventAt'], name=record.get('description'), tax='0', fee='0')
        if c and record.get('cash'):
            amount = D(c['amount'])
            row.update(kind=c['transactionType'], amount=str(amount))
            if amount != D(record['cash']['amount']):
                issues.append({'id':key, 'issue':'List/detail cash amount mismatch'})
            if c['transactionType'] in {'DEPOSIT','WITHDRAWAL','CASH_TRANSFER_IN','CASH_TRANSFER_OUT'}:
                flows += amount
            tax = c.get('taxDetails')
            if tax:
                if tax.get('grossAmount') is None or tax.get('taxAmount') is None:
                    issues.append({'id':key,'issue':'Incomplete cash tax breakdown'})
                else:
                    gross, withheld = D(tax['grossAmount']), D(tax['taxAmount'])
                    row.update(gross=str(gross), tax=str(withheld))
                    cash_tax += withheld
                    if abs(gross-withheld-amount) > D('0.0001'):
                        issues.append({'id':key,'issue':'Gross minus tax does not match cash'})
            elif c['transactionType'] not in {'DEPOSIT','WITHDRAWAL','CASH_TRANSFER_IN','CASH_TRANSFER_OUT'}:
                issues.append({'id':key,'issue':'Cash tax treatment unavailable'})
        elif s and record.get('security'):
            a = s.get('tradeTransactionAmounts') or {}
            if a.get('marketValuation') is None or s.get('side') not in {'BUY','SELL'}:
                issues.append({'id':key,'issue':'Incomplete trade breakdown'})
                continue
            # Use the canonical breakdown, not duplicate fee/tax summary fields.
            tax = D(a.get('taxAmount') or 0)
            fee = sum((D(a.get(k) or 0) for k in ('transactionFee','venueFee','cryptoSpreadFee')), Decimal(0))
            amount = D(s['totalAmount'])
            expected = D(a['marketValuation'])*(1 if s['side']=='SELL' else -1)-fee-tax
            row.update(kind=s['side'], amount=str(amount), gross=a['marketValuation'], tax=str(tax), fee=str(fee), amount_residual=str(amount-expected))
            cash_tax += 0
            trade_tax += tax
            fees += fee
            if abs(amount-expected)>D('0.0001') or amount != D(record['security']['amount']):
                issues.append({'id':key,'issue':'Trade amount breakdown mismatch'})
        else:
            issues.append({'id':key,'issue':'Unsupported activity type'})
            continue
        rows.append(row)
    value = D(snapshot['overview']['valuation']['total'])
    reported = D(next(p['simpleAbsoluteReturn'] for p in snapshot['overview']['performance'] if p['timeframe']=='MAX'))
    gain = value-flows
    adjusted = gain+cash_tax+trade_tax
    return dict(status='reconciled' if not issues and abs(reported-adjusted)<=D('0.005') else 'unresolved',
        captured_at=snapshot['capturedAt'], boundary='broker portfolio; zero opening value assumed',
        ending_value=str(value), net_external_flows=str(flows), after_tax_gain=str(gain),
        cash_tax_withheld=str(cash_tax), signed_trade_tax=str(trade_tax), net_tax=str(cash_tax+trade_tax),
        fees_already_in_cashflows=str(fees), reconstructed_pre_tax_gain=str(adjusted),
        broker_gain=str(reported), unexplained_residual=str(reported-adjusted),
        issues=issues, excluded_ids=excluded, transactions=rows, definition_source=SOURCE,
        assumptions=['Null cost components in populated trade breakdowns treated as zero; checked against signed totals.',
                     'Historical completeness and zero opening balances remain assumptions, supported by the holdings and cash audit.',
                     'Last-event dates are traceability labels, not validated execution dates.'])

def main():
    paths = [ROOT/'data/raw/snapshot.json', ROOT/'data/raw/transaction_details.json']
    result = build_report(*(json.loads(p.read_text(encoding='utf-8')) for p in paths))
    result['input_sha256'] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    out = ROOT/'reports'
    out.mkdir(exist_ok=True)
    (out/'performance_reconciliation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    metrics = [(k,v) for k,v in result.items() if isinstance(v,str)]
    escape = lambda x: html.escape(str(x))
    summary = ''.join(f'<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>' for k,v in metrics)
    columns = ['date','name','kind','amount','gross','tax','fee','amount_residual','id']
    ledger = ''.join('<tr>'+''.join('<td>'+escape(r.get(k,''))+'</td>' for k in columns)+'</tr>' for r in result['transactions'])
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Performance reconciliation</title><style>body{font:16px system-ui;max-width:1200px;margin:40px auto;padding:24px;background:#101723;color:#e1e8f1}table{border-collapse:collapse;display:block;overflow:auto}td,th{padding:10px;border-bottom:1px solid #334155;text-align:left}p{line-height:1.6}a{color:#65d6bd}</style><h1>Performance reconciliation</h1><p>After-tax gain + signed net taxes = broker pre-tax gain. Fees are already included in cash flows and are not added back.</p><table>'+summary+'</table><h2>Transaction evidence</h2><p>Positive tax is a charge; negative tax is a credit. All amounts are EUR.</p><table><tr>'+''.join('<th>'+k+'</th>' for k in columns)+'</tr>'+ledger+'</table><h2>Issues and assumptions</h2><pre>'+escape(json.dumps({'issues':result['issues'],'assumptions':result['assumptions']},indent=2))+'</pre><p><a href="'+SOURCE+'">Scalable performance definition</a></p></html>'
    (out/'performance_reconciliation.html').write_text(page,encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='transactions'},indent=2))

if __name__ == '__main__': main()
