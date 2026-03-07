import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from ingestion.pdf_extractor import build_context_message


class AgentProcess:
    """Manages a running claude CLI process."""

    def __init__(self, agent_name: str, system_prompt: str, user_message: str, model: str = "sonnet"):
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.user_message = user_message
        self.model = model

        self._lock = threading.Lock()
        self._status = "starting"  # starting | running | completed | failed
        self._result_text = ""
        self._error: str | None = None
        self._input_tokens = 0
        self._output_tokens = 0
        self._activity_log: list[str] = []

        self._proc: subprocess.Popen | None = None

    # ── Public state accessors ────────────────────────────────────────────────

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def activity_log(self) -> list[str]:
        with self._lock:
            return list(self._activity_log)

    def get_result(self) -> dict[str, Any]:
        with self._lock:
            return {
                "success": self._status == "completed",
                "raw_response": self._result_text,
                "input_tokens": self._input_tokens,
                "output_tokens": self._output_tokens,
                "error": self._error,
            }

    # ── Stop ──────────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Kill the running CLI process."""
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.kill()
            self._status = "failed"
            self._error = "Stopped by user"
            self._activity_log.append("Stopped by user")

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self) -> dict[str, Any]:
        """Run the CLI process, blocking until it finishes. Returns result dict."""
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        cmd = [
            "claude",
            "--print",
            "--output-format", "json",
            "--model", self.model,
            "--system-prompt", self.system_prompt,
            "--no-session-persistence",
            "--dangerously-skip-permissions",
        ]

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
        except FileNotFoundError:
            with self._lock:
                self._status = "failed"
                self._error = "claude CLI not found. Install it from https://claude.ai/code"
            return self.get_result()

        with self._lock:
            self._status = "running"
            self._activity_log.append("Process started")
            self._activity_log.append(f"PID: {self._proc.pid}")

        self._log(f"Sending message ({len(self.user_message)} chars)")

        try:
            stdout, stderr = self._proc.communicate(input=self.user_message)
        except Exception as e:
            with self._lock:
                self._status = "failed"
                self._error = f"Process error: {e}"
                self._activity_log.append(f"Error: {e}")
            return self.get_result()

        self._log(f"Process exited with code {self._proc.returncode}")

        if stderr and stderr.strip():
            self._log(f"[stderr] {stderr.strip()[:500]}")

        if self._proc.returncode != 0 and not stdout.strip():
            with self._lock:
                self._status = "failed"
                self._error = f"Process exited with code {self._proc.returncode}: {stderr.strip()[:500]}"
            return self.get_result()

        # Parse JSON output
        self._parse_output(stdout)
        return self.get_result()

    def _log(self, msg: str) -> None:
        with self._lock:
            self._activity_log.append(msg)

    def _parse_output(self, stdout: str) -> None:
        """Parse the JSON output from claude CLI."""
        stdout = stdout.strip()
        if not stdout:
            with self._lock:
                self._status = "failed"
                self._error = "Empty output from CLI"
            return

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            # Not JSON — treat raw text as the result
            with self._lock:
                self._result_text = stdout
                self._status = "completed"
                self._activity_log.append("Completed (raw text output)")
            return

        # --output-format json returns a single object with result, usage, cost, etc.
        result_text = data.get("result", "")
        usage = data.get("usage", {})
        cost = data.get("cost_usd", 0)
        duration = data.get("duration_ms", 0)

        with self._lock:
            self._result_text = result_text
            self._input_tokens = usage.get("input_tokens", 0)
            self._output_tokens = usage.get("output_tokens", 0)
            self._status = "completed" if result_text else "failed"
            if not result_text:
                self._error = "No result text in CLI output"

            cost_str = f"${cost:.4f}" if cost else ""
            dur_str = f"{duration / 1000:.1f}s" if duration else ""
            parts = [p for p in [cost_str, dur_str] if p]
            self._activity_log.append(f"Completed ({', '.join(parts)})" if parts else "Completed")


def run_agent(
    agent_name: str,
    system_prompt: str,
    files: list[tuple[str, Path]] | None = None,
    extra_context: str = "",
    agent_processes: dict | None = None,
    file_context: str = "",
    model: str = "sonnet",
) -> dict[str, Any]:
    """
    Run a Claude agent locally via the `claude` CLI.
    file_context: pre-built context string (skips file extraction if provided).
    """
    user_parts: list[str] = []

    if file_context:
        user_parts.append(file_context)
    elif files:
        user_parts.append(build_context_message(files))

    if extra_context:
        user_parts.append(extra_context)

    if not user_parts:
        user_parts.append("Please perform your analysis based on the context available.")

    user_message = "\n\n".join(user_parts)

    proc = AgentProcess(agent_name, system_prompt, user_message, model=model)

    if agent_processes is not None:
        agent_processes[agent_name] = proc

    return proc.run()
