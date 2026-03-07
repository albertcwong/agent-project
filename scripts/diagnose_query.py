#!/usr/bin/env python3
"""Run diagnostic steps for query construction issues."""

import json
import os
import sys

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def step1_intent():
    """Step 1: Check intent classification."""
    from agent.intent import classify

    questions = [
        "Show me total sales by region",
        "Who are the top 10 customers by revenue?",
        "Show me sales for the East region only",
        "Query the Empty datasource for total revenue",
        "Download the Sales Analytics workbook",
        "Publish my workbook to the Finance project",
    ]
    print("=== Step 1: Intent Classification ===\n")
    for q in questions:
        result = classify(q)
        preview = q[:50] + ("..." if len(q) > 50 else "")
        status = "OK" if (("query" in q.lower() or "sales" in q or "revenue" in q) and result == "query") or ("download" in q.lower() and result == "download") or ("publish" in q.lower() and result == "publish") else "CHECK"
        print(f"  '{preview}' -> '{result}' [{status}]")
    print()


def step2_tool_schema():
    """Step 2: Compare query-datasource schema (Tableau MCP vs mock vs prompt)."""
    print("=== Step 2: query-datasource Tool Schema ===\n")

    # Mock schema (evaluation)
    print("  [MOCK schema - evaluation]")
    print("    datasourceId, query (minimal)")
    print()

    # Tableau MCP schema
    ta_path = os.path.expanduser("~/.cursor/projects/Users-albert-wong-agents/mcps/user-tableau_mcp_server_ta/tools/query-datasource.json")
    if os.path.exists(ta_path):
        with open(ta_path) as f:
            ta = json.load(f)
        args = ta.get("arguments", {})
        props = args.get("properties", {})
        print("  [TABLEAU MCP schema]")
        print("    Top-level params:", list(props.keys()))
        print("    NOTE: Real MCP uses datasourceLuid; loop checks datasourceId/datasource_id")
        q = props.get("query", {})
        if isinstance(q, dict):
            qprops = q.get("properties", {})
            print("    query.properties:", list(qprops.keys()))
            fi = qprops.get("filters", {})
            if isinstance(fi, dict) and "items" in fi:
                first = fi["items"].get("anyOf", [{}])[0]
                field_schema = first.get("properties", {}).get("field", {})
                print("    SET filter.field: type=", field_schema.get("type"), "->", field_schema.get("properties", {}))
    else:
        print("  [TABLEAU MCP] File not found:", ta_path)
    print()


def step3_prompt_vs_schema():
    """Step 3: Compare prompt filter format vs MCP schema filter format."""
    print("=== Step 3: Prompt vs Schema Alignment ===\n")
    print("  PROMPT (ADDENDUM_QUERY_ANALYTICS) says for filtered query:")
    print('    query.filters: { "field": "Region", "filterType": "SET", "values": ["East"] }')
    print()
    print("  MCP schema (query-datasource.json) requires for SET filter:")
    print('    "field": { "fieldCaption": "Region" }  (object, not string)')
    print()
    print("  MISMATCH: prompt uses field as string; schema expects field as object with fieldCaption.")
    print()


if __name__ == "__main__":
    step1_intent()
    step2_tool_schema()
    step3_prompt_vs_schema()
