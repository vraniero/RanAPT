"""Recurring Global Intelligence assessment scheduler."""

import json
import threading
import time
from datetime import datetime, timezone

from config import SETTINGS_PATH
from db import queries
from tasks.background import run_assessment_in_background


_scheduler_thread: threading.Thread | None = None
_scheduler_lock = threading.Lock()
_stop_event = threading.Event()


def _load_recurring_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            settings = json.loads(SETTINGS_PATH.read_text())
            return settings.get("recurring_gfi", {})
        except Exception:
            pass
    return {}


def _save_recurring_settings(cfg: dict) -> None:
    settings = {}
    if SETTINGS_PATH.exists():
        try:
            settings = json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    settings["recurring_gfi"] = cfg
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))


def _scheduler_loop() -> None:
    """Main loop: check settings, run GFI if due, sleep until next run."""
    while not _stop_event.is_set():
        cfg = _load_recurring_settings()
        if not cfg.get("enabled"):
            _stop_event.wait(10)
            continue

        interval_minutes = cfg.get("interval_minutes", 60)
        model = cfg.get("model", "sonnet")
        last_run = cfg.get("last_run")

        now = datetime.now(timezone.utc)
        run_due = True
        if last_run:
            try:
                last_dt = datetime.fromisoformat(last_run)
                elapsed = (now - last_dt).total_seconds()
                if elapsed < interval_minutes * 60:
                    run_due = False
                    remaining = interval_minutes * 60 - elapsed
                    _stop_event.wait(min(remaining, 30))
                    continue
            except (ValueError, TypeError):
                pass

        if run_due and not _stop_event.is_set():
            try:
                _run_gfi_snapshot(model)
                cfg["last_run"] = datetime.now(timezone.utc).isoformat()
                _save_recurring_settings(cfg)
            except Exception as e:
                print(f"[recurring] GFI run failed: {e}")

            # Wait the full interval before next check
            _stop_event.wait(min(interval_minutes * 60, 30))


def _run_gfi_snapshot(model: str) -> None:
    """Create a snapshot with only GFI enabled and run it."""
    agents_config = {
        "asset-reader": {"enabled": False, "model": "sonnet"},
        "real-estate-assessor": {"enabled": False, "model": "sonnet"},
        "global-financial-intelligence": {"enabled": True, "model": model},
    }

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    label = f"Recurring GFI — {now_str}"

    snapshot_id = queries.create_snapshot(
        folder_path="",
        label=label,
        agents_config=json.dumps(agents_config),
    )

    run_assessment_in_background(
        snapshot_id,
        ar_folder="",
        re_folder=None,
        model_overrides={"global-financial-intelligence": model},
        enabled_agents=["global-financial-intelligence"],
    )


def start_scheduler() -> None:
    """Start the recurring scheduler if not already running."""
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return
        _stop_event.clear()
        _scheduler_thread = threading.Thread(
            target=_scheduler_loop, daemon=True, name="recurring-gfi"
        )
        _scheduler_thread.start()


def stop_scheduler() -> None:
    """Stop the recurring scheduler."""
    global _scheduler_thread
    with _scheduler_lock:
        _stop_event.set()
        _scheduler_thread = None


def is_scheduler_running() -> bool:
    with _scheduler_lock:
        return _scheduler_thread is not None and _scheduler_thread.is_alive()


def get_recurring_config() -> dict:
    return _load_recurring_settings()


def set_recurring_config(enabled: bool, interval_minutes: int, model: str) -> None:
    cfg = _load_recurring_settings()
    cfg["enabled"] = enabled
    cfg["interval_minutes"] = interval_minutes
    cfg["model"] = model
    _save_recurring_settings(cfg)
    if enabled:
        start_scheduler()
    else:
        stop_scheduler()
