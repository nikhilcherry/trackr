"""Schema and queries for the trackr SQLite store."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Optional


def get_trackr_dir() -> Path:
    override = os.environ.get("TRACKR_DIR")
    base = Path(override) if override else Path.home() / ".trackr"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_db_path() -> Path:
    return get_trackr_dir() / "trackr.db"


def get_artifacts_dir() -> Path:
    path = get_trackr_dir() / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    db_path = db_path or get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    name TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'running',
    start_time REAL NOT NULL,
    end_time REAL,
    heartbeat REAL,
    git_commit TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value REAL NOT NULL,
    step INTEGER NOT NULL,
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_run_id ON metrics(run_id);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    original_name TEXT NOT NULL,
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_run_id ON artifacts(run_id);
"""


def init_schema(db_path: Optional[Path] = None) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def insert_run(conn, *, run_id, project, name, config, status, start_time, git_commit):
    conn.execute(
        "INSERT INTO runs (id, project, name, config, status, start_time, heartbeat, git_commit) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, project, name, config, status, start_time, start_time, git_commit),
    )
    conn.commit()


def insert_metric(conn, run_id, key, value, step, timestamp):
    conn.execute(
        "INSERT INTO metrics (run_id, key, value, step, timestamp) VALUES (?, ?, ?, ?, ?)",
        (run_id, key, value, step, timestamp),
    )
    conn.commit()


def touch_heartbeat(conn, run_id, timestamp):
    conn.execute("UPDATE runs SET heartbeat = ? WHERE id = ?", (timestamp, run_id))
    conn.commit()


def insert_artifact(conn, run_id, path, original_name, timestamp):
    conn.execute(
        "INSERT INTO artifacts (run_id, path, original_name, timestamp) VALUES (?, ?, ?, ?)",
        (run_id, path, original_name, timestamp),
    )
    conn.commit()


def finish_run(conn, run_id, status, end_time):
    conn.execute(
        "UPDATE runs SET status = ?, end_time = ?, heartbeat = ? WHERE id = ?",
        (status, end_time, end_time, run_id),
    )
    conn.commit()


def list_runs(conn, project: Optional[str] = None):
    if project:
        rows = conn.execute(
            "SELECT * FROM runs WHERE project = ? ORDER BY start_time DESC", (project,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM runs ORDER BY start_time DESC").fetchall()
    return [dict(r) for r in rows]


def get_run(conn, run_id: str):
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def get_metrics(conn, run_id: str):
    rows = conn.execute(
        "SELECT key, value, step, timestamp FROM metrics WHERE run_id = ? ORDER BY step ASC",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_final_metrics(conn, run_id: str):
    rows = conn.execute(
        """
        SELECT m.key, m.value
        FROM metrics m
        INNER JOIN (
            SELECT key, MAX(step) AS max_step
            FROM metrics WHERE run_id = ?
            GROUP BY key
        ) latest ON m.key = latest.key AND m.step = latest.max_step
        WHERE m.run_id = ?
        """,
        (run_id, run_id),
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def get_artifacts(conn, run_id: str):
    rows = conn.execute(
        "SELECT * FROM artifacts WHERE run_id = ? ORDER BY timestamp ASC", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def delete_run(conn, run_id: str) -> bool:
    """Delete a run row (metrics/artifacts rows cascade via ON DELETE CASCADE).
    Returns True if a run was actually deleted, False if run_id didn't exist.
    Does not touch files under the artifacts directory — the caller (cli.py)
    handles that, since store.py doesn't own filesystem cleanup elsewhere.
    """
    cur = conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    conn.commit()
    return cur.rowcount > 0


def mark_stale_as_crashed(conn, stale_seconds: float):
    if stale_seconds <= 0:
        # A non-positive value pushes the cutoff to now-or-later, matching
        # (and marking crashed) every currently *healthy* running run --
        # the opposite of "stale". Fail loud instead of corrupting status.
        raise ValueError(f"stale_seconds must be positive, got {stale_seconds}")
    cutoff = time.time() - stale_seconds
    rows = conn.execute(
        "SELECT id FROM runs WHERE status = 'running' AND heartbeat < ?", (cutoff,)
    ).fetchall()
    ids = [r["id"] for r in rows]
    if ids:
        conn.executemany(
            "UPDATE runs SET status = 'crashed', end_time = heartbeat WHERE id = ?",
            [(i,) for i in ids],
        )
        conn.commit()
    return ids
