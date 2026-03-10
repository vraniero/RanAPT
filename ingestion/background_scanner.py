"""Background file scanner with progress tracking and cancellation.

Runs folder scanning + text extraction in a daemon thread so the Streamlit UI
stays responsive. The UI polls the ScanJob state to show progress.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ingestion.file_scanner import scan_folder, ScannedFile
from ingestion.pdf_extractor import extract_text


@dataclass
class ParsedFile:
    """A file that has been scanned and had its text extracted."""
    name: str
    path: Path
    file_type: str
    size: int
    modified: datetime
    text: str  # extracted text content
    error: str | None = None


class ScanJob:
    """Manages background scanning of a folder."""

    def __init__(self, folder_path: str, job_key: str):
        self.folder_path = folder_path
        self.job_key = job_key

        self._lock = threading.Lock()
        self._status = "pending"  # pending | scanning | parsing | completed | failed | cancelled
        self._scanned_files: list[ScannedFile] = []
        self._parsed_files: list[ParsedFile] = []
        self._current_file: str = ""
        self._files_parsed: int = 0
        self._total_files: int = 0
        self._error: str | None = None
        self._cancel_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Public state ──────────────────────────────────────────────────────────

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def scanned_files(self) -> list[ScannedFile]:
        with self._lock:
            return list(self._scanned_files)

    @property
    def parsed_files(self) -> list[ParsedFile]:
        with self._lock:
            return list(self._parsed_files)

    @property
    def current_file(self) -> str:
        with self._lock:
            return self._current_file

    @property
    def files_parsed(self) -> int:
        with self._lock:
            return self._files_parsed

    @property
    def total_files(self) -> int:
        with self._lock:
            return self._total_files

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def progress(self) -> float:
        with self._lock:
            if self._total_files == 0:
                return 0.0
            return self._files_parsed / self._total_files

    def doc_files(self) -> list[tuple[str, Path]]:
        """Return (name, path) tuples for non-image parsed files."""
        with self._lock:
            return [(f.name, f.path) for f in self._parsed_files if f.file_type != "image" and not f.error]

    # ── Control ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start scanning in a background thread."""
        if self._thread and self._thread.is_alive():
            return
        self._cancel_event.clear()
        with self._lock:
            self._status = "pending"
            self._scanned_files = []
            self._parsed_files = []
            self._current_file = ""
            self._files_parsed = 0
            self._total_files = 0
            self._error = None
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"scan-{self.job_key}"
        )
        self._thread.start()

    def cancel(self) -> None:
        """Cancel the running scan."""
        self._cancel_event.set()
        with self._lock:
            if self._status not in ("completed", "failed"):
                self._status = "cancelled"

    def restart(self) -> None:
        """Cancel any running scan and start fresh."""
        self.cancel()
        # Wait briefly for thread to notice cancellation
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
        self.start()

    # ── Background worker ─────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            # Phase 1: scan folder for files
            with self._lock:
                self._status = "scanning"

            scanned = scan_folder(self.folder_path)

            if self._cancel_event.is_set():
                return

            with self._lock:
                self._scanned_files = scanned
                self._total_files = len([f for f in scanned if f.file_type != "image"])
                self._status = "parsing"

            # Phase 2: extract text from each file
            for sf in scanned:
                if self._cancel_event.is_set():
                    return

                if sf.file_type == "image":
                    with self._lock:
                        self._parsed_files.append(ParsedFile(
                            name=sf.name, path=sf.path, file_type=sf.file_type,
                            size=sf.size, modified=sf.modified, text="",
                        ))
                    continue

                with self._lock:
                    self._current_file = sf.name

                try:
                    text = extract_text(sf.path)
                    error = None
                except Exception as e:
                    text = ""
                    error = str(e)

                if self._cancel_event.is_set():
                    return

                with self._lock:
                    self._parsed_files.append(ParsedFile(
                        name=sf.name, path=sf.path, file_type=sf.file_type,
                        size=sf.size, modified=sf.modified, text=text, error=error,
                    ))
                    self._files_parsed += 1

            with self._lock:
                self._current_file = ""
                self._status = "completed"

        except ValueError as e:
            with self._lock:
                self._status = "failed"
                self._error = str(e)
        except Exception as e:
            with self._lock:
                self._status = "failed"
                self._error = f"Unexpected error: {e}"


# ── Module-level registry ─────────────────────────────────────────────────────
# Keyed by (folder_path) so Streamlit reruns reuse the same job.

_scan_jobs: dict[str, ScanJob] = {}
_jobs_lock = threading.Lock()


def get_or_create_scan_job(folder_path: str, job_key: str) -> ScanJob:
    """Get an existing scan job or create a new one.

    If the folder_path changed for the same job_key, the old job is cancelled
    and a new one is created.
    """
    with _jobs_lock:
        existing = _scan_jobs.get(job_key)
        if existing and existing.folder_path == folder_path:
            return existing
        # Different folder or no existing job — create new
        if existing:
            existing.cancel()
        job = ScanJob(folder_path, job_key)
        _scan_jobs[job_key] = job
        return job


def remove_scan_job(job_key: str) -> None:
    """Cancel and remove a scan job."""
    with _jobs_lock:
        job = _scan_jobs.pop(job_key, None)
        if job:
            job.cancel()
