"""Nivara data quality desk: persisted evidence, review queue and explicit revalidation."""

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from pharma_suite.db import create_db, database_url
from pharma_suite.quality.models import Report
from pharma_suite.quality.schema import audit, datasets, findings, issues, records, runs
from pharma_suite.quality.store import set_issue_status, validate_dataset

st.set_page_config(page_title="Nivara • Data quality", page_icon="✚", layout="wide")
st.markdown(
    "<style>" + Path(__file__).parents[1].joinpath("style.css").read_text() + "</style>",
    unsafe_allow_html=True,
)


@st.cache_resource
def quality_engine(url):
    return create_db(url)


try:
    engine = quality_engine(database_url())
    with engine.connect() as conn:
        sources = list(conn.execute(select(datasets).order_by(datasets.c.name)).mappings())
except SQLAlchemyError:
    st.error("Quality database unavailable. Run `pharma init` and check DATABASE_URL.")
    st.stop()
st.markdown(
    '<div class="masthead"><span class="eyebrow">NIVARA / QUALITY ASSURANCE / PHASE 02</span>'
    '<span class="synthetic-tag">SYNTHETIC DATA ONLY</span></div>',
    unsafe_allow_html=True,
)
st.title("Trust starts with evidence.")
st.write("Validation history, quarantined source records, and a review queue you can trace.")
if not sources:
    st.info(
        "No staged datasets. Run `pharma dq validate --dataset demo-clean` and "
        "`pharma dq validate --dataset demo-corrupted` to populate this desk."
    )
    st.stop()
with st.sidebar:
    st.markdown(
        '<div class="brand">✚ nivara</div><div class="brand-sub">DATA QUALITY DESK / 02</div>',
        unsafe_allow_html=True,
    )
    name = st.selectbox("Dataset", [row["name"] for row in sources])
    source = next(row for row in sources if row["name"] == name)
    st.caption(f"Revision {source['version']} · {source['status']}\n\nNo automated corrections.")
with engine.connect() as conn:
    history = list(
        conn.execute(select(runs).where(runs.c.dataset == name).order_by(runs.c.id)).mappings()
    )
    current = pd.read_sql(select(issues).where(issues.c.dataset == name), conn)
if not history:
    st.info(
        "This source is staged but has no validation run. Run `pharma dq validate --dataset "
        + name
        + "`."
    )
    st.stop()
run_id = st.selectbox(
    "Validation run",
    [row["id"] for row in reversed(history)],
    format_func=lambda value: (
        f"Run #{value} · revision {next(r['dataset_version'] for r in history if r['id'] == value)}"
    ),
)
run = next(row for row in history if row["id"] == run_id)
report = Report.model_validate(run["report_json"])
previous = next((r for r in reversed(history) if r["id"] < run_id), None)
prior = Report.model_validate(previous["report_json"]) if previous else None
open_issues = current[current.status.isin(["open", "acknowledged"])]
a, b, c = st.columns(3)
a.metric(
    "Overall quality",
    f"{report.overall_score:.2f}%" if report.overall_score is not None else "N/A",
    delta=f"{report.overall_score - prior.overall_score:+.2f} pts"
    if prior and prior.overall_score is not None and report.overall_score is not None
    else None,
)
b.metric("Failing source records", f"{report.failed_records:,} / {report.total_records:,}")
c.metric("Open / acknowledged issues", f"{len(open_issues):,}")
st.caption(
    f"Run detected {len(report.findings)} findings · {report.passed_records:,} passing records · "
    f"assessment clock {report.reference_at.isoformat()} · actual detection {run['completed_at']}"
)
if run["dataset_version"] != source["version"]:
    st.warning(
        "Source has changed since this run. Revalidate the current revision before approval."
    )
if report.reference_at.year == 2026 and report.reference_at.month == 1:
    st.caption(
        "Historical synthetic replay clock. This does not assert that the 2025 feed is fresh today."
    )
for offset in (0, 3):
    columns = st.columns(3)
    for column, (dimension, metric) in zip(
        columns, list(report.dimensions.items())[offset : offset + 3], strict=True
    ):
        column.metric(
            dimension.replace("_", " ").title(),
            f"{metric['score']:.4f}%" if metric["score"] is not None else "N/A",
        )
        column.caption(
            f"{metric['failed']:,} failed / {metric['eligible']:,} eligible checks · "
            f"{metric['not_applicable']:,} dependent checks not applicable"
        )

st.divider()
left, right = st.columns([2, 1])
with left:
    st.subheader("Quality across runs")
    trend = pd.DataFrame(
        [
            {
                "run": row["id"],
                "quality": float(row["overall_score"])
                if row["overall_score"] is not None
                else None,
                "revision": row["dataset_version"],
                "failed_records": row["failed_records"],
            }
            for row in history
        ]
    )
    fig = px.line(
        trend,
        x="run",
        y="quality",
        markers=True,
        color_discrete_sequence=["#255f50"],
        hover_data=["revision", "failed_records"],
    )
    fig.update_layout(
        height=260,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=5, t=10, b=0),
        font=dict(family="Georgia", color="#254b40"),
    )
    fig.update_yaxes(range=[0, 101], title="Quality (%)", gridcolor="#dce1d5")
    st.plotly_chart(fig, width="stretch")
with right:
    st.subheader("Current review load")
    counts = (
        open_issues.groupby("severity")
        .size()
        .reindex(["critical", "error", "warning"], fill_value=0)
    )
    st.dataframe(counts.rename("open_issues").reset_index(), hide_index=True, width="stretch")
    if prior:
        st.caption(
            f"Previous run #{prior.run_id}: {len(prior.findings)} findings, "
            f"{prior.failed_records} failing records. New/persistent/reopened/resolved:"
        )
    st.json(report.transitions, expanded=False)

st.subheader("Validation review ledger")
st.caption(
    "Findings belong to the selected run. Status and reviewer notes reflect the current "
    "issue lifecycle. "
    "A false-positive label does not bypass scoring or approval."
)
with engine.connect() as conn:
    selected = pd.read_sql(
        select(issues)
        .join(findings, findings.c.issue_id == issues.c.id)
        .where(findings.c.run_id == run_id),
        conn,
    )
f1, f2, f3, f4 = st.columns(4)
severity = f1.multiselect(
    "Severity", ["critical", "error", "warning"], default=["critical", "error", "warning"]
)
status = f2.multiselect(
    "Issue status",
    ["open", "acknowledged", "resolved", "false_positive"],
    default=["open", "acknowledged", "resolved", "false_positive"],
)
entity = f3.multiselect(
    "Entity", sorted(selected.entity.unique()), default=sorted(selected.entity.unique())
)
search = f4.text_input("Record, rule, medicine or batch contains")
filtered = selected[
    selected.severity.isin(severity) & selected.status.isin(status) & selected.entity.isin(entity)
].copy()
if search:
    mask = (
        filtered[["record_ref", "rule_id", "medicine_ref", "batch_ref"]]
        .fillna("")
        .astype(str)
        .apply(lambda col: col.str.contains(search, case=False, regex=False))
        .any(axis=1)
    )
    filtered = filtered[mask]
columns = [
    "id",
    "rule_id",
    "rule_version",
    "entity",
    "record_ref",
    "field",
    "medicine_ref",
    "batch_ref",
    "severity",
    "status",
    "description",
    "resolution_notes",
    "detected_at",
    "last_seen_at",
]
st.dataframe(filtered[columns], hide_index=True, width="stretch")
st.download_button(
    "↓ Export filtered quality findings",
    filtered[columns].to_csv(index=False).encode(),
    file_name=f"synthetic_{name}_run_{run_id}_quality.csv",
    mime="text/csv",
)
with st.expander("Issue distribution by medicine, batch and entity"):
    for column in ("medicine_ref", "batch_ref", "entity"):
        st.caption(column.replace("_", " ").upper())
        st.dataframe(
            filtered.groupby(column, dropna=False).size().rename("findings").reset_index(),
            hide_index=True,
            width="stretch",
        )
if not filtered.empty:
    issue_id = st.selectbox(
        "Inspect finding",
        filtered.id.tolist(),
        format_func=lambda value: (
            f"#{value} · {filtered.loc[filtered.id == value, 'rule_id'].iloc[0]}"
        ),
    )
    finding = filtered[filtered.id == issue_id].iloc[0]
    st.write(f"**Suggested action:** {finding.remediation}")
    with engine.connect() as conn:
        payload = conn.scalar(
            select(records.c.payload).where(
                records.c.dataset == name,
                records.c.entity == finding.entity,
                records.c.record_ref == finding.record_ref,
            )
        )
    with st.expander("Raw failed record — no automatic correction"):
        st.json(payload or source["metadata_json"])
        st.code(
            f"pharma dq correct --dataset {name} --entity {finding.entity} "
            f"--record {finding.record_ref} --expected-version {source['version']} "
            "--patch '<reviewed JSON object>' --actor '<reviewer>' --notes '<evidence>'",
            language="bash",
        )
    with st.form("issue_review"):
        st.caption("Manual review changes issue status only. Source data stays untouched.")
        new_status = st.selectbox(
            "Reviewed status", ["acknowledged", "resolved", "false_positive", "open"]
        )
        actor = st.text_input("Reviewer")
        notes = st.text_area("Review evidence / resolution notes")
        submitted = st.form_submit_button("Save explicit issue review")
        if submitted:
            try:
                set_issue_status(engine, int(issue_id), new_status, actor, notes)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except SQLAlchemyError:
                st.error("Review failed; no change was committed. Check database connectivity.")
with st.expander("Cross-dataset issue distribution"):
    with engine.connect() as conn:
        distribution = pd.read_sql(
            select(
                issues.c.dataset, issues.c.severity, issues.c.status, func.count().label("issues")
            ).group_by(issues.c.dataset, issues.c.severity, issues.c.status),
            conn,
        )
    st.dataframe(distribution, hide_index=True, width="stretch")
with st.expander("Rule check denominators and not-applicable counts"):
    st.dataframe(
        pd.DataFrame(report.rules).T.reset_index(names="rule_id"), hide_index=True, width="stretch"
    )
with st.expander(
    "Audit history — recorded actors are local reviewer labels, not authenticated identities"
):
    with engine.connect() as conn:
        events = pd.read_sql(
            select(audit).where(audit.c.dataset == name).order_by(audit.c.id.desc()).limit(100),
            conn,
        )
    st.dataframe(
        events[["id", "action", "actor", "notes", "occurred_at"]], hide_index=True, width="stretch"
    )
if st.button("Revalidate current staged revision"):
    try:
        validate_dataset(engine, name)
        st.rerun()
    except (ValueError, SQLAlchemyError):
        st.error(
            "Revalidation failed; no partial run was committed. Check the source and database."
        )
st.caption(
    "All data is synthetic. This portfolio engine is not a validated GxP or FDA-compliant system. "
    "Production approval is an explicit CLI action; corrections require audit evidence "
    "and revalidation."
)
