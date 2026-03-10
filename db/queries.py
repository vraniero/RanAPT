from datetime import datetime, timezone
from typing import Optional
import sqlite3
from db.schema import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Snapshots ──────────────────────────────────────────────────────────────────

def create_snapshot(
    folder_path: str,
    label: Optional[str] = None,
    real_estate_folder: Optional[str] = None,
    agents_config: Optional[str] = None,
) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO snapshots (created_at, folder_path, real_estate_folder, label, status, agents_config) VALUES (?, ?, ?, ?, 'pending', ?)",
        (_now(), folder_path, real_estate_folder, label, agents_config),
    )
    conn.commit()
    snapshot_id = cur.lastrowid
    conn.close()
    return snapshot_id


def update_snapshot_status(snapshot_id: int, status: str, pdf_path: Optional[str] = None) -> None:
    conn = get_connection()
    if pdf_path:
        conn.execute(
            "UPDATE snapshots SET status=?, pdf_path=? WHERE id=?",
            (status, pdf_path, snapshot_id),
        )
    else:
        conn.execute("UPDATE snapshots SET status=? WHERE id=?", (status, snapshot_id))
    conn.commit()
    conn.close()


def get_snapshot(snapshot_id: int) -> Optional[sqlite3.Row]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
    conn.close()
    return row


def list_snapshots() -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM snapshots ORDER BY id DESC").fetchall()
    conn.close()
    return rows


def delete_snapshot(snapshot_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM snapshots WHERE id=?", (snapshot_id,))
    conn.commit()
    conn.close()


# ── Agent Results ──────────────────────────────────────────────────────────────

def create_agent_result(snapshot_id: int, agent_name: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO agent_results (snapshot_id, agent_name, status) VALUES (?, ?, 'pending')",
        (snapshot_id, agent_name),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def update_agent_result_started(agent_result_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE agent_results SET status='running', started_at=? WHERE id=?",
        (_now(), agent_result_id),
    )
    conn.commit()
    conn.close()


def update_agent_result_completed(
    agent_result_id: int,
    raw_response: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE agent_results
           SET status='completed', completed_at=?, raw_response=?,
               input_tokens=?, output_tokens=?
           WHERE id=?""",
        (_now(), raw_response, input_tokens, output_tokens, agent_result_id),
    )
    conn.commit()
    conn.close()


def update_agent_result_failed(agent_result_id: int, error_message: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE agent_results SET status='failed', completed_at=?, error_message=? WHERE id=?",
        (_now(), error_message, agent_result_id),
    )
    conn.commit()
    conn.close()


def fail_pending_agent_results(snapshot_id: int, error_message: str) -> None:
    """Mark all non-completed agent results for a snapshot as failed."""
    conn = get_connection()
    conn.execute(
        "UPDATE agent_results SET status='failed', completed_at=?, error_message=? "
        "WHERE snapshot_id=? AND status IN ('pending', 'running')",
        (_now(), error_message, snapshot_id),
    )
    conn.commit()
    conn.close()


def get_agent_results(snapshot_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM agent_results WHERE snapshot_id=? ORDER BY id",
        (snapshot_id,),
    ).fetchall()
    conn.close()
    return rows


def get_agent_result_by_name(snapshot_id: int, agent_name: str) -> Optional[sqlite3.Row]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM agent_results WHERE snapshot_id=? AND agent_name=?",
        (snapshot_id, agent_name),
    ).fetchone()
    conn.close()
    return row


# ── Snapshot Files ─────────────────────────────────────────────────────────────

def add_snapshot_file(
    snapshot_id: int,
    file_name: str,
    file_type: str,
    file_path: str,
    file_size: int,
) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO snapshot_files (snapshot_id, file_name, file_type, file_path, file_size) VALUES (?, ?, ?, ?, ?)",
        (snapshot_id, file_name, file_type, file_path, file_size),
    )
    conn.commit()
    conn.close()


def get_snapshot_files(snapshot_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM snapshot_files WHERE snapshot_id=? ORDER BY id",
        (snapshot_id,),
    ).fetchall()
    conn.close()
    return rows


def count_snapshot_files(snapshot_id: int) -> int:
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM snapshot_files WHERE snapshot_id=?", (snapshot_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else 0


# ── Asset Items ────────────────────────────────────────────────────────────────

def add_asset_item(
    snapshot_id: int,
    asset_name: Optional[str] = None,
    ticker: Optional[str] = None,
    asset_type: Optional[str] = None,
    currency: Optional[str] = None,
    quantity: Optional[float] = None,
    unit_price: Optional[float] = None,
    total_value_eur: Optional[float] = None,
    percentage: Optional[float] = None,
    cost_basis_eur: Optional[float] = None,
) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO asset_items
           (snapshot_id, asset_name, ticker, asset_type, currency, quantity, unit_price, total_value_eur, percentage, cost_basis_eur)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (snapshot_id, asset_name, ticker, asset_type, currency, quantity, unit_price, total_value_eur, percentage, cost_basis_eur),
    )
    conn.commit()
    conn.close()


def get_asset_items(snapshot_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM asset_items WHERE snapshot_id=? ORDER BY total_value_eur DESC",
        (snapshot_id,),
    ).fetchall()
    conn.close()
    return rows


def get_portfolio_totals_over_time() -> list[sqlite3.Row]:
    """Returns (snapshot_id, created_at, total_value_eur) per snapshot for trend chart."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT s.id as snapshot_id, s.created_at, s.label,
                  SUM(a.total_value_eur) as total_value_eur
           FROM snapshots s
           LEFT JOIN asset_items a ON a.snapshot_id = s.id
           WHERE s.status = 'completed'
           GROUP BY s.id
           ORDER BY s.created_at""",
    ).fetchall()
    conn.close()
    return rows


def get_net_worth_history() -> list[sqlite3.Row]:
    """Returns (snapshot_id, created_at, label, total_value_eur) for all completed snapshots, oldest first."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT s.id as snapshot_id, s.created_at, s.label,
                  SUM(a.total_value_eur) as total_value_eur
           FROM snapshots s
           JOIN asset_items a ON a.snapshot_id = s.id
           WHERE s.status = 'completed' AND a.total_value_eur IS NOT NULL
           GROUP BY s.id
           ORDER BY s.created_at""",
    ).fetchall()
    conn.close()
    return rows


def get_unrealized_gains(snapshot_id: int) -> float:
    """Returns total unrealized capital gains for a snapshot (where cost basis is known)."""
    conn = get_connection()
    row = conn.execute(
        """SELECT SUM(total_value_eur - cost_basis_eur) as total_gains
           FROM asset_items
           WHERE snapshot_id = ?
             AND total_value_eur IS NOT NULL
             AND cost_basis_eur IS NOT NULL
             AND total_value_eur > cost_basis_eur""",
        (snapshot_id,),
    ).fetchone()
    conn.close()
    return row["total_gains"] if row and row["total_gains"] else 0.0


def get_total_cost_basis(snapshot_id: int) -> float | None:
    """Returns total cost basis for a snapshot, or None if no cost basis data exists."""
    conn = get_connection()
    row = conn.execute(
        """SELECT SUM(cost_basis_eur) as total_cost_basis,
                  COUNT(cost_basis_eur) as has_basis
           FROM asset_items
           WHERE snapshot_id = ? AND total_value_eur IS NOT NULL""",
        (snapshot_id,),
    ).fetchone()
    conn.close()
    if row and row["has_basis"] and row["has_basis"] > 0:
        return row["total_cost_basis"]
    return None


def get_resolved_assets(snapshot_id: int) -> list[sqlite3.Row]:
    """Returns assets for a snapshot with merge rules applied (grouped by resolved name)."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT resolved_name as asset_name,
                  resolved_ticker as ticker,
                  asset_type,
                  SUM(total_value_eur) as total_value_eur
           FROM (
               SELECT COALESCE(
                          (SELECT m.canonical_name FROM asset_merges m
                           WHERE m.variant_name = a.asset_name LIMIT 1),
                          a.asset_name, 'Unknown'
                      ) as resolved_name,
                      COALESCE(
                          (SELECT m.canonical_ticker FROM asset_merges m
                           WHERE m.variant_name = a.asset_name LIMIT 1),
                          a.ticker, ''
                      ) as resolved_ticker,
                      COALESCE(a.asset_type, 'Other') as asset_type,
                      a.total_value_eur
               FROM asset_items a
               WHERE a.snapshot_id = ? AND a.total_value_eur IS NOT NULL
           )
           GROUP BY resolved_name
           ORDER BY total_value_eur DESC""",
        (snapshot_id,),
    ).fetchall()
    conn.close()
    return rows


def get_portfolio_breakdown_over_time() -> list[sqlite3.Row]:
    """Returns (snapshot_id, created_at, label, asset_type, type_value_eur) per snapshot+type."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT s.id as snapshot_id, s.created_at, s.label,
                  COALESCE(a.asset_type, 'Other') as asset_type,
                  SUM(a.total_value_eur) as type_value_eur
           FROM snapshots s
           JOIN asset_items a ON a.snapshot_id = s.id
           WHERE s.status = 'completed' AND a.total_value_eur IS NOT NULL
           GROUP BY s.id, a.asset_type
           ORDER BY s.created_at, a.asset_type""",
    ).fetchall()
    conn.close()
    return rows


def get_portfolio_assets_over_time() -> list[sqlite3.Row]:
    """Returns individual assets per snapshot for the stacked chart.

    Applies asset merge rules: if a merge exists mapping variant -> canonical,
    the variant's name/ticker are replaced with the canonical ones and values
    are summed.
    """
    conn = get_connection()
    # Use a subquery to resolve each asset's canonical name (first match wins)
    rows = conn.execute(
        """SELECT snapshot_id, created_at, label,
                  resolved_name as asset_name,
                  resolved_ticker as ticker,
                  asset_type,
                  SUM(total_value_eur) as total_value_eur
           FROM (
               SELECT s.id as snapshot_id, s.created_at, s.label,
                      COALESCE(
                          (SELECT m.canonical_name FROM asset_merges m
                           WHERE m.variant_name = a.asset_name LIMIT 1),
                          a.asset_name, 'Unknown'
                      ) as resolved_name,
                      COALESCE(
                          (SELECT m.canonical_ticker FROM asset_merges m
                           WHERE m.variant_name = a.asset_name LIMIT 1),
                          a.ticker, ''
                      ) as resolved_ticker,
                      COALESCE(a.asset_type, 'Other') as asset_type,
                      a.total_value_eur
               FROM snapshots s
               JOIN asset_items a ON a.snapshot_id = s.id
               WHERE s.status = 'completed' AND a.total_value_eur IS NOT NULL
           )
           GROUP BY snapshot_id, resolved_name, resolved_ticker
           ORDER BY created_at, asset_type, total_value_eur DESC""",
    ).fetchall()
    conn.close()
    return rows


# ── Watch Events ──────────────────────────────────────────────────────────────

def add_watch_event(
    snapshot_id: int,
    event_date: str,
    title: str,
    description: Optional[str] = None,
    category: Optional[str] = None,
    impact: Optional[str] = None,
) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO watch_events (snapshot_id, event_date, title, description, category, impact)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (snapshot_id, event_date, title, description, category, impact),
    )
    conn.commit()
    conn.close()


def get_all_watch_events() -> list[sqlite3.Row]:
    """Returns all watch events with snapshot info, ordered by event date."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT w.*, s.label, s.created_at as snapshot_created_at
           FROM watch_events w
           JOIN snapshots s ON s.id = w.snapshot_id
           WHERE s.status = 'completed'
           ORDER BY w.event_date""",
    ).fetchall()
    conn.close()
    return rows


def update_watch_event_impact(event_id: int, impact: str) -> None:
    """Update a watch event's impact level (high, medium, low)."""
    conn = get_connection()
    conn.execute("UPDATE watch_events SET impact=? WHERE id=?", (impact, event_id))
    conn.commit()
    conn.close()


def update_watch_event_status(event_id: int, status: str) -> None:
    """Update a watch event's status (active, archived, low_priority)."""
    conn = get_connection()
    conn.execute("UPDATE watch_events SET status=? WHERE id=?", (status, event_id))
    conn.commit()
    conn.close()


def archive_past_watch_events() -> int:
    """Auto-archive active events whose date has passed. Returns count of archived events."""
    conn = get_connection()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cur = conn.execute(
        "UPDATE watch_events SET status='archived' WHERE status='active' AND event_date < ?",
        (today,),
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def get_watch_events_for_snapshot(snapshot_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM watch_events WHERE snapshot_id=? ORDER BY event_date",
        (snapshot_id,),
    ).fetchall()
    conn.close()
    return rows


# ── Event Actions ─────────────────────────────────────────────────────────────

def add_event_action(
    event_id: int, model: str, raw_response: str,
    input_tokens: int = 0, output_tokens: int = 0,
) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO event_actions (event_id, created_at, model, raw_response, input_tokens, output_tokens)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (event_id, _now(), model, raw_response, input_tokens, output_tokens),
    )
    conn.commit()
    action_id = cur.lastrowid
    conn.close()
    return action_id


def get_event_actions(event_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM event_actions WHERE event_id=? ORDER BY id DESC",
        (event_id,),
    ).fetchall()
    conn.close()
    return rows


def delete_event_action(action_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM event_actions WHERE id=?", (action_id,))
    conn.commit()
    conn.close()


# ── Asset Merge Suggestions ──────────────────────────────────────────────────

def add_merge_suggestion(
    asset_name_a: str, ticker_a: Optional[str],
    asset_name_b: str, ticker_b: Optional[str],
    reason: str,
) -> None:
    conn = get_connection()
    # Check if this pair already exists (in either order)
    existing = conn.execute(
        """SELECT id FROM asset_merge_suggestions
           WHERE (asset_name_a=? AND asset_name_b=?)
              OR (asset_name_a=? AND asset_name_b=?)""",
        (asset_name_a, asset_name_b, asset_name_b, asset_name_a),
    ).fetchone()
    if not existing:
        conn.execute(
            """INSERT INTO asset_merge_suggestions
               (asset_name_a, ticker_a, asset_name_b, ticker_b, reason, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (asset_name_a, ticker_a, asset_name_b, ticker_b, reason, _now()),
        )
        conn.commit()
    conn.close()


def get_pending_merge_suggestions() -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM asset_merge_suggestions WHERE status='pending' ORDER BY id",
    ).fetchall()
    conn.close()
    return rows


def get_all_merge_suggestions() -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM asset_merge_suggestions ORDER BY status, id",
    ).fetchall()
    conn.close()
    return rows


def update_merge_suggestion_status(suggestion_id: int, status: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE asset_merge_suggestions SET status=? WHERE id=?",
        (status, suggestion_id),
    )
    conn.commit()
    conn.close()


# ── Asset Merges ─────────────────────────────────────────────────────────────

def add_asset_merge(
    canonical_name: str, canonical_ticker: Optional[str],
    variant_name: str, variant_ticker: Optional[str],
) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO asset_merges (canonical_name, canonical_ticker, variant_name, variant_ticker, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (canonical_name, canonical_ticker, variant_name, variant_ticker, _now()),
    )
    conn.commit()
    conn.close()


def get_all_asset_merges() -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM asset_merges ORDER BY canonical_name",
    ).fetchall()
    conn.close()
    return rows


def delete_asset_merge(merge_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM asset_merges WHERE id=?", (merge_id,))
    conn.commit()
    conn.close()


def get_all_unique_assets() -> list[sqlite3.Row]:
    """Returns all distinct asset names/tickers across all snapshots."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT DISTINCT asset_name, ticker, asset_type
           FROM asset_items
           WHERE asset_name IS NOT NULL
           ORDER BY asset_name""",
    ).fetchall()
    conn.close()
    return rows


# ── Custom Agents ─────────────────────────────────────────────────────────────

def create_custom_agent(
    name: str, goal: str, model: str = "sonnet",
    schedule_minutes: Optional[int] = None,
    slug: Optional[str] = None,
) -> int:
    conn = get_connection()
    now = _now()
    cur = conn.execute(
        """INSERT INTO custom_agents (name, slug, goal, model, schedule_minutes, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
        (name, slug, goal, model, schedule_minutes, now, now),
    )
    conn.commit()
    agent_id = cur.lastrowid
    conn.close()
    return agent_id


def update_custom_agent(
    agent_id: int, name: str, goal: str, model: str,
    schedule_minutes: Optional[int] = None,
    slug: Optional[str] = None,
) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE custom_agents SET name=?, slug=?, goal=?, model=?, schedule_minutes=?, updated_at=?
           WHERE id=?""",
        (name, slug, goal, model, schedule_minutes, _now(), agent_id),
    )
    conn.commit()
    conn.close()


def update_custom_agent_status(agent_id: int, status: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE custom_agents SET status=?, updated_at=? WHERE id=?",
        (status, _now(), agent_id),
    )
    conn.commit()
    conn.close()


def update_custom_agent_last_run(agent_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE custom_agents SET last_run_at=? WHERE id=?",
        (_now(), agent_id),
    )
    conn.commit()
    conn.close()


def delete_custom_agent(agent_id: int) -> None:
    """Delete agent and all its runs (cascade)."""
    conn = get_connection()
    conn.execute("DELETE FROM custom_agents WHERE id=?", (agent_id,))
    conn.commit()
    conn.close()


def get_custom_agent(agent_id: int) -> Optional[sqlite3.Row]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM custom_agents WHERE id=?", (agent_id,)).fetchone()
    conn.close()
    return row


def list_custom_agents(include_archived: bool = False) -> list[sqlite3.Row]:
    conn = get_connection()
    if include_archived:
        rows = conn.execute("SELECT * FROM custom_agents ORDER BY status, name").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM custom_agents WHERE status='active' ORDER BY name"
        ).fetchall()
    conn.close()
    return rows


def list_scheduled_custom_agents() -> list[sqlite3.Row]:
    """Return active agents that have a schedule configured."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM custom_agents WHERE status='active' AND schedule_minutes IS NOT NULL ORDER BY name"
    ).fetchall()
    conn.close()
    return rows


# ── Custom Agent Runs ────────────────────────────────────────────────────────

def create_custom_agent_run(agent_id: int) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO custom_agent_runs (agent_id, created_at, status) VALUES (?, ?, 'pending')",
        (agent_id, _now()),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def update_custom_agent_run_running(run_id: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE custom_agent_runs SET status='running' WHERE id=?", (run_id,))
    conn.commit()
    conn.close()


def update_custom_agent_run_completed(
    run_id: int, raw_response: str, input_tokens: int, output_tokens: int,
) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE custom_agent_runs SET status='completed', raw_response=?, input_tokens=?, output_tokens=? WHERE id=?",
        (raw_response, input_tokens, output_tokens, run_id),
    )
    conn.commit()
    conn.close()


def update_custom_agent_run_failed(run_id: int, error_message: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE custom_agent_runs SET status='failed', error_message=? WHERE id=?",
        (error_message, run_id),
    )
    conn.commit()
    conn.close()


def get_custom_agent_runs(agent_id: int, limit: int = 50) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM custom_agent_runs WHERE agent_id=? ORDER BY id DESC LIMIT ?",
        (agent_id, limit),
    ).fetchall()
    conn.close()
    return rows


def get_custom_agent_run(run_id: int) -> Optional[sqlite3.Row]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM custom_agent_runs WHERE id=?", (run_id,)).fetchone()
    conn.close()
    return row


def delete_custom_agent_runs(agent_id: int) -> None:
    """Delete all runs for an agent."""
    conn = get_connection()
    conn.execute("DELETE FROM custom_agent_runs WHERE agent_id=?", (agent_id,))
    conn.commit()
    conn.close()


# ── Scenarios (legacy) ───────────────────────────────────────────────────────

def create_scenario(prompt: str, model: str = "sonnet") -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO scenarios (created_at, prompt, model, status) VALUES (?, ?, ?, 'pending')",
        (_now(), prompt, model),
    )
    conn.commit()
    scenario_id = cur.lastrowid
    conn.close()
    return scenario_id


def update_scenario_running(scenario_id: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE scenarios SET status='running' WHERE id=?", (scenario_id,))
    conn.commit()
    conn.close()


def update_scenario_completed(
    scenario_id: int, raw_response: str, input_tokens: int, output_tokens: int,
) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE scenarios SET status='completed', raw_response=?, input_tokens=?, output_tokens=? WHERE id=?",
        (raw_response, input_tokens, output_tokens, scenario_id),
    )
    conn.commit()
    conn.close()


def update_scenario_failed(scenario_id: int, error_message: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE scenarios SET status='failed', error_message=? WHERE id=?",
        (error_message, scenario_id),
    )
    conn.commit()
    conn.close()


def get_scenario(scenario_id: int) -> Optional[sqlite3.Row]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM scenarios WHERE id=?", (scenario_id,)).fetchone()
    conn.close()
    return row


def list_scenarios() -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM scenarios ORDER BY id DESC").fetchall()
    conn.close()
    return rows


def delete_scenario(scenario_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM scenarios WHERE id=?", (scenario_id,))
    conn.commit()
    conn.close()
