"""Deterministic MCP tool responses for evaluation."""

import json
from pathlib import Path

from agent.tools import REQUIRED_TOOLS

# Minimal MCP tool schemas for agent to know what to call
MOCK_TOOL_SCHEMAS: list[dict] = [
    {"name": n, "description": f"Mock {n}", "inputSchema": {"type": "object", "properties": {}}}
    for n in REQUIRED_TOOLS
]
# Add required params for key tools
for t in MOCK_TOOL_SCHEMAS:
    if t["name"] == "get-datasource-metadata":
        t["inputSchema"]["properties"] = {"datasourceId": {"type": "string"}}
    elif t["name"] == "query-datasource":
        t["inputSchema"]["properties"] = {"datasourceId": {"type": "string"}, "query": {"type": "object"}}
    elif t["name"] == "search-content":
        t["inputSchema"]["properties"] = {"query": {"type": "string"}}
    elif t["name"] == "update-datasource-data":
        t["inputSchema"]["properties"] = {"datasourceId": {"type": "string"}, "contentBase64": {"type": "string"}}


class MockMCPPool:
    """Deterministic MCP tool responses for evaluation. Rejects metadata/query for undiscovered IDs."""

    def __init__(
        self,
        fixtures_dir: str | Path | None = None,
        scenario: str | None = None,
        conversation_state: dict | None = None,
    ):
        self.fixtures = self._load_fixtures(fixtures_dir or Path(__file__).parent / "fixtures")
        self.call_log: list[dict] = []
        self.scenario = scenario
        self.discovered_ids: set[str] = set()
        if conversation_state and conversation_state.get("currentDatasourceId"):
            self.discovered_ids.add(str(conversation_state["currentDatasourceId"]))

    def _load_fixtures(self, path: Path) -> dict:
        out = {}
        if not path.exists():
            return out
        for f in path.glob("*.json"):
            try:
                out[f.stem] = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return out

    async def list_tools(self, server_id: str) -> list[dict]:
        return MOCK_TOOL_SCHEMAS

    async def call_tool(self, server_id: str, tool_name: str, args: dict) -> str:
        self.call_log.append({"tool": tool_name, "args": args})

        if self.scenario == "auth_error_graceful" and len(self.call_log) == 1:
            return "Error: 401 Unauthorized. Authentication expired. Please sign in again."

        if tool_name == "list-datasources":
            datasources = [
                {"id": "ds-123", "name": "Sales Analytics", "type": "datasource"},
                {"id": "ds-456", "name": "HR Metrics", "type": "datasource"},
                {"id": "ds-empty", "name": "Empty", "type": "datasource"},
                {"id": "ds-flag-log", "name": "Flag Log", "type": "datasource"},
            ]
            if self.scenario == "wrong_datasource_employee":
                datasources = [{"id": "ds-123", "name": "Sales Analytics", "type": "datasource"}]
            if self.scenario == "ambiguous_datasource":
                datasources.extend([
                    {"id": "ds-789", "name": "Sales Summary", "type": "datasource"},
                    {"id": "ds-101", "name": "Sales by Region", "type": "datasource"},
                ])
            if self.scenario == "cross_datasource":
                datasources.extend([
                    {"id": "ds-regional", "name": "Regional Performance", "type": "datasource"},
                ])
            if self.scenario == "inspect_compare_schemas":
                datasources.extend([
                    {"id": "ds-789", "name": "Inventory", "type": "datasource"},
                ])
            result = json.dumps({"datasources": datasources})
            for ds in datasources:
                self.discovered_ids.add(ds["id"])
            return result
        if tool_name == "search-content":
            datasources = [{"id": "ds-123", "name": "Sales Analytics"}]
            if self.scenario == "wrong_datasource_employee":
                pass
            elif self.scenario == "field_not_found_recovery":
                datasources.append({"id": "ds-456", "name": "Revenue Metrics", "type": "datasource"})
            if self.scenario == "cross_datasource":
                datasources.append({"id": "ds-regional", "name": "Regional Performance", "type": "datasource"})
            if self.scenario == "inspect_compare_schemas":
                datasources.extend([
                    {"id": "ds-456", "name": "HR Metrics", "type": "datasource"},
                    {"id": "ds-789", "name": "Inventory", "type": "datasource"},
                ])
            projects = [{"id": "proj-1", "name": "Finance", "parentProjectId": None}]
            workbooks = [{"id": "wb-1", "name": "Sales Analytics", "projectId": "proj-1"}]
            result = json.dumps({"datasources": datasources, "workbooks": workbooks, "projects": projects})
            for ds in datasources:
                self.discovered_ids.add(ds["id"])
            return result
        if tool_name == "get-datasource-metadata":
            ds_id = str(args.get("datasourceId") or args.get("datasource_id") or "ds-123")
            if ds_id not in self.discovered_ids:
                return f'Error: Datasource "{ds_id}" not found. Use list-datasources or search-content to find available datasources.'
            key = f"metadata_{ds_id}"
            if key in self.fixtures:
                return json.dumps(self.fixtures[key])
            if self.scenario == "field_not_found_recovery":
                return json.dumps({
                    "columns": [
                        {"caption": "Category", "dataType": "string", "role": "dimension"},
                        {"caption": "Sales Amount", "dataType": "real", "role": "measure"},
                    ]
                })
            return json.dumps({
                "columns": [
                    {"caption": "Region", "dataType": "string", "role": "dimension"},
                    {"caption": "Sales", "dataType": "real", "role": "measure"},
                    {"caption": "Quarter", "dataType": "string", "role": "dimension"},
                ]
            })
        if tool_name == "query-datasource":
            ds_id = str(args.get("datasourceId") or args.get("datasource_id") or "ds-123")
            if ds_id not in self.discovered_ids:
                return f'Error: Datasource "{ds_id}" not found. Use list-datasources or search-content to find available datasources.'
            query = args.get("query") or {}
            if isinstance(query, str):
                try:
                    query = json.loads(query) if query.strip().startswith("{") else {}
                except Exception:
                    query = {}
            query_str = json.dumps(query)

            if ds_id == "ds-empty":
                return json.dumps({"rows": []})

            if self.scenario == "empty_result_antarctica":
                filters = query.get("filters") or query.get("filter") or []
                filter_str = json.dumps(filters) if isinstance(filters, (list, dict)) else str(filters)
                if "antarctica" in filter_str.lower():
                    return json.dumps({"rows": []})

            if self.scenario == "misspelled_technology":
                filter_str = json.dumps(query)
                if "tecnology" in filter_str.lower():
                    return json.dumps({
                        "rows": [
                            {"Category": "Technology", "Sales": 836000},
                            {"Category": "Furniture", "Sales": 742000},
                            {"Category": "Office Supplies", "Sales": 719000},
                        ]
                    })

            if self.scenario == "field_not_found_recovery":
                query_idx = sum(1 for c in self.call_log if c["tool"] == "query-datasource")
                if query_idx == 1 and ("revenue" in query_str.lower() or "Revenue" in query_str):
                    return "Error: Field 'Revenue' not found. Use fieldCaption from metadata."
                # success on retry or when using correct field
                return json.dumps({
                    "rows": [
                        {"Category": "A", "Sales Amount": 100000},
                        {"Category": "B", "Sales Amount": 150000},
                    ]
                })

            key = f"query_{ds_id}"
            if key in self.fixtures:
                return json.dumps(self.fixtures[key])
            return json.dumps({
                "rows": [
                    {"Region": "East", "Sales": 100000},
                    {"Region": "West", "Sales": 150000},
                    {"Region": "North", "Sales": 80000},
                ]
            })
        if tool_name == "list-workbooks":
            return json.dumps({
                "workbooks": [{"id": "wb-1", "name": "Sales Analytics", "projectId": "proj-1"}]
            })
        if tool_name == "list-projects":
            return json.dumps({
                "projects": [{"id": "proj-1", "name": "Finance", "parentProjectId": None}]
            })
        if tool_name in ("list-views", "list-flows"):
            return json.dumps({tool_name.replace("list-", "") + "s": []})
        if tool_name in ("download-workbook", "download-datasource", "download-flow"):
            return json.dumps({"id": "obj-1", "filename": "test.twbx", "contentBase64": "base64..."})
        if tool_name.startswith("inspect-"):
            if tool_name == "inspect-workbook-file":
                return json.dumps({
                    "id": "obj-1",
                    "name": "Sales Analytics",
                    "sheets": [{"name": "Sheet1"}],
                    "calculatedFields": [
                        {"name": "Profit Margin", "formula": "[Profit]/[Sales]"},
                        {"name": "Discount Rate", "formula": "[Discount]"},
                    ],
                })
            return json.dumps({"id": "obj-1", "name": "test", "sheets": []})
        if tool_name.startswith("publish-"):
            return json.dumps({"id": "pub-1", "name": "test", "projectId": "proj-1"})
        if tool_name == "update-datasource-data":
            ds_id = args.get("datasourceId") or args.get("datasource_id") or ""
            if ds_id not in self.discovered_ids:
                return f'Error: Datasource "{ds_id}" not found. Use list-datasources or search-content first.'
            return json.dumps({"id": ds_id, "name": "Flag Log", "rowsUpdated": 42})
        if tool_name == "get-workbook":
            return json.dumps({"id": "wb-1", "name": "test"})
        if tool_name == "get-view-data":
            if self.scenario == "cross_datasource":
                return json.dumps({
                    "rows": [
                        {"Region": "East", "Sales": 680000},
                        {"Region": "West", "Sales": 725000},
                        {"Region": "Central", "Sales": 501000},
                        {"Region": "South", "Sales": 392000},
                    ]
                })
            return json.dumps({"rows": [{"Region": "East", "Sales": 100000}]})

        return json.dumps({"error": f"No fixture for {tool_name}"})

    def get_tool_sequence(self) -> list[str]:
        return [c["tool"] for c in self.call_log]

    def get_pool_dict(self) -> dict:
        """Return pool dict compatible with run_agent_loop _pool_override."""
        return {"list_tools": self.list_tools, "call_tool": self.call_tool, "configs": {"mock": {}}}
