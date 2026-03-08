-- Pass rate of current running eval(s)
-- Run: sqlite3 evaluation/eval_results.db < evaluation/queries/in_progress_pass_rate.sql

SELECT r.run_id,
       r.model,
       r.provider,
       r.timestamp,
       COUNT(cr.id) AS cases_so_far,
       SUM(cr.passed) AS passed,
       ROUND(100.0 * SUM(cr.passed) / COUNT(cr.id), 1) AS pass_rate,
       ROUND(SUM(cr.elapsed_seconds), 1) AS total_seconds_so_far
FROM runs r
JOIN case_results cr ON cr.run_id = r.run_id
WHERE r.status = 'in_progress'
GROUP BY r.run_id, r.model, r.provider, r.timestamp
ORDER BY r.timestamp DESC;
