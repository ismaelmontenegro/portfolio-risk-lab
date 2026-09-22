# Portfolio Risk Lab

First milestone: an offline, reproducible audit of the user's authenticated Scalable portfolio. No trades, network requests, or credential storage are performed by this project.

Run with Python 3.11 or later, from this directory:

```sh
python audit.py
python performance_reconciliation.py
python market_data.py inventory
python -m unittest -v
```

Open `reports/audit.html` for the audit dashboard. `reports/audit.json` is the machine-readable result. Raw MCP responses are preserved under `data/raw/`; these and generated reports contain private financial information and are excluded from Git.

## Scope and assumptions

Historical-data tooling and the provider comparison are documented in [MARKET_DATA.md](MARKET_DATA.md). The inventory covers all historical instruments and produces `reports/market_data_inventory.html`. External daily-data coverage is not yet verified; a provider connection is still needed for the pilot.

- Zero opening holdings and cash are hypotheses tested against the returned ledger, not assumed proof of complete account history.
- Reconstruct positions from settled buy/sell records, including reinvestment. Exclude cancelled orders; flag unsupported records.
- The cash ledger initially uses signed list amounts without inventing fee adjustments. Any residual remains visible.
- Historical prices are chart observations, not validated daily total returns. Simulations are deliberately gated pending adequate data.
- Transaction last-event timestamps are not guaranteed execution timestamps. Raw detail responses preserve execution history for the next normalization stage.
- This snapshot is manually imported through the authenticated MCP tool session. It does not implement background OAuth or a refresh connection.

## Planned architecture

Python numerical engine (NumPy/pandas/SciPy), DuckDB and Parquet, Streamlit and Plotly dashboard, scikit-learn covariance estimators, research notebooks. The audit intentionally runs using the standard library so it remains usable before these dependencies are installed.

Separate modules will cover ingestion, event accounting, return construction, risk models, simulation policies and validation. Notebook and dashboard code must call the same numerical implementation. Each experiment will save input hashes, model parameters, seed, software version and validation results.

## Next steps

1. Cash reconciles at cent precision. The performance bridge now reconciles using signed taxes; verify timestamp semantics before daily accounting.
2. Audit a historical market-data source against all historical ISINs; require daily data, currency/exchange mapping and documented dividend/split treatment.
3. Reconstruct daily valuations; reconcile performance and external flows at a declared portfolio boundary.
4. Implement and backtest a Gaussian baseline and multivariate block bootstrap before adding conditional-volatility models.
