"""SQLite persistence for evaluation runs."""

import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "eval_results.db"


def _get_db() -> sqlite3.Connection:
    from evaluation.migrate import migrate
    migrate()
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            model TEXT,
            provider TEXT,
            prompt_version TEXT,
            git_commit TEXT,
            total_cases INTEGER,
            passed INTEGER,
            failed INTEGER,
            total_seconds REAL,
            metadata TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            completed_at TEXT,
            error TEXT
        );
        CREATE TABLE IF NOT EXISTS case_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            case_id TEXT NOT NULL,
            category TEXT,
            passed INTEGER NOT NULL,
            elapsed_seconds REAL,
            answer_preview TEXT,
            tool_sequence TEXT,
            evaluations TEXT,
            error TEXT,
            trace TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_case_results_run
            ON case_results(run_id);
        CREATE INDEX IF NOT EXISTS idx_case_results_case
            ON case_results(case_id);
        CREATE INDEX IF NOT EXISTS idx_runs_timestamp
            ON runs(timestamp);
    """)
    return db


def _prompt_version(system_prompt: str) -> str:
    """Short hash of the system prompt for version tracking."""
    return hashlib.sha256(system_prompt.encode()).hexdigest()[:12]


def _git_commit() -> str | None:
    """Get current git commit hash, or None if not in a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def start_run(
    run_id: str,
    model: str | None = None,
    provider: str = "openai",
    system_prompt: str = "",
    metadata: dict | None = None,
) -> None:
    """Insert a runs row at the beginning with status 'in_progress'."""
    db = _get_db()
    try:
        db.execute(
            """INSERT INTO runs
               (run_id, timestamp, model, provider, prompt_version,
                git_commit, total_cases, passed, failed, total_seconds, metadata, status)
               VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?, 'in_progress')""",
            (
                run_id,
                datetime.now(timezone.utc).isoformat(),
                model,
                provider,
                _prompt_version(system_prompt),
                _git_commit(),
                json.dumps(metadata or {}),
            ),
        )
        db.commit()
    finally:
        db.close()


def save_case_result(run_id: str, result: dict) -> None:
    """Insert a single case_results row immediately after a case completes."""
    db = _get_db()
    try:
        db.execute(
            """INSERT INTO case_results
               (run_id, case_id, category, passed, elapsed_seconds,
                answer_preview, tool_sequence, evaluations, error, trace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                result.get("id", ""),
                result.get("category", ""),
                1 if result.get("pass") else 0,
                result.get("elapsed_seconds"),
                result.get("answer_preview", ""),
                json.dumps(result.get("tool_calls", [])),
                json.dumps(result.get("evaluations", {})),
                result.get("error"),
                result.get("trace"),
            ),
        )
        db.commit()
    finally:
        db.close()


def complete_run(run_id: str, total_seconds: float, results: list[dict]) -> None:
    """Update the runs row with final summary and mark as completed."""
    passed = sum(1 for r in results if r.get("pass"))
    failed = len(results) - passed
    db = _get_db()
    try:
        db.execute(
            """UPDATE runs
               SET status = 'completed', total_cases = ?, passed = ?, failed = ?,
                   total_seconds = ?, completed_at = ?
               WHERE run_id = ?""",
            (
                len(results),
                passed,
                failed,
                total_seconds,
                datetime.now(timezone.utc).isoformat(),
                run_id,
            ),
        )
        db.commit()
    finally:
        db.close()


def fail_run(run_id: str, total_seconds: float, error_message: str) -> None:
    """Mark a run as failed if an unrecoverable error occurs."""
    db = _get_db()
    try:
        db.execute(
            """UPDATE runs
               SET status = 'failed', total_seconds = ?, completed_at = ?, error = ?
               WHERE run_id = ?""",
            (
                total_seconds,
                datetime.now(timezone.utc).isoformat(),
                error_message,
                run_id,
            ),
        )
        db.commit()
    finally:
        db.close()


def get_resumable_run(run_id: str) -> dict | None:
    """Return run metadata if run exists and status is in_progress or failed; else None."""
    db = _get_db()
    row = db.execute(
        "SELECT run_id, timestamp, model, provider, metadata FROM runs WHERE run_id = ? AND status IN ('in_progress', 'failed')",
        (run_id,),
    ).fetchone()
    db.close()
    return dict(row) if row else None


def get_run_results(run_id: str) -> list[dict]:
    """Fetch all case_results for a run, converted to result dict format for complete_run."""
    db = _get_db()
    rows = db.execute(
        """SELECT case_id, category, passed, elapsed_seconds, answer_preview,
                  tool_sequence, evaluations, error, trace
           FROM case_results WHERE run_id = ? ORDER BY id""",
        (run_id,),
    ).fetchall()
    db.close()
    out = []
    for r in rows:
        tool_calls = []
        evaluations = {}
        try:
            if r["tool_sequence"]:
                tool_calls = json.loads(r["tool_sequence"])
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            if r["evaluations"]:
                evaluations = json.loads(r["evaluations"])
        except (json.JSONDecodeError, TypeError):
            pass
        out.append({
            "id": r["case_id"],
            "category": r["category"] or "",
            "pass": bool(r["passed"]),
            "elapsed_seconds": r["elapsed_seconds"],
            "answer_preview": r["answer_preview"] or "",
            "tool_calls": tool_calls,
            "evaluations": evaluations,
            "error": r["error"],
            "trace": r["trace"],
        })
    return out


def get_case_history(case_id: str, limit: int = 20) -> list[dict]:
    """Show pass/fail history for a specific case across runs."""
    db = _get_db()
    rows = db.execute(
        """SELECT r.timestamp, r.model, r.prompt_version, r.git_commit,
                  cr.passed, cr.elapsed_seconds, cr.error
           FROM case_results cr
           JOIN runs r ON r.run_id = cr.run_id
           WHERE cr.case_id = ? AND r.status != 'in_progress'
           ORDER BY r.timestamp DESC
           LIMIT ?""",
        (case_id, limit),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_flaky_cases(min_runs: int = 5) -> list[dict]:
    """Find cases that sometimes pass and sometimes fail."""
    db = _get_db()
    rows = db.execute(
        """SELECT cr.case_id,
                  COUNT(*) as total_runs,
                  SUM(cr.passed) as passes,
                  COUNT(*) - SUM(cr.passed) as failures,
                  ROUND(100.0 * SUM(cr.passed) / COUNT(*), 1) as pass_rate
           FROM case_results cr
           JOIN runs r ON r.run_id = cr.run_id
           WHERE r.status = 'completed'
           GROUP BY cr.case_id
           HAVING COUNT(*) >= ? AND SUM(cr.passed) > 0 AND SUM(cr.passed) < COUNT(*)
           ORDER BY pass_rate ASC""",
        (min_runs,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_regression_candidates(last_n_runs: int = 5) -> list[dict]:
    """Find cases that passed in earlier runs but failed in recent ones."""
    db = _get_db()
    rows = db.execute(
        """WITH ranked AS (
             SELECT cr.case_id, cr.passed, r.timestamp,
                    ROW_NUMBER() OVER (PARTITION BY cr.case_id ORDER BY r.timestamp DESC) as rn
             FROM case_results cr
             JOIN runs r ON r.run_id = cr.run_id
             WHERE r.status = 'completed'
           )
           SELECT case_id,
                  SUM(CASE WHEN rn <= ? THEN 1 - passed ELSE 0 END) as recent_failures,
                  SUM(CASE WHEN rn > ? THEN passed ELSE 0 END) as older_passes
           FROM ranked
           GROUP BY case_id
           HAVING recent_failures > 0 AND older_passes > 0
           ORDER BY recent_failures DESC""",
        (last_n_runs, last_n_runs),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_pass_rate_trend(limit: int = 20) -> list[dict]:
    """Pass rate over time (per run, most recent first)."""
    db = _get_db()
    rows = db.execute(
        """SELECT run_id, timestamp, model, provider, prompt_version, git_commit,
                  total_cases, passed, failed, total_seconds,
                  ROUND(100.0 * passed / total_cases, 1) as pass_rate
           FROM runs
           WHERE status != 'in_progress' AND total_cases > 0
           ORDER BY timestamp DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_last_failure_details(limit: int = 1) -> list[dict]:
    """Most recent failed case(s) with full details."""
    db = _get_db()
    rows = db.execute(
        """SELECT r.run_id, r.timestamp, r.model, r.provider, r.git_commit,
                  cr.case_id, cr.category, cr.elapsed_seconds, cr.answer_preview,
                  cr.tool_sequence, cr.evaluations, cr.error, cr.trace
           FROM case_results cr
           JOIN runs r ON r.run_id = cr.run_id
           WHERE cr.passed = 0 AND r.status != 'in_progress'
           ORDER BY r.timestamp DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]
