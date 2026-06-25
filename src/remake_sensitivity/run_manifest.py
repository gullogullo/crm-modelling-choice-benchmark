from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .metric_definitions import METRIC_SCHEMA_VERSION


def _hash_files(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        digest.update(str(path).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def create_manifest(
    root: Path,
    config_path: Path,
    record_paths: list[Path],
    additional_input_paths: list[Path] | None = None,
    *,
    input_record_count: int,
    pipeline_version: str,
    metric_schema_version: str = METRIC_SCHEMA_VERSION,
) -> dict[str, Any]:
    code_paths = sorted((root / "src" / "remake_sensitivity").glob("*.py"))
    input_paths = record_paths + [config_path] + (additional_input_paths or [])
    timestamp = datetime.now(timezone.utc).isoformat()
    code_hash = _hash_files(code_paths)
    config_hash = _hash_files([config_path])
    input_data_hash = _hash_files(input_paths)
    commit = _git_commit(root)
    notes = []
    if commit is None:
        notes.append("Git metadata unavailable; git_commit is null.")
    run_seed = f"{timestamp}|{code_hash}|{config_hash}|{input_data_hash}"
    run_id = hashlib.sha256(run_seed.encode()).hexdigest()[:16]
    return {
        "run_id": run_id,
        "timestamp_utc": timestamp,
        "git_commit": commit,
        "code_hash": code_hash,
        "config_hash": config_hash,
        "input_data_hash": input_data_hash,
        "input_record_count": input_record_count,
        "pipeline_version": pipeline_version,
        "metric_schema_version": metric_schema_version,
        "notes": notes,
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
