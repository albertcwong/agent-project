"""Query correctness evaluator — inspects actual query arguments."""

import json


def evaluate_query(
    tool_calls: list[dict],
    must_contain: dict | None = None,
) -> dict:
    results = {"pass": True, "errors": []}
    query_calls = [tc for tc in tool_calls if tc.get("name") == "query-datasource"]

    if not query_calls:
        if must_contain and ("aggregation" in must_contain or "fields" in must_contain or "limit" in must_contain):
            results["pass"] = False
            results["errors"].append("No query-datasource call found")
        return results

    query_args = query_calls[-1].get("arguments") or {}
    query = query_args.get("query")
    if isinstance(query, str):
        try:
            query = json.loads(query) if query.strip().startswith("{") else {}
        except Exception:
            query = {}
    query = query or {}

    # Handle fields as list of dicts (with function) or list of strings
    fields = query.get("fields") or []

    if must_contain:
        if "aggregation" in must_contain:
            agg = must_contain["aggregation"].upper()
            agg_found = False
            for f in fields:
                fn = (f.get("function") or f.get("aggregation") or f.get("aggregateFunction") or "") if isinstance(f, dict) else ""
                if isinstance(f, dict) and fn.upper() == agg:
                    agg_found = True
                    break
                if isinstance(f, str) and agg in str(f).upper():
                    agg_found = True
                    break
            if not agg_found:
                    results["pass"] = False
                    results["errors"].append(f"Expected aggregation {must_contain['aggregation']} not found")

        if "fields" in must_contain:
            expected = [x if isinstance(x, str) else x.get("fieldCaption", x) for x in must_contain["fields"]]
            actual = []
            for f in fields:
                if isinstance(f, dict):
                    actual.append(f.get("fieldCaption") or f.get("field") or str(f))
                else:
                    actual.append(str(f))
            filters = query.get("filters") or query.get("filter") or []
            filter_fields = []
            for flt in filters if isinstance(filters, list) else []:
                if isinstance(flt, dict) and (flt.get("field") or flt.get("fieldCaption")):
                    filter_fields.append(str(flt.get("field") or flt.get("fieldCaption")))
            for exp in expected:
                in_fields = any(exp.lower() in str(a).lower() for a in actual)
                in_filters = any(exp.lower() in str(f).lower() for f in filter_fields)
                if not in_fields and not in_filters:
                    results["pass"] = False
                    results["errors"].append(f"Expected field '{exp}' not in query")
                    break

        if "limit" in must_contain:
            limit = query.get("limit") or query.get("rowLimit")
            if limit != must_contain["limit"]:
                results["pass"] = False
                results["errors"].append(f"Expected limit {must_contain['limit']}, got {limit}")

        if "filters" in must_contain:
            filters = query.get("filters") or query.get("filter") or query_args.get("filters") or {}
            filter_str = json.dumps(filters) if isinstance(filters, dict) else str(filters)
            filter_str += json.dumps(query_args)  # also check full args
            expected_vals = must_contain["filters"]
            if not isinstance(expected_vals, list):
                expected_vals = [expected_vals]
            found = any(str(v).lower() in filter_str.lower() for v in expected_vals)
            if not found:
                results["pass"] = False
                results["errors"].append(f"Expected filter value in {expected_vals} not found in query")

    return results
