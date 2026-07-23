import time

import pytest

import trackr
from trackr import store


@pytest.fixture(autouse=True)
def isolated_trackr_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKR_DIR", str(tmp_path))
    yield tmp_path


def test_connect_uses_wal_mode_for_concurrent_dashboard_reads():
    # trackr's own core use case is a live web dashboard reading while a
    # training script logs metrics concurrently -- the default rollback
    # journal mode blocks readers against writers, unlike WAL. flowr's and
    # batchr's own SQLite stores already enable WAL for the same
    # multi-process access pattern.
    conn = store.connect()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode.lower() == "wal"


def test_mark_stale_as_crashed_marks_only_old_heartbeats():
    run = trackr.init(project="p1", name="stale-run")
    conn = store.connect()
    store.touch_heartbeat(conn, run.run_id, time.time() - 3600)
    conn.close()

    conn = store.connect()
    crashed = store.mark_stale_as_crashed(conn, stale_seconds=60)
    conn.close()

    assert crashed == [run.run_id]
    conn = store.connect()
    assert store.get_run(conn, run.run_id)["status"] == "crashed"
    conn.close()


@pytest.mark.parametrize("bad_stale_seconds", [0, -600])
def test_mark_stale_as_crashed_rejects_non_positive_seconds(bad_stale_seconds):
    # A non-positive value pushes the cutoff to now-or-later, which would
    # match (and incorrectly crash) every currently *healthy* running run,
    # not just stale ones -- must fail loud instead of corrupting status.
    run = trackr.init(project="p1", name="healthy-run")
    run.log({"loss": 0.5})  # touches heartbeat to "now"

    conn = store.connect()
    with pytest.raises(ValueError, match="stale_seconds must be positive"):
        store.mark_stale_as_crashed(conn, stale_seconds=bad_stale_seconds)
    conn.close()

    conn = store.connect()
    assert store.get_run(conn, run.run_id)["status"] == "running"
    conn.close()
