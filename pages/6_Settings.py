import json
import subprocess
from pathlib import Path

import streamlit as st

from config import SETTINGS_PATH, DB_PATH, REPORTS_DIR
from db.schema import init_db

init_db()

st.title("Settings")


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    return {}


def save_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))


settings = load_settings()

# ── Claude CLI Status ─────────────────────────────────────────────────────────
st.subheader("Claude CLI")
st.markdown(
    "This app runs agents locally via the `claude` CLI. "
    "Make sure Claude Code is installed and authenticated."
)

try:
    result = subprocess.run(
        ["claude", "--version"], capture_output=True, text=True, timeout=5
    )
    if result.returncode == 0:
        st.success(f"Claude CLI found: **{result.stdout.strip()}**")
    else:
        st.error("Claude CLI found but returned an error.")
except FileNotFoundError:
    st.error("Claude CLI not found. Install it from https://claude.ai/code")
except Exception as e:
    st.error(f"Error checking Claude CLI: {e}")

# ── Default Folders ────────────────────────────────────────────────────────────
st.subheader("Default Document Folders")

default_folder = settings.get("default_folder", "")
new_default_folder = st.text_input(
    "Asset Reader — financial statements folder",
    value=default_folder,
    placeholder="/Users/you/Documents/portfolio",
    help="Folder with account statements, brokerage reports, and other financial documents.",
)

default_re_folder = settings.get("default_real_estate_folder", "")
new_default_re_folder = st.text_input(
    "Real Estate Assessor — property documents folder",
    value=default_re_folder,
    placeholder="/Users/you/Documents/real-estate",
    help="Folder with property documents, mortgage statements, rental agreements, etc.",
)

# ── Save ───────────────────────────────────────────────────────────────────────
if st.button("Save Settings", type="primary"):
    settings["default_folder"] = new_default_folder
    settings["default_real_estate_folder"] = new_default_re_folder
    save_settings(settings)
    st.success("Settings saved.")

st.divider()

# ── Storage Info ───────────────────────────────────────────────────────────────
st.subheader("Storage")

col1, col2 = st.columns(2)

with col1:
    db_size = DB_PATH.stat().st_size / 1024 if DB_PATH.exists() else 0
    st.metric("Database size", f"{db_size:.1f} KB")
    st.caption(str(DB_PATH))

with col2:
    if REPORTS_DIR.exists():
        report_files = list(REPORTS_DIR.glob("*.pdf"))
        reports_size = sum(f.stat().st_size for f in report_files) / 1024
        st.metric("PDF reports", f"{len(report_files)} files ({reports_size:.0f} KB)")
    else:
        st.metric("PDF reports", "0 files")
    st.caption(str(REPORTS_DIR))
