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

# Security policy: Bandit rules this project always treats as HIGH (release blockers),
# whatever severity Bandit itself reports (Bandit rates SQL injection MEDIUM and
# hard-coded passwords LOW).
POLICY_SEVERITY = {
    "B608": "HIGH",  # SQL built with string formatting (SQL injection)
    "B105": "HIGH",  # hard-coded password string
    "B106": "HIGH",  # hard-coded password argument
    "B107": "HIGH",  # hard-coded password default
}

# Bandit rules skipped as noise: importing subprocess and calling it with a fixed
# argument list (no shell) is how this pipeline runs git / pytest / ruff.
BANDIT_SKIP = ["B404", "B603", "B607"]

AUTO, MANUAL, BLOCKED = "AUTO DEPLOY", "MANUAL APPROVAL", "RELEASE BLOCKED"


def report_path(name: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return REPORT_DIR / f"{name}.json"
