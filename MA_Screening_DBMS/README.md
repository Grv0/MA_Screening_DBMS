# DBMS Project – M&A (Mergers & Acquisitions) Target Screening and Valuation Analytics

Relational database (SQLite) that screens acquisition targets against each acquirer's
criteria, values them (precedent-transaction comps + DCF) and tracks the deal pipeline.

## Files
| File | Purpose |
|---|---|
| schema.sql | 10 tables, constraints, indexes, 3 analytical views, 1 audit trigger |
| main.py | Builds DB, seeds 40 companies / 5 yrs financials, runs valuations, prints reports |
| queries.sql | Ready-made analytical queries (joins, window functions, subqueries, aggregates) |
| ma_screening.db | Generated database |

## Run
    python main.py                                   # rebuild + full report
    python main.py --sql "SELECT * FROM v_screen_results"
    sqlite3 ma_screening.db < queries.sql

## ER overview
sector 1—N company 1—N financials; company 1—1 market_data; sector 1—N comparable_deal;
acquirer 1—1 screening_criteria; acquirer N—M company via deal_pipeline (→ pipeline_audit via trigger);
company 1—N valuation (one row per method).

## Key concepts demonstrated
- Normalization (3NF), PK/FK, CHECK, UNIQUE, ON DELETE CASCADE
- Views: v_company_metrics (margin, growth, leverage, EV/EBITDA), v_sector_multiples, v_screen_results
- Trigger: logs every pipeline stage change
- Window function ranking, correlated subqueries, aggregate group-by
- Valuation: EV = Market Cap + Debt − Cash; comps EV = EBITDA × sector avg multiple; 5-yr DCF (WACC 10%, TG 2.5%)

## Dashboard
    python main.py && python build_dashboard.py     # then open dashboard.html
Interactive page: acquirer selector, KPI cards, sector chart, growth-vs-multiple scatter,
valuation range vs market EV, pipeline donut and a sortable screened-targets table.

## Streamlit app (interactive, live DB)
    pip install -r requirements.txt
    streamlit run app.py
Pages: Overview · Screening (live sliders, save criteria, add to pipeline) · Valuation Lab (live DCF + sensitivity) ·
Pipeline (editable stages + trigger audit log) · SQL Console (read-only, preset queries, CSV export).
The database is auto-created on first launch if `ma_screening.db` is missing.
