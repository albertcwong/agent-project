"""Generates pass/fail summary from evaluation results."""


def format_single_result(r: dict, verbose: bool = False) -> str:
    """Format one result for display."""
    status = "PASS" if r.get("pass") else "FAIL"
    sid = r.get("id", "?")
    elapsed = r.get("elapsed_seconds")
    header = f"  [{status}] {sid}" + (f" ({elapsed}s)" if elapsed is not None else "")
    lines = [header]
    if r.get("error"):
        lines.append(f"       Error: {r['error']}")
    elif not r.get("pass") and r.get("evaluations"):
        for name, ev in r["evaluations"].items():
            if isinstance(ev, dict) and not ev.get("pass", True):
                for err in ev.get("errors", []):
                    lines.append(f"       - {name}: {err}")
    if verbose:
        lines.append(f"       Tools: {r.get('tool_calls', [])}")
        lines.append(f"       Answer: {r.get('answer_preview', '')[:100]}...")
    return "\n".join(lines)


def format_summary(results: list[dict]) -> str:
    """Aggregate summary with failed cases list. For CI and end-of-run."""
    passed = sum(1 for r in results if r.get("pass"))
    total = len(results)
    failed = total - passed
    lines = [f"\n{'='*60}", f"Results: {passed}/{total} passed, {failed} failed"]
    total_sec = sum(r.get("elapsed_seconds", 0) for r in results)
    if total_sec:
        lines.append(f"Total time: {total_sec:.1f}s")
    if failed:
        lines.append("\nFailed cases:")
        for r in results:
            if not r.get("pass"):
                errors = []
                for name, ev in r.get("evaluations", {}).items():
                    if isinstance(ev, dict) and not ev.get("pass", True):
                        errors.extend(ev.get("errors", []))
                msg = "; ".join(errors) if errors else r.get("error", "unknown")
                lines.append(f"  - {r.get('id', '?')}: {msg}")
    lines.append("")
    return "\n".join(lines)


def print_report(results: list[dict], verbose: bool = False, summary_only: bool = False) -> str:
    passed = sum(1 for r in results if r.get("pass"))
    total = len(results)
    if summary_only:
        return format_summary(results)
    lines = [f"\n=== Evaluation Report: {passed}/{total} passed ===\n"]
    for r in results:
        lines.append(format_single_result(r, verbose))
    return "\n".join(lines)
