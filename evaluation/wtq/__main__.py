"""CLI entry point for WikiTableQuestions benchmark."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add agent-project root to path when run as module
_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from evaluation.wtq.loader import load_wtq_dataset
from evaluation.wtq.runner import run_wtq_eval, verify_adapter


def main():
    parser = argparse.ArgumentParser(description="Run WikiTableQuestions benchmark")
    parser.add_argument("data_dir", type=Path, help="Path to WTQ dataset (WikiTableQuestions repo)")
    parser.add_argument("--model", "-m", type=str, default=None)
    parser.add_argument("--provider", "-p", type=str, default="openai")
    parser.add_argument("--split", choices=["test", "train"], default="test")
    parser.add_argument("--limit", "-n", type=int, default=None)
    parser.add_argument("--no-persist", action="store_true", help="Skip persisting results to SQLite")
    parser.add_argument("--resume", type=str, default=None, help="Resume interrupted WTQ run by run_id")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--verify-only", action="store_true", help="Validate adapter on first table and exit")
    args = parser.parse_args()

    if args.verify_only:
        questions, tables = load_wtq_dataset(args.data_dir, split=args.split, limit=1)
        if not questions or not tables:
            print("No questions/tables loaded.")
            sys.exit(1)
        q = questions[0]
        ds_id = q.get("datasource_id", "")
        table = tables.get(ds_id)
        if not table:
            print(f"Table not found: {ds_id}")
            sys.exit(1)
        out = asyncio.run(verify_adapter(ds_id, table))
        print("Adapter verification:")
        print(f"  Datasources: {out['datasources']}")
        print(f"  Metadata: {out['metadata']}")
        rows = out.get("sample_rows", [])
        print(f"  Sample rows ({len(rows) if isinstance(rows, list) else 'N/A'}): {json.dumps(rows[:3], indent=2) if isinstance(rows, list) else rows}")
        sys.exit(0)

    results = asyncio.run(
        run_wtq_eval(
            data_dir=args.data_dir,
            model=args.model,
            provider=args.provider,
            split=args.split,
            limit=args.limit,
            verbose=args.verbose,
            persist=not args.no_persist,
            resume_run_id=args.resume,
        )
    )

    passed = sum(1 for r in results if r.get("pass"))
    sys.exit(0 if (results and passed == len(results)) else 1)


if __name__ == "__main__":
    main()
