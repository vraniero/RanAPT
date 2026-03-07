import sqlite3
from config import DB_PATH

DDL = """
CREATE TABLE IF NOT EXISTS snapshots (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at           TEXT    NOT NULL,
    folder_path          TEXT    NOT NULL,
    real_estate_folder   TEXT,
    label                TEXT,
    status               TEXT    NOT NULL DEFAULT 'pending',
    pdf_path             TEXT,
    agents_config        TEXT
);

CREATE TABLE IF NOT EXISTS agent_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    agent_name      TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending',
    started_at      TEXT,
    completed_at    TEXT,
    raw_response    TEXT,
    error_message   TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER
);

CREATE TABLE IF NOT EXISTS asset_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    asset_name      TEXT,
    ticker          TEXT,
    asset_type      TEXT,
    currency        TEXT,
    quantity        REAL,
    unit_price      REAL,
    total_value_eur REAL,
    percentage      REAL
);

CREATE TABLE IF NOT EXISTS snapshot_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    file_name   TEXT    NOT NULL,
    file_type   TEXT    NOT NULL,
    file_path   TEXT    NOT NULL,
    file_size   INTEGER
);

CREATE TABLE IF NOT EXISTS watch_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    event_date  TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    description TEXT,
    category    TEXT,
    impact      TEXT
);

CREATE TABLE IF NOT EXISTS asset_merge_suggestions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_name_a    TEXT NOT NULL,
    ticker_a        TEXT,
    asset_name_b    TEXT NOT NULL,
    ticker_b        TEXT,
    reason          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenarios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,
    prompt          TEXT    NOT NULL,
    model           TEXT    NOT NULL DEFAULT 'sonnet',
    status          TEXT    NOT NULL DEFAULT 'pending',
    raw_response    TEXT,
    error_message   TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER
);

CREATE TABLE IF NOT EXISTS event_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        INTEGER NOT NULL REFERENCES watch_events(id) ON DELETE CASCADE,
    created_at      TEXT    NOT NULL,
    model           TEXT    NOT NULL,
    raw_response    TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER
);

CREATE TABLE IF NOT EXISTS asset_merges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name  TEXT NOT NULL,
    canonical_ticker TEXT,
    variant_name    TEXT NOT NULL,
    variant_ticker  TEXT,
    created_at      TEXT NOT NULL
);
"""

PRAGMA = "PRAGMA foreign_keys = ON;"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(PRAGMA)
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    conn.executescript(DDL)
    # Migrate: add columns if missing
    cols = [row[1] for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()]
    if "real_estate_folder" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN real_estate_folder TEXT")
    if "agents_config" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN agents_config TEXT")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"DB initialized at {DB_PATH}")
