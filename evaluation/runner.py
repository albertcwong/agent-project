"""Runs evaluation cases and collects results."""

import logging
import sys
import time
import uuid
from pathlib import Path

# Ensure agent-project root is on path when run as script
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import yaml

from agent.loop import run_agent_loop
from agent.prompts import get_system_prompt

logger = logging.getLogger(__name__)
CASES_DIR = Path(__file__).parent / "cases"
FIXTURES_DIR = Path(__file__).parent / "mocks" / "fixtures"


async def run_evaluation(
    cases_path: str | Path | None = None,
    case_filter: str | None = None,
    use_llm_judge: bool = False,
    model: str | None = None,
    provider: str = "openai",
    verbose: bool = False,
    trace_failures: bool = True,
    persist: bool = True,
) -> list[dict]:
    cases_path = cases_path or CASES_DIR
    if isinstance(cases_path, str):
        cases_path = Path(cases_path)

    cases = []
    if cases_path.is_file():
        cases = yaml.safe_load(cases_path.read_text()) or []
    else:
        for f in sorted(cases_path.glob("*.yaml")):
            cases.extend(yaml.safe_load(f.read_text()) or [])

    if case_filter:
        cases = [c for c in cases if case_filter in c.get("id", "")]
    if not cases:
        return []

    run_id = str(uuid.uuid4())[:8]
    start_time = time.monotonic()

    from evaluation.mocks import MockMCPPool
    from evaluation.report import format_single_result
    from evaluation.evaluators import (
        evaluate_tool_sequence,
        evaluate_query,
        evaluate_answer_quality,
        evaluate_efficiency,
    )

    mock_configs = [{"id": "mock", "url": "http://mock"}]
    client = None
    if use_llm_judge:
        import os
        from openai import AsyncOpenAI
        base_url = os.environ.get("LLM_PROXY_URL", "http://localhost:8000").rstrip("/")
        client = AsyncOpenAI(base_url=f"{base_url}/v1", api_key=os.environ.get("LLM_PROXY_API_KEY", "dummy"))

    if persist:
        from evaluation.persistence import start_run
        start_run(run_id=run_id, model=model, provider=provider, system_prompt=get_system_prompt(""))

    results = []
    total = len(cases)
    try:
        for i, case in enumerate(cases):
            case_id = case.get("id", "?")
            print(f"Running case {i + 1}/{total}: {case_id}...", flush=True)
            conv_state = case.get("conversation_state")
            conv_state = dict(conv_state) if conv_state else None
            mock_pool = MockMCPPool(
                FIXTURES_DIR,
                scenario=case.get("scenario"),
                conversation_state=conv_state,
            )
            pool_dict = mock_pool.get_pool_dict()

            start = time.monotonic()
            try:
                answer, sources, tool_calls, awaiting, state, trace = await run_agent_loop(
                    question=case["question"],
                    system_prompt=get_system_prompt(case["question"]),
                    server_configs=mock_configs,
                    model=model,
                    provider=provider,
                    history=case.get("history"),
                    conversation_state=conv_state,
                    attachments=case.get("attachments"),
                    _pool_override=pool_dict,
                    _trace=trace_failures or verbose,
                )
            except Exception as e:
                r = {
                    "id": case.get("id", "?"),
                    "category": case.get("category", ""),
                    "pass": False,
                    "error": str(e),
                    "evaluations": {},
                    "answer_preview": "",
                    "elapsed_seconds": round(time.monotonic() - start, 2),
                    "trace": None,
                }
                results.append(r)
                if persist:
                    from evaluation.persistence import save_case_result
                    save_case_result(run_id, r)
                print(format_single_result(r, verbose), flush=True)
                continue

            elapsed = round(time.monotonic() - start, 2)
            expected = case.get("expected") or {}
            actual_tools = mock_pool.get_tool_sequence()
            logged_tools = [tc.get("name") for tc in tool_calls]
            BUILTIN_TOOLS = {"execute_python"}
            pool_tools = [t for t in actual_tools if t not in BUILTIN_TOOLS]
            logged_mcp = [t for t in logged_tools if t not in BUILTIN_TOOLS]
            if pool_tools != logged_mcp:
                logger.warning(
                    "Tool sequence mismatch for case %s: pool=%s loop=%s",
                    case_id, pool_tools, logged_mcp,
                )

            # Use logged_tools for required check (write tools like publish return early before mock is called)
            tool_seq = evaluate_tool_sequence(
                logged_tools,
                required=expected.get("tools_required"),
                required_any=expected.get("tools_required_any"),
                prohibited=expected.get("tools_prohibited"),
            )
            query_eval = evaluate_query(
                tool_calls,
                must_contain=expected.get("query_must_contain"),
            )
            answer_eval = await evaluate_answer_quality(
                case["question"],
                answer,
                must_contain=expected.get("answer_must_contain"),
                must_contain_any=expected.get("answer_must_contain_any"),
                must_not_contain=expected.get("answer_must_not_contain"),
                client=client if use_llm_judge else None,
            )
            eff_eval = evaluate_efficiency(
                tool_calls,
                max_iterations=expected.get("max_iterations"),
                min_tool_calls=expected.get("min_tool_calls"),
            )

            evals = {
                "tool_sequence": tool_seq,
                "query": query_eval,
                "answer": answer_eval,
                "efficiency": eff_eval,
            }

            all_pass = all(
                e.get("pass", True) for e in evals.values() if isinstance(e, dict)
            )

            if (trace_failures or verbose) and trace and not all_pass:
                print("\n--- TRACE (failed case) ---", flush=True)
                print(trace.format(), flush=True)
                print("--- END TRACE ---\n", flush=True)
            elif verbose and trace:
                print("\n--- TRACE ---", flush=True)
                print(trace.format(), flush=True)
                print("--- END TRACE ---\n", flush=True)

            r = {
                "id": case.get("id", "?"),
                "category": case.get("category", ""),
                "pass": all_pass,
                "evaluations": evals,
                "answer_preview": (answer or "")[:200],
                "tool_calls": logged_tools,
                "elapsed_seconds": elapsed,
                "trace": trace.format() if trace and not all_pass else None,
            }
            results.append(r)
            if persist:
                from evaluation.persistence import save_case_result
                save_case_result(run_id, r)
            print(format_single_result(r, verbose), flush=True)

        total_seconds = time.monotonic() - start_time
        if persist:
            from evaluation.persistence import complete_run
            complete_run(run_id, total_seconds, results)
    except Exception as e:
        total_seconds = time.monotonic() - start_time
        if persist:
            from evaluation.persistence import fail_run
            fail_run(run_id, total_seconds, str(e))
        raise

    return results


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Run agent evaluation cases")
    parser.add_argument("--cases", type=str, default=None, help="Path to cases file or directory")
    parser.add_argument("--filter", "-f", type=str, default=None, help="Run only cases whose id contains this string")
    parser.add_argument("--model", "-m", type=str, default=None, help="LLM model to use")
    parser.add_argument("--provider", "-p", type=str, default="openai")
    parser.add_argument("--llm-judge", action="store_true", help="Enable LLM-as-judge scoring")
    parser.add_argument("--no-persist", action="store_true", help="Skip persisting results to SQLite")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from evaluation.report import format_summary

    results = asyncio.run(run_evaluation(
        cases_path=Path(args.cases) if args.cases else None,
        case_filter=args.filter,
        use_llm_judge=args.llm_judge,
        model=args.model,
        provider=args.provider,
        verbose=args.verbose,
        persist=not args.no_persist,
    ))
    print(format_summary(results), flush=True)
    sys.exit(0 if all(r.get("pass") for r in results) else 1)
