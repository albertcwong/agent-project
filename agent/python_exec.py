"""Sandboxed Python execution for analytics. Runs code with provided datasets."""

import json
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

TIMEOUT = 60
RESULT_SIZE_LIMIT = 1 << 20  # 1MB

_RUNNER = r"""
import json
import sys

# Allowlist: analytics libs only
import math
try:
    import numpy as np
except ImportError:
    np = None
try:
    import pandas as pd
except ImportError:
    pd = None
try:
    import scipy
except ImportError:
    scipy = None
try:
    import statsmodels
except ImportError:
    statsmodels = None
try:
    import sklearn
except ImportError:
    sklearn = None

def _run():
    raw = sys.stdin.read()
    inp = json.loads(raw)
    code = inp.get("code", "")
    data = inp.get("data") or {}
    globals_ = {
        "data": data,
        "pd": pd,
        "np": np,
        "math": math,
        "json": json,
        "scipy": scipy,
        "statsmodels": statsmodels,
        "sklearn": sklearn,
    }
    out_buf = []
    def _print(*a, sep=" ", end="\n", **k):
        s = sep.join(str(x) for x in a) + end
        out_buf.append(s)
    globals_["print"] = _print
    exec(code, globals_)
    result = globals_.get("result")
    if result is None and "_" in globals_:
        result = globals_["_"]
    return "".join(out_buf), result

stdout, result = _run()
out = {"stdout": stdout, "result": result}
try:
    if hasattr(result, "to_dict") and callable(getattr(result, "to_dict", None)):
        out["result"] = result.to_dict(orient="records")
    elif hasattr(result, "tolist"):
        out["result"] = result.tolist()
    elif hasattr(result, "__iter__") and not isinstance(result, (str, dict)):
        out["result"] = list(result)
    elif result is not None and not isinstance(result, (str, int, float, bool, list, dict, type(None))):
        out["result"] = str(result)
except Exception:
    out["result"] = str(result) if result is not None else None
print(json.dumps(out))
"""


def execute_python(code: str, data: dict | None = None) -> str:
    """Run Python code with data. Returns JSON string with stdout, result, error."""
    if not code or not code.strip():
        return json.dumps({"stdout": "", "result": None, "error": "Empty code"})
    payload = json.dumps({"code": code, "data": data or {}})
    if len(payload) > RESULT_SIZE_LIMIT:
        return json.dumps({"stdout": "", "result": None, "error": "Input too large"})
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _RUNNER],
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"stdout": "", "result": None, "error": "Execution timed out"})
    except Exception as e:
        logger.exception("Python exec failed")
        return json.dumps({"stdout": "", "result": None, "error": str(e)})
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    err = proc.stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        return json.dumps({"stdout": out, "stderr": err, "result": None, "error": err or "Non-zero exit"})
    try:
        parsed = json.loads(out)
        if len(json.dumps(parsed)) > RESULT_SIZE_LIMIT:
            parsed["result"] = "(truncated: result too large)"
        return json.dumps(parsed)
    except json.JSONDecodeError:
        return json.dumps({"stdout": out, "result": None, "error": "Invalid output"})
