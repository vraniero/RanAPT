import json
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

from db.schema import init_db
from db import queries

init_db()

st.title("Assessment History")

snapshots = queries.list_snapshots()

if not snapshots:
    st.info("No assessments yet. Go to **New Assessment** to run your first analysis.")
    st.stop()

# ── Total Net Worth ───────────────────────────────────────────────────────────
nw_history = queries.get_net_worth_history()

if nw_history:
    latest = nw_history[-1]
    current_nw = latest["total_value_eur"]

    PERIOD_OPTIONS = {
        "Previous": None,
        "1 Week": 7,
        "1 Month": 30,
        "3 Months": 90,
        "6 Months": 180,
        "1 Year": 365,
        "Custom date": "custom",
    }

    col_nw, col_period, col_custom = st.columns([3, 1, 1])

    with col_period:
        period_label = st.selectbox(
            "Compare to", list(PERIOD_OPTIONS.keys()), key="nw_period"
        )

    with col_custom:
        if period_label == "Custom date":
            earliest_dt = datetime.fromisoformat(nw_history[0]["created_at"].replace("Z", "")).date()
            custom_date = st.date_input(
                "Date",
                value=earliest_dt,
                min_value=earliest_dt,
                max_value=datetime.utcnow().date(),
                key="nw_custom_date",
            )

    # Find comparison snapshot
    comparison_nw = None
    comparison_date = None
    period_value = PERIOD_OPTIONS[period_label]

    if period_value is None:
        # "Previous" — just the second-to-last snapshot
        if len(nw_history) >= 2:
            prev = nw_history[-2]
            comparison_nw = prev["total_value_eur"]
            comparison_date = prev["created_at"][:10]
    elif period_value == "custom":
        # Custom date — find the snapshot closest to the picked date
        cutoff = datetime.combine(custom_date, datetime.min.time())
        best = None
        for row in nw_history[:-1]:
            row_dt = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00").replace("+00:00", ""))
            if best is None or abs((row_dt - cutoff).total_seconds()) < abs((best[0] - cutoff).total_seconds()):
                best = (row_dt, row)
        if best:
            comparison_nw = best[1]["total_value_eur"]
            comparison_date = best[1]["created_at"][:10]
    else:
        # Find the snapshot closest to (now - days)
        cutoff = datetime.utcnow() - timedelta(days=period_value)
        best = None
        for row in nw_history[:-1]:  # exclude latest
            row_dt = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00").replace("+00:00", ""))
            if best is None or abs((row_dt - cutoff).total_seconds()) < abs((best[0] - cutoff).total_seconds()):
                best = (row_dt, row)
        if best:
            comparison_nw = best[1]["total_value_eur"]
            comparison_date = best[1]["created_at"][:10]

    with col_nw:
        if comparison_nw is not None and comparison_nw != 0:
            delta = current_nw - comparison_nw
            delta_pct = (delta / comparison_nw) * 100
            color = "green" if delta >= 0 else "red"
            arrow = "\u25B2" if delta >= 0 else "\u25BC"
            st.metric(
                label="Total Net Worth",
                value=f"\u20ac{current_nw:,.0f}",
            )
            st.markdown(
                f":{color}[{arrow} \u20ac{delta:+,.0f} ({delta_pct:+.1f}%) vs {comparison_date}]"
            )
        else:
            st.metric(label="Total Net Worth", value=f"\u20ac{current_nw:,.0f}")

    st.divider()

# ── Portfolio Value Trend Chart ────────────────────────────────────────────────
asset_data = queries.get_portfolio_assets_over_time()
if asset_data:
    try:
        import pandas as pd
        import plotly.express as px

        df = pd.DataFrame([dict(r) for r in asset_data])
        df["created_at"] = pd.to_datetime(df["created_at"])
        # Sort by time first, then snapshot id
        df = df.sort_values(["created_at", "snapshot_id"]).reset_index(drop=True)
        # Build x-axis label: "date\n#id" or "date\nlabel"
        df["x_label"] = df.apply(
            lambda r: r["created_at"].strftime("%d %b %Y") + f"<br>#{r['snapshot_id']}"
            + (f" – {r['label']}" if r["label"] else ""),
            axis=1,
        )
        # Preserve ordered unique categories for the x-axis
        x_order = list(df["x_label"].unique())
        # Display name: use ticker if available, otherwise asset name
        df["display_name"] = df.apply(
            lambda r: r["ticker"] if r["ticker"] else r["asset_name"], axis=1
        )
        # Format values for bar text
        df["value_display"] = df["total_value_eur"].apply(lambda v: f"\u20ac{v:,.0f}")
        fig = px.bar(
            df,
            x="x_label",
            y="total_value_eur",
            color="display_name",
            text="value_display",
            hover_data=["asset_name", "asset_type", "ticker"],
            title="Portfolio Value Over Time (EUR)",
            labels={
                "x_label": "Assessment",
                "total_value_eur": "Value (EUR)",
                "display_name": "Asset",
                "asset_name": "Name",
                "asset_type": "Type",
                "ticker": "Ticker",
            },
            barmode="stack",
        )
        fig.update_xaxes(type="category", categoryorder="array", categoryarray=x_order)
        fig.update_traces(textposition="inside", textfont_size=10)
        # Deduplicate legend entries (one per asset)
        seen = set()
        for trace in fig.data:
            trace.legendgroup = trace.name
            if trace.name in seen:
                trace.showlegend = False
            else:
                seen.add(trace.name)
        st.plotly_chart(fig, use_container_width=True)
        st.divider()
    except ImportError:
        pass

# ── Snapshot Table ─────────────────────────────────────────────────────────────
STATUS_ICONS = {
    "pending": "⏳",
    "running": "🔄",
    "completed": "✅",
    "failed": "❌",
}

for snap in snapshots:
    snap_id = snap["id"]
    created = snap["created_at"][:19].replace("T", " ")
    label = snap["label"] or f"Snapshot #{snap_id}"
    status = snap["status"]
    file_count = queries.count_snapshot_files(snap_id)

    # Check if this was a user-stopped assessment
    stopped_by_user = False
    if status == "failed":
        _results = queries.get_agent_results(snap_id)
        stopped_by_user = any(
            "Stopped by user" in (dict(r).get("error_message") or "") for r in _results
        )

    if stopped_by_user:
        icon = "🛑"
        display_status = "stopped"
    else:
        icon = STATUS_ICONS.get(status, "❓")
        display_status = status

    with st.expander(f"{icon} **{label}** — {created} — {file_count} file(s) — `{display_status}`"):
        st.markdown(f"**Asset Reader folder:** `{snap['folder_path']}`")
        re_folder = snap["real_estate_folder"] if "real_estate_folder" in snap.keys() else None
        if re_folder:
            st.markdown(f"**Real Estate folder:** `{re_folder}`")

        # Show agents config (which agents ran and their models)
        agents_config_raw = snap["agents_config"] if "agents_config" in snap.keys() else None
        if agents_config_raw:
            try:
                agents_cfg = json.loads(agents_config_raw)
                agent_labels = {
                    "asset-reader": "Asset Reader",
                    "real-estate-assessor": "Real Estate",
                    "global-financial-intelligence": "Global Intelligence",
                }
                parts = []
                for aname, alabel in agent_labels.items():
                    cfg = agents_cfg.get(aname, {})
                    if cfg.get("enabled", True):
                        parts.append(f":green[{alabel}] (`{cfg.get('model', '?')}`)")
                    else:
                        parts.append(f":gray[~~{alabel}~~]")
                st.caption("Agents: " + " · ".join(parts))
            except (json.JSONDecodeError, TypeError):
                pass

        agent_results = queries.get_agent_results(snap_id)
        results_map = {r["agent_name"]: dict(r) for r in agent_results}

        # Token usage and duration summary
        total_in = sum(dict(r).get("input_tokens") or 0 for r in agent_results)
        total_out = sum(dict(r).get("output_tokens") or 0 for r in agent_results)
        # Calculate total duration from earliest start to latest completion
        started_times = []
        completed_times = []
        for r in agent_results:
            rd = dict(r)
            if rd.get("started_at"):
                try:
                    started_times.append(datetime.fromisoformat(rd["started_at"]))
                except ValueError:
                    pass
            if rd.get("completed_at"):
                try:
                    completed_times.append(datetime.fromisoformat(rd["completed_at"]))
                except ValueError:
                    pass
        duration_str = ""
        if started_times and completed_times:
            total_seconds = int((max(completed_times) - min(started_times)).total_seconds())
            minutes, secs = divmod(total_seconds, 60)
            duration_str = f"{minutes}m {secs}s" if minutes else f"{secs}s"

        caption_parts = []
        if duration_str:
            caption_parts.append(f"Duration: **{duration_str}**")
        if total_in or total_out:
            caption_parts.append(f"Tokens: **{total_in:,}** in / **{total_out:,}** out ({total_in + total_out:,} total)")
        if caption_parts:
            st.caption(" · ".join(caption_parts))

        AGENT_TABS = [
            ("asset-reader", "Asset Reader"),
            ("global-financial-intelligence", "Global Intelligence"),
            ("real-estate-assessor", "Real Estate"),
        ]

        tab_labels = [t[1] for t in AGENT_TABS]
        tabs = st.tabs(tab_labels)

        for tab, (agent_name, _) in zip(tabs, AGENT_TABS):
            with tab:
                result = results_map.get(agent_name)
                if not result:
                    st.info("Not run yet.")
                    continue

                ag_status = result["status"]
                if ag_status == "completed":
                    tokens_in = result.get("input_tokens") or 0
                    tokens_out = result.get("output_tokens") or 0
                    started = (result.get("started_at") or "")[:19].replace("T", " ")
                    completed = (result.get("completed_at") or "")[:19].replace("T", " ")
                    st.caption(f"Started: {started} | Completed: {completed} | Tokens: {tokens_in} in / {tokens_out} out")
                    raw = result.get("raw_response") or ""
                    st.markdown(raw)
                elif ag_status == "failed":
                    err = result.get("error_message") or "Unknown error"
                    if "Stopped by user" in err:
                        st.warning(f"Stopped by user")
                    else:
                        st.error(f"Failed: {err}")
                else:
                    st.info(f"Status: {ag_status}")

        # PDF download
        pdf_path = snap["pdf_path"]
        if pdf_path and Path(pdf_path).exists():
            with open(pdf_path, "rb") as f:
                st.download_button(
                    "Download PDF Report",
                    data=f.read(),
                    file_name=f"ranapt_assessment_{snap_id}.pdf",
                    mime="application/pdf",
                    key=f"pdf_dl_{snap_id}",
                )
        elif status == "completed":
            st.caption("PDF not available.")

        # Delete button with confirmation dialog
        if st.button("Delete Snapshot", key=f"del_{snap_id}"):
            st.session_state[f"confirm_del_{snap_id}"] = True

        if st.session_state.get(f"confirm_del_{snap_id}"):
            @st.dialog(f"Delete {label}?")
            def _confirm_delete(sid=snap_id):
                st.warning(f"Are you sure you want to delete **{label}**? This cannot be undone.")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Yes, delete", key=f"yes_del_{sid}", type="primary"):
                        queries.delete_snapshot(sid)
                        del st.session_state[f"confirm_del_{sid}"]
                        st.rerun()
                with col2:
                    if st.button("Cancel", key=f"cancel_del_{sid}"):
                        del st.session_state[f"confirm_del_{sid}"]
                        st.rerun()
            _confirm_delete()
