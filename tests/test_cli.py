import pytest

import trackr
from trackr import cli, store


@pytest.fixture(autouse=True)
def isolated_trackr_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKR_DIR", str(tmp_path))
    yield tmp_path


def _make_run(project="p1", name="run-a", artifact_text=None, tmp_path=None):
    run = trackr.init(project=project, name=name)
    if artifact_text is not None:
        src = tmp_path / f"{name}.txt"
        src.write_text(artifact_text)
        run.log_artifact(str(src))
    run.finish()
    return run


def test_rm_with_yes_deletes_run_and_artifacts(tmp_path, capsys):
    run = _make_run(name="run-a", artifact_text="hello", tmp_path=tmp_path)
    artifacts_dir = store.get_artifacts_dir() / run.run_id
    assert artifacts_dir.exists()

    cli.main(["rm", run.run_id, "--yes"])

    conn = store.connect()
    assert store.get_run(conn, run.run_id) is None
    conn.close()
    assert not artifacts_dir.exists()
    assert f"Deleted {run.run_id}" in capsys.readouterr().out


def test_rm_without_yes_prompts_and_aborts_on_no(tmp_path, monkeypatch, capsys):
    run = _make_run(name="run-b", tmp_path=tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: "n")

    cli.main(["rm", run.run_id])

    conn = store.connect()
    assert store.get_run(conn, run.run_id) is not None
    conn.close()
    assert "Aborted." in capsys.readouterr().out


def test_rm_without_yes_confirms_on_y(tmp_path, monkeypatch):
    run = _make_run(name="run-c", tmp_path=tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: "y")

    cli.main(["rm", run.run_id])

    conn = store.connect()
    assert store.get_run(conn, run.run_id) is None
    conn.close()


def test_rm_missing_run_id_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["rm", "does-not-exist", "--yes"])
    assert exc_info.value.code != 0
    assert "error: run not found: does-not-exist" in capsys.readouterr().err


def test_rm_multiple_runs_one_missing_deletes_found_and_exits_nonzero(tmp_path, capsys):
    run = _make_run(name="run-d", tmp_path=tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["rm", run.run_id, "missing-id", "--yes"])
    assert exc_info.value.code != 0

    conn = store.connect()
    assert store.get_run(conn, run.run_id) is None
    conn.close()
    captured = capsys.readouterr()
    assert "error: run not found: missing-id" in captured.err
    assert f"Deleted {run.run_id}" in captured.out


def test_rm_without_yes_treats_eof_as_abort(tmp_path, monkeypatch, capsys):
    # A non-interactive invocation (CI, cron, no stdin attached) without -y
    # must abort cleanly like a "no", not crash with a raw EOFError
    # traceback.
    run = _make_run(name="run-e", tmp_path=tmp_path)

    def _raise_eof(_):
        raise EOFError()

    monkeypatch.setattr("builtins.input", _raise_eof)

    cli.main(["rm", run.run_id])

    conn = store.connect()
    assert store.get_run(conn, run.run_id) is not None
    conn.close()
    assert "Aborted." in capsys.readouterr().out


def test_main_prints_clean_error_instead_of_raw_traceback(monkeypatch, capsys):
    def _boom(_conn, project=None):
        raise RuntimeError("simulated store failure")

    monkeypatch.setattr(store, "list_runs", _boom)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["list"])
    assert exc_info.value.code != 0
    err = capsys.readouterr().err
    assert "Error: simulated store failure" in err
    assert "Traceback" not in err
