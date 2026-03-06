"""Answer quality evaluator — keyword checks and optional LLM-as-judge."""


async def evaluate_answer_quality(
    question: str,
    answer: str,
    must_contain: list[str] | None = None,
    must_contain_any: list[str] | None = None,
    must_not_contain: list[str] | None = None,
    client=None,
) -> dict:
    results = {"pass": True, "errors": [], "score": None}
    answer_lower = (answer or "").lower()

    if must_contain:
        for term in must_contain:
            if term.lower() not in answer_lower:
                results["pass"] = False
                results["errors"].append(f"Answer missing expected term: '{term}'")

    if must_contain_any:
        found = any(t.lower() in answer_lower for t in must_contain_any)
        if not found:
            results["pass"] = False
            results["errors"].append(f"Answer missing any of: {must_contain_any}")

    if must_not_contain:
        for term in must_not_contain:
            if term.lower() in answer_lower:
                results["pass"] = False
                results["errors"].append(f"Answer contains prohibited term: '{term}'")

    if client and not results["errors"]:
        try:
            judge_prompt = f"""Rate this answer on a scale of 1-5:
Question: {question}
Answer: {answer}

Criteria:
- Does it answer the question directly?
- Is it well-structured?
- Does it avoid hallucination or refusal?

Return JSON only: {{"score": N, "reasoning": "..."}}"""
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": judge_prompt}],
                max_tokens=200,
            )
            content = (resp.choices[0].message.content or "").strip()
            if content:
                import json
                for block in content.split("```"):
                    block = block.strip().strip("json").strip()
                    if block.startswith("{"):
                        try:
                            d = json.loads(block)
                            results["score"] = d.get("score")
                            results["reasoning"] = d.get("reasoning", "")
                            if isinstance(results["score"], (int, float)) and results["score"] < 3:
                                results["pass"] = False
                                results["errors"].append(f"LLM judge score {results['score']} < 3")
                        except json.JSONDecodeError:
                            pass
                        break
        except Exception:
            pass

    return results
