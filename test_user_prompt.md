# Test User Prompt for Brief Generation

Use this prompt to test the agent's datasource discovery and Flag Log handling:

```
Use datasource '15_day_metrics_daily_simplified_ai' to produce a brief. 
Include anomalies and trends. Suppress flags that already exist in the Flag Log 
(resolved_date is null, date_generated within last 7 days). 
Return the brief as structured text.
```

## Expected behavior

1. **Datasource discovery**: Agent calls `list-datasources` with a name filter to find `15_day_metrics_daily_simplified_ai` — does NOT reuse cached `currentDatasourceId` from prior context.
2. **Flag Log query**: Agent queries Flag Log without complex null filters; uses `execute_python` to filter for `resolved_date is null` and `date_generated` within last 7 days.
3. **Metrics query**: Agent queries the metrics datasource for anomalies/trends.
4. **Output**: Agent produces a structured brief with suppression applied.
