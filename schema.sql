-- M&A Target Screening and Valuation Analytics : schema (SQLite)
PRAGMA foreign_keys = ON;

CREATE TABLE sector (
  sector_id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE company (
  company_id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  sector_id INTEGER NOT NULL REFERENCES sector(sector_id),
  country TEXT NOT NULL,
  founded_year INTEGER CHECK (founded_year > 1800),
  is_public INTEGER NOT NULL DEFAULT 0 CHECK (is_public IN (0,1))
);

CREATE TABLE financials (
  fin_id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES company(company_id) ON DELETE CASCADE,
  fiscal_year INTEGER NOT NULL,
  revenue REAL NOT NULL CHECK (revenue > 0),     -- USD millions
  ebitda REAL NOT NULL,
  net_income REAL NOT NULL,
  total_debt REAL NOT NULL CHECK (total_debt >= 0),
  cash REAL NOT NULL CHECK (cash >= 0),
  capex REAL NOT NULL DEFAULT 0,
  UNIQUE (company_id, fiscal_year)
);

CREATE TABLE market_data (
  company_id INTEGER PRIMARY KEY REFERENCES company(company_id) ON DELETE CASCADE,
  market_cap REAL NOT NULL,                      -- USD millions (private: last-round est.)
  as_of_date TEXT NOT NULL
);

CREATE TABLE comparable_deal (
  deal_id INTEGER PRIMARY KEY,
  target_name TEXT NOT NULL,
  sector_id INTEGER NOT NULL REFERENCES sector(sector_id),
  deal_date TEXT NOT NULL,
  enterprise_value REAL NOT NULL,
  ev_revenue REAL NOT NULL,
  ev_ebitda REAL NOT NULL
);

CREATE TABLE acquirer (
  acquirer_id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  budget REAL NOT NULL CHECK (budget > 0),
  preferred_sector_id INTEGER REFERENCES sector(sector_id)
);

CREATE TABLE screening_criteria (
  criteria_id INTEGER PRIMARY KEY,
  acquirer_id INTEGER NOT NULL UNIQUE REFERENCES acquirer(acquirer_id) ON DELETE CASCADE,
  min_revenue REAL NOT NULL,
  min_ebitda_margin REAL NOT NULL,               -- e.g. 0.15
  min_revenue_growth REAL NOT NULL,              -- e.g. 0.05
  max_net_debt_ebitda REAL NOT NULL,             -- e.g. 3.5
  max_ev_ebitda REAL NOT NULL
);

CREATE TABLE valuation (
  valuation_id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES company(company_id) ON DELETE CASCADE,
  method TEXT NOT NULL CHECK (method IN ('COMPS_EV_EBITDA','COMPS_EV_REVENUE','DCF')),
  enterprise_value REAL NOT NULL,
  equity_value REAL NOT NULL,
  valued_on TEXT NOT NULL DEFAULT (date('now')),
  UNIQUE (company_id, method)
);

CREATE TABLE deal_pipeline (
  pipeline_id INTEGER PRIMARY KEY,
  acquirer_id INTEGER NOT NULL REFERENCES acquirer(acquirer_id),
  company_id INTEGER NOT NULL REFERENCES company(company_id),
  stage TEXT NOT NULL DEFAULT 'SCREENED'
    CHECK (stage IN ('SCREENED','CONTACTED','DUE_DILIGENCE','OFFER_MADE','CLOSED','DROPPED')),
  offer_value REAL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (acquirer_id, company_id)
);

CREATE TABLE pipeline_audit (
  audit_id INTEGER PRIMARY KEY,
  pipeline_id INTEGER NOT NULL,
  old_stage TEXT,
  new_stage TEXT,
  changed_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_fin_company ON financials(company_id, fiscal_year);
CREATE INDEX idx_company_sector ON company(sector_id);
CREATE INDEX idx_pipeline_stage ON deal_pipeline(stage);

-- Audit trigger on stage change
CREATE TRIGGER trg_pipeline_stage AFTER UPDATE OF stage ON deal_pipeline
WHEN OLD.stage <> NEW.stage
BEGIN
  INSERT INTO pipeline_audit(pipeline_id, old_stage, new_stage)
  VALUES (OLD.pipeline_id, OLD.stage, NEW.stage);
  UPDATE deal_pipeline SET updated_at = datetime('now') WHERE pipeline_id = NEW.pipeline_id;
END;

-- Latest-year metrics with YoY growth, margin and leverage
CREATE VIEW v_company_metrics AS
SELECT c.company_id, c.name, s.name AS sector, c.sector_id, c.country, c.is_public,
       f.fiscal_year, f.revenue, f.ebitda, f.net_income, f.total_debt, f.cash,
       ROUND(f.ebitda / f.revenue, 4)                          AS ebitda_margin,
       ROUND((f.revenue - p.revenue) / p.revenue, 4)           AS revenue_growth,
       ROUND((f.total_debt - f.cash) / NULLIF(f.ebitda,0), 2)  AS net_debt_ebitda,
       (f.total_debt - f.cash)                                 AS net_debt,
       m.market_cap,
       ROUND((m.market_cap + f.total_debt - f.cash), 1)        AS enterprise_value,
       ROUND((m.market_cap + f.total_debt - f.cash) / NULLIF(f.ebitda,0), 2) AS ev_ebitda
FROM company c
JOIN sector s ON s.sector_id = c.sector_id
JOIN financials f ON f.company_id = c.company_id
 AND f.fiscal_year = (SELECT MAX(fiscal_year) FROM financials WHERE company_id = c.company_id)
JOIN financials p ON p.company_id = c.company_id AND p.fiscal_year = f.fiscal_year - 1
JOIN market_data m ON m.company_id = c.company_id;

-- Sector benchmark multiples from precedent transactions
CREATE VIEW v_sector_multiples AS
SELECT sector_id,
       COUNT(*)                    AS deals,
       ROUND(AVG(ev_ebitda), 2)    AS avg_ev_ebitda,
       ROUND(AVG(ev_revenue), 2)   AS avg_ev_revenue
FROM comparable_deal GROUP BY sector_id;

-- Screening: every acquirer x company pair that passes that acquirer's criteria
CREATE VIEW v_screen_results AS
SELECT a.acquirer_id, a.name AS acquirer, v.company_id, v.name AS target, v.sector,
       v.revenue, v.ebitda_margin, v.revenue_growth, v.net_debt_ebitda, v.ev_ebitda,
       v.enterprise_value
FROM acquirer a
JOIN screening_criteria sc ON sc.acquirer_id = a.acquirer_id
JOIN v_company_metrics v
  ON (a.preferred_sector_id IS NULL OR v.sector_id = a.preferred_sector_id)
WHERE v.revenue         >= sc.min_revenue
  AND v.ebitda_margin   >= sc.min_ebitda_margin
  AND v.revenue_growth  >= sc.min_revenue_growth
  AND v.net_debt_ebitda <= sc.max_net_debt_ebitda
  AND v.ev_ebitda       <= sc.max_ev_ebitda
  AND v.enterprise_value <= a.budget;
