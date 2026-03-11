"""Lightweight intent classification for prompt routing."""

INTENTS = ("query", "download", "inspect", "publish", "project", "general")

# Keywords per intent (lowercase)
_QUERY_KW = ("sales", "revenue", "forecast", "trend", "chart", "graph", "visualize", "data", "query", "how many", "top ", "show me", "list ", "break down", "compare", "aggregate", "count", "sum", "average")
_DOWNLOAD_KW = ("download", "export", "save", "get file", "twbx", "tdsx", "tflx")
_INSPECT_KW = ("inspect", "structure", "schema", "metadata", "connections", "calculated field", "parse")
_PUBLISH_KW = ("publish", "upload", "deploy", "push to", "update-datasource-data", "flag log")
_PROJECT_KW = ("project", "folder", "list projects", "projects named")

def classify(question: str) -> str:
    """Classify user intent. Returns query|download|inspect|publish|project|general."""
    intents = classify_multi(question)
    return intents[0] if intents else "general"


def classify_multi(question: str) -> list[str]:
    """Classify user intent; returns all matching intents for multi-intent injection."""
    if not question or not isinstance(question, str):
        return ["general"]
    q = question.lower().strip()
    if not q:
        return ["general"]

    matched = []
    # Publish often has attachments; check first
    if any(kw in q for kw in _PUBLISH_KW):
        matched.append("publish")
    if any(kw in q for kw in _DOWNLOAD_KW):
        matched.append("download")
    if any(kw in q for kw in _INSPECT_KW):
        matched.append("inspect")
    if any(kw in q for kw in _PROJECT_KW):
        matched.append("project")
    if any(kw in q for kw in _QUERY_KW):
        matched.append("query")

    if not matched:
        return ["general"]
    return matched
