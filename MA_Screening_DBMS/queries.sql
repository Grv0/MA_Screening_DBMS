-- Q1: Screened targets per acquirer
SELECT acquirer, target, sector, revenue, ebitda_margin, revenue_growth, net_debt_ebitda, ev_ebitda
FROM v_screen_results ORDER BY acquirer, ev_ebitda;

-- Q2: Comps-based valuation vs current market EV (upside/downside)
SELECT v.name, v.sector, v.enterprise_value AS market_ev,
       ROUND(v.ebitda * sm.avg_ev_ebitda, 1) AS comps_ev,
       ROUND((v.ebitda * sm.avg_ev_ebitda / v.enterprise_value - 1) * 100, 1) AS upside_pct
FROM v_company_metrics v JOIN v_sector_multiples sm ON sm.sector_id = v.sector_id
ORDER BY upside_pct DESC LIMIT 10;

-- Q3: Sector summary
SELECT sector, COUNT(*) AS companies, ROUND(AVG(ebitda_margin)*100,1) AS avg_margin_pct,
       ROUND(AVG(revenue_growth)*100,1) AS avg_growth_pct, ROUND(AVG(ev_ebitda),2) AS avg_ev_ebitda
FROM v_company_metrics GROUP BY sector ORDER BY avg_growth_pct DESC;

-- Q4: Ranked targets using a composite score (window function)
SELECT RANK() OVER (ORDER BY (revenue_growth*100 + ebitda_margin*100 - net_debt_ebitda*2 - ev_ebitda) DESC) AS rnk,
       name, sector,
       ROUND(revenue_growth*100 + ebitda_margin*100 - net_debt_ebitda*2 - ev_ebitda,1) AS score
FROM v_company_metrics ORDER BY rnk LIMIT 10;

-- Q5: Pipeline funnel
SELECT stage, COUNT(*) AS deals, ROUND(SUM(COALESCE(offer_value,0)),1) AS total_offer
FROM deal_pipeline GROUP BY stage;

-- Q6: Revenue multiple over the 5-year window (growth leaders)
SELECT c.name,
 ROUND((SELECT revenue FROM financials WHERE company_id=c.company_id ORDER BY fiscal_year DESC LIMIT 1) /
       (SELECT revenue FROM financials WHERE company_id=c.company_id ORDER BY fiscal_year ASC LIMIT 1), 2) AS revenue_multiple
FROM company c ORDER BY revenue_multiple DESC LIMIT 5;
