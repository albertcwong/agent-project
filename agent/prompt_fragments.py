"""Workflow-specific prompt addenda. Injected based on intent classification."""

ADDENDUM_QUERY_ANALYTICS = """
## Query/Analytics workflow
## Python analytics (execute_python)

### When to use Python
- Forecasting, trends, anomaly detection, statistical tests, correlations, clustering, or analysis beyond Tableau aggregation.
- Transformations: pivoting, percentages, running totals, period-over-period comparisons.
- Combining results from multiple queries.

### How to use Python
- Always query Tableau first. Do not fabricate data.
- When you pass empty or placeholder data, the system injects the last query result as `data["rows"]`. Use `df = pd.DataFrame(data["rows"])` — do not use `pd.DataFrame(data)`.
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
- Prefer aggregation over raw rows. When unsure about volume, profile with COUNT first.

### Query construction patterns
- **Aggregation query** (e.g. "total sales by region"): dimension `{ "fieldCaption": "Region" }` + measure `{ "fieldCaption": "Sales", "function": "SUM" }` in query.fields.
- **Top-N query** (e.g. "top 10 customers by revenue"): dimension `{ "fieldCaption": "Customer Name" }` + measure `{ "fieldCaption": "Revenue", "function": "SUM" }` + sort descending on the measure + limit 10. Or use filterType TOP with field as object.
- **Filtered query** (e.g. "sales for East region only"): include the filter dimension in query.fields if the user wants to see it; add to query.filters: `{ "field": { "fieldCaption": "Region" }, "filterType": "SET", "values": ["East"] }`.

## Tool selection
- `query-datasource`: Use for custom queries when you need specific fields, filters, or aggregations.
- `get-view-data`: Use when a view already answers the question and you just need its data.

## Data and visualization
- Your job is to return the right data. The application handles visualization.
- When the user asks for a chart, visualization, or graph, query the appropriate data and return it. The application will render the chart.
- Do not refuse visualization requests. Do not suggest external tools (Excel, Sheets).
"""

ADDENDUM_DOWNLOAD_INSPECT = """
## Download
- Use `list-workbooks`, `list-datasources`, or `search-content` with `filter=projectName:eq:ProjectName` or `contentTypes: ['flow']` to find objects in a project.
- Call `download-workbook`, `download-datasource`, or `download-flow` for each object. Paginate with `limit` and `pageSize` if needed.
- For inspection-only (structure, connections, calculated fields): use `includeExtract: false` on download-workbook and download-datasource to skip extract data—faster and smaller files.
- For recursive (all sub-projects): use `search-content` with `contentTypes: ['project']` to list projects, then for each project list and download content.

## Inspect
- Server metadata: use `get-workbook`, `get-datasource-metadata`, or `get-flow`/`search-content` for flows.
- File structure (sheets, connections, calculated fields): use `inspect-workbook-file`, `inspect-datasource-file`, or `inspect-flow-file`. Pass the object ID to download and parse, or `contentBase64` if the file was already downloaded. When using ID, pass `includeExtract: false` for faster inspection (structure only).
"""

ADDENDUM_PUBLISH = """
## Publish
- Use `publish-workbook`, `publish-datasource`, or `publish-flow` with `projectId` for the target project. Same location = same projectId as source; different location = target projectId from user.
- When the user has attached files and asks to publish, call the publish tool with contentBase64: 'ATTACHMENT_0' (first file), 'ATTACHMENT_1' (second file), etc. Do not ask the user to provide the file again.
- When you know the project name from context (e.g. from list-projects or search-content), include `projectName` in the publish tool arguments so the confirmation dialog can show it to the user.
- Publish tools require user confirmation; the system will prompt. After the user confirms, proceed with the publish.
"""

ADDENDUM_PROJECT = """
## Projects
- Use `search-content` with `contentTypes: ['project']` or `list-projects` to discover projects.
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
