import threading
import time

import streamlit as st

from db.schema import init_db
from db import queries
from agents.custom_agent_files import (
    create_agent_files,
    update_agent_files,
    archive_agent_files,
    reactivate_agent_files,
    delete_agent_files,
    agent_slug,
)
from tasks.agent_scheduler import (
    run_custom_agent,
    get_running_agent_proc,
    start_agent_scheduler,
    is_agent_scheduler_running,
)

init_db()

st.title("Agents")
st.markdown("Create custom financial agents with their own goals and schedules.")

MODEL_OPTIONS = ["haiku", "sonnet", "opus"]

SCHEDULE_OPTIONS = {
    "Manual only": None,
    "15 min": 15,
    "30 min": 30,
    "1 hour": 60,
    "2 hours": 120,
    "4 hours": 240,
    "8 hours": 480,
    "12 hours": 720,
    "Daily": 1440,
    "Weekly": 10080,
}

# Ensure scheduler is running if any agents have schedules
scheduled = queries.list_scheduled_custom_agents()
if scheduled and not is_agent_scheduler_running():
    start_agent_scheduler()


def _schedule_label(minutes):
    """Convert minutes back to a display label."""
    if minutes is None:
        return "Manual only"
    for label, val in SCHEDULE_OPTIONS.items():
        if val == minutes:
            return label
    return f"{minutes} min"


# ── Create New Agent ─────────────────────────────────────────────────────────

with st.expander("Create new agent", icon=":material/add:"):
    col_name, col_model, col_schedule = st.columns([2, 1, 1])
    with col_name:
        new_name = st.text_input("Name", placeholder="ECB Rate Monitor", key="new_agent_name")
    with col_model:
        new_model = st.selectbox("Model", MODEL_OPTIONS, index=1, key="new_agent_model")
    with col_schedule:
        new_schedule_label = st.selectbox("Schedule", list(SCHEDULE_OPTIONS.keys()), key="new_agent_schedule")
        new_schedule = SCHEDULE_OPTIONS[new_schedule_label]

    new_goal = st.text_area(
        "Goal",
        placeholder="Monitor ECB interest rate decisions and analyze their impact on my EUR-denominated bonds and real estate portfolio.",
        height=120,
        key="new_agent_goal",
    )

    can_create = bool(new_name and new_name.strip() and new_goal and new_goal.strip())
    if st.button("Create Agent", disabled=not can_create, type="primary"):
        name = new_name.strip()
        goal = new_goal.strip()
        # Create Claude agent .md file + memory directory
        slug = create_agent_files(name, goal, new_model)
        # Create DB record with slug reference
        queries.create_custom_agent(name, goal, new_model, new_schedule, slug=slug)
        if new_schedule is not None and not is_agent_scheduler_running():
            start_agent_scheduler()
        st.rerun()

# ── Agent List ───────────────────────────────────────────────────────────────
show_archived = st.checkbox("Show archived agents", value=False, key="agents_show_archived")
agents = queries.list_custom_agents(include_archived=show_archived)

if not agents:
    st.info("No agents yet. Create one above to get started.")
    st.stop()

_needs_poll = False

STATUS_ICONS = {
    "active": ":material/smart_toy:",
    "archived": ":material/archive:",
}

for agent in agents:
    a = dict(agent)
    aid = a["id"]
    a_status = a["status"]
    a_slug = a.get("slug") or agent_slug(a["name"])
    schedule_text = _schedule_label(a.get("schedule_minutes"))
    last_run = (a.get("last_run_at") or "")[:19].replace("T", " ")

    # Check if currently running
    running_proc = get_running_agent_proc(aid)
    is_running = running_proc is not None and running_proc.status == "running"

    icon = STATUS_ICONS.get(a_status, ":material/smart_toy:")
    header = f"**{a['name']}** — `{a['model']}` · {schedule_text}"
    if a_status == "archived":
        header += " · :gray[(archived)]"
    if is_running:
        header += " · :blue[running...]"

    with st.expander(header, icon=icon):
        # ── Agent details / Edit form ────────────────────────────────────
        editing_key = f"editing_{aid}"
        if st.session_state.get(editing_key):
            # Edit mode
            col_en, col_em, col_es = st.columns([2, 1, 1])
            with col_en:
                edit_name = st.text_input("Name", value=a["name"], key=f"edit_name_{aid}")
            with col_em:
                edit_model = st.selectbox(
                    "Model", MODEL_OPTIONS,
                    index=MODEL_OPTIONS.index(a["model"]) if a["model"] in MODEL_OPTIONS else 1,
                    key=f"edit_model_{aid}",
                )
            with col_es:
                current_sched_label = _schedule_label(a.get("schedule_minutes"))
                sched_labels = list(SCHEDULE_OPTIONS.keys())
                edit_schedule_label = st.selectbox(
                    "Schedule", sched_labels,
                    index=sched_labels.index(current_sched_label) if current_sched_label in sched_labels else 0,
                    key=f"edit_schedule_{aid}",
                )
                edit_schedule = SCHEDULE_OPTIONS[edit_schedule_label]

            edit_goal = st.text_area("Goal", value=a["goal"], height=120, key=f"edit_goal_{aid}")

            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.button("Save", key=f"save_{aid}", type="primary"):
                    new_name_val = edit_name.strip()
                    new_goal_val = edit_goal.strip()
                    # Update Claude agent .md file (handles rename if name changed)
                    new_slug = update_agent_files(a["name"], new_name_val, new_goal_val, edit_model)
                    # Update DB
                    queries.update_custom_agent(
                        aid, new_name_val, new_goal_val,
                        edit_model, edit_schedule, slug=new_slug,
                    )
                    st.session_state[editing_key] = False
                    if edit_schedule is not None and not is_agent_scheduler_running():
                        start_agent_scheduler()
                    st.rerun()
            with col_cancel:
                if st.button("Cancel", key=f"cancel_edit_{aid}"):
                    st.session_state[editing_key] = False
                    st.rerun()
        else:
            # View mode
            st.markdown(f"**Goal:** {a['goal']}")
            st.caption(f"Agent file: `.claude/agents/{a_slug}.md`")
            if last_run:
                st.caption(f"Last run: {last_run}")
            st.caption(f"Created: {a['created_at'][:19].replace('T', ' ')}")

            # Action buttons
            col_run, col_edit, col_status, col_delete = st.columns(4)
            with col_run:
                if a_status == "active" and not is_running:
                    if st.button("Run now", key=f"run_{aid}", type="primary"):
                        st.session_state[f"agent_thread_{aid}"] = True
                        t = threading.Thread(
                            target=run_custom_agent, args=(aid,),
                            daemon=True, name=f"manual-agent-{aid}",
                        )
                        t.start()
                        st.session_state[f"agent_thread_obj_{aid}"] = t
                        _needs_poll = True
            with col_edit:
                if st.button("Edit", key=f"edit_{aid}"):
                    st.session_state[editing_key] = True
                    st.rerun()
            with col_status:
                if a_status == "active":
                    if st.button("Archive", key=f"archive_{aid}"):
                        archive_agent_files(a["name"])
                        queries.update_custom_agent_status(aid, "archived")
                        st.rerun()
                else:
                    if st.button("Reactivate", key=f"reactivate_{aid}"):
                        reactivate_agent_files(a["name"], a["goal"], a["model"])
                        queries.update_custom_agent_status(aid, "active")
                        st.rerun()
            with col_delete:
                if st.button("Delete", key=f"del_{aid}", type="secondary"):
                    st.session_state[f"confirm_del_agent_{aid}"] = True

            # Delete confirmation dialog
            if st.session_state.get(f"confirm_del_agent_{aid}"):
                @st.dialog(f"Delete {a['name']}?")
                def _confirm_delete(agent_id=aid, agent_name=a["name"]):
                    st.warning(
                        f"This will permanently delete **{agent_name}**, "
                        f"its Claude agent file, memory directory, and all run history. "
                        f"This cannot be undone."
                    )
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Yes, delete", key=f"yes_del_agent_{agent_id}", type="primary"):
                            delete_agent_files(agent_name)
                            queries.delete_custom_agent(agent_id)
                            del st.session_state[f"confirm_del_agent_{agent_id}"]
                            st.rerun()
                    with c2:
                        if st.button("Cancel", key=f"cancel_del_agent_{agent_id}"):
                            del st.session_state[f"confirm_del_agent_{agent_id}"]
                            st.rerun()
                _confirm_delete()

        # ── Live running status ──────────────────────────────────────────
        if is_running:
            st.divider()
            with st.status("Agent is running...", expanded=True):
                log = running_proc.activity_log
                if log:
                    st.caption(log[-1])
            _needs_poll = True
        elif st.session_state.get(f"agent_thread_{aid}"):
            # Thread just finished
            st.session_state.pop(f"agent_thread_{aid}", None)
            st.session_state.pop(f"agent_thread_obj_{aid}", None)
            _needs_poll = True

        # ── Run history ──────────────────────────────────────────────────
        st.divider()
        runs = queries.get_custom_agent_runs(aid)
        if runs:
            st.markdown(f"**Run history** ({len(runs)} run{'s' if len(runs) != 1 else ''})")
            RUN_ICONS = {
                "pending": "hourglass_flowing_sand",
                "running": "arrows_counterclockwise",
                "completed": "white_check_mark",
                "failed": "x",
            }
            for run in runs:
                r = dict(run)
                rid = r["id"]
                r_status = r["status"]
                r_created = r["created_at"][:19].replace("T", " ")
                r_icon = RUN_ICONS.get(r_status, "question")
                tokens_in = r.get("input_tokens") or 0
                tokens_out = r.get("output_tokens") or 0

                with st.expander(f":{r_icon}: {r_created} — `{r_status}`"):
                    if tokens_in or tokens_out:
                        st.caption(f"Tokens: {tokens_in:,} in / {tokens_out:,} out")

                    if r_status == "completed" and r.get("raw_response"):
                        st.markdown(r["raw_response"])
                    elif r_status == "failed":
                        st.error(r.get("error_message") or "Unknown error")
                    elif r_status in ("pending", "running"):
                        st.info(f"Status: {r_status}")
        else:
            st.caption("No runs yet.")

# Poll if anything is running
if _needs_poll:
    time.sleep(2)
    st.rerun()
