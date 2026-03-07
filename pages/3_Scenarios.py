import threading
import time

import streamlit as st

from db.schema import init_db
from db import queries
from agents.loader import load_system_prompt, load_agent_model
from agents.runner import AgentProcess

init_db()

st.title("Scenarios")
st.markdown("Describe a hypothetical scenario and the **Scenario Analyst** agent will assess risks and opportunities.")

# ── New scenario input ────────────────────────────────────────────────────────
MODEL_OPTIONS = ["haiku", "sonnet", "opus"]
_default_model = load_agent_model("scenario-analyst")

col_input, col_model = st.columns([4, 1])
with col_model:
    model = st.selectbox(
        "Model", MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(_default_model) if _default_model in MODEL_OPTIONS else 1,
        key="scenario_model",
    )
with col_input:
    prompt = st.text_area(
        "Scenario",
        value=st.session_state.get("scenario_prompt_saved", ""),
        placeholder="What if the ECB raises interest rates by 200 basis points over the next 6 months?",
        height=100,
        key="scenario_prompt",
    )
    # Persist the prompt so it survives page navigation
    st.session_state["scenario_prompt_saved"] = prompt

# Include latest portfolio context if available
_portfolio_context = ""
_latest_snapshots = queries.list_snapshots()
for _snap in _latest_snapshots:
    if _snap["status"] == "completed":
        _ar_result = queries.get_agent_result_by_name(_snap["id"], "asset-reader")
        if _ar_result and _ar_result["raw_response"]:
            _portfolio_context = _ar_result["raw_response"]
            break

can_run = bool(prompt and prompt.strip())

if st.button("Analyze Scenario", disabled=not can_run, type="primary"):
    scenario_id = queries.create_scenario(prompt.strip(), model)
    st.session_state["running_scenario_id"] = scenario_id
    st.session_state["scenario_thread_done"] = False

    system_prompt = load_system_prompt("scenario-analyst")

    # Build user message with portfolio context
    user_parts = [prompt.strip()]
    if _portfolio_context:
        user_parts.append("=== CURRENT PORTFOLIO (from latest assessment) ===\n\n" + _portfolio_context)
    user_message = "\n\n".join(user_parts)

    proc = AgentProcess("scenario-analyst", system_prompt, user_message, model=model)
    st.session_state["scenario_proc"] = proc
    queries.update_scenario_running(scenario_id)

    def _run():
        proc.run()
        result = proc.get_result()
        if result["success"]:
            queries.update_scenario_completed(
                scenario_id, result["raw_response"],
                result["input_tokens"], result["output_tokens"],
            )
        else:
            queries.update_scenario_failed(scenario_id, result.get("error", "Unknown error"))
        st.session_state["scenario_thread_done"] = True

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    st.session_state["scenario_thread"] = t
    st.rerun()

# ── Live monitor ──────────────────────────────────────────────────────────────
running_id = st.session_state.get("running_scenario_id")
if running_id:
    scenario = queries.get_scenario(running_id)
    if scenario:
        status = scenario["status"]
        proc = st.session_state.get("scenario_proc")
        thread = st.session_state.get("scenario_thread")

        if status == "running":
            st.info(f"Analyzing scenario #{running_id}...")
            if proc:
                log = proc.activity_log
                if log:
                    with st.expander("Activity"):
                        st.code("\n".join(log[-20:]), language=None)
            if thread and thread.is_alive():
                time.sleep(2)
                st.rerun()
            else:
                st.rerun()

        elif status == "completed":
            st.success(f"Scenario #{running_id} complete!")
            if st.button("New Scenario"):
                del st.session_state["running_scenario_id"]
                st.rerun()

        elif status == "failed":
            st.error(f"Failed: {scenario['error_message']}")
            if st.button("Dismiss"):
                del st.session_state["running_scenario_id"]
                st.rerun()

st.divider()

# ── Past scenarios ────────────────────────────────────────────────────────────
st.subheader("Past Scenarios")

scenarios = queries.list_scenarios()
if not scenarios:
    st.info("No scenarios yet. Describe a scenario above to get started.")
else:
    STATUS_ICONS = {"pending": "hourglass_flowing_sand", "running": "arrows_counterclockwise", "completed": "white_check_mark", "failed": "x"}

    for sc in scenarios:
        s = dict(sc)
        sid = s["id"]
        created = s["created_at"][:19].replace("T", " ")
        status = s["status"]
        icon = STATUS_ICONS.get(status, "question")
        prompt_preview = s["prompt"][:80] + ("..." if len(s["prompt"]) > 80 else "")
        tokens_in = s.get("input_tokens") or 0
        tokens_out = s.get("output_tokens") or 0

        with st.expander(f":{icon}: **#{sid}** — {prompt_preview} — `{status}`"):
            st.caption(f"{created} · Model: `{s['model']}` · Tokens: {tokens_in:,} in / {tokens_out:,} out")
            st.markdown(f"**Prompt:** {s['prompt']}")

            if status == "completed" and s.get("raw_response"):
                st.divider()
                st.markdown(s["raw_response"])
            elif status == "failed":
                st.error(s.get("error_message") or "Unknown error")

            if st.button("Delete", key=f"del_scenario_{sid}"):
                queries.delete_scenario(sid)
                st.rerun()
