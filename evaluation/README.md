# Tableau Agent Evaluation Harness

Custom evaluation harness for measuring agent correctness and efficiency. Run after every prompt or loop change to catch regressions.

## Quick Start

```bash
# From agent-project root; requires LLM proxy running (LLM_PROXY_URL)
uv run python evaluation/run_eval.py
# Or: uv run python evaluation/runner.py

# Run a single case (filter by id)
uv run python evaluation/run_eval.py --filter sales_by_region
uv run python evaluation/runner.py -f list_datasources

# Specify model (non-interactive)
uv run python evaluation/run_eval.py --model gpt-4o-mini

# Single case file, verbose
uv run python evaluation/run_eval.py --cases evaluation/cases/query_basic.yaml -v

# With LLM-as-judge for answer quality (adds cost)
uv run python evaluation/run_eval.py --llm-judge
```

Exit code 1 on any failure (for CI gates).

## Structure

```
evaluation/
├── cases/
│   ├── query_basic.yaml      # sales_by_region, top_customers, sales_with_filter
│   ├── query_advanced.yaml   # forecast_sales (Python analytics)
│   ├── discovery.yaml        # list_datasources, metadata_before_query
│   ├── download_inspect.yaml # download_workbook, inspect_datasource
│   ├── publish.yaml          # publish_workbook (with attachments)
│   ├── error_recovery.yaml   # no_datasources_empty, field_not_found_recovery
│   ├── multi_turn.yaml       # follow_up_breakdown
│   └── edge_cases.yaml       # ambiguous_question, ambiguous_datasource
├── mocks/           # MockMCPPool + fixtures (supports scenario: for conditional responses)
├── evaluators/      # tool_sequence, query_correctness, answer_quality, efficiency
├── runner.py        # Runs cases, collects results
├── report.py        # Pass/fail summary
└── run_eval.py      # CLI entry point
```

## Test Case Format

```yaml
- id: "sales_by_region"
  question: "Show me total sales by region"
  category: "query"
  scenario: "field_not_found_recovery"  # optional: mock behavior variant
  expected:
    tools_required: ["get-datasource-metadata", "query-datasource"]
    tools_required_any: [["list-datasources", "search-content"]]  # at least one
    tools_prohibited: ["publish-workbook"]
    query_must_contain:
      fields: ["Region"]
      aggregation: "SUM"
      filters: ["East"]  # optional: assert filter applied
    answer_must_contain: ["region", "sales"]
    answer_must_contain_any: ["no data", "empty"]  # at least one
    answer_must_not_contain: ["I cannot", "reconnect"]
    max_iterations: 8
    min_tool_calls: 3  # optional: for recovery cases
```

## Prerequisites

- LLM proxy running (default: `http://localhost:8000`)
- `LLM_PROXY_URL` and `LLM_PROXY_API_KEY` env vars if non-default

## CI Integration

```yaml
# .github/workflows/eval.yml
- run: uv run python evaluation/run_eval.py
  env:
    LLM_PROXY_URL: ${{ secrets.LLM_PROXY_URL }}
```
