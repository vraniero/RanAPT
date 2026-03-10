import threading
import time
from datetime import date, datetime, timedelta
import calendar

import streamlit as st

from db.schema import init_db
from db import queries
from agents.loader import load_system_prompt, load_agent_model
from agents.runner import AgentProcess

init_db()

MODEL_OPTIONS = ["haiku", "sonnet", "opus"]

st.title("Watch List")
st.markdown("Upcoming events identified by the **Global Financial Intelligence** agent.")

# Auto-archive past events
queries.archive_past_watch_events()

events = queries.get_all_watch_events()

if not events:
    st.info("No watch events yet. Run an assessment to populate the calendar.")
    st.stop()

# Parse events into dicts with proper dates
parsed_events = []
for e in events:
    ed = dict(e)
    try:
        ed["_date"] = datetime.strptime(ed["event_date"], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        continue
    ed["status"] = ed.get("status") or "active"
    parsed_events.append(ed)

if not parsed_events:
    st.info("No valid events found.")
    st.stop()

# Filter controls
show_archived = st.checkbox("Show archived events", value=False, key="show_archived")
visible_events = [e for e in parsed_events if show_archived or e["status"] != "archived"]

# ── Month navigation ──────────────────────────────────────────────────────────
all_dates = [e["_date"] for e in visible_events]
if not all_dates:
    st.info("No active events. Enable **Show archived events** to see past items.")
    st.stop()
min_date = min(all_dates)
max_date = max(all_dates)

# Default to current month, or earliest event month if all in future
today = date.today()
default_month = today if min_date <= today <= max_date else min_date

if "cal_year" not in st.session_state:
    st.session_state.cal_year = default_month.year
if "cal_month" not in st.session_state:
    st.session_state.cal_month = default_month.month

nav_cols = st.columns([1, 3, 1])
with nav_cols[0]:
    if st.button("< Prev"):
        if st.session_state.cal_month == 1:
            st.session_state.cal_month = 12
            st.session_state.cal_year -= 1
        else:
            st.session_state.cal_month -= 1
        st.rerun()
with nav_cols[1]:
    month_name = calendar.month_name[st.session_state.cal_month]
    st.markdown(f"### {month_name} {st.session_state.cal_year}")
with nav_cols[2]:
    if st.button("Next >"):
        if st.session_state.cal_month == 12:
            st.session_state.cal_month = 1
            st.session_state.cal_year += 1
        else:
            st.session_state.cal_month += 1
        st.rerun()

# ── Build calendar grid ──────────────────────────────────────────────────────
year = st.session_state.cal_year
month = st.session_state.cal_month

# Events for this month
month_events = [e for e in visible_events if e["_date"].year == year and e["_date"].month == month]
events_by_day = {}
for e in month_events:
    day = e["_date"].day
    events_by_day.setdefault(day, []).append(e)

IMPACT_COLORS = {
    "high": "red",
    "medium": "orange",
    "low": "blue",
}

CATEGORY_LABELS = {
    "central_bank": "Central Bank",
    "earnings": "Earnings",
    "economic_data": "Economic Data",
    "geopolitical": "Geopolitical",
    "regulatory": "Regulatory",
    "other": "Other",
}

# Calendar header
day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
header_cols = st.columns(7)
for i, name in enumerate(day_names):
    header_cols[i].markdown(f"**{name}**")

# Calendar weeks
cal = calendar.Calendar(firstweekday=0)
month_days = cal.monthdayscalendar(year, month)

for week in month_days:
    cols = st.columns(7)
    for i, day in enumerate(week):
        with cols[i]:
            if day == 0:
                st.markdown("&nbsp;")
                continue

            day_events = events_by_day.get(day, [])
            if day_events:
                # Show day number with event indicator
                event_dots = ""
                for ev in day_events:
                    if ev["status"] == "archived":
                        event_dots += " :gray[○]"
                    elif ev["status"] == "low_priority":
                        event_dots += " :gray[●]"
                    else:
                        color = IMPACT_COLORS.get(ev.get("impact", ""), "gray")
                        event_dots += f" :{color}[●]"
                is_today = (day == today.day and month == today.month and year == today.year)
                day_label = f"**{day}**" if is_today else str(day)
                st.markdown(f"{day_label}{event_dots}")
                for ev in day_events:
                    if ev["status"] == "archived":
                        st.markdown(f":gray[~~{ev['title'][:20]}~~]", help=ev.get("description", ""))
                    elif ev["status"] == "low_priority":
                        st.markdown(f":gray[{ev['title'][:20]}]", help=ev.get("description", ""))
                    else:
                        color = IMPACT_COLORS.get(ev.get("impact", ""), "gray")
                        st.markdown(f":{color}[{ev['title'][:20]}]", help=ev.get("description", ""))
            else:
                is_today = (day == today.day and month == today.month and year == today.year)
                st.markdown(f"**{day}**" if is_today else str(day))

st.divider()

# ── Event list with details ──────────────────────────────────────────────────
st.subheader("Events")

# Sort by date
sorted_events = sorted(visible_events, key=lambda e: e["_date"])

# Get latest portfolio context for scenario analysis
_portfolio_context = ""
_latest_snapshots = queries.list_snapshots()
for _snap in _latest_snapshots:
    if _snap["status"] == "completed":
        _ar_result = queries.get_agent_result_by_name(_snap["id"], "asset-reader")
        if _ar_result and _ar_result["raw_response"]:
            _portfolio_context = _ar_result["raw_response"]
            break

_needs_poll = False

STATUS_LABELS = {"active": "", "archived": " :gray[(archived)]", "low_priority": " :gray[(low priority)]"}

for ev in sorted_events:
    impact = ev.get("impact", "medium")
    ev_status = ev.get("status", "active")
    color = "gray" if ev_status in ("archived", "low_priority") else IMPACT_COLORS.get(impact, "gray")
    category = CATEGORY_LABELS.get(ev.get("category", ""), ev.get("category", ""))
    snap_label = ev.get("label") or f"Assessment #{ev['snapshot_id']}"
    snap_date = (ev.get("snapshot_created_at") or "")[:10]
    ev_id = ev["id"]
    status_suffix = STATUS_LABELS.get(ev_status, "")

    with st.expander(f":{color}[{impact.upper()}] **{ev['title']}** — {ev['event_date']}{status_suffix}"):
        st.markdown(ev.get("description") or "No description.")
        st.caption(
            f"Category: **{category}** · Impact: **{impact}** · "
            f"Source: [{snap_label}]({''}) ({snap_date})"
        )
        st.caption(f"From assessment **#{ev['snapshot_id']}** — {snap_label} — run on {snap_date}")

        # Status actions
        status_cols = st.columns(4)
        with status_cols[0]:
            if ev_status != "active":
                if st.button("Mark active", key=f"active_{ev_id}"):
                    queries.update_watch_event_status(ev_id, "active")
                    st.rerun()
        with status_cols[1]:
            if ev_status != "low_priority":
                if st.button("Low priority", key=f"low_{ev_id}"):
                    queries.update_watch_event_status(ev_id, "low_priority")
                    st.rerun()
        with status_cols[2]:
            if ev_status != "archived":
                if st.button("Archive", key=f"archive_{ev_id}"):
                    queries.update_watch_event_status(ev_id, "archived")
                    st.rerun()

        # Suggested actions via scenario-analyst
        running_key = f"actions_running_{ev_id}"
        model_key = f"actions_model_{ev_id}"

        def _launch_analysis(ev_id=ev_id, ev=ev, category=category, impact=impact):
            """Start the scenario-analyst for this event."""
            model = st.session_state.get(model_key, load_agent_model("scenario-analyst"))
            system_prompt = load_system_prompt("scenario-analyst")

            scenario_prompt = (
                f"Upcoming event: **{ev['title']}** on {ev['event_date']}.\n\n"
                f"Description: {ev.get('description', 'No details available.')}\n\n"
                f"Category: {category} · Impact: {impact}\n\n"
                "Based on this upcoming event and the investor's current portfolio, "
                "formulate exactly 3 concrete strategies the investor could use to "
                "prepare for or capitalize on this event. For each strategy, include:\n"
                "1. A clear action title\n"
                "2. What to do and when\n"
                "3. Expected outcome if the event plays out as expected\n"
                "4. Risk if the event doesn't materialize or plays out differently\n"
            )

            user_parts = [scenario_prompt]
            if _portfolio_context:
                user_parts.append(
                    "=== CURRENT PORTFOLIO (from latest assessment) ===\n\n"
                    + _portfolio_context
                )

            proc = AgentProcess(
                "scenario-analyst", system_prompt,
                "\n\n".join(user_parts), model=model,
            )
            st.session_state[f"actions_proc_{ev_id}"] = proc
            st.session_state[f"actions_model_used_{ev_id}"] = model
            st.session_state[running_key] = True
            threading.Thread(target=proc.run, daemon=True).start()

        if st.session_state.get(running_key):
            proc = st.session_state.get(f"actions_proc_{ev_id}")
            if proc and proc.status == "completed":
                result = proc.get_result()
                model_used = st.session_state.get(f"actions_model_used_{ev_id}", "sonnet")
                queries.add_event_action(
                    ev_id, model_used, result.get("raw_response", ""),
                    result.get("input_tokens", 0), result.get("output_tokens", 0),
                )
                st.session_state[running_key] = False
                _needs_poll = True  # rerun after loop to show saved result
            elif proc and proc.status == "failed":
                st.session_state[running_key] = False
                st.error(f"Analysis failed: {proc.get_result().get('error', 'Unknown error')}")
            else:
                st.divider()
                with st.status("Scenario analyst is working...", expanded=True):
                    log = proc.activity_log if proc else []
                    if log:
                        st.caption(log[-1])
                if st.button("Cancel", key=f"cancel_actions_{ev_id}"):
                    if proc:
                        proc.stop()
                    st.session_state[running_key] = False
                    _needs_poll = True
                else:
                    _needs_poll = True  # keep polling

        else:
            # Show saved actions from DB
            saved_actions = queries.get_event_actions(ev_id)
            if saved_actions:
                st.divider()
                for idx, action in enumerate(saved_actions):
                    a = dict(action)
                    action_date = (a["created_at"] or "")[:19].replace("T", " ")
                    tokens_in = a.get("input_tokens") or 0
                    tokens_out = a.get("output_tokens") or 0

                    header_col, del_col = st.columns([6, 1])
                    with header_col:
                        st.caption(f"Analysis #{len(saved_actions) - idx} · {action_date} · Model: `{a['model']}` · Tokens: {tokens_in:,} in / {tokens_out:,} out")
                    with del_col:
                        if st.button("Delete", key=f"del_action_{a['id']}"):
                            queries.delete_event_action(a["id"])
                            _needs_poll = True
                    st.markdown(a.get("raw_response") or "")
                    if idx < len(saved_actions) - 1:
                        st.divider()

            # Controls: model selector + run button
            st.divider()
            _default_model = load_agent_model("scenario-analyst")
            col_model, col_run = st.columns([2, 3])
            with col_model:
                st.selectbox(
                    "Model", MODEL_OPTIONS,
                    index=MODEL_OPTIONS.index(_default_model) if _default_model in MODEL_OPTIONS else 1,
                    key=model_key,
                )
            with col_run:
                btn_label = "New Analysis" if saved_actions else "Suggested Actions"
                if st.button(btn_label, key=f"actions_{ev_id}", type="primary"):
                    _launch_analysis()
                    _needs_poll = True

# Poll after all events have been rendered
if _needs_poll:
    time.sleep(2)
    st.rerun()
