"""Small cached EODHD reader. Credentials are never written into request logs."""
import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load_token(path):
    token = os.environ.get('EODHD_API_TOKEN', '').strip()
    if not token and path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() == 'EODHD_API_TOKEN':
                token = value.strip().strip('\"\'')
    if not token:
        raise ValueError('EODHD_API_TOKEN not found in environment or supplied token file')
    return token

class Client:
    def __init__(self, token, cache, max_calls=4):
        self.token, self.cache, self.max_calls = token, Path(cache), max_calls
        self.calls = 0

    def get(self, endpoint, params=None):
        if not re.fullmatch(r'(search|eod)/[A-Za-z0-9._-]+', endpoint):
            raise ValueError('Unsupported endpoint')
        params = dict(params or {})
        if 'api_token' in params:
            raise ValueError('Supply credentials only through the token loader')
        params['fmt'] = 'json'
        identity = json.dumps([endpoint, params], sort_keys=True)
        key = hashlib.sha256(identity.encode()).hexdigest()
        path = self.cache/(key+'.json')
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        if self.calls >= self.max_calls:
            raise ValueError('Per-run request cap reached; no further request sent')
        self.calls += 1
        url = 'https://eodhd.com/api/'+endpoint+'?'+urllib.parse.urlencode({**params,'api_token':self.token})
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                raw = response.read()
            data = json.loads(raw)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'EODHD HTTP {error.code}; not retried') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise RuntimeError('EODHD request or JSON decoding failed; not retried') from None
        if not isinstance(data, list):
            raise RuntimeError('Unexpected EODHD response shape; not cached')
        # Refuse to persist any response containing the credential.
        if self.token in raw.decode('utf-8', errors='replace'):
            raise RuntimeError('Response contained credential; not saved')
        result = dict(endpoint=endpoint, parameters=params, retrieved_at=datetime.now(timezone.utc).isoformat(),
                      sha256=hashlib.sha256(raw).hexdigest(), data=data)
        self.cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token-file',type=Path,default=ROOT/'.env')
    parser.add_argument('--max-calls',type=int,default=4)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('search-pilot')
    sub.add_parser('pilot')
    p=sub.add_parser('fetch');p.add_argument('symbol');p.add_argument('--start',required=True);p.add_argument('--end',required=True)
    args=parser.parse_args()
    client=Client(load_token(args.token_file),ROOT/'data/raw/eodhd',args.max_calls)
    if args.command=='search-pilot':
        from market_data import PILOT
        for isin in sorted(PILOT):
            result=client.get('search/'+isin,{'limit':50})
            candidates=[{k:r.get(k) for k in ('Code','Exchange','Name','Currency','ISIN','isPrimary')} for r in result['data']]
            print(json.dumps({'query_isin':isin,'candidates':candidates}))
    elif args.command=='pilot':
        from market_data import validate_series
        items=[('IE00B53SZB19','SXRV.XETRA'),('IE00B8GKDB10','VGWD.XETRA'),('US67066G1040','NVD.XETRA'),('US17253J1060','3A9.F')]
        reports=[]
        for isin,symbol in items:
            result=client.get('eod/'+symbol,{'from':'2026-01-26','to':'2026-09-21','period':'d','order':'a'})
            metadata=dict(provider='EODHD',symbol=symbol,isin=isin,exchange=symbol.split('.')[-1],currency='EUR',frequency='daily',adjustment='split_and_dividend',mapping_verified=False,source_url='https://eodhd.com/financial-apis/api-for-historical-data-and-volumes',retrieved_at=result['retrieved_at'])
            reports.append(dict(isin=isin,symbol=symbol,**validate_series(result['data'],metadata,'2026-01-26','2026-09-21')))
        (ROOT/'reports').mkdir(exist_ok=True)
        (ROOT/'reports/eodhd_pilot.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
        print(json.dumps(reports,indent=2))
    else:
        from datetime import date
        if date.fromisoformat(args.start)>date.fromisoformat(args.end):
            raise ValueError('Start follows end')
        result=client.get('eod/'+args.symbol,{'from':args.start,'to':args.end,'period':'d','order':'a'})
        print(json.dumps({'symbol':args.symbol,'observations':len(result['data']),'first':result['data'][0]['date'] if result['data'] else None,'last':result['data'][-1]['date'] if result['data'] else None}))
    print(json.dumps({'network_calls_this_run':client.calls}))

if __name__=='__main__':
    try: main()
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from None
