"""Load WikiTableQuestions dataset: questions and tables."""

import csv
from pathlib import Path

from evaluation.wtq.adapter import WTQTable


def load_wtq_dataset(
    data_dir: Path,
    split: str = "test",
    limit: int | None = None,
) -> tuple[list[dict], dict[str, WTQTable]]:
    """
    Load WTQ questions and tables.
    Returns (questions, tables_by_id).

    Expected structure:
      data_dir/
        data/
          pristine-unseen-tables.tsv   # Test questions
          training.tsv                  # Train questions
        csv/
          xxx-csv/yyy.csv or yyy.tsv   # Table data
    """
    if split == "test":
        questions_path = data_dir / "data" / "pristine-unseen-tables.tsv"
    else:
        questions_path = data_dir / "data" / "training.tsv"

    if not questions_path.exists():
        return [], {}

    questions = []
    with open(questions_path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            questions.append({
                "id": row.get("id", ""),
                "question": row.get("utterance", ""),
                "table_id": row.get("context", ""),
                "answer": row.get("targetValue", ""),
            })

    if limit:
        questions = questions[:limit]

    table_ids = set(q["table_id"] for q in questions)
    tables: dict[str, WTQTable] = {}

    for table_path_str in table_ids:
        table_path = data_dir / table_path_str
        if not table_path.exists():
            continue
        table_id = table_path_str.replace("/", "_").replace(".csv", "").replace(".tsv", "")
        tables[table_id] = WTQTable.from_file(table_id, table_path)
        for q in questions:
            if q["table_id"] == table_path_str:
                q["datasource_id"] = table_id

    return questions, tables
