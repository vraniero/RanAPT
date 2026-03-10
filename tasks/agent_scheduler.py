"""Scheduler for user-created custom agents.

Runs a single daemon thread that checks all active agents with a schedule,
and executes them when they are due.
"""

import threading
import time
from datetime import datetime, timezone

from db import queries
from agents.runner import AgentProcess


_scheduler_thread: threading.Thread | None = None
_scheduler_lock = threading.Lock()
_stop_event = threading.Event()

# Track running agent processes so the UI can show activity
_running_agents: dict[int, AgentProcess] = {}
_running_lock = threading.Lock()


def get_running_agent_proc(agent_id: int) -> AgentProcess | None:
    with _running_lock:
        return _running_agents.get(agent_id)


def _build_system_prompt(agent) -> str:
    """Build a system prompt from the agent's goal."""
    return (
        f"You are a financial analysis agent named '{agent['name']}'.\n\n"
        f"Your goal:\n{agent['goal']}\n\n"
        "You have access to the investor's portfolio context below (if provided). "
        "Provide clear, actionable analysis. Use markdown formatting."
    )


def _build_user_message(agent) -> str:
    """Build user message with latest portfolio context."""
    parts = [f"Please perform your analysis according to your goal: {agent['goal']}"]

    # Include latest portfolio context if available
    latest_snapshots = queries.list_snapshots()
    for snap in latest_snapshots:
        if snap["status"] == "completed":
            ar_result = queries.get_agent_result_by_name(snap["id"], "asset-reader")
            if ar_result and ar_result["raw_response"]:
                parts.append(
                    "=== CURRENT PORTFOLIO (from latest assessment) ===\n\n"
                    + ar_result["raw_response"]
                )
                break

    return "\n\n".join(parts)


def run_custom_agent(agent_id: int) -> None:
    """Run a custom agent immediately. Creates a run record and executes."""
    agent = queries.get_custom_agent(agent_id)
    if not agent or agent["status"] != "active":
        return

    run_id = queries.create_custom_agent_run(agent_id)
    queries.update_custom_agent_run_running(run_id)

    system_prompt = _build_system_prompt(agent)
    user_message = _build_user_message(agent)
    model = agent["model"]

    proc = AgentProcess(f"custom-{agent['name']}", system_prompt, user_message, model=model)

    with _running_lock:
        _running_agents[agent_id] = proc

    try:
        proc.run()
        result = proc.get_result()
        if result["success"]:
            queries.update_custom_agent_run_completed(
                run_id, result["raw_response"],
                result["input_tokens"], result["output_tokens"],
            )
        else:
            queries.update_custom_agent_run_failed(
                run_id, result.get("error", "Unknown error"),
            )
    except Exception as e:
        queries.update_custom_agent_run_failed(run_id, str(e))
    finally:
        queries.update_custom_agent_last_run(agent_id)
        with _running_lock:
            _running_agents.pop(agent_id, None)


def _scheduler_loop() -> None:
    """Main loop: check all scheduled agents, run if due."""
    while not _stop_event.is_set():
        try:
            agents = queries.list_scheduled_custom_agents()
            now = datetime.now(timezone.utc)

            for agent in agents:
                if _stop_event.is_set():
                    break

                schedule_min = agent["schedule_minutes"]
                last_run = agent["last_run_at"]

                run_due = True
                if last_run:
                    try:
                        last_dt = datetime.fromisoformat(last_run)
                        elapsed = (now - last_dt).total_seconds()
                        if elapsed < schedule_min * 60:
                            run_due = False
                    except (ValueError, TypeError):
                        pass

                if run_due:
                    # Already running?
                    with _running_lock:
                        if agent["id"] in _running_agents:
                            continue
                    # Run in a separate thread so we don't block other agents
                    t = threading.Thread(
                        target=run_custom_agent,
                        args=(agent["id"],),
                        daemon=True,
                        name=f"custom-agent-{agent['id']}",
                    )
                    t.start()

        except Exception as e:
            print(f"[agent-scheduler] Error: {e}")

        # Check every 30 seconds
        _stop_event.wait(30)


def start_agent_scheduler() -> None:
    """Start the custom agent scheduler if not already running."""
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return
        _stop_event.clear()
        _scheduler_thread = threading.Thread(
            target=_scheduler_loop, daemon=True, name="agent-scheduler"
        )
        _scheduler_thread.start()


def stop_agent_scheduler() -> None:
    global _scheduler_thread
    with _scheduler_lock:
        _stop_event.set()
        _scheduler_thread = None


def is_agent_scheduler_running() -> bool:
    with _scheduler_lock:
        return _scheduler_thread is not None and _scheduler_thread.is_alive()
