# Tableau MCP Server: Download, Publish, and Flow Tools

**Audience**: MCP server team  
**Purpose**: Requirements for extending the Tableau MCP server to support agent-driven download, inspect, and publish operations.  
**Dependencies**: Agent team will consume these tools; no agent-side fallback.

---

## Python Analytics (Built-in)

The agent includes a built-in `execute_python` tool for advanced analytics (forecasting, anomaly detection, statistical tests, clustering, custom aggregations). No external MCP server is required.

**Workflow:** 1) Use `query-datasource` or `get-view-data` to fetch rows; 2) Call `execute_python` with `code` and `data: { "dataset_name": rows }`.

**Schema:**
- `code` (required): Python code. Use the `data` dict for input datasets.
- `data` (optional): Named datasets from query results, e.g. `{"sales": [{"Month":"2023-01","Sales":10000}]}`.

The executor runs in a subprocess with timeout (60s) and supports pandas, numpy, scipy, statsmodels, scikit-learn. Set `result = ...` in code to return structured output.

---

## Overview

The agent needs the following tools to support:
- Download all workbooks, datasources, or flows from a project (flat or recursive)
- Inspect objects (metadata, structure)
- Publish objects to the same or a different project

All tools must use the existing MCP server auth (Bearer token, site context) and Tableau REST API.

---

## Required Tools

### 1. Download Tools

#### `download-workbook`

Downloads a workbook as `.twbx` (packaged) or `.twb` (when extract excluded).

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `workbookId` | string | Yes | LUID of the workbook |
| `includeExtract` | boolean | No | Default true. When false, excludes the extract (data) from the download. Use for faster downloads when inspecting structure only. REST: `?includeExtract=False` |

**REST**: `GET /api/{ver}/sites/{siteId}/workbooks/{workbookId}/content` or `.../content?includeExtract=False`

**Response**: Return JSON `{"filename": "workbook.twbx", "contentBase64": "..."}` (or `.twb` when extract excluded). The agent streams this as a `download` chunk to the frontend for user download. Do not return raw binary (MCP tool results are text).

**Errors**: Return clear error text for 404, 403, 401 (e.g. "Workbook not found", "Insufficient permissions").

---

#### `download-datasource`

Downloads a datasource as `.tdsx`.

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `datasourceId` | string | Yes | LUID of the datasource |
| `includeExtract` | boolean | No | Default true. When false, excludes the extract (data) from the download. Use for faster downloads when inspecting structure only. REST: `?includeExtract=False` |

**REST**: `GET /api/{ver}/sites/{siteId}/datasources/{datasourceId}/content` or `.../content?includeExtract=False`

**Response**: `{"filename": "datasource.tdsx", "contentBase64": "..."}`. When extract excluded, file is smaller (metadata/connection only).

---

#### `download-flow`

Downloads a flow as `.tflx` (zipped; contains .tfl metadata).

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `flowId` | string | Yes | LUID of the flow |

**REST**: `GET /api/{ver}/sites/{siteId}/flows/{flowId}/content` (or equivalent per Tableau REST docs).

**Response**: `{"filename": "flow.tflx", "contentBase64": "..."}`. (.tflx = zipped flow; .tfl = metadata inside)

**Note**: Flows are metadata-focused; if the Tableau REST API supports an exclude-data option for flows, add an `includeExtract`-style parameter per Tableau docs.

---

### 2. Publish Tools

Publish tools accept either:
- **Inline**: File content as base64 in the request (for small files, e.g. &lt; 64 MB)
- **Upload session**: `uploadSessionId` from a prior Initiate File Upload + Append sequence (for large files)

For large files, the MCP server should:
1. Call `POST /api/{ver}/sites/{siteId}/fileUploads` to get `uploadSessionId`
2. Call `PUT .../fileUploads/{uploadSessionId}` with file blocks (optionally with `sequenceID` for parallel upload)
3. Call the publish endpoint with `uploadSessionId` and no body

#### `publish-workbook`

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `projectId` | string | Yes | LUID of target project |
| `name` | string | Yes | Display name for the workbook |
| `contentBase64` | string | No* | Base64-encoded .twbx file content |
| `uploadSessionId` | string | No* | From Initiate File Upload (for large files) |
| `overwrite` | boolean | No | Default false; true to overwrite existing same-name workbook |

*One of `contentBase64` or `uploadSessionId` required.

**REST**: 
- Single call: `POST /api/{ver}/sites/{siteId}/workbooks` (multipart with file)
- Multi-part: Initiate File Upload → Append blocks → `POST .../workbooks?uploadSessionId=...`

**Response**: Return JSON with published workbook metadata (id, name, projectId, contentUrl, etc.) so the agent can confirm success.

---

#### `publish-datasource`

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `projectId` | string | Yes | LUID of target project |
| `name` | string | Yes | Display name for the datasource |
| `contentBase64` | string | No* | Base64-encoded .tdsx file content |
| `uploadSessionId` | string | No* | From Initiate File Upload |
| `overwrite` | boolean | No | Default false |
| `append` | boolean | No | Default false; for appending to extract |

*One of `contentBase64` or `uploadSessionId` required.

**REST**: `POST /api/{ver}/sites/{siteId}/datasources` (same pattern as workbooks).

**Response**: Published datasource metadata (id, name, projectId, etc.).

---

#### `publish-flow`

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `projectId` | string | Yes | LUID of target project |
| `name` | string | Yes | Display name for the flow |
| `contentBase64` | string | No* | Base64-encoded .tflx file content |
| `uploadSessionId` | string | No* | From Initiate File Upload |
| `overwrite` | boolean | No | Default false |

*One of `contentBase64` or `uploadSessionId` required.

**REST**: `POST /api/{ver}/sites/{siteId}/flows` (per Tableau REST API).

**Response**: Published flow metadata.

---

### 3. Optional: List and Inspect Tools

The agent can use `search-content` with `contentTypes: ['flow', 'project']` for discovery. If you add dedicated tools, the agent will use them.

#### `list-projects` (optional)

List projects on the site. Supports recursive project discovery.

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `filter` | string | No | Field:operator:value (e.g. `name:eq:Finance`) |
| `parentProjectId` | string | No | If provided, return only child projects |
| `pageSize` | number | No | Pagination |
| `limit` | number | No | Max results |

**REST**: Projects API or `search-content` with `contentTypes: ['project']`.

**Response (project objects)**: For disambiguating projects with the same name, the agent builds a hierarchical path (e.g. "Sales / Finance"). Include `parentProjectId` (or `parentId`) in project objects so the agent can traverse parents. The Tableau REST API returns `parentProjectId`. Optionally include a computed `path` or `locationPath` field (e.g. "Sales / Finance") to avoid recursive lookups. If `get-project` is implemented, it should return a single project object with the same shape (`id`, `name`, `parentProjectId`).

---

#### `list-flows` (optional)

List flows. If not implemented, agent uses `search-content` with `contentTypes: ['flow']`.

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `filter` | string | No | e.g. `projectName:eq:MyProject` |
| `pageSize` | number | No | Pagination |
| `limit` | number | No | Max results |

**REST**: Flows list endpoint or search-content.

---

#### `get-flow` / `get-flow-metadata` (optional)

Retrieve flow metadata for inspect operations. If not implemented, agent uses `search-content` results for flow info.

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `flowId` | string | Yes | LUID of the flow |

**Response**: Flow metadata (name, project, owner, updatedAt, outputs, etc.).

---

### 4. File-Level Inspection Tools (Inspect File Contents)

These tools parse the *file contents* of downloaded objects—not just server metadata. Use when the user wants to inspect structure, connections, calculated fields, etc. from the actual file.

**File format reference:**
- **Workbooks**: `.twbx` = ZIP containing `.twb` (XML). `.twb` = unpackaged XML. Parse the XML for sheets, dashboards, data sources, calculated fields.
- **Datasources**: `.tdsx` = ZIP containing `.tds` (XML). `.tds` = unpackaged XML. Parse for connections, column definitions, extracts.
- **Flows**: `.tflx` = ZIP containing `.tfl` (metadata). Parse the .tfl for structure. Schema TBD.

#### `inspect-workbook-file`

Parses the workbook file (twbx or twb) and returns structured inspection.

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `workbookId` | string | No* | LUID—download, unzip, parse |
| `contentBase64` | string | No* | Base64 of .twbx or .twb (e.g. from prior download) |
| `includeExtract` | boolean | No | When using workbookId: pass through to download-workbook for faster fetch (default true) |

*One of `workbookId` or `contentBase64` required.

**Processing**: If twbx, unzip to get .twb; parse XML. If twb, parse XML directly. When fetching by workbookId, use `includeExtract=false` for inspection-only (structure only, no extract).

**Response** (JSON): Structured inspection. Suggested fields (refine per Tableau XML schema):
- `sheets`: [{name, id, type}]
- `dashboards`: [{name, id}]
- `dataSources`: [{name, id, connectionType}]
- `calculatedFields`: [{name, formula}]
- `parameters`: [{name, dataType, currentValue}]

---

#### `inspect-datasource-file`

Parses the datasource file (tdsx or tds) and returns structured inspection.

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `datasourceId` | string | No* | LUID—download, unzip, parse |
| `contentBase64` | string | No* | Base64 of .tdsx or .tds |
| `includeExtract` | boolean | No | When using datasourceId: pass through to download-datasource for faster fetch (default true) |

*One of `datasourceId` or `contentBase64` required.

**Processing**: If tdsx, unzip to get .tds; parse XML. If tds, parse XML directly. When fetching by datasourceId, use `includeExtract=false` for inspection-only (metadata/connections only, no extract).

**Response** (JSON): Suggested fields:
- `connections`: [{server, database, username}]
- `columns`: [{name, dataType, role}]
- `calculatedFields`: [{name, formula}]
- `extracts`: [{table, path}]

---

#### `inspect-flow-file`

Parses the flow file (.tflx or .tfl) and returns structured inspection.

| Parameter | Type | Required | Description |
|----------|------|----------|-------------|
| `flowId` | string | No* | LUID—download, unzip, parse |
| `contentBase64` | string | No* | Base64 of .tflx or .tfl |

*One of `flowId` or `contentBase64` required.

**Processing**: .tflx = ZIP containing .tfl (metadata). Unzip to get .tfl; parse. If input is .tfl directly, parse. Specific fields to extract TBD; initial implementation can return the raw parsed structure or a minimal schema (e.g. nodes, outputs, inputs).

**Response** (JSON): Structure to be defined. Return parsed JSON or a documented schema.

---

## Tool Naming and Schema

- Tool names must match exactly: `download-workbook`, `download-datasource`, `download-flow`, `publish-workbook`, `publish-datasource`, `publish-flow`, `inspect-workbook-file`, `inspect-datasource-file`, `inspect-flow-file`.
- Use standard MCP tool schema (JSON Schema for `inputSchema`).
- Descriptions should mention: when to use, required params, and that these tools integrate with the agent’s download/publish workflows.

---

## Error Handling

Return human-readable error strings. The agent surfaces these to the user. Examples:
- `"Workbook not found: {workbookId}"`
- `"Insufficient permissions to download workbook"`
- `"Project not found: {projectId}"`
- `"Publish failed: file too large for single request; use upload session"`

---

## Auth and Context

- Reuse existing MCP server auth (Bearer token, site ID from session/config).
- All tools operate in the context of the connected Tableau site.
- Ensure PAT or OAuth scopes include: `tableau:content:read`, `tableau:file_uploads:create`, `tableau:datasources:create`, `tableau:workbooks:create`, and flow equivalents per Tableau docs.

---

## Coordination with Agent Team

- Agent will add these tool names to `REQUIRED_TOOLS` and `WRITE_TOOLS` (for publish-*).
- Agent assumes tools return the response shapes above. If you change the contract, coordinate with the agent team.
- Publish tools are gated by a write-confirmation flow in the agent; the MCP server does not need to implement confirmation.
