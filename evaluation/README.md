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

# Skip persisting to SQLite (e.g. CI or one-off runs)
uv run python evaluation/run_eval.py --no-persist
```

Exit code 1 on any failure (for CI gates).

## Structure

```
evaluation/
├── cases/
│   ├── query_basic.yaml        # sales_by_region, top_customers, sales_with_filter
│   ├── query_advanced.yaml     # multi_measure_comparison, yoy_growth, percentile, etc.
│   ├── multi_step.yaml         # find_then_query, inspect_then_query, iterative_drill_down
│   ├── ambiguity.yaml          # vague_metric, misspelled_entity, pronoun_resolution
│   ├── error_recovery.yaml    # wrong_datasource, auth_error, empty_result, etc.
│   ├── python_advanced.yaml   # forecast, anomaly, clustering, pareto
│   ├── cross_workflow.yaml    # analyze_then_publish, inspect_compare
│   ├── conversation_stress.yaml # five_turn, context_switch, rapid_topic_change
│   ├── discovery.yaml         # list_datasources, metadata_before_query
│   ├── download_inspect.yaml  # download_workbook, inspect_datasource
│   ├── publish.yaml           # publish_workbook (with attachments)
│   └── edge_cases.yaml        # sql_injection, long_question, zero_division, meta_question
├── mocks/           # MockMCPPool + fixtures (supports scenario: for conditional responses)
├── wtq/             # WikiTableQuestions benchmark (adapter, loader, runner)
├── evaluators/      # tool_sequence, query_correctness, answer_quality, efficiency
├── persistence.py   # SQLite storage for runs and case results
├── history.py       # CLI for querying evaluation history
├── runner.py        # Runs cases, collects results
├── report.py        # Pass/fail summary
├── run_eval.py      # CLI entry point
└── eval_results.db # SQLite DB (gitignored)
```

## Mock Scenarios

Cases can set `scenario:` to trigger conditional mock behavior:

| Scenario | Behavior |
|----------|----------|
| `auth_error_graceful` | First tool call returns 401 auth error |
| `empty_result_antarctica` | Query with Antarctica filter returns empty rows |
| `wrong_datasource_employee` | Only Sales Analytics (no employee fields) returned |
| `cross_datasource` | Sales Analytics + Regional Performance datasources |
| `inspect_compare_schemas` | Multiple datasources with different schemas |
| `misspelled_technology` | Query with "Tecnology" returns Technology data |
| `field_not_found_recovery` | First query with "Revenue" returns field error |
| `ambiguous_datasource` | Multiple sales-named datasources |

Run cases that work with existing mocks first; enable scenario-dependent cases incrementally.

## Persistence

Results are stored in `evaluation/eval_results.db` (SQLite). Each run records metadata (timestamp, model, provider, prompt version, git commit) and per-case results (pass/fail, evaluations, answer preview, tool sequence, trace for failures).

### Query History

```bash
# Pass rate over time (per run)
uv run python evaluation/history.py trend [--limit 20]

# Most recent failure(s) with full details (error, trace, evaluations)
uv run python evaluation/history.py last-failure [--limit 1]

# History for a specific case
uv run python evaluation/history.py case <case_id> [--limit 10]

# Cases that sometimes pass and sometimes fail
uv run python evaluation/history.py flaky

# Cases that passed earlier but failed in recent runs
uv run python evaluation/history.py regressions [--last 5]
```

| Command | Purpose |
|---------|---------|
| `trend` | Pass rate per run over time |
| `last-failure` | Most recent failed case(s) with error, trace, evaluations |
| `case <id>` | Pass/fail history for one case |
| `flaky` | Cases with inconsistent results (min 5 runs) |
| `regressions` | Recently broken cases (passed before, failing now) |

### Programmatic Access

```python
from evaluation.persistence import (
    get_pass_rate_trend,
    get_last_failure_details,
    get_case_history,
    get_flaky_cases,
    get_regression_candidates,
)
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

## WikiTableQuestions (WTQ)

Public benchmark for analytical question answering over flat tables. WTQ uses 22k questions over Wikipedia tables — structurally identical to Tableau datasources (no joins, single flat table per question).

### Setup

```bash
git clone https://github.com/ppasupat/WikiTableQuestions.git
```

### Usage

```bash
# From agent-project root
uv run python -m evaluation.wtq ./WikiTableQuestions --limit 50 --verbose

# Full test set
uv run python -m evaluation.wtq ./WikiTableQuestions --model gpt-4o

# Train split
uv run python -m evaluation.wtq ./WikiTableQuestions --split train --limit 20
```

| Option | Description |
|--------|--------------|
| `data_dir` | Path to cloned WikiTableQuestions repo |
| `--split` | `test` (pristine-unseen-tables) or `train` |
| `--limit` | Max questions to run |
| `--model` | LLM model (e.g. gpt-4o, gpt-4o-mini) |
| `--verbose` | Print gold vs agent, table columns, query-datasource args, and full trace on failures |
| `--verify-only` | Validate adapter on first table (list, metadata, sample query) and exit |

Target: ≥40% pass on 50 questions as baseline before expanding to full test set.

## Prerequisites

- LLM proxy running (default: `http://localhost:8000`)
- `LLM_PROXY_URL` and `LLM_PROXY_API_KEY` env vars if non-default

## CI Integration

```yaml
# .github/workflows/eval.yml
- run: uv run python evaluation/run_eval.py --no-persist
  env:
    LLM_PROXY_URL: ${{ secrets.LLM_PROXY_URL }}
```

Use `--no-persist` in CI to avoid writing to a shared DB; persistence is for local trend analysis.
