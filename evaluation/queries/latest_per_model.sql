-- Latest completed run per model with pass rate and avg time per case
-- Run: sqlite3 evaluation/eval_results.db < evaluation/queries/latest_per_model.sql

WITH latest AS (
  SELECT run_id,
         model,
         ROW_NUMBER() OVER (PARTITION BY COALESCE(model, 'default') ORDER BY timestamp DESC) AS rn
  FROM runs
  WHERE total_cases > 0
)
SELECT r.model,
       r.timestamp,
       r.passed,
       r.total_cases,
       ROUND(100.0 * r.passed / r.total_cases, 1) AS pass_rate,
       ROUND(r.total_seconds, 1) AS total_run_seconds,
       ROUND(AVG(cr.elapsed_seconds), 1) AS avg_seconds_per_case
FROM runs r
JOIN latest l ON r.run_id = l.run_id AND COALESCE(r.model, 'default') = COALESCE(l.model, 'default')
JOIN case_results cr ON cr.run_id = r.run_id
WHERE l.rn = 1
  AND r.model IS NOT NULL
GROUP BY r.model, r.run_id, r.timestamp, r.passed, r.total_cases, r.total_seconds
ORDER BY pass_rate DESC;
