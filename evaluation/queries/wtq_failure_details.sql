-- Most recent WTQ failure(s) with full details
-- Run: sqlite3 evaluation/eval_results.db < evaluation/queries/wtq_failure_details.sql

SELECT r.run_id,
       r.timestamp,
       r.model,
       cr.case_id,
       cr.elapsed_seconds,
       cr.answer_preview,
       cr.tool_sequence,
       cr.evaluations,
       cr.error,
       cr.trace
FROM case_results cr
JOIN runs r ON r.run_id = cr.run_id
WHERE cr.passed = 0
  AND cr.category = 'wtq'
  AND r.status != 'in_progress'
ORDER BY r.timestamp DESC
LIMIT 10;
