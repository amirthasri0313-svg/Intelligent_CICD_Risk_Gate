"""Central settings for the Intelligent CI/CD Risk Gate.

Every pipeline stage writes its result as JSON into REPORT_DIR, so the
GitHub Actions jobs, the local pipeline and the dashboard all read the same data.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT_DIR = Path(os.environ.get("RISKGATE_REPORTS", ROOT / "reports"))
HISTORY_FILE = REPORT_DIR / "history.json"
MODEL_FILE = Path(os.environ.get("RISKGATE_MODEL", ROOT / "model" / "jit_model.joblib"))

# Folders that are never scanned as application code
EXCLUDE_DIRS = {".git", ".github", "__pycache__", ".venv", "venv", "env", "reports",
                "model", ".pytest_cache", ".ruff_cache", "node_modules"}

# Risk score R = W_EVAL * E + W_HIST * H   (0 = safe, 100 = very risky)
W_EVAL = 0.65
W_HIST = 0.35

# Gate bands on the risk score
AUTO_MAX = 30      # 0-30   -> AUTO DEPLOY
MANUAL_MAX = 70    # 31-70  -> MANUAL APPROVAL ; 71-100 -> RELEASE BLOCKED

# Coverage below this adds risk
COVERAGE_TARGET = 0.80

AUTO, MANUAL, BLOCKED = "AUTO DEPLOY", "MANUAL APPROVAL", "RELEASE BLOCKED"


def report_path(name: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return REPORT_DIR / f"{name}.json"
