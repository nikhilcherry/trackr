import pytest

import trackr
from trackr import store
from trackr.ui.app import create_app

fastapi_testclient = pytest.importorskip("starlette.testclient")


@pytest.fixture(autouse=True)
def isolated_trackr_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKR_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def client():
    return fastapi_testclient.TestClient(create_app())


def _make_run_with_artifact(tmp_path):
    run = trackr.init(project="p1", name="r1")
    src = tmp_path / "legit.txt"
    src.write_text("legit content")
    run.log_artifact(str(src))
    run.finish()
    return run


def test_artifact_endpoint_serves_legitimate_files(client, tmp_path):
    run = _make_run_with_artifact(tmp_path)
    resp = client.get(f"/api/artifacts/{run.run_id}/legit.txt")
    assert resp.status_code == 200
    assert resp.content == b"legit content"


def test_artifact_endpoint_missing_file_404s(client, tmp_path):
    run = _make_run_with_artifact(tmp_path)
    resp = client.get(f"/api/artifacts/{run.run_id}/nope.txt")
    assert resp.status_code == 404


def test_artifact_endpoint_rejects_path_traversal_via_run_id(client, tmp_path):
    # The containment check was previously computed from
    # (get_artifacts_dir() / run_id).resolve() -- so a run_id of ".."
    # (URL-encoded as %2e%2e, a single path segment with no literal "/",
    # so it passes routing) moved the boundary itself up to TRACKR_DIR
    # before the check ran, leaking any file there, including trackr.db.
    _make_run_with_artifact(tmp_path)
    secret = store.get_trackr_dir() / "super_secret.txt"
    secret.write_text("TOP SECRET DATA THAT SHOULD NEVER LEAK")

    for traversal in ("%2e%2e", "..", "%2e%2e%2f%2e%2e"):
        resp = client.get(f"/api/artifacts/{traversal}/super_secret.txt", follow_redirects=False)
        assert resp.status_code == 404, f"traversal {traversal!r} was not blocked"

    resp = client.get("/api/artifacts/%2e%2e/trackr.db", follow_redirects=False)
    assert resp.status_code == 404


def test_artifact_endpoint_rejects_path_traversal_via_filename(client, tmp_path):
    run = _make_run_with_artifact(tmp_path)
    secret = store.get_trackr_dir() / "super_secret.txt"
    secret.write_text("TOP SECRET DATA THAT SHOULD NEVER LEAK")

    resp = client.get(f"/api/artifacts/{run.run_id}/%2e%2e/super_secret.txt", follow_redirects=False)
    assert resp.status_code == 404
