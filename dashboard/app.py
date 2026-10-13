"""Nivara | synthetic pharmaceutical operations desk."""

from datetime import date
from pathlib import Path

import plotly.express as px
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from pharma_suite.analytics import build_report, load_facts
from pharma_suite.db import create_db, database_url

st.set_page_config(page_title="Nivara • Pharma operations", page_icon="✚", layout="wide")
st.markdown(
    "<style>" + Path(__file__).with_name("style.css").read_text() + "</style>",
    unsafe_allow_html=True,
)


@st.cache_resource
def engine_for(url: str):
    return create_db(url)


@st.cache_data(ttl=60)
def facts_for(url: str):
    return load_facts(engine_for(url))


def rupees(value) -> str:
    number = float(value)
    if abs(number) >= 10_000_000:
        return f"₹{number / 10_000_000:,.2f} Cr"
    if abs(number) >= 100_000:
        return f"₹{number / 100_000:,.2f} L"
    return f"₹{number:,.0f}"


def chart_style(fig, height=320):
    fig.update_layout(
        height=height,
        margin=dict(l=0, r=15, t=15, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Georgia", color="#254b40"),
        showlegend=False,
        xaxis_title=None,
        yaxis_title=None,
    )
    fig.update_yaxes(gridcolor="#dce1d5", zeroline=False)
    return fig


def export_frame(label, frame, filename, key):
    st.download_button(
        label,
        frame.to_csv(index=False).encode("utf-8"),
        file_name=f"synthetic_{filename}.csv",
        mime="text/csv",
        key=key,
    )


try:
    url = database_url()
    sales, batches = facts_for(url)
except SQLAlchemyError:
    st.error("Database unavailable. Set DATABASE_URL, then run `pharma init` and `pharma ingest`.")
    st.stop()
if sales.empty or batches.empty:
    st.info("Your synthetic foundation is empty. Run `pharma ingest`, then refresh this page.")
    st.stop()

with st.sidebar:
    st.markdown(
        '<div class="brand">✚ nivara</div><div class="brand-sub">PHARMA OPERATIONS DESK / 01</div>',
        unsafe_allow_html=True,
    )
    st.caption("REPORTING WINDOW")
    dates = st.date_input(
        "Sales dates",
        (date(2025, 1, 1), date(2025, 12, 31)),
        min_value=date(2024, 1, 1),
        max_value=batches.snapshot_date.min().date(),
        format="DD/MM/YYYY",
    )
    selected_regions = st.multiselect(
        "Distribution regions",
        sorted(batches.region.unique()),
        default=sorted(batches.region.unique()),
    )
    selected_categories = st.multiselect(
        "Medicine categories",
        sorted(batches.category.unique()),
        default=sorted(batches.category.unique()),
    )
    risk_days = st.select_slider("Expiry horizon (days)", options=[30, 60, 90, 180], value=90)
    st.divider()
    st.caption("DATA PROVENANCE")
    st.write("100% synthetic · India")
    st.caption(
        "Fixed seed 20251011\n\n24 months · Jan 2024–Dec 2025\n\n"
        "No patients. No clinical decisions."
    )
    if st.button("Refresh database snapshot"):
        facts_for.clear()
        st.rerun()
    st.caption(
        f"Source: {'PostgreSQL' if url.startswith('postgres') else 'SQLite demo'}"
        " · cache 60 seconds"
    )
if len(dates) != 2:
    st.info("Select both a start and an end date to build your report.")
    st.stop()
start, end = dates
try:
    report = build_report(
        sales, batches, start, end, selected_regions, selected_categories, risk_days
    )
except ValueError as exc:
    st.error(str(exc))
    st.stop()

st.markdown(
    '<div class="masthead"><span class="eyebrow">NIVARA / INTELLIGENCE / PHASE 01</span>'
    '<span class="synthetic-tag">SYNTHETIC DATA ONLY</span></div>',
    unsafe_allow_html=True,
)
left, right = st.columns([3, 1])
with left:
    st.title("A clearer view of your distribution.")
    st.write("Sales performance, stock position, and the batches that need attention.")
with right:
    st.caption("REPORTING AS OF")
    st.subheader(end.strftime("%d %B %Y"))
    st.caption(
        f"{len(selected_regions)} regions · {len(selected_categories)} categories\n\n"
        f"{start:%d %b %Y} — {end:%d %b %Y}"
    )
st.write("")
cols = st.columns(4)
cols[0].metric("Net sales revenue", rupees(report["revenue"]))
cols[0].caption(f"{report['invoices']:,} distinct invoices · ex-tax")
cols[1].metric("Units distributed", f"{report['units']:,}")
cols[1].caption("Sale units across the selected window")
cols[2].metric("Stock at cost", rupees(report["stock_value"]))
cols[2].caption(f"{report['stock_units']:,} units · as of end date")
cols[3].metric(
    "Inventory turnover", f"{report['turnover']:.2f}×" if report["turnover"] is not None else "—"
)
cols[3].caption("Period COGS / daily average book inventory")
sales_tab, inventory_tab, method_tab = st.tabs(
    ["01 / Sales performance", "02 / Inventory watch", "03 / Definitions & provenance"]
)
with sales_tab:
    a, b = st.columns([2.05, 1], gap="large")
    with a:
        st.subheader("Revenue rhythm")
        st.caption("MONTHLY NET SALES · INR · PARTIAL MONTHS FOLLOW YOUR DATE FILTER")
        fig = px.area(
            report["monthly"], x="month", y="revenue", color_discrete_sequence=["#255f50"]
        )
        fig.update_traces(
            line=dict(width=2),
            fillcolor="rgba(37,95,80,.12)",
            hovertemplate="%{x}<br>₹%{y:,.2f}<extra></extra>",
        )
        st.plotly_chart(chart_style(fig), width="stretch")
        export_frame(
            "↓ Export monthly revenue", report["monthly"], "monthly_revenue", "monthly_export"
        )
    with b:
        st.subheader("Regional contribution")
        st.caption("REVENUE ATTRIBUTED TO THE FULFILLING WAREHOUSE")
        fig = px.bar(
            report["regions"],
            x="revenue",
            y="region",
            orientation="h",
            color_discrete_sequence=["#8ca68d"],
        )
        fig.update_traces(hovertemplate="%{y}<br>₹%{x:,.2f}<extra></extra>")
        st.plotly_chart(chart_style(fig), width="stretch")
    st.divider()
    a, b = st.columns([1.15, 1.9], gap="large")
    with a:
        st.subheader("Therapy mix")
        fig = px.bar(
            report["categories"].sort_values("revenue"),
            x="revenue",
            y="category",
            orientation="h",
            color_discrete_sequence=["#366c5b"],
        )
        st.plotly_chart(chart_style(fig, 350), width="stretch")
    with b:
        st.subheader("Products moving the market")
        st.caption("TOP 10 BY UNITS · ALL VALUES SYNTHETIC")
        st.dataframe(
            report["products"].head(10),
            hide_index=True,
            width="stretch",
            column_config={
                "medicine": "Medicine / pack",
                "revenue": st.column_config.NumberColumn("Revenue (₹)", format="%.2f"),
                "units": "Units",
            },
        )
        export_frame(
            "↓ Export product performance",
            report["products"],
            "product_performance",
            "product_export",
        )
    export_frame("↓ Export regional contribution", report["regions"], "regions", "region_export")
    export_frame("↓ Export therapy mix", report["categories"], "categories", "category_export")
with inventory_tab:
    a, b, c = st.columns(3)
    a.metric("Stock at risk · book cost", rupees(report["risk_value"]))
    b.metric("Near expiry units", f"{report['near_expiry_units']:,}")
    c.metric("Expired units · held", f"{report['expired_units']:,}")
    st.markdown(
        f'<div class="risk-note">Review queue · expired stock and batches expiring within '
        f"{risk_days} days of the reporting date. Values represent acquisition cost, "
        "not projected sales.</div>",
        unsafe_allow_html=True,
    )
    st.subheader("Batch attention ledger")
    columns = [
        "batch_number",
        "medicine",
        "region",
        "warehouse",
        "expiry_date",
        "days_to_expiry",
        "status",
        "stock_units",
        "stock_value",
    ]
    st.dataframe(
        report["risk"][columns],
        hide_index=True,
        width="stretch",
        column_config={
            "stock_value": st.column_config.NumberColumn("Book value (₹)", format="%.2f"),
            "expiry_date": st.column_config.DateColumn("Expiry date", format="DD MMM YYYY"),
        },
    )
    if report["risk"].empty:
        st.success("No held stock falls inside the selected expiry horizon.")
    export_frame(
        "↓ Export expiry review queue", report["risk"][columns], "expiry_risk", "risk_export"
    )
    st.subheader("Stock by distribution hub")
    hubs = (
        report["stock"]
        .groupby("warehouse", as_index=False)
        .agg(units=("stock_units", "sum"), value=("stock_value", "sum"))
    )
    st.dataframe(hubs, hide_index=True, width="stretch")
    with st.expander("Full batch stock ledger"):
        st.dataframe(report["stock"][columns], hide_index=True, width="stretch")
    export_frame(
        "↓ Export closing stock", report["stock"][columns], "closing_stock", "stock_export"
    )
with method_tab:
    st.subheader("Numbers you can trace.")
    st.markdown("""
All entities, medicines, distributors, prices, and transactions are fictional. This is a portfolio
simulation of wholesale distribution, **not clinical, regulatory, or financial reporting software**.

- **Net sales:** line quantity × actual discounted price, excluding GST, freight and returns.
- **Closing stock:** received units through the end date minus sales through that date. The start
  date filters sales performance; it does not discard opening stock.
- **Risk:** held stock with expiry ≤ end date + selected horizon. Expired units are included and
  remain at book cost until disposal; they cannot be sold by the generator.
- **Turnover:** selected-period COGS / exact daily average end-of-day inventory at batch cost.
  This is a period ratio, not annualised. Zero average inventory displays a dash.
- **Filters:** regions apply to the fulfilling warehouse, categories to the batch's medicine.
  Invoice counts are distinct after line filters. Cleared selections return no matching data.
- **Model:** four Indian regions, 120 medicines, four receipt waves, FEFO batch allocation,
  seed 20251011, 1 January 2024 to 31 December 2025. Data cache expires after 60 seconds.

Executable SQL, schema, hand-verified fixtures, and assumptions are in the repository.
""")
st.markdown(
    '<div class="footer">NIVARA • PHARMA DATA & AUTOMATION SUITE / PHASE 1 &nbsp; — &nbsp; '
    "SYNTHETIC PORTFOLIO ENVIRONMENT</div>",
    unsafe_allow_html=True,
)
