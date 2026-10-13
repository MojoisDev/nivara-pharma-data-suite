"""Nivara automation desk: durable workflow evidence and explicit local actions."""

import uuid
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from pharma_suite.automation.alerts import acknowledge, evaluate_alerts
from pharma_suite.automation.config import load_config
from pharma_suite.automation.reporting import report_path
from pharma_suite.automation.scheduler import status
from pharma_suite.automation.schema import (
    alert_events,
    alerts,
    attempts,
    emails,
    events,
    executions,
    reports,
)
from pharma_suite.automation.workflow import enqueue
from pharma_suite.db import create_db, database_url

st.set_page_config(page_title="Nivara • Automation", page_icon="✚", layout="wide")
st.markdown(
    "<style>" + Path(__file__).parents[1].joinpath("style.css").read_text() + "</style>",
    unsafe_allow_html=True,
)


@st.cache_resource
def engine_for_automation(url):
    return create_db(url)


try:
    engine = engine_for_automation(database_url())
    config = load_config()
    scheduler = status(engine)
    with engine.connect() as conn:
        history = pd.read_sql(
            select(executions).order_by(executions.c.created_at.desc()).limit(100), conn
        )
        counts = dict(
            conn.execute(
                select(executions.c.status, func.count()).group_by(executions.c.status)
            ).all()
        )
        review = pd.read_sql(select(alerts).order_by(alerts.c.id.desc()), conn)
        artifacts = pd.read_sql(
            select(reports).order_by(reports.c.created_at.desc()).limit(100), conn
        )
        outbox = pd.read_sql(select(emails).order_by(emails.c.created_at.desc()).limit(100), conn)
except (SQLAlchemyError, ValueError):
    st.error("Automation unavailable. Check DATABASE_URL and AUTOMATION_CONFIG; run pharma init.")
    st.stop()

st.markdown(
    '<div class="masthead"><span class="eyebrow">NIVARA / WORKFLOW OPERATIONS / PHASE 03</span>'
    '<span class="synthetic-tag">SYNTHETIC DATA ONLY</span></div>',
    unsafe_allow_html=True,
)
st.title("Work that leaves a trace.")
st.write("Reporting workflows, batch attention, and delivery evidence in one operations desk.")
with st.sidebar:
    st.markdown(
        '<div class="brand">✚ nivara</div><div class="brand-sub">AUTOMATION DESK / 03</div>',
        unsafe_allow_html=True,
    )
    st.write("Scheduler: " + ("healthy" if scheduler["healthy"] else scheduler["status"]))
    st.caption("One dedicated scheduler process. This page never starts a scheduler.")
    st.caption(
        f"Timezone: {config.timezone}\n\nDaily: {config.daily_cron}\n\nWeekly: {config.weekly_cron}"
    )
    if st.button("Refresh automation evidence"):
        st.rerun()

cols = st.columns(4)
cols[0].metric("Successful workflows", str(counts.get("succeeded", 0)))
cols[1].metric("Failed / timed out", str(counts.get("failed", 0) + counts.get("timed_out", 0)))
cols[2].metric("Queued / running", str(counts.get("queued", 0) + counts.get("running", 0)))
cols[3].metric(
    "Active alert conditions", str(int(review.status.isin(["new", "acknowledged"]).sum()))
)
st.caption("Statistics cover all persisted executions. History tables show the latest 100 records.")
job_tab, alert_tab, report_tab, mail_tab = st.tabs(
    ["01 / Workflow control", "02 / Alert review", "03 / Report library", "04 / Mail evidence"]
)
with job_tab:
    st.subheader("Next scheduled briefings")
    if scheduler.get("jobs"):
        st.dataframe(pd.DataFrame(scheduler["jobs"]), hide_index=True, width="stretch")
        st.caption(
            f"Last scheduler heartbeat: {scheduler.get('heartbeat_at')} · "
            "timezone offsets are shown explicitly."
        )
    else:
        st.info(
            "Scheduler has not started. Run pharma auto schedule in a "
            "dedicated process or start the Compose scheduler service."
        )
    with st.expander("Queue a manual reporting workflow"):
        st.caption(
            "Local operation: queues a persisted request for the dedicated "
            "worker. It never repairs or approves business data."
        )
        if "automation_request_key" not in st.session_state:
            st.session_state.automation_request_key = "ui:" + str(uuid.uuid4())
        with st.form("manual_workflow"):
            kind = st.selectbox("Workflow cadence", ["daily", "weekly"])
            actor = st.text_input("Workflow reviewer")
            notes = st.text_area("Workflow purpose / evidence")
            confirmed = st.checkbox("I confirm this synthetic reporting workflow should be queued")
            submitted = st.form_submit_button("Queue confirmed workflow")
            if submitted:
                if not confirmed:
                    st.error("Confirm the workflow before queueing it.")
                else:
                    try:
                        run_id = enqueue(
                            engine,
                            kind,
                            st.session_state.automation_request_key,
                            actor,
                            notes,
                            config,
                        )
                        st.success(
                            f"Workflow queued: {run_id}. "
                            "Repeated submission uses the same request key."
                        )
                    except (ValueError, SQLAlchemyError):
                        st.error(
                            "Request rejected. Supply reviewer/evidence and check the database."
                        )
        if st.button("Prepare a new workflow request"):
            st.session_state.automation_request_key = "ui:" + str(uuid.uuid4())
            st.rerun()
    st.subheader("Execution ledger")
    columns = [
        "id",
        "kind",
        "status",
        "actor",
        "created_at",
        "started_at",
        "completed_at",
        "duration_seconds",
        "attempts",
        "error_type",
    ]
    st.dataframe(history[columns], hide_index=True, width="stretch")
    if not history.empty:
        chart = px.bar(
            history.fillna({"duration_seconds": 0}),
            x="created_at",
            y="duration_seconds",
            color="status",
            color_discrete_map={
                "succeeded": "#255f50",
                "failed": "#b46c46",
                "timed_out": "#b59446",
                "queued": "#8ca68d",
                "running": "#487f8e",
            },
        )
        chart.update_layout(
            height=260,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=10, b=0, l=0, r=0),
        )
        st.plotly_chart(chart, width="stretch")
        run_id = st.selectbox("Inspect execution", history.id.tolist())
        with engine.connect() as conn:
            stage_events = pd.read_sql(
                select(events).where(events.c.execution_id == run_id).order_by(events.c.id), conn
            )
            attempt_rows = pd.read_sql(
                select(attempts).where(attempts.c.execution_id == run_id), conn
            )
        st.dataframe(attempt_rows, hide_index=True, width="stretch")
        st.dataframe(stage_events, hide_index=True, width="stretch")
with alert_tab:
    st.subheader("Conditions that need attention")
    st.caption(
        "Expiry and stock conditions use stored inventory snapshot dates. "
        "They do not assert present physical stock. Unchanged alerts are "
        "not re-notified."
    )
    severity = st.multiselect(
        "Alert severity", ["critical", "error", "warning"], default=["critical", "error", "warning"]
    )
    lifecycle = st.multiselect(
        "Alert lifecycle", ["new", "acknowledged", "resolved"], default=["new", "acknowledged"]
    )
    filtered = review[review.severity.isin(severity) & review.status.isin(lifecycle)]
    st.dataframe(
        filtered[
            [
                "id",
                "kind",
                "severity",
                "status",
                "reason",
                "record_ids",
                "revision",
                "detected_at",
                "last_seen_at",
            ]
        ],
        hide_index=True,
        width="stretch",
    )
    active = filtered[filtered.status != "resolved"]
    if not active.empty:
        with st.form("alert_acknowledgement"):
            alert_id = st.selectbox("Alert to acknowledge", active.id.tolist())
            reviewer = st.text_input("Alert reviewer")
            evidence = st.text_area("Alert review notes")
            if st.form_submit_button("Acknowledge selected alert"):
                try:
                    acknowledge(engine, int(alert_id), reviewer, evidence)
                    st.rerun()
                except (ValueError, SQLAlchemyError):
                    st.error(
                        "Review rejected. Supply reviewer and notes; check database availability."
                    )
    if st.button("Re-evaluate current alert conditions"):
        try:
            evaluate_alerts(engine, config)
            st.rerun()
        except SQLAlchemyError:
            st.error("Alert evaluation failed; transaction rolled back.")
    with st.expander("Alert lifecycle audit"):
        with engine.connect() as conn:
            alert_audit = pd.read_sql(
                select(alert_events).order_by(alert_events.c.id.desc()).limit(100), conn
            )
        st.dataframe(alert_audit, hide_index=True, width="stretch")
with report_tab:
    st.subheader("Briefings you can inspect")
    st.caption(
        "Every workbook includes snapshot provenance, KPI assumptions and "
        "the persisted validation findings. Files are checksum-verified "
        "before download."
    )
    if artifacts.empty:
        st.info("No generated reports yet. Queue a workflow above or run pharma auto run.")
    else:
        st.dataframe(
            artifacts[["id", "execution_id", "created_at", "byte_size", "snapshot_hash"]],
            hide_index=True,
            width="stretch",
        )
        report_id = st.selectbox("Workbook", artifacts.id.tolist())
        try:
            path = report_path(engine, report_id, config)
            st.download_button(
                "↓ Download synthetic Excel briefing",
                path.read_bytes(),
                file_name=path.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            selected = artifacts[artifacts.id == report_id].iloc[0]
            st.json(selected.summary_json)
        except ValueError:
            st.error("Artifact is absent or changed; download blocked. Restore the report volume.")
with mail_tab:
    st.subheader("Prepared, attempted, delivered.")
    st.caption(
        "Default mode writes a local .eml preview and opens no SMTP "
        "connection. Sent, failed and uncertain states are distinct; "
        "uncertain delivery requires manual reconciliation."
    )
    if outbox.empty:
        st.info("No prepared email summaries yet.")
    else:
        st.dataframe(
            outbox[
                [
                    "id",
                    "execution_id",
                    "subject",
                    "status",
                    "attempts",
                    "created_at",
                    "delivered_at",
                    "error_type",
                ]
            ],
            hide_index=True,
            width="stretch",
        )
        email_id = st.selectbox("Email preview", outbox.id.tolist())
        chosen = outbox[outbox.id == email_id].iloc[0]
        st.write(chosen.subject)
        st.code(chosen.body_text, language=None, wrap_lines=True)
        st.caption(
            "SMTP delivery is controlled through environment configuration and"
            " authenticated CLI/API actions."
        )
st.caption(
    "All data is synthetic. This portfolio system is not validated "
    "clinical, regulatory or GxP software. Reviewers are locally "
    "attributed labels, not authenticated electronic signatures."
)
