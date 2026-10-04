"""M&A Target Screening & Valuation Analytics - Streamlit app.
Run:  streamlit run app.py
Connects directly to ma_screening.db (auto-built via main.py if missing)."""
import os, sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import main as ma

DB = ma.DB
STAGES = ["SCREENED", "CONTACTED", "DUE_DILIGENCE", "OFFER_MADE", "CLOSED", "DROPPED"]
st.set_page_config(page_title="M&A Screening & Valuation", page_icon="📊", layout="wide")

# ---------------------------------------------------------------- data layer
def init_db(force=False):
    if force and os.path.exists(DB):
        os.remove(DB)
    if not os.path.exists(DB):
        c = sqlite3.connect(DB); c.execute("PRAGMA foreign_keys=ON")
        ma.build(c); ma.seed(c); ma.run_valuations(c); ma.seed_pipeline(c); c.close()

@st.cache_resource
def conn():
    init_db()
    c = sqlite3.connect(DB, check_same_thread=False)
    c.execute("PRAGMA foreign_keys=ON")
    return c

@st.cache_data(show_spinner=False)
def q(sql, params=()):
    return pd.read_sql(sql, conn(), params=params)

def write(sql, params=()):
    conn().execute(sql, params); conn().commit(); st.cache_data.clear()

def metrics():
    return q("""SELECT v.*,
        MAX(CASE WHEN a.method='COMPS_EV_EBITDA' THEN a.enterprise_value END) AS comps_ebitda_ev,
        MAX(CASE WHEN a.method='COMPS_EV_REVENUE' THEN a.enterprise_value END) AS comps_rev_ev,
        MAX(CASE WHEN a.method='DCF' THEN a.enterprise_value END) AS dcf_ev
        FROM v_company_metrics v LEFT JOIN valuation a ON a.company_id=v.company_id
        GROUP BY v.company_id""")

def dcf(rev, margin, growth, wacc, tg, conv, years=5):
    r, pv = rev, 0.0
    for t in range(1, years + 1):
        r *= 1 + growth
        fcf = r * margin * conv
        pv += fcf / (1 + wacc) ** t
    return pv + (fcf * (1 + tg) / (wacc - tg)) / (1 + wacc) ** years

# ------------------------------------------------------------------- sidebar
st.sidebar.title("📊 M&A Analytics")
page = st.sidebar.radio("Navigate", ["Overview", "Screening", "Valuation", "Pipeline", "SQL Console"])
if st.sidebar.button("♻️ Reset demo database"):
    try: conn().close()
    except Exception: pass
    st.cache_resource.clear(); st.cache_data.clear(); init_db(True); st.rerun()
st.sidebar.caption("USD millions · latest fiscal year · SQLite backend")

M = metrics()

# ------------------------------------------------------------------ overview
if page == "Overview":
    st.title("M&A Target Screening & Valuation Analytics")
    pipe = q("SELECT COUNT(*) n, COALESCE(SUM(offer_value),0) v FROM deal_pipeline").iloc[0]
    c = st.columns(5)
    c[0].metric("Companies", len(M))
    c[1].metric("Total market EV", f"${M.enterprise_value.sum():,.0f}M")
    c[2].metric("Avg EV/EBITDA", f"{M.ev_ebitda.mean():.1f}x")
    c[3].metric("Pipeline deals", int(pipe.n))
    c[4].metric("Pipeline offer value", f"${pipe.v:,.0f}M")

    l, r = st.columns(2)
    sec = M.groupby("sector").agg(growth=("revenue_growth", "mean"), margin=("ebitda_margin", "mean"),
                                  ev_ebitda=("ev_ebitda", "mean"), n=("name", "count")).reset_index()
    sec[["growth", "margin"]] *= 100
    l.plotly_chart(px.bar(sec.melt("sector", ["growth", "margin"]), x="sector", y="value", color="variable",
                          barmode="group", title="Sector growth vs EBITDA margin (%)"), use_container_width=True)
    r.plotly_chart(px.scatter(M, x=M.revenue_growth * 100, y="ev_ebitda", color="sector", size="revenue",
                              hover_name="name", title="Growth vs EV/EBITDA (bubble = revenue)",
                              labels={"x": "Revenue growth %"}), use_container_width=True)
    l, r = st.columns(2)
    l.plotly_chart(px.histogram(M, x="net_debt_ebitda", nbins=15, title="Leverage distribution (Net debt/EBITDA)"),
                   use_container_width=True)
    mult = q("SELECT s.name sector, cd.ev_ebitda FROM comparable_deal cd JOIN sector s USING(sector_id)")
    r.plotly_chart(px.box(mult, x="sector", y="ev_ebitda", title="Precedent-deal EV/EBITDA by sector"),
                   use_container_width=True)

# ----------------------------------------------------------------- screening
elif page == "Screening":
    st.title("🔎 Target Screening")
    acq = q("""SELECT a.acquirer_id, a.name, a.budget, a.preferred_sector_id, sc.min_revenue, sc.min_ebitda_margin,
               sc.min_revenue_growth, sc.max_net_debt_ebitda, sc.max_ev_ebitda
               FROM acquirer a JOIN screening_criteria sc USING(acquirer_id)""")
    who = st.selectbox("Acquirer (loads saved criteria)", acq.name)
    a = acq[acq.name == who].iloc[0]
    secs = q("SELECT sector_id, name FROM sector")
    default_secs = (secs[secs.sector_id == a.preferred_sector_id].name.tolist()
                    if pd.notna(a.preferred_sector_id) else secs.name.tolist())
    c1, c2, c3 = st.columns(3)
    min_rev = c1.slider("Min revenue ($M)", 0.0, 1500.0, float(a.min_revenue), 10.0)
    min_mar = c1.slider("Min EBITDA margin %", 0.0, 40.0, float(a.min_ebitda_margin * 100), 0.5) / 100
    min_gr = c2.slider("Min revenue growth %", -5.0, 25.0, float(a.min_revenue_growth * 100), 0.5) / 100
    max_lev = c2.slider("Max net debt/EBITDA", 0.0, 6.0, float(a.max_net_debt_ebitda), 0.1)
    max_ev = c3.slider("Max EV/EBITDA", 4.0, 20.0, float(a.max_ev_ebitda), 0.5)
    budget = c3.slider("Budget ($M EV)", 100.0, 6000.0, float(a.budget), 50.0)
    pick = st.multiselect("Sectors", secs.name.tolist(), default_secs)

    F = M[(M.revenue >= min_rev) & (M.ebitda_margin >= min_mar) & (M.revenue_growth >= min_gr) &
          (M.net_debt_ebitda <= max_lev) & (M.ev_ebitda <= max_ev) & (M.enterprise_value <= budget) &
          (M.sector.isin(pick))].copy()
    st.subheader(f"{len(F)} of {len(M)} companies pass")
    show = F[["name", "sector", "country", "revenue", "ebitda_margin", "revenue_growth", "net_debt_ebitda",
              "ev_ebitda", "enterprise_value", "dcf_ev"]].sort_values("ev_ebitda")
    show = show.assign(ebitda_margin=show.ebitda_margin * 100, revenue_growth=show.revenue_growth * 100)
    show = show.rename(columns={"ebitda_margin": "ebitda_margin_%", "revenue_growth": "growth_%"}).round(2)
    st.dataframe(show, use_container_width=True, hide_index=True)
    if len(F):
        st.plotly_chart(px.scatter(F, x=F.revenue_growth * 100, y="ev_ebitda", size="revenue", color="sector",
                                   hover_name="name", labels={"x": "Growth %"}), use_container_width=True)
    b1, b2 = st.columns(2)
    chosen = b1.multiselect("Add targets to pipeline", F.name.tolist())
    if b1.button("➕ Add to pipeline", disabled=not chosen):
        for n in chosen:
            row = F[F.name == n].iloc[0]
            write("INSERT OR IGNORE INTO deal_pipeline(acquirer_id,company_id,offer_value) VALUES (?,?,?)",
                  (int(a.acquirer_id), int(row.company_id), round(float(row.enterprise_value) * 1.2, 1)))
        st.success(f"Added {len(chosen)} target(s) with a 20% premium offer placeholder.")
    if b2.button("💾 Save these criteria for " + who):
        write("""UPDATE screening_criteria SET min_revenue=?,min_ebitda_margin=?,min_revenue_growth=?,
                 max_net_debt_ebitda=?,max_ev_ebitda=? WHERE acquirer_id=?""",
              (min_rev, min_mar, min_gr, max_lev, max_ev, int(a.acquirer_id)))
        write("UPDATE acquirer SET budget=? WHERE acquirer_id=?", (budget, int(a.acquirer_id)))
        st.success("Criteria saved to database.")
    st.download_button("⬇️ Export shortlist (CSV)", show.to_csv(index=False), "shortlist.csv")

# ----------------------------------------------------------------- valuation
elif page == "Valuation":
    st.title("💰 Valuation Lab")
    name = st.selectbox("Company", M.sort_values("name").name)
    co = M[M.name == name].iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    wacc = c1.slider("WACC %", 6.0, 16.0, 10.0, 0.5) / 100
    tg = c2.slider("Terminal growth %", 0.0, 4.0, 2.5, 0.25) / 100
    gr = c3.slider("Revenue growth %", 0.0, 25.0, float(min(max(co.revenue_growth, 0), .15) * 100), 0.5) / 100
    conv = c4.slider("EBITDA→FCF conversion %", 30.0, 90.0, 60.0, 5.0) / 100
    my_dcf = dcf(co.revenue, co.ebitda_margin, gr, wacc, tg, conv) if wacc > tg else float("nan")
    methods = {"Comps EV/EBITDA": co.comps_ebitda_ev, "Comps EV/Revenue": co.comps_rev_ev, "DCF (live)": my_dcf}
    k = st.columns(4)
    k[0].metric("Market EV", f"${co.enterprise_value:,.0f}M")
    for i, (m, v) in enumerate(methods.items(), 1):
        k[i].metric(m, f"${v:,.0f}M", f"{(v / co.enterprise_value - 1) * 100:+.1f}% vs market")
    fig = go.Figure(go.Bar(x=list(methods.values()), y=list(methods), orientation="h", marker_color="#2f5bea"))
    fig.add_vline(x=co.enterprise_value, line_dash="dash", line_color="orange", annotation_text="Market EV")
    fig.update_layout(title=f"Valuation football field – {name}", height=320)
    st.plotly_chart(fig, use_container_width=True)
    st.subheader("DCF sensitivity (EV, $M)")
    waccs, tgs = [.08, .09, .10, .11, .12], [.015, .02, .025, .03, .035]
    sens = pd.DataFrame([[dcf(co.revenue, co.ebitda_margin, gr, w, t, conv) for t in tgs] for w in waccs],
                        index=[f"WACC {w:.0%}" for w in waccs], columns=[f"TG {t:.1%}" for t in tgs]).round(0)
    st.dataframe(sens, use_container_width=True)
    if st.button("💾 Save this DCF to valuation table"):
        write("INSERT OR REPLACE INTO valuation(company_id,method,enterprise_value,equity_value) VALUES (?,?,?,?)",
              (int(co.company_id), "DCF", round(my_dcf, 1), round(my_dcf - co.net_debt, 1)))
        st.success("Saved.")
    st.subheader("Financial history")
    st.dataframe(q("SELECT fiscal_year, revenue, ebitda, net_income, total_debt, cash, capex FROM financials "
                   "WHERE company_id=? ORDER BY fiscal_year", (int(co.company_id),)), hide_index=True,
                 use_container_width=True)

# ------------------------------------------------------------------ pipeline
elif page == "Pipeline":
    st.title("🧭 Deal Pipeline")
    P = q("""SELECT p.pipeline_id, a.name AS acquirer, c.name AS target, p.stage, p.offer_value, p.updated_at
             FROM deal_pipeline p JOIN acquirer a USING(acquirer_id) JOIN company c USING(company_id)
             ORDER BY p.pipeline_id""")
    f = st.multiselect("Filter acquirer", P.acquirer.unique().tolist(), P.acquirer.unique().tolist())
    P = P[P.acquirer.isin(f)]
    cnt = P.groupby("stage").agg(deals=("stage", "count"), offer=("offer_value", "sum")).reindex(STAGES).fillna(0).reset_index()
    l, r = st.columns(2)
    l.plotly_chart(px.funnel(cnt, x="deals", y="stage", title="Pipeline funnel"), use_container_width=True)
    r.plotly_chart(px.bar(cnt, x="stage", y="offer", title="Offer value by stage ($M)"), use_container_width=True)
    st.caption("Edit stage or offer value, then save. Stage changes are logged automatically by a database trigger.")
    E = st.data_editor(P, hide_index=True, use_container_width=True, key="pe",
                       disabled=["pipeline_id", "acquirer", "target", "updated_at"],
                       column_config={"stage": st.column_config.SelectboxColumn("stage", options=STAGES, required=True)})
    if st.button("💾 Save pipeline changes"):
        n = 0
        for (_, o), (_, e) in zip(P.iterrows(), E.iterrows()):
            if o.stage != e.stage or o.offer_value != e.offer_value:
                conn().execute("UPDATE deal_pipeline SET stage=?, offer_value=? WHERE pipeline_id=?",
                               (e.stage, None if pd.isna(e.offer_value) else float(e.offer_value), int(o.pipeline_id))); n += 1
        conn().commit(); st.cache_data.clear()
        st.success(f"{n} deal(s) updated."); st.rerun() if n else None
    st.subheader("Audit log (trigger-generated)")
    st.dataframe(q("""SELECT au.changed_at, c.name AS target, au.old_stage, au.new_stage
                      FROM pipeline_audit au JOIN deal_pipeline p USING(pipeline_id) JOIN company c USING(company_id)
                      ORDER BY au.audit_id DESC"""), hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- SQL console
else:
    st.title("🗄️ SQL Console (read-only)")
    objs = q("SELECT type, name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type, name")
    st.caption("Tables & views: " + ", ".join(f"`{n}`" for n in objs.name))
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries.sql")
    presets = {}
    if os.path.exists(path):
        for blk in open(path).read().split(";"):
            blk = blk.strip()
            if blk.startswith("--"):
                title, _, body = blk.partition("\n"); presets[title.strip("- ").strip()] = body.strip()
    pick = st.selectbox("Preset query", ["(custom)"] + list(presets))
    sql = st.text_area("SQL", presets.get(pick, "SELECT * FROM v_company_metrics LIMIT 10"), height=180)
    if st.button("▶ Run"):
        try:
            ro = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
            out = pd.read_sql(sql, ro); ro.close()
            st.dataframe(out, use_container_width=True, hide_index=True)
            st.download_button("⬇️ CSV", out.to_csv(index=False), "result.csv")
        except Exception as ex:
            st.error(ex)
