"""
rewrite_code.py – deterministic code-editing tool for regression_pipeline.py.
"""

from __future__ import annotations

from datetime import datetime
import ast
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parents[1]
REGRESSION_FILE = BASE_DIR / "regression_pipeline.py"
BACKUP_DIR = BASE_DIR / "outputs" / "code_backups"
START_MARKER = "# BEGIN_MODEL_SETTINGS"
END_MARKER = "# END_MODEL_SETTINGS"

os.makedirs(BACKUP_DIR, exist_ok=True)


def _load_settings_block(code: str) -> Dict[str, Any]:
    pattern = re.compile(rf"{START_MARKER}\s*(.*?)\s*{END_MARKER}", re.DOTALL)
    match = pattern.search(code)
    if not match:
        raise ValueError("MODEL_SETTINGS block not found in regression_pipeline.py")
    block = match.group(1)
    dict_match = re.search(r"=\s*(\{.*\})", block, re.DOTALL)
    if not dict_match:
        raise ValueError("MODEL_SETTINGS dictionary not found.")
    literal = dict_match.group(1)
    settings = ast.literal_eval(literal)
    return dict(settings)


def _format_settings(settings: Dict[str, Any]) -> str:
    lines = ["MODEL_SETTINGS: Dict[str, Any] = {"]
    for key, value in settings.items():
        formatted_value = json.dumps(value)
        lines.append(f'    "{key}": {formatted_value},')
    lines.append("}")
    return "\n".join(lines)


def _apply_changes(settings: Dict[str, Any], instructions: str) -> List[Dict[str, Any]]:
    try:
        payload = json.loads(instructions)
    except json.JSONDecodeError:
        payload = {"changes": []}
    applied: List[Dict[str, Any]] = []
    for change in payload.get("changes", []):
        param = change.get("parameter")
        value = change.get("value")
        if param is None:
            continue
        settings[param] = value
        applied.append({"parameter": param, "value": value})
    return applied


def rewrite_code(instructions: str) -> Dict[str, Any]:
    """Apply structured updates to MODEL_SETTINGS."""
    code = REGRESSION_FILE.read_text(encoding="utf-8")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"regression_pipeline_{timestamp}.py"
    shutil.copyfile(REGRESSION_FILE, backup_path)

    settings = _load_settings_block(code)
    applied_changes = _apply_changes(settings, instructions)

    pattern = re.compile(rf"({START_MARKER}\s*)(.*?)(\s*{END_MARKER})", re.DOTALL)
    formatted_block = _format_settings(settings)
    new_code = pattern.sub(rf"\1{formatted_block}\3", code)

    REGRESSION_FILE.write_text(new_code, encoding="utf-8")

    return {
        "status": "updated",
        "backup_file": str(backup_path),
        "applied_changes": applied_changes,
    }
