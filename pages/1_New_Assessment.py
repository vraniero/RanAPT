import json
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from config import SETTINGS_PATH
from db.schema import init_db
from db import queries
from agents.loader import load_agent_model
from ingestion.background_scanner import get_or_create_scan_job, remove_scan_job
from tasks.background import (
    run_assessment_in_background,
    get_running_assessment,
    get_all_running_ids,
)
from tasks.recurring import (
    get_recurring_config,
    set_recurring_config,
    is_scheduler_running,
    start_scheduler,
)

init_db()

st.title("New Assessment")
st.markdown("Specify the document folders for each agent.")

# ── Load default folders from settings ────────────────────────────────────────
_default_folder = ""
_default_re_folder = ""
if SETTINGS_PATH.exists():
    try:
        _settings = json.loads(SETTINGS_PATH.read_text())
        _default_folder = _settings.get("default_folder", "")
        _default_re_folder = _settings.get("default_real_estate_folder", "")
    except Exception:
        pass

# ── Folder Inputs ─────────────────────────────────────────────────────────────
MODEL_OPTIONS = ["haiku", "sonnet", "opus"]

col_ar, col_re, col_gfi = st.columns(3)

with col_ar:
    ar_enabled = st.checkbox("Asset Reader", value=True, key="ar_enabled")
    _ar_default = load_agent_model("asset-reader")
    ar_model = st.selectbox(
        "Model", MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(_ar_default) if _ar_default in MODEL_OPTIONS else 1,
        key="ar_model", disabled=not ar_enabled,
    )
    ar_folder_input = st.text_input(
        "Financial statements folder",
        placeholder=_default_folder or "/Users/you/Documents/portfolio",
        help="Account statements, brokerage reports, etc. "
             + (f"Leave empty to use default: `{_default_folder}`" if _default_folder else ""),
        key="ar_folder", disabled=not ar_enabled,
    )
    ar_folder = (ar_folder_input or _default_folder) if ar_enabled else ""
    if ar_enabled and not ar_folder_input and _default_folder:
        st.caption(f"Default: `{_default_folder}`")

with col_re:
    re_enabled = st.checkbox("Real Estate Assessor", value=True, key="re_enabled")
    _re_default = load_agent_model("real-estate-assessor")
    re_model = st.selectbox(
        "Model", MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(_re_default) if _re_default in MODEL_OPTIONS else 1,
        key="re_model", disabled=not re_enabled,
    )
    re_folder_input = st.text_input(
        "Property documents folder",
        placeholder=_default_re_folder or "/Users/you/Documents/real-estate",
        help="Mortgage statements, rental agreements, property docs, etc. "
             + (f"Leave empty to use default: `{_default_re_folder}`" if _default_re_folder else ""),
        key="re_folder", disabled=not re_enabled,
    )
    re_folder = (re_folder_input or _default_re_folder) if re_enabled else ""
    if re_enabled and not re_folder_input and _default_re_folder:
        st.caption(f"Default: `{_default_re_folder}`")

with col_gfi:
    gfi_enabled = st.checkbox("Global Intelligence", value=True, key="gfi_enabled")
    _gfi_default = load_agent_model("global-financial-intelligence")
    gfi_model = st.selectbox(
        "Model", MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(_gfi_default) if _gfi_default in MODEL_OPTIONS else 1,
        key="gfi_model", disabled=not gfi_enabled,
    )
    st.info("Reads all files from both folders plus the output of the other two agents.")

# ── Recurring Global Intelligence ─────────────────────────────────────────────
st.divider()
_rec_cfg = get_recurring_config()
_rec_enabled = _rec_cfg.get("enabled", False)
_rec_interval = _rec_cfg.get("interval_minutes", 60)
_rec_model = _rec_cfg.get("model", _gfi_default)

col_rec_toggle, col_rec_interval, col_rec_model, col_rec_status = st.columns([2, 2, 2, 2])
with col_rec_toggle:
    rec_enabled = st.toggle("Recurring Global Intelligence", value=_rec_enabled, key="rec_gfi_enabled")
with col_rec_interval:
    INTERVAL_OPTIONS = {"15 min": 15, "30 min": 30, "1 hour": 60, "2 hours": 120, "4 hours": 240, "8 hours": 480, "12 hours": 720, "24 hours": 1440}
    _interval_labels = list(INTERVAL_OPTIONS.keys())
    _current_label = next((k for k, v in INTERVAL_OPTIONS.items() if v == _rec_interval), "1 hour")
    rec_interval_label = st.selectbox(
        "Interval", _interval_labels,
        index=_interval_labels.index(_current_label),
        key="rec_gfi_interval",
    )
    rec_interval = INTERVAL_OPTIONS[rec_interval_label]
with col_rec_model:
    rec_model = st.selectbox(
        "Model", MODEL_OPTIONS,
        index=MODEL_OPTIONS.index(_rec_model) if _rec_model in MODEL_OPTIONS else 1,
        key="rec_gfi_model",
    )
with col_rec_status:
    if is_scheduler_running():
        _last = _rec_cfg.get("last_run", "")
        _next_in = ""
        if _last:
            try:
                _last_dt = datetime.fromisoformat(_last)
                _elapsed = (datetime.now(timezone.utc) - _last_dt).total_seconds()
                _remaining = max(0, rec_interval * 60 - _elapsed)
                _mins = int(_remaining // 60)
                _secs = int(_remaining % 60)
                _next_in = f"{_mins}m {_secs}s" if _mins > 0 else f"{_secs}s"
            except (ValueError, TypeError):
                pass
        if _next_in:
            st.success(f"Scheduler ON — next run in {_next_in}")
        else:
            st.success("Scheduler ON — next run imminent")
        if _last:
            st.caption(f"Last run: {_last[:19].replace('T', ' ')}")
    elif rec_enabled:
        st.warning("Scheduler starting...")
    else:
        st.caption("Scheduler off")

# Apply changes if settings differ
if (rec_enabled != _rec_enabled or rec_interval != _rec_interval or rec_model != _rec_model):
    set_recurring_config(rec_enabled, rec_interval, rec_model)

# Ensure scheduler is running if enabled (e.g. after app restart)
if rec_enabled and not is_scheduler_running():
    start_scheduler()

st.divider()

label = st.text_input(
    "Label (optional)",
    placeholder="Q1 2026 Assessment",
    help="A short name to identify this snapshot in History.",
)


# ── Helper to render a scan job status ────────────────────────────────────────
def _render_scan_job(job, col_container, label_text: str, job_key: str):
    """Render scan progress, file preview, and controls for one scan job."""
    status = job.status

    with col_container:
        if status == "pending":
            st.info(f"Ready to scan. Press **Scan Files** to start.")
        elif status == "scanning":
            st.info(f"Discovering files in folder...")
        elif status == "parsing":
            parsed = job.files_parsed
            total = job.total_files
            current = job.current_file
            st.progress(job.progress, text=f"Parsing {parsed}/{total}: {current}")
        elif status == "completed":
            parsed_files = job.parsed_files
            doc_files = [f for f in parsed_files if f.file_type != "image"]
            errors = [f for f in doc_files if f.error]
            st.success(f"{len(doc_files)} file(s) parsed for {label_text}")
            if errors:
                st.warning(f"{len(errors)} file(s) had extraction errors")
            if doc_files:
                st.dataframe(
                    [
                        {
                            "File": f.name,
                            "Type": f.file_type.upper(),
                            "Size": f"{f.size / 1024:.1f} KB",
                            "Extracted": f"{len(f.text)} chars" if not f.error else f"Error: {f.error[:50]}",
                        }
                        for f in doc_files
                    ],
                    width="stretch", hide_index=True,
                )
        elif status == "failed":
            st.error(f"Scan failed: {job.error}")
        elif status == "cancelled":
            st.warning("Scan cancelled.")

        # Controls
        btn_cols = st.columns(3)
        with btn_cols[0]:
            if status in ("pending", "failed", "cancelled"):
                if st.button("Scan Files", key=f"start_{job_key}", type="primary"):
                    job.restart()
                    st.rerun()
            elif status == "completed":
                if st.button("Rescan", key=f"rescan_{job_key}"):
                    job.restart()
                    st.rerun()
        with btn_cols[1]:
            if status in ("scanning", "parsing"):
                if st.button("Cancel", key=f"cancel_{job_key}"):
                    job.cancel()
                    st.rerun()
        # Polling for active scans
        if status in ("scanning", "parsing") and job.is_alive:
            return True  # signal: needs polling
    return False


# ── File Scanning ─────────────────────────────────────────────────────────────
needs_poll = False

prev_col_ar, prev_col_re = st.columns(2)

ar_job = None
re_job = None

if ar_folder:
    ar_job = get_or_create_scan_job(ar_folder, "ar")
    # Auto-start on first visit if not already running/done
    if ar_job.status == "pending" and not ar_job.is_alive:
        ar_job.start()
    if _render_scan_job(ar_job, prev_col_ar, "Asset Reader", "ar"):
        needs_poll = True

if re_folder:
    re_job = get_or_create_scan_job(re_folder, "re")
    if re_job.status == "pending" and not re_job.is_alive:
        re_job.start()
    if _render_scan_job(re_job, prev_col_re, "Real Estate Assessor", "re"):
        needs_poll = True

# Poll for scan progress
if needs_poll:
    time.sleep(0.5)
    st.rerun()

# ── Run Button ─────────────────────────────────────────────────────────────────
ar_ready = ar_enabled and ar_job and ar_job.status == "completed" and ar_job.parsed_files
any_agent_enabled = ar_enabled or re_enabled or gfi_enabled
can_run = bool(any_agent_enabled and (not ar_enabled or (ar_folder and ar_ready)))

if st.button("Run Assessment", disabled=not can_run, type="primary"):
    ar_parsed = ar_job.parsed_files if ar_job else []
    re_parsed = re_job.parsed_files if re_job and re_job.status == "completed" else []

    enabled_agents = []
    if ar_enabled:
        enabled_agents.append("asset-reader")
    if re_enabled:
        enabled_agents.append("real-estate-assessor")
    if gfi_enabled:
        enabled_agents.append("global-financial-intelligence")

    model_overrides = {
        "asset-reader": ar_model,
        "real-estate-assessor": re_model,
        "global-financial-intelligence": gfi_model,
    }

    # Build agents config for DB storage
    agents_config = {
        name: {"enabled": name in enabled_agents, "model": model_overrides.get(name, "sonnet")}
        for name in ["asset-reader", "real-estate-assessor", "global-financial-intelligence"]
    }

    snapshot_id = queries.create_snapshot(
        ar_folder or "", label or None,
        real_estate_folder=re_folder or None,
        agents_config=json.dumps(agents_config),
    )
    run_assessment_in_background(
        snapshot_id, ar_folder or "", re_folder or None,
        ar_parsed=ar_parsed or None,
        re_parsed=re_parsed or None,
        model_overrides=model_overrides,
        enabled_agents=enabled_agents,
    )
    # Clean up scan jobs
    remove_scan_job("ar")
    remove_scan_job("re")
    st.rerun()

# ── Gather all assessments to monitor ─────────────────────────────────────────
_monitor_ids: list[int] = []

# 1. IDs from live thread registry
_monitor_ids.extend(get_all_running_ids())

# 2. IDs from DB that are running/pending (covers stale or recurring runs)
for _snap in queries.list_snapshots():
    if _snap["status"] in ("running", "pending") and _snap["id"] not in _monitor_ids:
        _monitor_ids.append(_snap["id"])

# 3. Recently completed/failed that haven't been dismissed
_dismissed = st.session_state.get("dismissed_snapshot_ids", set())
for _snap in queries.list_snapshots():
    if _snap["status"] in ("completed", "failed") and _snap["id"] not in _monitor_ids and _snap["id"] not in _dismissed:
        # Only show recently finished ones (from thread registry or last started)
        registry_entry = get_running_assessment(_snap["id"])
        if registry_entry is not None:
            _monitor_ids.append(_snap["id"])

# Deduplicate and sort
_monitor_ids = sorted(set(_monitor_ids))

AGENT_LABELS = {
    "asset-reader": "Asset Reader",
    "global-financial-intelligence": "Global Financial Intelligence",
    "real-estate-assessor": "Real Estate Assessor",
}

STATUS_COLORS = {
    "pending": "orange",
    "running": "blue",
    "completed": "green",
    "failed": "red",
}

# ── Live Status Monitor ────────────────────────────────────────────────────────
_any_running = False

for monitoring_id in _monitor_ids:
    snapshot = queries.get_snapshot(monitoring_id)
    if not snapshot:
        continue

    status = snapshot["status"]

    # Get live data from the module-level registry (survives refresh)
    registry_entry = get_running_assessment(monitoring_id)
    thread = registry_entry["thread"] if registry_entry else None
    agent_processes = registry_entry["agent_processes"] if registry_entry else {}

    snap_label = snapshot["label"] or f"Assessment #{monitoring_id}"

    st.divider()
    header_col, stop_col = st.columns([5, 1])
    with header_col:
        color = STATUS_COLORS.get(status, "gray")
        st.subheader(f"{snap_label} — :{color}[{status.upper()}]")
    with stop_col:
        if status in ("running", "pending") and agent_processes:
            if st.button("Stop All", key=f"stop_all_{monitoring_id}", type="secondary"):
                for proc in agent_processes.values():
                    proc.stop()
                queries.fail_pending_agent_results(monitoring_id, "Stopped by user")
                queries.update_snapshot_status(monitoring_id, "failed")
                _any_running = True

    agent_results = queries.get_agent_results(monitoring_id)
    agent_status_map = {r["agent_name"]: r["status"] for r in agent_results}

    # Determine files per agent from snapshot folders
    snap_ar_folder = snapshot["folder_path"]
    snap_re_folder = snapshot["real_estate_folder"] if "real_estate_folder" in snapshot.keys() else None
    snap_files = queries.get_snapshot_files(monitoring_id)
    ar_files = [f for f in snap_files if snap_ar_folder and f["file_path"].startswith(snap_ar_folder)] if snap_ar_folder else []
    re_files = [f for f in snap_files if snap_re_folder and f["file_path"].startswith(snap_re_folder)] if snap_re_folder else []
    all_files = snap_files

    AGENT_FILES = {
        "asset-reader": ar_files,
        "real-estate-assessor": re_files,
        "global-financial-intelligence": all_files,
    }

    for agent_name, label_text in AGENT_LABELS.items():
        live_proc = agent_processes.get(agent_name)
        if live_proc:
            ag_status = live_proc.status
        else:
            ag_status = agent_status_map.get(agent_name, "pending")

        ag_color = STATUS_COLORS.get(ag_status, "gray")
        ag_model = load_agent_model(agent_name)
        agent_file_list = AGENT_FILES.get(agent_name, [])
        file_names = ", ".join(f["file_name"] for f in agent_file_list) if agent_file_list else "—"

        header_cols = st.columns([6, 1])
        with header_cols[0]:
            st.markdown(f"**{label_text}**: :{ag_color}[{ag_status}]")
            st.caption(f"Model: `{ag_model}` · Files ({len(agent_file_list)}): {file_names}")
        with header_cols[1]:
            if live_proc and ag_status == "running":
                if st.button("Stop", key=f"stop_{agent_name}_{monitoring_id}", type="secondary"):
                    live_proc.stop()
                    _any_running = True

        if live_proc and ag_status == "running":
            with st.expander(f"Activity ({label_text})"):
                log = live_proc.activity_log
                if log:
                    st.code("\n".join(log[-30:]), language=None)

    if status in ("running", "pending"):
        if thread and thread.is_alive():
            _any_running = True
        else:
            # Thread gone but DB still says running — stale state
            _any_running = True

    elif status == "completed":
        st.success("Assessment complete!")
        pdf_path = snapshot["pdf_path"]
        if pdf_path and Path(pdf_path).exists():
            with open(pdf_path, "rb") as f:
                st.download_button(
                    "Download PDF Report",
                    data=f.read(),
                    file_name=f"ranapt_assessment_{monitoring_id}.pdf",
                    mime="application/pdf",
                    key=f"pdf_dl_new_{monitoring_id}",
                )
        st.info("View full results in the **History** page.")
        if st.button("Dismiss", key=f"dismiss_{monitoring_id}"):
            dismissed = st.session_state.get("dismissed_snapshot_ids", set())
            dismissed.add(monitoring_id)
            st.session_state["dismissed_snapshot_ids"] = dismissed
            _any_running = True

    elif status == "failed":
        st.error("Assessment failed. Check the History page for details.")
        if st.button("Dismiss", key=f"dismiss_fail_{monitoring_id}"):
            dismissed = st.session_state.get("dismissed_snapshot_ids", set())
            dismissed.add(monitoring_id)
            st.session_state["dismissed_snapshot_ids"] = dismissed
            _any_running = True

# Poll if any assessment is still running
if _any_running:
    time.sleep(2)
    st.rerun()
