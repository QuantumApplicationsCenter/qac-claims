"""Rerun a reproduction (notebook or script) in its pinned environment and compare its results."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .loader import ENTRYPOINTS, load_json, sha256

IGNORED_IN_COMPARE = ("generated_at",)
OUTPUTS = {"results.json", "run.json", "requirements.lock.txt"}


def _flatten(node, trail=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _flatten(value, f"{trail}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _flatten(value, f"{trail}/{index}")
    else:
        yield trail, node


def diff_results(committed: dict, fresh: dict) -> list[str]:
    left = {k: v for k, v in _flatten(committed) if not k.endswith(IGNORED_IN_COMPARE)}
    right = {k: v for k, v in _flatten(fresh) if not k.endswith(IGNORED_IN_COMPARE)}
    diffs = []
    for key in sorted(set(left) | set(right)):
        if left.get(key, "<absent>") != right.get(key, "<absent>"):
            diffs.append(f"{key}: committed={left.get(key, '<absent>')!r} fresh={right.get(key, '<absent>')!r}")
    return diffs


def _git_user(root: Path) -> str | None:
    try:
        name = subprocess.run(["git", "config", "user.name"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
        return name or None
    except Exception:
        return None


def _python_version(python: str) -> str:
    return subprocess.run([python, "-c", "import platform; print(platform.python_version())"], capture_output=True, text=True, check=True).stdout.strip()


def _freeze(python: str) -> str:
    out = subprocess.run([python, "-m", "pip", "freeze"], capture_output=True, text=True, check=True).stdout
    lines = [line for line in out.splitlines() if line and "qacclaims" not in line and "@ file://" not in line and not line.startswith("-e ")]
    return "\n".join(sorted(lines)) + "\n"


def find_entrypoint(repro_dir: Path) -> Path:
    found = [repro_dir / name for name in ENTRYPOINTS if (repro_dir / name).exists()]
    if len(found) != 1:
        raise SystemExit(f"{repro_dir} needs exactly one of {', '.join(ENTRYPOINTS)} (found {len(found)})")
    return found[0]


def command_for(entrypoint: Path, python: str, timeout: int) -> list[str]:
    if entrypoint.suffix == ".ipynb":
        return [
            python, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute",
            f"--ExecutePreprocessor.timeout={timeout}", "--ExecutePreprocessor.kernel_name=python3",
            "--output", "executed.ipynb", entrypoint.name,
        ]
    return [python, entrypoint.name]


def execute(
    root: Path,
    repro_dir: Path,
    python: str | None = None,
    write: bool = False,
    operator: str | None = None,
    github: str | None = None,
    automation: str | None = None,
    refresh_lock: bool = False,
    timeout: int = 3600,
) -> tuple[list[str], float]:
    python = python or sys.executable
    repro_dir = repro_dir.resolve()
    entrypoint = find_entrypoint(repro_dir)
    committed_results = load_json(repro_dir / "results.json") if (repro_dir / "results.json").exists() else None
    command = command_for(entrypoint, python, timeout)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        # Copy the reproduction's own inputs (everything except the files it produces).
        for item in repro_dir.iterdir():
            if item.name in OUTPUTS:
                continue
            if item.is_dir():
                shutil.copytree(item, work / item.name)
            else:
                shutil.copy2(item, work / item.name)
        started = time.time()
        try:
            proc = subprocess.run(command, cwd=work, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise SystemExit(f"{entrypoint.name} did not finish within {timeout}s")
        duration = round(time.time() - started, 2)
        if proc.returncode != 0:
            raise SystemExit(f"{entrypoint.name} failed after {duration}s:\n{proc.stderr[-4000:]}")
        fresh_results_path = work / "results.json"
        if not fresh_results_path.exists():
            raise SystemExit(f"{entrypoint.name} ran but did not write results.json")
        fresh_results = load_json(fresh_results_path)
        diffs = diff_results(committed_results, fresh_results) if committed_results else []

        if write:
            if entrypoint.suffix == ".ipynb":
                shutil.copy2(work / "executed.ipynb", entrypoint)
            shutil.copy2(fresh_results_path, repro_dir / "results.json")
            lockfile = repro_dir / "requirements.lock.txt"
            if refresh_lock or not lockfile.exists():
                lockfile.write_text(_freeze(python), encoding="utf-8")
            run_record = {
                "schema_version": "1.0",
                "reproduction_id": repro_dir.name,
                "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "executed_by": {"name": operator or _git_user(root) or "unknown"},
                "host": {"platform": platform.platform(), "machine": platform.machine()},
                "duration_seconds": duration,
                "python": _python_version(python),
                "lockfile": "requirements.lock.txt",
                "entrypoint": entrypoint.name,
                "entrypoint_sha256": sha256(entrypoint),
                "results_sha256": sha256(repro_dir / "results.json"),
                "lockfile_sha256": sha256(lockfile),
                "command": " ".join(command),
            }
            if github:
                run_record["executed_by"]["github"] = github
            if automation:
                run_record["executed_by"]["automation"] = automation
            (repro_dir / "run.json").write_text(json.dumps(run_record, indent=2) + "\n", encoding="utf-8")
    return diffs, duration
