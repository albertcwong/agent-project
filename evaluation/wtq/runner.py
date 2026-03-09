"""WTQ evaluation runner."""

import json
import re
import time
import uuid
from pathlib import Path

from agent.loop import run_agent_loop
from agent.prompts import get_system_prompt

from evaluation.wtq.adapter import WTQMCPAdapter, WTQTable
from evaluation.wtq.loader import load_wtq_dataset


async def verify_adapter(ds_id: str, table: WTQTable) -> dict:
    """Confirm the adapter returns expected data for basic queries."""
    adapter = WTQMCPAdapter({ds_id: table})
    pool = adapter.get_pool_dict()

    ds_list = await pool["call_tool"](ds_id, "list-datasources", {})
    meta = await pool["call_tool"](ds_id, "get-datasource-metadata", {"datasourceId": ds_id})
    rows_resp = await pool["call_tool"](
        ds_id,
        "query-datasource",
        {"datasourceId": ds_id, "query": {"fields": [{"fieldCaption": h} for h in table.headers[:3]]}},
    )

    out = {"datasources": ds_list, "metadata": meta}
    try:
        parsed = json.loads(rows_resp)
        out["sample_rows"] = parsed.get("data") or parsed.get("rows") or parsed
    except json.JSONDecodeError:
        out["sample_rows"] = rows_resp[:500]
    return out


def _normalize_answer(s: str) -> str:
    """Normalize an answer string for comparison."""
    s = s.lower().strip()
    s = s.replace("\u2013", "-").replace("\u2014", "-")  # en-dash, em-dash
    s = s.replace(",", "").replace("$", "").replace("%", "")
    s = s.replace(" to ", "-").replace(" through ", "-")
    for prefix in ("the ", "a ", "an "):
        if s.startswith(prefix):
            s = s[len(prefix) :]
    return s.strip()


def _answers_match(agent_answer: str, gold_answer: str) -> dict:
    """
    Check if agent answer contains the gold answer value(s).
    WTQ gold answers can be single values or pipe-separated lists.
    """
    result = {"pass": False, "errors": [], "match_details": ""}

    gold_values = [v.strip() for v in gold_answer.split("|") if v.strip()]
    if not gold_values:
        result["errors"].append("Empty gold answer")
        return result

    agent_lower = _normalize_answer(agent_answer)
    matched = 0

    for gold_val in gold_values:
        normalized_gold = _normalize_answer(gold_val)
        if normalized_gold in agent_lower:
            matched += 1
            continue

        try:
            gold_num = float(normalized_gold)
            numbers = re.findall(r"[\d]+\.?\d*", agent_lower)
            if any(abs(float(n) - gold_num) < 0.1 for n in numbers if n):
                matched += 1
                continue
        except ValueError:
            pass

    match_rate = matched / len(gold_values)
    result["pass"] = match_rate >= 0.5
    result["match_rate"] = match_rate
    result["match_details"] = f"{matched}/{len(gold_values)} gold values found"

    if not result["pass"]:
        result["errors"].append(
            f"Gold: {gold_answer} | Agent answer did not contain expected values"
        )

    return result


async def run_wtq_eval(
    data_dir: Path,
    model: str | None = None,
    provider: str = "openai",
    split: str = "test",
    limit: int | None = None,
    verbose: bool = False,
    persist: bool = True,
    resume_run_id: str | None = None,
) -> list[dict]:
    if resume_run_id and not persist:
        raise ValueError("--resume requires persistence; do not use --no-persist")

    questions, tables = load_wtq_dataset(data_dir, split=split, limit=limit)

    if not questions:
        print("No questions loaded.")
        return []

    print(f"Loaded {len(questions)} questions across {len(tables)} tables")

    if resume_run_id:
        from evaluation.persistence import get_resumable_run, get_run_results
        run_meta = get_resumable_run(resume_run_id)
        if not run_meta:
            raise ValueError(
                f"Run {resume_run_id} not found or not resumable. "
                "Check with: sqlite3 evaluation/eval_results.db < evaluation/queries/wtq_in_progress_pass_rate.sql"
            )
        meta = json.loads(run_meta.get("metadata") or "{}")
        if meta.get("eval_type") != "wtq":
            raise ValueError(f"Run {resume_run_id} is not a WTQ run (eval_type={meta.get('eval_type')})")
        existing_results = get_run_results(resume_run_id)
        run_id = resume_run_id
        results = list(existing_results)
        completed_ids = {r["id"] for r in existing_results}
        questions = [q for q in questions if q["id"] not in completed_ids]
        if not questions:
            total_seconds = sum(r.get("elapsed_seconds") or 0 for r in results)
            from evaluation.persistence import complete_run
            complete_run(run_id, total_seconds, results)
            passed = sum(1 for r in results if r["pass"])
            print(f"Resume complete: all {len(results)} cases done ({passed} passed).", flush=True)
            return results
        print(f"Resuming run {run_id}: {len(existing_results)} done, {len(questions)} remaining.", flush=True)
    else:
        run_id = str(uuid.uuid4())[:8]
        results = []
        if persist:
            from evaluation.persistence import start_run
            start_run(
                run_id=run_id,
                model=model,
                provider=provider,
                system_prompt=get_system_prompt(""),
                metadata={"eval_type": "wtq", "split": split},
            )

    start_time = time.monotonic()
    try:
        for i, q in enumerate(questions):
            ds_id = q.get("datasource_id", "")
            table = tables.get(ds_id)
            if not table:
                r = {
                    "id": q["id"],
                    "category": "wtq",
                    "pass": False,
                    "error": f"Table not found: {ds_id}",
                    "elapsed_seconds": 0,
                    "answer_preview": "",
                    "tool_calls": [],
                    "evaluations": {},
                    "trace": None,
                }
                results.append(r)
                if persist:
                    from evaluation.persistence import save_case_result
                    save_case_result(run_id, r)
                continue

            print(f"Running {i+1}/{len(questions)}: {q['question'][:60]}...", flush=True)

            adapter = WTQMCPAdapter({ds_id: table})
            mock_configs = [{"id": ds_id, "url": f"mock://{ds_id}"}]

            case_start = time.monotonic()
            try:
                answer, sources, tool_calls, _, _, trace = await run_agent_loop(
                    question=q["question"],
                    system_prompt=get_system_prompt(q["question"]),
                    server_configs=mock_configs,
                    model=model,
                    provider=provider,
                    _pool_override=adapter.get_pool_dict(),
                    _trace=True,
                )
            except Exception as e:
                r = {
                    "id": q["id"],
                    "category": "wtq",
                    "pass": False,
                    "error": str(e),
                    "elapsed_seconds": round(time.monotonic() - case_start, 2),
                    "answer_preview": "",
                    "tool_calls": [],
                    "evaluations": {},
                    "trace": None,
                }
                results.append(r)
                if persist:
                    from evaluation.persistence import save_case_result
                    save_case_result(run_id, r)
                continue

            elapsed = round(time.monotonic() - case_start, 2)
            match = _answers_match(answer, q["answer"])
            tool_names = [tc.get("name") for tc in tool_calls]

            r = {
                "id": q["id"],
                "category": "wtq",
                "question": q["question"],
                "gold_answer": q["answer"],
                "pass": match["pass"],
                "match_rate": match.get("match_rate", 0),
                "match_details": match.get("match_details", ""),
                "errors": match.get("errors", []),
                "tool_calls": tool_names,
                "iterations": len(trace.iterations) if trace else None,
                "answer_preview": answer[:200],
                "elapsed_seconds": elapsed,
                "evaluations": {
                    "wtq": {
                        "match_rate": match.get("match_rate"),
                        "match_details": match.get("match_details"),
                        "errors": match.get("errors", []),
                    }
                },
                "error": "; ".join(match.get("errors", [])) if not match["pass"] else None,
                "trace": trace.format() if trace and not match["pass"] else None,
            }
            results.append(r)
            if persist:
                from evaluation.persistence import save_case_result
                save_case_result(run_id, r)

            status = "PASS" if r["pass"] else "FAIL"
            print(f"  [{status}] {match.get('match_details', '')}", flush=True)
            if verbose and not r["pass"]:
                print(f"    Gold: {q['answer']}")
                print(f"    Agent: {answer[:300]}")
                print(f"    Tools: {tool_names}")
                print(f"    Table columns: {table.headers}")
                for entry in adapter.call_log:
                    if entry["tool"] == "query-datasource":
                        qry = entry["args"].get("query", {})
                        print(f"    >> query-datasource: {qry}")
                if trace:
                    print("    --- Trace ---")
                    print(trace.format())

        total_seconds = sum(r.get("elapsed_seconds") or 0 for r in results)
        if persist:
            from evaluation.persistence import complete_run
            complete_run(run_id, total_seconds, results)
    except Exception as e:
        total_seconds = time.monotonic() - start_time
        if persist:
            from evaluation.persistence import fail_run
            fail_run(run_id, total_seconds, str(e))
        raise

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    if total > 0:
        print(f"\nWTQ Results: {passed}/{total} ({100*passed/total:.0f}%)")

    return results
