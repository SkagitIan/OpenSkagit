"""
Assist in rolling regression_pipeline.py back to the latest backup.
"""

from __future__ import annotations

from pathlib import Path
import shutil

BASE_DIR = Path(__file__).resolve().parents[1]
REGRESSION_FILE = BASE_DIR / "regression_pipeline.py"
BACKUP_DIR = BASE_DIR / "outputs" / "code_backups"


def revert_last_change():
    backups = sorted(BACKUP_DIR.glob("regression_pipeline_*.py"))
    if not backups:
        return {"status": "noop", "detail": "No backups available."}

    latest = backups[-1]
    shutil.copyfile(latest, REGRESSION_FILE)
    return {"status": "reverted", "restored_from": str(latest)}
