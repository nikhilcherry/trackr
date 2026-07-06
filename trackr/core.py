"""Run object and lifecycle: init, log, log_artifact, finish."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from . import store


def _detect_git_commit() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _generate_run_id() -> str:
    return f"{int(time.time())}-{uuid.uuid4().hex[:6]}"


class Run:
    def __init__(self, run_id, project, name, config, db_path, artifacts_dir):
        self.run_id = run_id
        self.project = project
        self.name = name
        self.config = config
        self._db_path = db_path
        self._artifacts_dir = artifacts_dir
        self._step_counter = 0
        self._finished = False

    def log(self, metrics: Dict[str, Any], step: Optional[int] = None) -> None:
        if self._finished:
            raise RuntimeError(f"run {self.run_id} already finished; cannot log")
        if step is None:
            step = self._step_counter
            self._step_counter += 1
        else:
            self._step_counter = step + 1
        timestamp = time.time()
        conn = store.connect(self._db_path)
        try:
            for key, value in metrics.items():
                store.insert_metric(conn, self.run_id, key, float(value), step, timestamp)
            store.touch_heartbeat(conn, self.run_id, timestamp)
        finally:
            conn.close()

    def log_artifact(self, path: str) -> None:
        if self._finished:
            raise RuntimeError(f"run {self.run_id} already finished; cannot log artifact")
        src = Path(path)
        if not src.exists():
            raise FileNotFoundError(f"artifact not found: {path}")
        run_dir = self._artifacts_dir / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        dest = run_dir / src.name
        shutil.copy2(src, dest)
        conn = store.connect(self._db_path)
        try:
            store.insert_artifact(conn, self.run_id, str(dest), src.name, time.time())
        finally:
            conn.close()

    def finish(self, status: str = "completed") -> None:
        if self._finished:
            return
        conn = store.connect(self._db_path)
        try:
            store.finish_run(conn, self.run_id, status, time.time())
        finally:
            conn.close()
        self._finished = True

    def __enter__(self) -> "Run":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.finish(status="failed" if exc_type else "completed")
        return False


def init(project: str, name: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> Run:
    db_path = store.get_db_path()
    artifacts_dir = store.get_artifacts_dir()
    store.init_schema(db_path)

    run_id = _generate_run_id()
    if name is None:
        name = run_id

    now = time.time()
    conn = store.connect(db_path)
    try:
        store.insert_run(
            conn,
            run_id=run_id,
            project=project,
            name=name,
            config=json.dumps(config or {}),
            status="running",
            start_time=now,
            git_commit=_detect_git_commit(),
        )
    finally:
        conn.close()

    return Run(run_id, project, name, config or {}, db_path, artifacts_dir)


# --- Non-goals for v1 (see README) — TODO stubs only, not implemented ---
# TODO: remote sync — push/pull runs to a shared trackr server
# TODO: teams / multi-user access control
# TODO: sweep() — hyperparameter sweep orchestration across runs
# TODO: GPU utilization / system metrics logging
