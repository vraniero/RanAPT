import json
import re
import threading
from pathlib import Path

from config import REPORTS_DIR
from db import queries
from agents.loader import load_system_prompt, load_agent_model
from agents.runner import run_agent
from ingestion.file_scanner import scan_folder
from ingestion.pdf_extractor import build_context_from_parsed
from ingestion.background_scanner import ParsedFile
from pdf_report.generator import generate_report
from tasks.merge_detector import run_merge_detection

# ── Module-level registry (survives Streamlit reruns / page refreshes) ────────
# Maps snapshot_id -> {"thread": Thread, "agent_processes": {agent_name: AgentProcess}}
_running_assessments: dict[int, dict] = {}
_registry_lock = threading.Lock()


def get_running_assessment(snapshot_id: int) -> dict | None:
    """Get the registry entry for a running assessment, or None."""
    with _registry_lock:
        return _running_assessments.get(snapshot_id)


def get_all_running_ids() -> list[int]:
    """Return snapshot IDs that still have a live thread."""
    with _registry_lock:
        return [
            sid for sid, entry in _running_assessments.items()
            if entry["thread"].is_alive()
        ]


def _cleanup_finished() -> None:
    """Remove entries whose threads have finished."""
    with _registry_lock:
        finished = [sid for sid, e in _running_assessments.items() if not e["thread"].is_alive()]
        for sid in finished:
            del _running_assessments[sid]


def _parse_asset_items(snapshot_id: int, asset_reader_output: str) -> None:
    """Extract structured asset data from the ASSET_DATA_JSON block in asset-reader output."""
    if not asset_reader_output:
        return

    # Find JSON array in a ```json ... ``` fenced block after ASSET_DATA_JSON
    match = re.search(r"ASSET_DATA_JSON[\s\S]*?```json\s*(\[[\s\S]*\])\s*```", asset_reader_output)
    if not match:
        # Fallback: look for any JSON array in a fenced block
        match = re.search(r"```json\s*(\[[\s\S]*\])\s*```", asset_reader_output)
    if not match:
        return

    try:
        items = json.loads(match.group(1))
    except json.JSONDecodeError:
        return

    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("asset_name")
        total_val = item.get("total_value_eur")
        if not name or total_val is None:
            continue
        queries.add_asset_item(
            snapshot_id,
            asset_name=name,
            ticker=item.get("ticker"),
            asset_type=item.get("asset_type", "Other"),
            currency=item.get("currency"),
            quantity=item.get("quantity"),
            unit_price=item.get("unit_price"),
            total_value_eur=total_val,
            percentage=item.get("percentage"),
        )


def _parse_watch_events(snapshot_id: int, gfi_output: str) -> None:
    """Extract watch list events from WATCH_LIST_JSON block in GFI output."""
    if not gfi_output:
        return

    match = re.search(r"WATCH_LIST_JSON[\s\S]*?```json\s*(\[[\s\S]*\])\s*```", gfi_output)
    if not match:
        return

    try:
        items = json.loads(match.group(1))
    except json.JSONDecodeError:
        return

    for item in items:
        if not isinstance(item, dict):
            continue
        event_date = item.get("event_date")
        title = item.get("title")
        if not event_date or not title:
            continue
        queries.add_watch_event(
            snapshot_id,
            event_date=event_date,
            title=title,
            description=item.get("description"),
            category=item.get("category"),
            impact=item.get("impact"),
        )


def _run_single_agent(
    snapshot_id: int,
    agent_name: str,
    files: list[tuple[str, Path]] | None = None,
    extra_context: str = "",
    agent_processes: dict | None = None,
    file_context: str = "",
    model_override: str | None = None,
) -> dict:
    """Run one agent, persist results, return result dict."""
    result_id = queries.create_agent_result(snapshot_id, agent_name)
    queries.update_agent_result_started(result_id)

    system_prompt = load_system_prompt(agent_name)
    model = model_override or load_agent_model(agent_name)
    result = run_agent(
        agent_name, system_prompt, files,
        extra_context=extra_context,
        agent_processes=agent_processes,
        file_context=file_context,
        model=model,
    )

    if result["success"]:
        queries.update_agent_result_completed(
            result_id,
            result["raw_response"],
            result["input_tokens"],
            result["output_tokens"],
        )
    else:
        queries.update_agent_result_failed(result_id, result.get("error", "Unknown error"))

    return result


def _orchestrate(
    snapshot_id: int,
    ar_folder: str,
    re_folder: str | None,
    agent_processes: dict,
    ar_parsed: list[ParsedFile] | None = None,
    re_parsed: list[ParsedFile] | None = None,
    model_overrides: dict[str, str] | None = None,
    enabled_agents: list[str] | None = None,
) -> None:
    """Main orchestration logic — runs in a daemon thread.

    If ar_parsed / re_parsed are provided (from background scanner), their
    pre-extracted text is reused instead of re-reading files from disk.
    """
    model_overrides = model_overrides or {}
    if enabled_agents is None:
        enabled_agents = ["asset-reader", "real-estate-assessor", "global-financial-intelligence"]
    try:
        queries.update_snapshot_status(snapshot_id, "running")

        # 1. Register files in DB
        all_parsed = list(ar_parsed or []) + list(re_parsed or [])
        if all_parsed:
            for f in all_parsed:
                queries.add_snapshot_file(
                    snapshot_id,
                    file_name=f.name,
                    file_type=f.file_type,
                    file_path=str(f.path),
                    file_size=f.size,
                )
        else:
            # Fallback: scan from disk if no pre-parsed files
            if ar_folder and "asset-reader" in enabled_agents:
                ar_scanned = scan_folder(ar_folder)
                for f in ar_scanned:
                    queries.add_snapshot_file(
                        snapshot_id, file_name=f.name, file_type=f.file_type,
                        file_path=str(f.path), file_size=f.size,
                    )
            if re_folder and "real-estate-assessor" in enabled_agents:
                re_scanned = scan_folder(re_folder)
                for f in re_scanned:
                    queries.add_snapshot_file(
                        snapshot_id, file_name=f.name, file_type=f.file_type,
                        file_path=str(f.path), file_size=f.size,
                    )

        # 2. Build context strings
        ar_context = ""
        re_context = ""
        if ar_parsed:
            ar_context = build_context_from_parsed(ar_parsed)
        if re_parsed:
            re_context = build_context_from_parsed(re_parsed)

        # If no pre-parsed data, agent will extract from files on its own
        ar_doc_files: list[tuple[str, Path]] | None = None
        re_doc_files: list[tuple[str, Path]] | None = None
        if not ar_context and ar_folder:
            ar_scanned_files = scan_folder(ar_folder) if not all_parsed else []
            ar_doc_files = [(f.name, f.path) for f in ar_scanned_files if f.file_type != "image"]
        if not re_context and re_folder:
            re_scanned_files = scan_folder(re_folder) if not all_parsed else []
            re_doc_files = [(f.name, f.path) for f in re_scanned_files if f.file_type != "image"]

        asset_reader_output = ""
        real_estate_output = ""

        # 3. asset-reader runs first (sequential)
        if "asset-reader" in enabled_agents:
            ar_result = _run_single_agent(
                snapshot_id, "asset-reader", ar_doc_files,
                agent_processes=agent_processes,
                file_context=ar_context,
                model_override=model_overrides.get("asset-reader"),
            )
            asset_reader_output = ar_result.get("raw_response", "")

            # 3b. Parse asset items from asset-reader output for the breakdown chart
            try:
                _parse_asset_items(snapshot_id, asset_reader_output)
            except Exception as parse_err:
                print(f"[background] Asset item parsing failed for snapshot {snapshot_id}: {parse_err}")

            # 3c. Detect potential duplicate assets for merge suggestions
            try:
                new_suggestions = run_merge_detection()
                if new_suggestions:
                    print(f"[background] Found {new_suggestions} new merge suggestion(s) for snapshot {snapshot_id}")
            except Exception as merge_err:
                print(f"[background] Merge detection failed for snapshot {snapshot_id}: {merge_err}")

        # 4. real-estate-assessor runs second
        if "real-estate-assessor" in enabled_agents:
            re_result = _run_single_agent(
                snapshot_id, "real-estate-assessor", re_doc_files,
                agent_processes=agent_processes,
                file_context=re_context,
                model_override=model_overrides.get("real-estate-assessor"),
            )
            real_estate_output = re_result.get("raw_response", "")

        # 5. global-financial-intelligence runs last — gets all docs + both agents' output
        if "global-financial-intelligence" in enabled_agents:
            all_file_context = ar_context
            if re_context:
                all_file_context = (all_file_context + "\n\n" + re_context) if all_file_context else re_context

            gfi_extra_parts: list[str] = []
            if asset_reader_output:
                gfi_extra_parts.append(
                    "=== ASSET READER ANALYSIS ===\n\n" + asset_reader_output
                )
            if real_estate_output:
                gfi_extra_parts.append(
                    "=== REAL ESTATE ASSESSOR ANALYSIS ===\n\n" + real_estate_output
                )

            # Combine all doc files for fallback (when no pre-parsed context)
            all_doc_files = list(ar_doc_files or []) + list(re_doc_files or [])

            gfi_result = _run_single_agent(
                snapshot_id, "global-financial-intelligence",
                all_doc_files or None,
                extra_context="\n\n".join(gfi_extra_parts),
                agent_processes=agent_processes,
                file_context=all_file_context,
                model_override=model_overrides.get("global-financial-intelligence"),
            )

            # 5b. Parse watch events from GFI output
            try:
                _parse_watch_events(snapshot_id, gfi_result.get("raw_response", ""))
            except Exception as parse_err:
                print(f"[background] Watch event parsing failed for snapshot {snapshot_id}: {parse_err}")

        # 6. Generate PDF
        pdf_path = REPORTS_DIR / f"assessment_{snapshot_id}.pdf"
        try:
            agent_results = queries.get_agent_results(snapshot_id)
            results_map = {row["agent_name"]: dict(row) for row in agent_results}
            generate_report(snapshot_id, ar_folder, results_map, pdf_path)
            queries.update_snapshot_status(snapshot_id, "completed", str(pdf_path))
        except Exception as pdf_err:
            # PDF failure should not mark whole snapshot as failed
            queries.update_snapshot_status(snapshot_id, "completed")
            print(f"[background] PDF generation failed for snapshot {snapshot_id}: {pdf_err}")

    except Exception as e:
        queries.update_snapshot_status(snapshot_id, "failed")
        print(f"[background] Snapshot {snapshot_id} failed: {e}")


def run_assessment_in_background(
    snapshot_id: int,
    ar_folder: str,
    re_folder: str | None = None,
    ar_parsed: list[ParsedFile] | None = None,
    re_parsed: list[ParsedFile] | None = None,
    model_overrides: dict[str, str] | None = None,
    enabled_agents: list[str] | None = None,
) -> tuple[threading.Thread, dict]:
    """Spawn a daemon thread to run the full assessment pipeline.

    Returns (thread, agent_processes) where agent_processes is a dict
    that maps agent_name -> AgentProcess once each agent starts.
    If ar_parsed / re_parsed are provided, their pre-extracted text is reused.
    """
    # Clean up finished entries first
    _cleanup_finished()

    agent_processes: dict = {}

    thread = threading.Thread(
        target=_orchestrate,
        args=(snapshot_id, ar_folder, re_folder, agent_processes, ar_parsed, re_parsed, model_overrides, enabled_agents),
        daemon=True,
        name=f"assessment-{snapshot_id}",
    )
    thread.start()

    # Register in module-level registry
    with _registry_lock:
        _running_assessments[snapshot_id] = {
            "thread": thread,
            "agent_processes": agent_processes,
        }

    return thread, agent_processes
