"""trackr command-line interface: list, compare, rm, ui, doctor."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time

from . import store


def _fmt_duration(start, end) -> str:
    if end is None:
        end = time.time()
    secs = int(end - start)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m}m"
    if m:
        return f"{m}m{s}s"
    return f"{s}s"


def _fmt_metric(v) -> str:
    if v is None:
        return "-"
    return f"{v:.4g}"


def _print_table(headers, rows) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))


def cmd_list(args) -> None:
    store.init_schema()
    conn = store.connect()
    try:
        runs = store.list_runs(conn, project=args.project)
        if not runs:
            print("No runs found.")
            return
        headers = ["id", "project", "name", "status", "duration", "metrics"]
        rows = []
        for r in runs:
            metrics = store.get_final_metrics(conn, r["id"])
            metrics_str = ", ".join(f"{k}={_fmt_metric(v)}" for k, v in sorted(metrics.items()))
            rows.append(
                [
                    r["id"],
                    r["project"],
                    r["name"],
                    r["status"],
                    _fmt_duration(r["start_time"], r["end_time"]),
                    metrics_str,
                ]
            )
        _print_table(headers, rows)
    finally:
        conn.close()


def cmd_compare(args) -> None:
    store.init_schema()
    conn = store.connect()
    try:
        runs = []
        for run_id in args.run_ids:
            r = store.get_run(conn, run_id)
            if r is None:
                print(f"error: run not found: {run_id}", file=sys.stderr)
                sys.exit(1)
            r["config"] = json.loads(r["config"])
            r["final_metrics"] = store.get_final_metrics(conn, run_id)
            runs.append(r)

        headers = ["param"] + [r["id"] for r in runs]

        print("Config diff:")
        all_keys = sorted({k for r in runs for k in r["config"]})
        rows = []
        for key in all_keys:
            values = [r["config"].get(key, "-") for r in runs]
            if len({str(v) for v in values}) > 1:
                rows.append([key] + [str(v) for v in values])
        if rows:
            _print_table(headers, rows)
        else:
            print("  (no config differences)")

        print("\nFinal metrics:")
        metric_keys = sorted({k for r in runs for k in r["final_metrics"]})
        rows = []
        for key in metric_keys:
            rows.append([key] + [_fmt_metric(r["final_metrics"].get(key)) for r in runs])
        if rows:
            _print_table(headers, rows)
        else:
            print("  (no metrics logged)")
    finally:
        conn.close()


def cmd_rm(args) -> None:
    store.init_schema()
    conn = store.connect()
    try:
        runs = []
        missing = []
        for run_id in args.run_ids:
            r = store.get_run(conn, run_id)
            if r is None:
                missing.append(run_id)
            else:
                runs.append(r)

        for run_id in missing:
            print(f"error: run not found: {run_id}", file=sys.stderr)

        if not runs:
            sys.exit(1)

        if not args.yes:
            names = ", ".join(f"{r['id']} ({r['project']}/{r['name']})" for r in runs)
            try:
                reply = input(f"Delete {len(runs)} run(s): {names}? [y/N] ")
            except EOFError:
                # No stdin to read from (CI, cron, a piped/non-interactive
                # invocation without -y): treat like a "no" rather than
                # crashing with a raw traceback.
                reply = ""
            if reply.strip().lower() not in ("y", "yes"):
                print("Aborted.")
                return

        artifacts_dir = store.get_artifacts_dir()
        for r in runs:
            store.delete_run(conn, r["id"])
            run_artifacts_dir = artifacts_dir / r["id"]
            if run_artifacts_dir.exists():
                shutil.rmtree(run_artifacts_dir)
            print(f"Deleted {r['id']} ({r['project']}/{r['name']})")

        if missing:
            sys.exit(1)
    finally:
        conn.close()


def cmd_ui(args) -> None:
    import uvicorn

    from .ui.app import create_app

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)


def cmd_doctor(args) -> None:
    store.init_schema()
    conn = store.connect()
    try:
        stale_seconds = args.stale_minutes * 60
        crashed = store.mark_stale_as_crashed(conn, stale_seconds)
        if crashed:
            print(f"Marked {len(crashed)} stale run(s) as crashed:")
            for run_id in crashed:
                print(f"  - {run_id}")
        else:
            print("No stale runs found.")
    finally:
        conn.close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="trackr", description="Local-first ML experiment tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list runs")
    p_list.add_argument("--project", default=None)
    p_list.set_defaults(func=cmd_list)

    p_compare = sub.add_parser("compare", help="compare runs")
    p_compare.add_argument("run_ids", nargs="+")
    p_compare.set_defaults(func=cmd_compare)

    p_rm = sub.add_parser("rm", help="delete run(s) and their artifacts")
    p_rm.add_argument("run_ids", nargs="+")
    p_rm.add_argument("-y", "--yes", action="store_true", help="skip confirmation prompt")
    p_rm.set_defaults(func=cmd_rm)

    p_ui = sub.add_parser("ui", help="launch web UI")
    p_ui.add_argument("--host", default="127.0.0.1")
    p_ui.add_argument("--port", type=int, default=8000)
    p_ui.set_defaults(func=cmd_ui)

    p_doctor = sub.add_parser("doctor", help="mark stale running runs as crashed")
    p_doctor.add_argument("--stale-minutes", type=int, default=10)
    p_doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
