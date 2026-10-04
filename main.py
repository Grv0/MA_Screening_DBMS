"""M&A Target Screening and Valuation Analytics - runner.
Usage:  python main.py            (build DB, seed, valuate, screen, report)
        python main.py --sql "SELECT * FROM v_company_metrics LIMIT 5"
"""
import sqlite3, random, os, sys, math

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "ma_screening.db")
YEARS = [2021, 2022, 2023, 2024, 2025]
SECTORS = ["Technology", "Healthcare", "Industrials", "Consumer", "Energy"]
COUNTRIES = ["USA", "UK", "Germany", "India", "Japan", "Canada"]
NAMES = ["Apex","Nova","Orion","Zenith","Vertex","Helix","Quanta","Terra","Blue","Atlas",
         "Cobalt","Ember","Fusion","Gale","Ionic","Jade","Kinetic","Lumen","Meridian","Nimbus"]
SUFFIX = ["Systems","Labs","Group","Holdings","Industries","Partners"]

def build(conn):
    conn.executescript(open(os.path.join(HERE, "schema.sql")).read())

def seed(conn):
    random.seed(42)
    cur = conn.cursor()
    cur.executemany("INSERT INTO sector(name) VALUES (?)", [(s,) for s in SECTORS])
    used = set()
    for i in range(40):
        while True:
            nm = f"{random.choice(NAMES)} {random.choice(SUFFIX)}"
            if nm not in used: used.add(nm); break
        sid = random.randint(1, len(SECTORS))
        cur.execute("INSERT INTO company(name,sector_id,country,founded_year,is_public) VALUES (?,?,?,?,?)",
                    (nm, sid, random.choice(COUNTRIES), random.randint(1975, 2015), random.randint(0, 1)))
        cid = cur.lastrowid
        rev = random.uniform(60, 900)
        growth = random.uniform(-0.03, 0.22)
        margin = random.uniform(0.06, 0.34)
        debt_x = random.uniform(0.3, 5.0)
        for y in YEARS:
            rev *= 1 + growth + random.uniform(-0.02, 0.02)
            ebitda = rev * margin * random.uniform(0.95, 1.05)
            cur.execute("""INSERT INTO financials(company_id,fiscal_year,revenue,ebitda,net_income,
                           total_debt,cash,capex) VALUES (?,?,?,?,?,?,?,?)""",
                        (cid, y, round(rev,1), round(ebitda,1), round(ebitda*random.uniform(.3,.6),1),
                         round(ebitda*debt_x,1), round(rev*random.uniform(.03,.15),1), round(rev*random.uniform(.03,.08),1)))
        mult = random.uniform(6, 16)
        net_debt = ebitda*debt_x - rev*0.08
        cur.execute("INSERT INTO market_data VALUES (?,?,?)",
                    (cid, round(max(ebitda*mult - net_debt, 50),1), "2025-12-31"))
    # precedent deals
    for sid in range(1, len(SECTORS)+1):
        base = random.uniform(8, 13)
        for k in range(6):
            m = base + random.uniform(-2, 2)
            cur.execute("INSERT INTO comparable_deal(target_name,sector_id,deal_date,enterprise_value,ev_revenue,ev_ebitda) VALUES (?,?,?,?,?,?)",
                        (f"Precedent {sid}-{k+1}", sid, f"202{random.randint(2,5)}-0{random.randint(1,9)}-15",
                         round(random.uniform(300, 2500),1), round(m*0.22,2), round(m,2)))
    # acquirers + criteria
    acq = [("Titan Capital", 1500, 1, 120, .15, .05, 3.0, 12),
           ("Meridian Strategic", 2500, None, 150, .12, .03, 3.5, 13),
           ("Helios Partners", 1000, 2, 80, .10, .06, 4.0, 11)]
    for n, b, ps, mr, mm, mg, nd, ev in acq:
        cur.execute("INSERT INTO acquirer(name,budget,preferred_sector_id) VALUES (?,?,?)", (n, b, ps))
        cur.execute("INSERT INTO screening_criteria(acquirer_id,min_revenue,min_ebitda_margin,min_revenue_growth,max_net_debt_ebitda,max_ev_ebitda) VALUES (?,?,?,?,?,?)",
                    (cur.lastrowid, mr, mm, mg, nd, ev))
    conn.commit()

def run_valuations(conn):
    """Comps (EV/EBITDA, EV/Revenue) + 5-year DCF; results stored in valuation."""
    cur = conn.cursor()
    rows = cur.execute("""SELECT v.company_id, v.revenue, v.ebitda, v.net_debt, v.revenue_growth, v.ebitda_margin,
                                 sm.avg_ev_ebitda, sm.avg_ev_revenue
                          FROM v_company_metrics v JOIN v_sector_multiples sm USING(sector_id)""").fetchall()
    wacc, tg = 0.10, 0.025
    for cid, rev, ebitda, nd, g, mar, mE, mR in rows:
        out = {"COMPS_EV_EBITDA": ebitda*mE, "COMPS_EV_REVENUE": rev*mR}
        fg, pv, r = max(min(g, 0.15), 0.0), 0.0, rev
        for t in range(1, 6):
            r *= 1 + fg
            fcf = r * mar * 0.6                      # ~60% EBITDA->FCF conversion
            pv += fcf / (1+wacc)**t
        tv = (fcf*(1+tg)/(wacc-tg)) / (1+wacc)**5
        out["DCF"] = pv + tv
        for m, ev in out.items():
            cur.execute("""INSERT OR REPLACE INTO valuation(company_id,method,enterprise_value,equity_value)
                           VALUES (?,?,?,?)""", (cid, m, round(ev,1), round(ev-nd,1)))
    conn.commit()

def seed_pipeline(conn):
    cur = conn.cursor()
    for aid, cid, ev in cur.execute("SELECT acquirer_id, company_id, enterprise_value FROM v_screen_results").fetchall():
        cur.execute("INSERT OR IGNORE INTO deal_pipeline(acquirer_id,company_id,offer_value) VALUES (?,?,?)",
                    (aid, cid, round(ev*1.2,1)))   # 20% premium placeholder
    first = cur.execute("SELECT pipeline_id FROM deal_pipeline LIMIT 1").fetchone()
    if first:   # demonstrate the audit trigger
        cur.execute("UPDATE deal_pipeline SET stage='CONTACTED' WHERE pipeline_id=?", first)
        cur.execute("UPDATE deal_pipeline SET stage='DUE_DILIGENCE' WHERE pipeline_id=?", first)
    conn.commit()

def show(conn, title, sql):
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]; rows = cur.fetchall()
    print(f"\n=== {title} ===")
    w = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(c) for i, c in enumerate(cols)]
    print(" | ".join(c.ljust(w[i]) for i, c in enumerate(cols)))
    print("-+-".join("-"*x for x in w))
    for r in rows: print(" | ".join(str(v).ljust(w[i]) for i, v in enumerate(r)))

def main():
    if "--sql" in sys.argv:
        conn = sqlite3.connect(DB); show(conn, "Custom query", sys.argv[sys.argv.index("--sql")+1]); return
    if os.path.exists(DB): os.remove(DB)
    conn = sqlite3.connect(DB); conn.execute("PRAGMA foreign_keys=ON")
    build(conn); seed(conn); run_valuations(conn); seed_pipeline(conn)
    show(conn, "Screened targets (per acquirer criteria)",
         "SELECT acquirer,target,sector,revenue,ebitda_margin,revenue_growth,net_debt_ebitda,ev_ebitda FROM v_screen_results ORDER BY acquirer, ev_ebitda LIMIT 12")
    show(conn, "Top 8 undervalued vs sector precedent multiples",
         """SELECT v.name, v.sector, v.enterprise_value AS market_ev, ROUND(v.ebitda*sm.avg_ev_ebitda,1) AS comps_ev,
            ROUND((v.ebitda*sm.avg_ev_ebitda/v.enterprise_value-1)*100,1) AS upside_pct
            FROM v_company_metrics v JOIN v_sector_multiples sm USING(sector_id) ORDER BY upside_pct DESC LIMIT 8""")
    show(conn, "Valuation football field (avg across methods, top 8 by DCF)",
         """SELECT c.name, ROUND(MIN(enterprise_value),1) AS low_ev, ROUND(AVG(enterprise_value),1) AS mid_ev,
            ROUND(MAX(enterprise_value),1) AS high_ev FROM valuation v JOIN company c USING(company_id)
            GROUP BY c.name ORDER BY MAX(CASE WHEN method='DCF' THEN enterprise_value END) DESC LIMIT 8""")
    show(conn, "Sector summary",
         """SELECT sector, COUNT(*) companies, ROUND(AVG(ebitda_margin)*100,1) avg_margin_pct,
            ROUND(AVG(revenue_growth)*100,1) avg_growth_pct, ROUND(AVG(ev_ebitda),2) avg_ev_ebitda
            FROM v_company_metrics GROUP BY sector ORDER BY avg_growth_pct DESC""")
    show(conn, "Pipeline funnel", "SELECT stage, COUNT(*) deals, ROUND(SUM(offer_value),1) total_offer FROM deal_pipeline GROUP BY stage")
    show(conn, "Audit log (trigger demo)", "SELECT * FROM pipeline_audit")
    print(f"\nDatabase written to {DB}")

if __name__ == "__main__":
    main()
