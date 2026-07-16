import json
import time

import pytest

import trackr
from trackr import store


@pytest.fixture(autouse=True)
def isolated_trackr_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKR_DIR", str(tmp_path))
    yield tmp_path


def test_init_creates_run():
    run = trackr.init(project="p1", name="run-a", config={"lr": 0.1})
    assert run.project == "p1"
    assert run.name == "run-a"

    conn = store.connect()
    row = store.get_run(conn, run.run_id)
    conn.close()
    assert row is not None
    assert row["status"] == "running"
    assert json.loads(row["config"]) == {"lr": 0.1}


def test_init_defaults_name_to_run_id():
    run = trackr.init(project="p1")
    assert run.name == run.run_id


def test_log_and_finish():
    run = trackr.init(project="p1", name="run-b")
    for step in range(5):
        run.log({"loss": 1.0 / (step + 1)}, step=step)
    run.finish(status="completed")

    conn = store.connect()
    metrics = store.get_metrics(conn, run.run_id)
    row = store.get_run(conn, run.run_id)
    conn.close()

    assert len(metrics) == 5
    assert row["status"] == "completed"
    assert row["end_time"] is not None


def test_log_without_explicit_step_autoincrements():
    run = trackr.init(project="p1", name="run-auto")
    run.log({"loss": 1.0})
    run.log({"loss": 0.5})
    run.finish()

    conn = store.connect()
    metrics = store.get_metrics(conn, run.run_id)
    conn.close()
    assert [m["step"] for m in metrics] == [0, 1]


def test_log_after_finish_raises():
    run = trackr.init(project="p1", name="run-c")
    run.finish()
    with pytest.raises(RuntimeError):
        run.log({"loss": 1.0})


def test_log_artifact_copies_file(tmp_path):
    src = tmp_path / "art.txt"
    src.write_text("hello")
    run = trackr.init(project="p1", name="run-d")
    run.log_artifact(str(src))
    run.finish()

    conn = store.connect()
    artifacts = store.get_artifacts(conn, run.run_id)
    conn.close()

    assert len(artifacts) == 1
    assert artifacts[0]["original_name"] == "art.txt"
    dest = store.get_artifacts_dir() / run.run_id / "art.txt"
    assert dest.exists()
    assert dest.read_text() == "hello"


def test_log_artifact_missing_file_raises():
    run = trackr.init(project="p1", name="run-e")
    with pytest.raises(FileNotFoundError):
        run.log_artifact("/no/such/file.txt")


def test_list_runs_by_project():
    trackr.init(project="alpha", name="a1").finish()
    trackr.init(project="beta", name="b1").finish()

    conn = store.connect()
    alpha_runs = store.list_runs(conn, project="alpha")
    all_runs = store.list_runs(conn)
    conn.close()

    assert len(alpha_runs) == 1
    assert alpha_runs[0]["project"] == "alpha"
    assert len(all_runs) == 2


def test_final_metrics_returns_latest_step():
    run = trackr.init(project="p1", name="run-f")
    run.log({"loss": 1.0}, step=0)
    run.log({"loss": 0.5}, step=1)
    run.finish()

    conn = store.connect()
    final = store.get_final_metrics(conn, run.run_id)
    conn.close()

    assert final["loss"] == 0.5


def test_doctor_marks_stale_running_run_as_crashed():
    run = trackr.init(project="p1", name="run-g")
    conn = store.connect()
    stale_time = time.time() - 3600
    conn.execute(
        "UPDATE runs SET heartbeat = ?, start_time = ? WHERE id = ?",
        (stale_time, stale_time, run.run_id),
    )
    conn.commit()

    crashed = store.mark_stale_as_crashed(conn, stale_seconds=60)
    conn.close()

    assert run.run_id in crashed

    conn = store.connect()
    row = store.get_run(conn, run.run_id)
    conn.close()
    assert row["status"] == "crashed"


def test_doctor_leaves_fresh_running_run_alone():
    run = trackr.init(project="p1", name="run-fresh")

    conn = store.connect()
    crashed = store.mark_stale_as_crashed(conn, stale_seconds=600)
    row = store.get_run(conn, run.run_id)
    conn.close()

    assert run.run_id not in crashed
    assert row["status"] == "running"


def test_run_context_manager_marks_failed_on_exception():
    with pytest.raises(ValueError):
        with trackr.init(project="p1", name="run-h") as run:
            run.log({"loss": 1.0})
            raise ValueError("boom")

    conn = store.connect()
    row = store.get_run(conn, run.run_id)
    conn.close()
    assert row["status"] == "failed"


def test_delete_run_removes_row_and_cascades_metrics_and_artifacts(tmp_path):
    src = tmp_path / "art.txt"
    src.write_text("hello")
    run = trackr.init(project="p1", name="run-del")
    run.log({"loss": 1.0}, step=0)
    run.log_artifact(str(src))
    run.finish()

    conn = store.connect()
    deleted = store.delete_run(conn, run.run_id)
    assert deleted is True
    assert store.get_run(conn, run.run_id) is None
    assert store.get_metrics(conn, run.run_id) == []
    assert store.get_artifacts(conn, run.run_id) == []
    conn.close()


def test_delete_run_missing_id_returns_false():
    store.init_schema()
    conn = store.connect()
    assert store.delete_run(conn, "does-not-exist") is False
    conn.close()


def test_run_context_manager_marks_completed_on_success():
    with trackr.init(project="p1", name="run-i") as run:
        run.log({"loss": 1.0})

    conn = store.connect()
    row = store.get_run(conn, run.run_id)
    conn.close()
    assert row["status"] == "completed"
