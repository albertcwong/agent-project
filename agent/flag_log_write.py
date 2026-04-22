"""Parse FLAGS_JSON from execute_python output for deterministic Flag Log write."""

import json
import logging

logger = logging.getLogger(__name__)


def parse_flags_json(result_str: str) -> dict | None:
    """Extract FLAGS_JSON line from result, parse JSON. Returns {flag_records, resolved_flag_ids?, datasourceId} or None."""
    if not result_str or "FLAGS_JSON:" not in result_str:
        return None
    for line in result_str.split("\n"):
        line = line.strip()
        if line.startswith("FLAGS_JSON:"):
            try:
                raw = line[len("FLAGS_JSON:"):].strip()
                data = json.loads(raw)
                if isinstance(data, dict) and data.get("flag_records") is not None and data.get("datasourceId"):
                    return data
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Failed to parse FLAGS_JSON: %s", e)
            return None
    return None
