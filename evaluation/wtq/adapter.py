"""WTQ tables as mock Tableau datasources with VDS-style query execution."""

import csv
import json
from pathlib import Path

from evaluation.mocks.mock_mcp_pool import MOCK_TOOL_SCHEMAS

# Tools WTQ adapter supports
WTQ_TOOLS = {"list-datasources", "get-datasource-metadata", "query-datasource", "search-content"}
WTQ_SCHEMAS = [t for t in MOCK_TOOL_SCHEMAS if t["name"] in WTQ_TOOLS]


class WTQTable:
    """A single WikiTableQuestions table loaded as a mock datasource."""

    def __init__(self, table_id: str, rows: list[dict], headers: list[str]):
        self.table_id = table_id
        self.rows = rows
        self.headers = headers

    @classmethod
    def from_file(cls, table_id: str, path: Path) -> "WTQTable":
        """Load table from CSV or TSV file."""
        suffix = path.suffix.lower()
        delimiter = "\t" if suffix == ".tsv" else ","
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            headers = reader.fieldnames or []
            rows = [dict(r) for r in reader]
        return cls(table_id, rows, headers)

    @classmethod
    def from_tsv(cls, table_id: str, path: Path) -> "WTQTable":
        """Load table from TSV file."""
        return cls.from_file(table_id, path)

    def get_metadata(self) -> dict:
        """Generate Tableau-style metadata from the table."""
        columns = []
        for header in self.headers:
            sample = next((r.get(header, "") for r in self.rows if r.get(header)), "")
            data_type, role = self._infer_type(str(sample))
            columns.append({"caption": header, "dataType": data_type, "role": role})
        return {"columns": columns}

    def _infer_type(self, value: str) -> tuple[str, str]:
        if not value:
            return "string", "dimension"
        cleaned = value.replace(",", "").replace("$", "").replace("%", "").strip()
        try:
            float(cleaned)
            return "real", "measure"
        except ValueError:
            pass
        return "string", "dimension"

    def query(
        self,
        fields: list[dict],
        filters: list[dict] | None = None,
    ) -> list[dict]:
        """Execute a VDS-style query against the table data."""
        valid_fields = set(self.headers)
        for field in fields:
            caption = field.get("fieldCaption", "")
            if caption and caption not in valid_fields:
                raise ValueError(f"Field '{caption}' not found. Available: {list(self.headers)}")

        filtered_rows = list(self.rows)

        for f in filters or []:
            field_obj = f.get("field", {})
            field_name = (
                field_obj.get("fieldCaption")
                if isinstance(field_obj, dict)
                else f.get("field")
            )
            filter_type = f.get("filterType", "")
            values = f.get("values", [])

            if not field_name or field_name not in valid_fields:
                continue

            if filter_type == "SET" and values:
                values_norm = [str(v).lower().strip() for v in values]
                values_set = set(values_norm)

                def _cell_matches(cell: str) -> bool:
                    c = str(cell).lower().strip()
                    if c in values_set:
                        return True
                    for v in values_norm:
                        if not v.isdigit():
                            continue
                        if c == v:
                            return True
                        rest = c[len(v):].lstrip()
                        if c.startswith(v) and (not rest or not rest[0].isdigit()):
                            return True
                    return False

                filtered_rows = [r for r in filtered_rows if _cell_matches(r.get(field_name, ""))]
            elif filter_type == "QUANTITATIVE_NUMERICAL":
                min_val = f.get("minValue")
                max_val = f.get("maxValue")
                new_rows = []
                for r in filtered_rows:
                    raw = str(r.get(field_name, "")).replace(",", "").strip()
                    try:
                        val = float(raw)
                        if min_val is not None and val < float(min_val):
                            continue
                        if max_val is not None and val > float(max_val):
                            continue
                        new_rows.append(r)
                    except ValueError:
                        continue
                filtered_rows = new_rows

        dimensions = []
        measures = []
        for field in fields:
            caption = field.get("fieldCaption", "")
            func = field.get("function")
            if func:
                measures.append({"caption": caption, "function": func.upper()})
            else:
                dimensions.append(caption)

        if not measures:
            all_fields = dimensions or self.headers
            return [{f: r.get(f, "") for f in all_fields} for r in filtered_rows]

        if not dimensions:
            row = {}
            for m in measures:
                row[m["caption"]] = self._aggregate(filtered_rows, m["caption"], m["function"])
            return [row]

        groups: dict[tuple, list[dict]] = {}
        for r in filtered_rows:
            key = tuple(str(r.get(d, "")) for d in dimensions)
            groups.setdefault(key, []).append(r)

        result = []
        for key, group_rows in groups.items():
            row = dict(zip(dimensions, key))
            for m in measures:
                row[m["caption"]] = self._aggregate(group_rows, m["caption"], m["function"])
            result.append(row)
        return result

    def _aggregate(self, rows: list[dict], field: str, func: str) -> float | int | str:
        """Aggregate values. Handles both numeric and string fields."""
        raw_values = [str(r.get(field, "")).strip() for r in rows if r.get(field)]

        if func == "COUNT":
            return len(raw_values)

        if func == "COUNTD":
            return len(set(raw_values))

        if func in ("ATTR", "FIRST"):
            return raw_values[0] if raw_values else ""

        numeric_values = []
        for v in raw_values:
            cleaned = v.replace(",", "").replace("$", "").replace("%", "").strip()
            try:
                numeric_values.append(float(cleaned))
            except ValueError:
                continue

        if not numeric_values:
            return 0

        if func == "SUM":
            return round(sum(numeric_values), 2)
        elif func == "AVG":
            return round(sum(numeric_values) / len(numeric_values), 2)
        elif func == "MIN":
            return min(numeric_values)
        elif func == "MAX":
            return max(numeric_values)
        elif func == "MEDIAN":
            s = sorted(numeric_values)
            n = len(s)
            return s[n // 2] if n % 2 else round((s[n // 2 - 1] + s[n // 2]) / 2, 2)
        return 0


class WTQMCPAdapter:
    """Mock MCP pool backed by WTQ tables."""

    def __init__(self, tables: dict[str, WTQTable]):
        self.tables = tables
        self.call_log: list[dict] = []

    async def list_tools(self, server_id: str) -> list[dict]:
        return WTQ_SCHEMAS

    async def call_tool(self, server_id: str, tool_name: str, args: dict) -> str:
        self.call_log.append({"tool": tool_name, "args": args})

        if tool_name == "list-datasources":
            datasources = [
                {"id": tid, "name": tid.replace("_", " ").title(), "type": "datasource"}
                for tid in self.tables
            ]
            return json.dumps({"datasources": datasources})

        if tool_name == "get-datasource-metadata":
            ds_id = args.get("datasourceLuid") or args.get("datasourceId") or args.get("datasource_id")
            table = self.tables.get(ds_id or "")
            if not table:
                return f'Error: Datasource "{ds_id}" not found'
            return json.dumps(table.get_metadata())

        if tool_name == "query-datasource":
            ds_id = args.get("datasourceLuid") or args.get("datasourceId") or args.get("datasource_id")
            query = args.get("query", {})
            if isinstance(query, str) and query.strip().startswith("{"):
                try:
                    query = json.loads(query)
                except json.JSONDecodeError:
                    query = {}
            table = self.tables.get(ds_id or "")
            if not table:
                return f'Error: Datasource "{ds_id}" not found'
            try:
                rows = table.query(
                    fields=query.get("fields", []),
                    filters=query.get("filters", []),
                )
                return json.dumps({"data": rows, "rows": rows})
            except Exception as e:
                return f"Error: {e}"

        if tool_name == "search-content":
            return await self.call_tool(server_id, "list-datasources", args)

        return json.dumps({"error": f"Tool {tool_name} not supported"})

    def get_pool_dict(self) -> dict:
        return {"list_tools": self.list_tools, "call_tool": self.call_tool}

    def get_tool_sequence(self) -> list[str]:
        return [c["tool"] for c in self.call_log]
