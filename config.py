from pathlib import Path

REPO_ROOT = Path(".")
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"
DB_PATH = Path.home() / ".ranapt" / "ranapt.db"
REPORTS_DIR = Path.home() / ".ranapt" / "reports"
SETTINGS_PATH = Path.home() / ".ranapt" / "settings.json"

AGENT_NAMES = ["asset-reader", "global-financial-intelligence", "real-estate-assessor"]

# Ensure dirs exist
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
