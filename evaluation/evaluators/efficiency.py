"""Efficiency evaluator — iteration count, redundant calls."""


def evaluate_efficiency(
    tool_calls: list[dict],
    max_iterations: int | None = None,
    min_tool_calls: int | None = None,
) -> dict:
    results = {"pass": True, "errors": [], "iterations": len(tool_calls)}

    if min_tool_calls is not None and len(tool_calls) < min_tool_calls:
        results["pass"] = False
        results["errors"].append(
            f"Too few tool calls: {len(tool_calls)} < {min_tool_calls}"
        )
    if max_iterations is not None and len(tool_calls) > max_iterations:
        results["pass"] = False
        results["errors"].append(
            f"Exceeded max iterations: {len(tool_calls)} > {max_iterations}"
        )

    # Redundant calls: same tool + same key args
    seen: set[tuple] = set()
    for tc in tool_calls:
        name = tc.get("name", "")
        args = tc.get("arguments") or {}
        key = (name, _args_key(args))
        if key in seen:
            results["pass"] = False
            results["errors"].append(f"Redundant call: {name} with same args")
        seen.add(key)

    return results


def _args_key(args: dict) -> str:
    """Stable key for args (ignore order)."""
    import json
    if isinstance(args, dict):
        return json.dumps({k: v for k, v in sorted(args.items())}, sort_keys=True)
    return str(args)
