import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from db.schema import init_db
from db import queries
from agents.loader import load_system_prompt, load_agent_model
from agents.runner import AgentProcess

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
                max_value=datetime.now(timezone.utc).date(),
                key="nw_custom_date",
            )

    # Find comparison snapshot
    comparison_nw = None
    comparison_date = None
    comparison_snap_id = None
    period_value = PERIOD_OPTIONS[period_label]

    def _find_closest(cutoff_dt):
        best = None
        for row in nw_history[:-1]:
            row_dt = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00").replace("+00:00", ""))
            if best is None or abs((row_dt - cutoff_dt).total_seconds()) < abs((best[0] - cutoff_dt).total_seconds()):
                best = (row_dt, row)
        return best

    if period_value is None:
        # "Previous" — just the second-to-last snapshot
        if len(nw_history) >= 2:
            prev = nw_history[-2]
            comparison_nw = prev["total_value_eur"]
            comparison_date = prev["created_at"][:10]
            comparison_snap_id = prev["snapshot_id"]
    elif period_value == "custom":
        cutoff = datetime.combine(custom_date, datetime.min.time())
        best = _find_closest(cutoff)
        if best:
            comparison_nw = best[1]["total_value_eur"]
            comparison_date = best[1]["created_at"][:10]
            comparison_snap_id = best[1]["snapshot_id"]
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=period_value)
        best = _find_closest(cutoff)
        if best:
            comparison_nw = best[1]["total_value_eur"]
            comparison_date = best[1]["created_at"][:10]
            comparison_snap_id = best[1]["snapshot_id"]

    _has_comparison = comparison_nw is not None and comparison_nw != 0

    # Calculate after-tax net worth
    TAX_RATE = 0.26375  # German Abgeltungsteuer
    unrealized_gains = queries.get_unrealized_gains(latest["snapshot_id"])
    estimated_tax = unrealized_gains * TAX_RATE
    after_tax_nw = current_nw - estimated_tax
    has_cost_basis = queries.get_total_cost_basis(latest["snapshot_id"]) is not None

    with col_nw:
        if _has_comparison:
            delta = current_nw - comparison_nw
            delta_pct = (delta / comparison_nw) * 100
            color = "green" if delta >= 0 else "red"
            arrow = "\u25B2" if delta >= 0 else "\u25BC"
            st.metric(
                label="Total Net Worth",
                value=f"\u20ac{current_nw:,.0f}",
            )
        else:
            st.metric(label="Total Net Worth", value=f"\u20ac{current_nw:,.0f}")
        if has_cost_basis:
            st.caption(f"After tax (est.): \u20ac{after_tax_nw:,.0f} · Tax on gains: \u20ac{estimated_tax:,.0f}")
        else:
            st.caption("After-tax estimate unavailable — no cost basis data")

    # Popover outside columns so it can use full page width
    if _has_comparison:
        with st.popover(f":{color}[{arrow} \u20ac{delta:+,.0f} ({delta_pct:+.1f}%) vs {comparison_date}]", use_container_width=True):
            import pandas as pd
            latest_assets = {r["asset_name"]: r for r in queries.get_resolved_assets(latest["snapshot_id"])}
            prev_assets = {r["asset_name"]: r for r in queries.get_resolved_assets(comparison_snap_id)}
            all_names = sorted(set(latest_assets) | set(prev_assets))
            rows = []
            for name in all_names:
                cur_val = latest_assets[name]["total_value_eur"] if name in latest_assets else 0
                prev_val = prev_assets[name]["total_value_eur"] if name in prev_assets else 0
                asset_delta = cur_val - prev_val
                ticker = (latest_assets.get(name) or prev_assets.get(name))["ticker"] or ""
                display = ticker if ticker else name
                rows.append({
                    "Asset": display,
                    comparison_date: prev_val,
                    "Now": cur_val,
                    "\u0394": asset_delta,
                })
            rows.sort(key=lambda r: r["\u0394"], reverse=True)
            df = pd.DataFrame(rows)
            st.dataframe(
                df.style.format({
                    comparison_date: "\u20ac{:,.0f}",
                    "Now": "\u20ac{:,.0f}",
                    "\u0394": "\u20ac{:+,.0f}",
                }).map(
                    lambda v: "color: green" if v > 0 else ("color: red" if v < 0 else ""),
                    subset=["\u0394"],
                ),
                hide_index=True, use_container_width=True,
            )

    # ── Ask about net worth changes ─────────────────────────────────────────
    if _has_comparison:
        st.subheader("Ask the agents")

        MODEL_OPTIONS = ["haiku", "sonnet", "opus"]
        _default_model = load_agent_model("scenario-analyst")

        col_q, col_qmodel = st.columns([4, 1])
        with col_qmodel:
            nw_q_model = st.selectbox(
                "Model", MODEL_OPTIONS,
                index=MODEL_OPTIONS.index(_default_model) if _default_model in MODEL_OPTIONS else 1,
                key="nw_q_model",
            )
        with col_q:
            nw_question = st.text_input(
                "Question",
                placeholder="Why did my net worth change? Which assets contributed the most?",
                key="nw_question",
            )

        if st.button("Ask", disabled=not nw_question, type="primary", key="nw_q_ask"):
            # Build context: asset deltas + agent reports from both snapshots
            import pandas as pd
            latest_assets = {r["asset_name"]: r for r in queries.get_resolved_assets(latest["snapshot_id"])}
            prev_assets = {r["asset_name"]: r for r in queries.get_resolved_assets(comparison_snap_id)}
            all_names = sorted(set(latest_assets) | set(prev_assets))

            delta_lines = [f"Period: {comparison_date} -> now", f"Total net worth: €{comparison_nw:,.0f} -> €{current_nw:,.0f} (Δ €{delta:+,.0f}, {delta_pct:+.1f}%)", "", "Per-asset breakdown:"]
            for name in all_names:
                cur_val = latest_assets[name]["total_value_eur"] if name in latest_assets else 0
                prev_val = prev_assets[name]["total_value_eur"] if name in prev_assets else 0
                ad = cur_val - prev_val
                ticker = (latest_assets.get(name) or prev_assets.get(name))["ticker"] or ""
                display = f"{name} ({ticker})" if ticker else name
                delta_lines.append(f"  {display}: €{prev_val:,.0f} -> €{cur_val:,.0f} (Δ €{ad:+,.0f})")

            context_parts = ["\n".join(delta_lines)]

            # Add asset-reader reports from both snapshots for richer context
            for snap_id, snap_label in [(comparison_snap_id, f"Assessment from {comparison_date}"), (latest["snapshot_id"], "Latest assessment")]:
                ar_result = queries.get_agent_result_by_name(snap_id, "asset-reader")
                if ar_result and ar_result["raw_response"]:
                    context_parts.append(f"=== {snap_label} — Asset Reader report ===\n{ar_result['raw_response']}")
                gfi_result = queries.get_agent_result_by_name(snap_id, "global-financial-intelligence")
                if gfi_result and gfi_result["raw_response"]:
                    context_parts.append(f"=== {snap_label} — Global Intelligence report ===\n{gfi_result['raw_response']}")

            system_prompt = load_system_prompt("scenario-analyst")
            user_message = nw_question.strip() + "\n\n" + "\n\n".join(context_parts)

            proc = AgentProcess("scenario-analyst", system_prompt, user_message, model=nw_q_model)
            st.session_state["nw_q_proc"] = proc
            st.session_state["nw_q_running"] = True
            st.session_state["nw_q_result"] = None

            def _run_nw_q():
                proc.run()
                st.session_state["nw_q_running"] = False

            t = threading.Thread(target=_run_nw_q, daemon=True)
            t.start()
            st.session_state["nw_q_thread"] = t
            st.rerun()

        # Live monitor
        if st.session_state.get("nw_q_running"):
            proc = st.session_state.get("nw_q_proc")
            thread = st.session_state.get("nw_q_thread")
            st.info("Analyzing...")
            if proc:
                log = proc.activity_log
                if log:
                    with st.expander("Activity"):
                        st.code("\n".join(log[-20:]), language=None)
            if thread and thread.is_alive():
                time.sleep(2)
                st.rerun()
            else:
                # Done
                result = proc.get_result()
                st.session_state["nw_q_running"] = False
                st.session_state["nw_q_result"] = result
                st.rerun()

        # Show result
        nw_q_result = st.session_state.get("nw_q_result")
        if nw_q_result:
            if nw_q_result["success"]:
                st.markdown(nw_q_result["raw_response"])
                tokens_in = nw_q_result.get("input_tokens", 0)
                tokens_out = nw_q_result.get("output_tokens", 0)
                st.caption(f"Tokens: {tokens_in:,} in / {tokens_out:,} out")
            else:
                st.error(f"Failed: {nw_q_result.get('error', 'Unknown error')}")
            if st.button("Clear", key="nw_q_clear"):
                st.session_state.pop("nw_q_result", None)
                st.rerun()

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
