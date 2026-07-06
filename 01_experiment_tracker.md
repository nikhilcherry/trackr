# Claude Code Task Handout — "trackr": Local-First ML Experiment Tracker

You are building **trackr**, a lightweight, local-first experiment tracker — a
minimal alternative to W&B/MLflow. It must work fully offline, store everything
in a single SQLite file, and ship with a small web UI for comparing runs.

This is a standalone, reusable tool. Do NOT hardcode anything specific to any
one project. First consumer will be an exoplanet ML pipeline (PyTorch), but
the API must be framework-agnostic.

## Project structure

```
trackr/
├── pyproject.toml            # installable package: pip install -e .
├── README.md
├── trackr/
│   ├── __init__.py           # public API: trackr.init(), run.log(), run.finish()
│   ├── core.py               # Run object, SQLite persistence
│   ├── store.py              # schema + queries (runs, metrics, params, artifacts)
│   ├── cli.py                # `trackr ui`, `trackr list`, `trackr compare`
│   └── ui/                   # small web UI (FastAPI + vanilla JS or Streamlit — your choice, keep deps light)
└── tests/
    └── test_core.py
```

## Core API (must match exactly)

```python
import trackr

run = trackr.init(project="arvyo", name="cnn-baseline", config={"lr": 3e-4, "epochs": 20})
for step in range(100):
    run.log({"loss": 0.5, "val_acc": 0.81}, step=step)
run.log_artifact("confusion_matrix.png")   # copies file into run folder
run.finish(status="completed")
```

## Requirements

1. **Storage**: one SQLite DB at `~/.trackr/trackr.db` (overridable via env var
   `TRACKR_DIR`). Artifacts copied to `~/.trackr/artifacts/<run_id>/`.
2. **Schema**: runs (id, project, name, config JSON, status, start/end time,
   git commit hash if repo detected), metrics (run_id, key, value, step,
   timestamp), artifacts (run_id, path, original name).
3. **Crash safety**: if the process dies, run status stays "running"; a
   `trackr doctor` command marks stale runs as "crashed".
4. **CLI**:
   - `trackr list [--project X]` — table of runs with final metric values
   - `trackr compare RUN1 RUN2 ...` — side-by-side config diff + final metrics
   - `trackr ui` — launch web UI on localhost
5. **Web UI (v1 scope, keep it simple)**: runs table with filter by project,
   click a run → metric line charts (all logged keys vs step), config viewer,
   artifact list with image preview. No auth, no multi-user.
6. **Zero required external services.** Dependencies: keep to fastapi/uvicorn
   (or streamlit), and stdlib sqlite3. No pandas requirement in core.

## Verification (do not skip)

- Write a demo script `examples/fake_training.py` that simulates 3 runs with
  noisy loss curves and different configs; run it, then confirm `trackr list`
  and the UI display all 3 correctly.
- Kill a run mid-way (simulate), confirm `trackr doctor` flags it.
- `pytest` passes.

## Non-goals for v1

Remote sync, teams, sweeps, GPU monitoring. Leave TODO stubs only.
