#!/usr/bin/env python3
"""CLI entry point for running the evaluation harness."""

import argparse
import asyncio
import sys
from pathlib import Path

# Unbuffered stdout so progress appears immediately
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

# Add agent-project root to path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))


async def main():
    parser = argparse.ArgumentParser(description="Run Tableau agent evaluation harness")
    parser.add_argument("--cases", type=Path, default=None, help="Cases file or directory")
    parser.add_argument("--filter", "-f", type=str, default=None, help="Run only cases whose id contains this string")
    parser.add_argument("--model", "-m", type=str, default=None, help="LLM model (e.g. gpt-4o, gpt-4o-mini). Default: DEFAULT_MODEL env or gpt-4")
    parser.add_argument("--provider", "-p", type=str, default="openai", help="LLM provider (default: openai)")
    parser.add_argument("--llm-judge", action="store_true", help="Use LLM-as-judge for answer quality")
    parser.add_argument("--no-persist", action="store_true", help="Skip persisting results to SQLite")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    from evaluation.runner import run_evaluation
    from evaluation.report import format_summary

    print("Loading cases...", flush=True)
    if args.model:
        print(f"Model: {args.model} (provider: {args.provider})", flush=True)
    results = await run_evaluation(
        cases_path=args.cases,
        case_filter=args.filter,
        use_llm_judge=args.llm_judge,
        model=args.model,
        provider=args.provider,
        verbose=args.verbose,
        persist=not args.no_persist,
    )
    print(format_summary(results), flush=True)
    sys.exit(0 if all(r.get("pass") for r in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
