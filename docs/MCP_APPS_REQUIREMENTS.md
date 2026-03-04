# MCP Apps Requirements for Tableau MCP Server

**Purpose:** This document outlines our goals and expectations for MCP Apps support in the Tableau MCP server. We use the Tableau MCP server in an agent-based chat application and want to render interactive charts and data visualizations directly in the conversation.

**Audience:** Tableau MCP server maintainers / MCP team

---

## Our Use Case

We run a chat application where users ask natural language questions about their Tableau data (e.g., "How are sales?", "Show me top customers by region"). An LLM agent calls Tableau MCP tools (`search-content`, `list-datasources`, `get-datasource-metadata`, `query-datasource`, `get-view-data`) and returns text and markdown tables. Users often want to explore the data interactively—filter, sort, drill down, or see charts—without additional prompts.

---

## Goals

1. **Interactive charts** – When a tool returns tabular data, we want the option to render it as an interactive chart (bar, line, pie, etc.) that users can filter and explore in-conversation.

2. **View preview** – When `get-view-data` returns data from a Tableau view, we want to optionally render it as the view’s native visualization (or a close approximation) instead of only a markdown table.

3. **Data exploration** – Users should be able to:
   - Change chart type
   - Filter by dimension (e.g., region, time period)
   - Drill down into segments
   - Export or share the visualization

4. **Standards compliance** – We want to adopt the official [MCP Apps extension](https://modelcontextprotocol.io/docs/extensions/apps) so our chat client can render UIs consistently with other MCP hosts (Claude, ChatGPT, etc.).

---

## Expectations

### Tools That Should Support MCP Apps

| Tool | Current Return | Desired UI |
|------|----------------|------------|
| `query-datasource` | Tabular JSON/text | Interactive chart or data grid with chart options |
| `get-view-data` | Tabular JSON/text | View visualization or interactive chart of the data |
| `search-content` | List of content items | Optional: rich preview cards with thumbnails |

We do not require MCP Apps for `list-datasources` or `get-datasource-metadata`; text/metadata is sufficient.

### Technical Requirements

1. **Tool metadata** – Tools that support MCP Apps should include `_meta.ui.resourceUri` pointing to a `ui://` resource, per the [MCP Apps spec](https://modelcontextprotocol.io/docs/extensions/apps).

2. **UI resources** – The server should serve bundled HTML/JS at the `ui://` URI. The UI should:
   - Accept tool result data (e.g., rows, columns) as input
   - Render an interactive chart or data grid
   - Use the `@modelcontextprotocol/ext-apps` `App` class (or equivalent) for host communication
   - Support calling back to MCP tools (e.g., to re-query with filters)

3. **Data format** – Tool results passed to the UI should include structured data (e.g., `{ columns: [...], rows: [...] }`) in addition to any text summary, so the UI can render charts without re-parsing markdown.

4. **Security** – UIs should run in a sandboxed iframe. We expect the server to follow MCP Apps security practices (CSP, no sensitive data in client bundle, etc.).

### Optional / Nice-to-Have

- **Chart type hint** – Tool input or result could include a suggested chart type (e.g., `bar`, `line`, `pie`) based on the query or view.
- **View thumbnail** – For `get-view-data`, include a reference to the Tableau view’s thumbnail or screenshot if available.
- **Export** – UI supports exporting the chart as PNG or CSV.

---

## Acceptance Criteria

We would consider MCP Apps support complete when:

1. At least `query-datasource` and `get-view-data` expose `_meta.ui.resourceUri` in their tool definitions.
2. The server serves a `ui://` resource that renders an interactive chart or data grid from the tool result.
3. The UI can be rendered in an MCP Apps–compatible host (e.g., our chat app using `@modelcontextprotocol/ext-apps` or `@mcp-ui/client`).
4. Documentation describes how to enable MCP Apps, which tools support it, and the expected data format for the UI.

---

## References

- [MCP Apps documentation](https://modelcontextprotocol.io/docs/extensions/apps)
- [MCP Apps spec / ext-apps](https://github.com/modelcontextprotocol/ext-apps)
- [Data exploration examples](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples) (e.g., `cohort-heatmap-server`, `customer-segmentation-server`)

---

## Contact

We are happy to provide feedback, test early builds, or clarify requirements. Please reach out if you have questions.
