"""Tool sequence evaluator — deterministic, no LLM needed."""


def evaluate_tool_sequence(
    actual_tools: list[str],
    required: list[str] | None = None,
    required_any: list[list[str]] | None = None,
    prohibited: list[str] | None = None,
) -> dict:
    results = {"pass": True, "errors": []}

    if required:
        for tool in required:
            if tool not in actual_tools:
                results["pass"] = False
                results["errors"].append(f"Required tool '{tool}' not called")

    if required_any:
        for group in required_any:
            if not any(t in actual_tools for t in group):
                results["pass"] = False
                results["errors"].append(f"Required at least one of {group}")

    if prohibited:
        for tool in prohibited:
            if tool in actual_tools:
                results["pass"] = False
                results["errors"].append(f"Prohibited tool '{tool}' was called")

    return results
