"""Pipeline history: one JSON file (reports/history.json) shared by the
GitHub Actions pipeline, the local pipeline and the dashboard."""
import json
from datetime import datetime, timezone

from config import HISTORY_FILE, REPORT_DIR


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load():
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save(runs):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(runs, indent=1), encoding="utf-8")


def add(record):
    runs = load()
    record["id"] = (max((r.get("id", 0) for r in runs), default=0) + 1)
    record.setdefault("created_at", now())
    runs.append(record)
    save(runs)
    return record["id"]


def update(run_id, **fields):
    runs = load()
    for r in runs:
        if r.get("id") == run_id:
            r.update(fields)
            save(runs)
            return r
    return None


def get(run_id):
    return next((r for r in load() if r.get("id") == run_id), None)
