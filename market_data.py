"""Offline historical-data inventory and validation; no prices are fabricated."""
import argparse
import hashlib
import html
import json
import math
from datetime import date
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
PILOT = {'IE00B53SZB19', 'IE00B8GKDB10', 'US67066G1040', 'US17253J1060'}

def instrument_universe(snapshot):
    current = {h['isin']: h for h in snapshot['holdings']['holdings']}
    universe = {}
    for t in snapshot['transactions']['transactions']:
        s = t.get('security')
        if not s or t['status'] != 'SETTLED' or t.get('isCancellation'):
            continue
        isin = s['isin']
        row = universe.setdefault(isin, dict(isin=isin, names=[], first_activity=t['lastEventAt'][:10], last_activity=t['lastEventAt'][:10]))
        if t.get('description') not in row['names']:
            row['names'].append(t.get('description'))
        row['first_activity'] = min(row['first_activity'], t['lastEventAt'][:10])
        row['last_activity'] = max(row['last_activity'], t['lastEventAt'][:10])
    for isin, h in current.items():
        universe.setdefault(isin, dict(isin=isin, names=[h['name']], first_activity=None, last_activity=None))
    for isin, row in universe.items():
        row.update(current=isin in current, pilot=isin in PILOT, name=current.get(isin, {}).get('name') or row['names'][0],
                   required_end=snapshot['capturedAt'][:10] if isin in current else row['last_activity'],
                   provider_symbol=None, exchange=None, currency=None, mapping_status='unverified')
    return sorted(universe.values(), key=lambda x: x['isin'])

def validate_series(rows, metadata, start, end, expected_sessions=None):
    """Validate one listing. Sessions must come from its exchange calendar.

    Returns observations and blockers, not a claim of economic correctness.
    No forward filling, outlier deletion or currency conversion is performed.
    """
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if start > end:
        raise ValueError('Start must not follow end')
    blockers, invalid, parsed = [], [], []
    for index, row in enumerate(rows):
        try:
            day = date.fromisoformat(row['date'])
            close, adjusted = float(row['close']), float(row['adjusted_close'])
            if not all(math.isfinite(v) and v > 0 for v in (close, adjusted)):
                raise ValueError('Prices must be finite and positive')
            parsed.append((day, close, adjusted))
        except (KeyError, TypeError, ValueError):
            invalid.append(index)
    dates = [d for d, _, _ in parsed]
    duplicates = len(dates)-len(set(dates))
    if invalid: blockers.append('invalid_prices_or_dates')
    if duplicates: blockers.append('duplicate_dates')
    if dates != sorted(dates): blockers.append('unsorted_dates')
    window = sorted(x for x in parsed if start <= x[0] <= end)
    if not window: blockers.append('empty_requested_window')
    if metadata.get('frequency') != 'daily': blockers.append('daily_frequency_not_documented')
    if metadata.get('adjustment') != 'split_and_dividend': blockers.append('total_return_adjustment_not_documented')
    for field in ('provider','symbol','isin','exchange','currency','source_url','retrieved_at'):
        if not metadata.get(field): blockers.append('missing_'+field)
    if metadata.get('mapping_verified') is not True: blockers.append('instrument_mapping_unverified')
    if metadata.get('currency') != 'EUR': blockers.append('eur_conversion_required')
    gaps = [(b[0]-a[0]).days for a,b in zip(window,window[1:])]
    jumps = [{'date': b[0].isoformat(), 'return': b[2]/a[2]-1} for a,b in zip(window,window[1:]) if abs(b[2]/a[2]-1) > 0.25]
    if jumps: blockers.append('large_adjusted_return_requires_review')
    missing = None
    if expected_sessions is None:
        blockers.append('exchange_calendar_not_supplied')
    else:
        sessions = {date.fromisoformat(d) for d in expected_sessions if start <= date.fromisoformat(d) <= end}
        if not sessions: blockers.append('empty_exchange_calendar')
        missing = sorted(d.isoformat() for d in sessions-set(dates))
        if missing: blockers.append('missing_exchange_sessions')
        if {x[0] for x in window}-sessions: blockers.append('unexpected_session_dates')
    return dict(structural_checks_passed=not blockers, model_ready=False,
        note='Economic validation, corporate actions and adequate estimation history remain separate gates.',
        observations=len(window), first=window[0][0].isoformat() if window else None,
        last=window[-1][0].isoformat() if window else None, invalid_rows=invalid,
        duplicate_dates=duplicates, median_gap_days=median(gaps) if gaps else None,
        missing_sessions=missing, large_moves=jumps, blockers=blockers)

def inventory():
    raw = ROOT/'data/raw/snapshot.json'
    snapshot = json.loads(raw.read_text(encoding='utf-8'))
    universe = instrument_universe(snapshot)
    chart_sets = [('max', snapshot['charts']), ('one_year', json.loads((ROOT/'data/raw/one_year_charts.json').read_text(encoding='utf-8')))]
    coverage = []
    for timeframe, charts in chart_sets:
        for chart in charts:
            result = chart.get('result', {})
            rows = [{'date':p['timestampUtc'][:10], 'close':p['midPrice'], 'adjusted_close':p['midPrice']} for p in result.get('dataPoints', []) if p.get('timestampUtc')]
            # Copying midPrice into the validator's adjusted column permits structural inspection only.
            # Metadata explicitly rejects the unknown adjustment; no return series is exported.
            meta = dict(provider='Scalable MCP', symbol=chart['isin'], isin=chart['isin'], currency=result.get('currency'), frequency='sampled_chart', adjustment='unknown', mapping_verified=False)
            check = validate_series(rows, meta, '2016-01-01', snapshot['capturedAt'][:10])
            coverage.append(dict(isin=chart['isin'], timeframe=timeframe, **check))
    report = dict(snapshot_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(), as_of=snapshot['capturedAt'],
                  instruments=universe, chart_checks=coverage, daily_provider_tested=False,
                  benchmark_status='not selected', model_ready=False)
    out=ROOT/'reports'; out.mkdir(exist_ok=True)
    (out/'market_data_inventory.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    e=lambda v:html.escape(str(v))
    table=''.join('<tr>'+''.join('<td>'+e(r.get(k,''))+'</td>' for k in ['name','isin','current','pilot','first_activity','required_end','mapping_status'])+'</tr>' for r in universe)
    ct=''.join(f'<tr><td>{e(c["isin"])}</td><td>{c["timeframe"]}</td><td>{c["observations"]}</td><td>{c["median_gap_days"]}</td><td>{e(", ".join(c["blockers"]))}</td></tr>' for c in coverage)
    page='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Market data readiness</title><style>body{font:16px system-ui;max-width:1200px;margin:40px auto;padding:24px;background:#101723;color:#e1e8f1}table{display:block;overflow:auto;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #334155;text-align:left}p{line-height:1.6}</style><h1>Historical market data readiness</h1><p>20 historical instruments; four pilot instruments. No external provider has been authenticated or validated. Models remain gated.</p><p>Required dates use last-activity timestamps as an initial coverage bound, not validated execution dates. Obtain at least one preceding trading close. Current holdings require a separate multi-year estimation window; short histories must not be extended with invented observations.</p><table><tr><th>Name</th><th>ISIN</th><th>Current</th><th>Pilot</th><th>First activity</th><th>Required through</th><th>Mapping</th></tr>'+table+'</table><h2>Existing MCP chart checks</h2><p>Mid-prices are not assumed to be total-return adjusted. Weekdays are not used as exchange calendars.</p><table><tr><th>ISIN</th><th>Window</th><th>Points</th><th>Median gap (days)</th><th>Blockers</th></tr>'+ct+'</table></html>'
    (out/'market_data_inventory.html').write_text(page,encoding='utf-8')
    print(json.dumps({'instruments':len(universe),'pilot':sum(r['pilot'] for r in universe),'chart_checks':len(coverage),'daily_provider_tested':False}))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('inventory')
    p=sub.add_parser('validate'); p.add_argument('file',type=Path)
    args=parser.parse_args()
    if args.command=='inventory': inventory()
    else:
        data=json.loads(args.file.read_text(encoding='utf-8'))
        report=validate_series(data['rows'],data['metadata'],data['start'],data['end'],data.get('expected_sessions'))
        print(json.dumps(report,indent=2))
        if not report['structural_checks_passed']: raise SystemExit(1)

if __name__=='__main__':main()
