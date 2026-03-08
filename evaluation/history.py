#!/usr/bin/env python3
"""CLI for querying evaluation history."""

import argparse
import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from evaluation.persistence import (
    get_case_history,
    get_flaky_cases,
    get_last_failure_details,
    get_pass_rate_trend,
    get_regression_candidates,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Query evaluation history")
    sub = parser.add_subparsers(dest="command", required=True)

    h = sub.add_parser("case", help="History for a specific case")
    h.add_argument("case_id", help="Case ID to look up")
    h.add_argument("--limit", type=int, default=10)

    r = sub.add_parser("regressions", help="Recently broken cases")
    r.add_argument("--last", type=int, default=5, help="Number of recent runs to consider")

    t = sub.add_parser("trend", help="Pass rate over time")
    t.add_argument("--limit", type=int, default=20)

    lf = sub.add_parser("last-failure", help="Most recent failure(s) with full details")
    lf.add_argument("--limit", type=int, default=1)

    sub.add_parser("flaky", help="Cases with inconsistent results")

    args = parser.parse_args()

    if args.command == "case":
        for row in get_case_history(args.case_id, args.limit):
            status = "PASS" if row["passed"] else "FAIL"
            print(f"  {row['timestamp'][:16]}  {status}  model={row['model']}  "
                  f"prompt={row['prompt_version']}  commit={row['git_commit']}")
    elif args.command == "flaky":
        for row in get_flaky_cases():
            print(f"  {row['case_id']}: {row['pass_rate']}% "
                  f"({row['passes']}/{row['total_runs']})")
    elif args.command == "regressions":
        for row in get_regression_candidates(args.last):
            print(f"  {row['case_id']}: {row['recent_failures']} recent failures, "
                  f"{row['older_passes']} older passes")
    elif args.command == "trend":
        for row in get_pass_rate_trend(args.limit):
            print(f"  {row['timestamp'][:19]}  {row['pass_rate']}%  "
                  f"{row['passed']}/{row['total_cases']}  model={row['model']}  "
                  f"commit={row['git_commit']}")
    elif args.command == "last-failure":
        for row in get_last_failure_details(args.limit):
            print(f"  case_id: {row['case_id']}")
            print(f"  run_id: {row['run_id']}  timestamp: {row['timestamp']}")
            print(f"  model: {row['model']}  commit: {row['git_commit']}")
            print(f"  elapsed: {row['elapsed_seconds']}s")
            if row.get("error"):
                print(f"  error: {row['error']}")
            if row.get("answer_preview"):
                print(f"  answer_preview: {row['answer_preview'][:200]}...")
            if row.get("tool_sequence"):
                tools = json.loads(row["tool_sequence"]) if isinstance(row["tool_sequence"], str) else row["tool_sequence"]
                print(f"  tools: {tools}")
            if row.get("evaluations"):
                ev = json.loads(row["evaluations"]) if isinstance(row["evaluations"], str) else row["evaluations"]
                for k, v in (ev or {}).items():
                    if isinstance(v, dict) and not v.get("pass", True):
                        print(f"  {k}: {v.get('errors', v)}")
            if row.get("trace"):
                print("  --- trace ---")
                for line in row["trace"].split("\n"):
                    print(f"    {line}")
            print()


if __name__ == "__main__":
    main()
