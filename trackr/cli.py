"""trackr command-line interface: list, compare, ui, doctor."""
from __future__ import annotations

import argparse
import json
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

    p_ui = sub.add_parser("ui", help="launch web UI")
    p_ui.add_argument("--host", default="127.0.0.1")
    p_ui.add_argument("--port", type=int, default=8000)
    p_ui.set_defaults(func=cmd_ui)

    p_doctor = sub.add_parser("doctor", help="mark stale running runs as crashed")
    p_doctor.add_argument("--stale-minutes", type=int, default=10)
    p_doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
