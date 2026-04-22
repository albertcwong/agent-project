"""Workflow-specific prompt addenda. Injected based on intent classification."""

ADDENDUM_QUERY_ANALYTICS = """
## Query/Analytics workflow
## Python analytics (execute_python)

### When to use Python
- Forecasting, trends, anomaly detection, statistical tests, correlations, clustering, or analysis beyond Tableau aggregation.
- Transformations: pivoting, percentages, running totals, period-over-period comparisons.
- Combining results from multiple queries.
- Extracting information from string fields (e.g. parsing country codes from names like "Davide Rebellin (ITA)", splitting combined fields).
- COUNT, ranking, or comparison that you cannot express in a single VDS query.
- When you have the raw data but the question asks for a derived insight (e.g. "which X had the most Y"): always compute the final answer — do not just list the raw data and leave the counting to the user.

### How to use Python
- Always query Tableau first. Do not fabricate data.
- When you pass empty or placeholder data, the system injects query results. Single query: `data["rows"]`. Multiple queries: data is keyed by datasource LUID — use the IDs from list-datasources. Example: `metrics_df = pd.DataFrame(data["<metrics_id>"]); flag_log_df = pd.DataFrame(data["<flag_log_id>"]) if "<flag_log_id>" in data else pd.DataFrame()`.
- When you pass named datasets: `data: { "sales": [rows] }`. Access: `df = pd.DataFrame(data["sales"])`.
- Available: pandas, numpy, scipy, statsmodels, sklearn. Do not import other libraries.
- Your code must `print()` its final output; the printed output is returned to you.
- For forecasting: aggregate to the appropriate grain (monthly unless user specifies) before calling Python.

### Common patterns
- Period comparison: query both periods, use Python to calculate differences and percentage changes.
- Forecasting: use exponential smoothing or linear regression on monthly aggregates. Return predicted values and confidence context.
- Anomaly detection: calculate z-scores or IQR bounds on the metric of interest.

## Query construction (Tableau VDS)
- Queries use `fieldCaption` from metadata (not internal field names). Get metadata with `get-datasource-metadata` first.
- Dimensions: `{ "fieldCaption": "Category" }` in `query.fields`. Measures require `function`: SUM, AVG, COUNT, COUNTD, MIN, MAX, MEDIAN, STDEV, VAR.
- Filters: `query.filters` array. filterType: SET (dimensions), QUANTITATIVE_NUMERICAL (measures), QUANTITATIVE_DATE (dates). For SET filters, `field` must be an object: `{ "fieldCaption": "Region" }`, not a string.
- Date filters: use `minDate`/`maxDate` in ISO format (YYYY-MM-DD). For relative dates (e.g. "last year"), compute the actual date range.
- If "field not found" or similar error: re-check metadata; fieldCaption may differ from user wording (e.g. "revenue" vs "Sales Amount"). Use the closest match and attempt the query; if it fails, re-check metadata for the correct fieldCaption.
- When a user-requested metric (e.g. "revenue") does not exist as a fieldCaption but a clearly related field does (e.g. "Sales Amount", "Total Revenue", "Net Sales"), use the closest match and state your assumption. Do not ask the user to confirm field mappings. Example: "Using 'Sales Amount' as the revenue metric."
- Prefer aggregation over raw rows. When unsure about volume, profile with COUNT first.

### Query construction patterns
- **Aggregation query** (e.g. "total sales by region"): dimension `{ "fieldCaption": "Region" }` + measure `{ "fieldCaption": "Sales", "function": "SUM" }` in query.fields.
- **Top-N query** (e.g. "top 10 customers by revenue"): dimension `{ "fieldCaption": "Customer Name" }` + measure `{ "fieldCaption": "Revenue", "function": "SUM" }` + sort descending on the measure + limit 10. Or use filterType TOP with field as object.
- **Filtered query** (e.g. "sales for East region only"): include the filter dimension in query.fields if the user wants to see it; add to query.filters: `{ "field": { "fieldCaption": "Region" }, "filterType": "SET", "values": ["East"] }`.

## Tool selection
- `query-datasource`: Use for custom queries when you need specific fields, filters, or aggregations.
- `get-view-data`: Use when a view already answers the question and you just need its data.

## Flag Log and null-date filtering
- When querying the Flag Log datasource for unresolved flags (resolved_date is null), do not use QUANTITATIVE_DATE or QUANTITATIVE_NUMERICAL filters for null — the query-datasource tool does not support them for date columns.
- Instead: query all records from the Flag Log without filtering on resolved_date, then use execute_python to filter for resolved_date is null and date_generated within the last 7 days.

## Data and visualization
- Your job is to return the right data. The application handles visualization.
- When the user asks for a chart, visualization, or graph, query the appropriate data and return it. The application will render the chart.
- Do not refuse visualization requests. Do not suggest external tools (Excel, Sheets).
"""

ADDENDUM_DOWNLOAD_INSPECT = """
## Download
- Use `list-workbooks` or `list-datasources` to find objects. Use `search-content` with `filter=projectName:eq:ProjectName` or `contentTypes: ['flow']` only when you need to filter by project or list flows.
- Call `download-workbook`, `download-datasource`, or `download-flow` for each object. Paginate with `limit` and `pageSize` if needed.
- For inspection-only (structure, connections, calculated fields): use `includeExtract: false` on download-workbook and download-datasource to skip extract data—faster and smaller files.
- For recursive (all sub-projects): use `search-content` with `contentTypes: ['project']` to list projects, then for each project list and download content.

## Inspect
- Server metadata: use `get-workbook`, `get-datasource-metadata`, or `get-flow`/`search-content` for flows.
- File structure (sheets, connections, calculated fields): use `inspect-workbook-file`, `inspect-datasource-file`, or `inspect-flow-file`. Pass the object ID to download and parse, or `contentBase64` if the file was already downloaded. When using ID, pass `includeExtract: false` for faster inspection (structure only).
"""

ADDENDUM_PUBLISH = """
## Publish workflow

IMPORTANT: Do NOT ask the user for text confirmation (e.g. "Is this correct?", "Should I proceed?"). The system has a built-in confirmation dialog for publish actions. Just call the tool — the user will be prompted automatically.

### Step 1: Resolve the target project
- Always call `list-projects` (NOT list-datasources) to find the `projectId` for the target project. Do not guess, fabricate, or reuse project IDs from previous failed attempts.
- Use `search-content` with `contentTypes: ['project']` only if list-projects is unavailable.

### Step 2: Publish with the attached file
- The user's attached file is already available. Use `contentBase64: 'ATTACHMENT_0'` for the first file, `'ATTACHMENT_1'` for the second, etc. Do NOT ask the user to provide the file again — it is already attached and ready.
- Call `publish-workbook`, `publish-datasource`, or `publish-flow` with `projectId` from step 1, `name` from the user, and `contentBase64: 'ATTACHMENT_0'`.
- Include `projectName` in the publish tool arguments so the confirmation dialog can show it to the user.

### Updating existing datasources
- When the user asks to update or refresh a datasource (e.g. Flag Log) with attached data, use `update-datasource-data` with datasourceId from list-datasources and contentBase64: 'ATTACHMENT_0' for the first attached file. Requires user confirmation.
- Flag Log write from execute_python: when Python prints FLAGS_JSON (flag_records + datasourceId), the system handles the update-datasource-data call deterministically. Do not call update-datasource-data for Flag Log from execute_python output.
"""

ADDENDUM_PROJECT = """
## Projects
- Use `list-projects` to discover projects. Use `search-content` with `contentTypes: ['project']` only when list-projects is unavailable.
- Use `projectName` filter (e.g. `filter=projectName:eq:Finance`) when listing workbooks, datasources, or flows.
- When `list-projects` or `search-content` returns multiple projects with the same name, do NOT assume which one the user meant. Ask the user to clarify: e.g. "I found multiple projects named Finance: Sales/Finance and Marketing/Finance. Which one do you want to publish to?"
- When the user specifies a project by path (e.g. "Sales / Finance"), use that to disambiguate. Prefer `parentProjectId` or path filters when the MCP server supports them.
"""

ADDENDA = {
    "query": ADDENDUM_QUERY_ANALYTICS,
    "download": ADDENDUM_DOWNLOAD_INSPECT,
    "inspect": ADDENDUM_DOWNLOAD_INSPECT,
    "publish": ADDENDUM_PUBLISH,
    "project": ADDENDUM_PROJECT,
    "general": ADDENDUM_QUERY_ANALYTICS,
}
