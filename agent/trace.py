"""Execution trace for agent loop debugging."""

from dataclasses import dataclass, field


@dataclass
class LoopTrace:
    """Captures the full execution trace of an agent loop run."""

    intent: str = ""
    system_prompt_length: int = 0
    iterations: list[dict] = field(default_factory=list)
    termination_reason: str = ""
    total_tool_calls: int = 0

    def add_iteration(self, iteration_num: int) -> None:
        self.iterations.append({
            "iteration": iteration_num,
            "llm_response": None,
            "tool_calls": [],
            "tool_results": [],
        })

    def set_llm_response(
        self,
        content: str,
        finish_reason: str | None,
        tool_call_names: list[str],
    ) -> None:
        if self.iterations:
            self.iterations[-1]["llm_response"] = {
                "content_preview": (content or "")[:300],
                "finish_reason": finish_reason,
                "tool_calls_requested": tool_call_names,
            }

    def add_tool_call(
        self,
        name: str,
        args: dict,
        result_preview: str,
        was_redundant: bool = False,
    ) -> None:
        if self.iterations:
            self.iterations[-1]["tool_calls"].append({
                "name": name,
                "args_preview": {k: str(v)[:100] for k, v in args.items()},
                "result_preview": result_preview[:300],
                "was_redundant": was_redundant,
            })
            self.total_tool_calls += 1

    def format(self) -> str:
        lines = [
            f"Intent: {self.intent}",
            f"System prompt length: {self.system_prompt_length}",
            f"Iterations: {len(self.iterations)}",
            f"Total tool calls: {self.total_tool_calls}",
            f"Termination: {self.termination_reason}",
            "",
        ]
        for it in self.iterations:
            lines.append(f"--- Iteration {it['iteration']} ---")
            llm = it.get("llm_response") or {}
            lines.append(f"  LLM finish_reason: {llm.get('finish_reason')}")
            lines.append(f"  LLM content: {llm.get('content_preview', '(none)')}")
            lines.append(f"  LLM tool calls: {llm.get('tool_calls_requested', [])}")
            for tc in it.get("tool_calls", []):
                redundant = " [REDUNDANT - SKIPPED]" if tc["was_redundant"] else ""
                lines.append(f"  Tool: {tc['name']}{redundant}")
                lines.append(f"    Args: {tc['args_preview']}")
                lines.append(f"    Result: {tc['result_preview']}")
            lines.append("")
        return "\n".join(lines)
