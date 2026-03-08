-- Pass rate of current running WTQ eval(s)
-- Run: sqlite3 evaluation/eval_results.db < evaluation/queries/wtq_in_progress_pass_rate.sql

SELECT r.run_id,
       r.model,
       r.timestamp,
       COUNT(cr.id) AS cases_so_far,
       SUM(cr.passed) AS passed,
       ROUND(100.0 * SUM(cr.passed) / COUNT(cr.id), 1) AS pass_rate
FROM runs r
JOIN case_results cr ON cr.run_id = r.run_id
WHERE r.status = 'in_progress'
  AND json_extract(r.metadata, '$.eval_type') = 'wtq'
GROUP BY r.run_id, r.model, r.timestamp;
