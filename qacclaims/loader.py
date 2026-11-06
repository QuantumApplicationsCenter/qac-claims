"""Discover claim directories and load their files."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ASPECT_UNITS = {
    "logical_qubits": "count",
    "toffoli_count": "count",
    "t_count": "count",
    "physical_qubits": "count",
    "runtime_seconds": "seconds",
    "code_distance": "count",
}


def find_root(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "schemas").is_dir() and (candidate / "claims").is_dir():
            return candidate
    raise SystemExit("not inside a qac-claims checkout (no schemas/ and claims/ found)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_schema(root: Path, name: str) -> dict:
    return load_json(root / "schemas" / f"{name}.schema.json")


ENTRYPOINTS = ("notebook.ipynb", "reproduce.py")


@dataclass
class Reproduction:
    id: str
    dir: Path
    results: Path
    run: Path
    lockfile: Path

    @property
    def entrypoints(self) -> list[Path]:
        """The entry points present in the directory; a valid reproduction has exactly one."""
        return [self.dir / name for name in ENTRYPOINTS if (self.dir / name).exists()]

    @property
    def entrypoint(self) -> Path | None:
        found = self.entrypoints
        return found[0] if len(found) == 1 else None


@dataclass
class ClaimDir:
    id: str
    dir: Path
    claim_file: Path
    estimate_files: list[Path] = field(default_factory=list)
    reproductions: list[Reproduction] = field(default_factory=list)


def discover_claims(root: Path) -> list[ClaimDir]:
    claims: list[ClaimDir] = []
    for directory in sorted((root / "claims").iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        claim = ClaimDir(id=directory.name, dir=directory, claim_file=directory / "claim.yaml")
        estimates = directory / "estimates"
        if estimates.is_dir():
            claim.estimate_files = sorted(estimates.glob("*.yaml"))
        reproductions = directory / "reproductions"
        if reproductions.is_dir():
            for repro in sorted(reproductions.iterdir()):
                if repro.is_dir():
                    claim.reproductions.append(
                        Reproduction(
                            id=repro.name,
                            dir=repro,
                            results=repro / "results.json",
                            run=repro / "run.json",
                            lockfile=repro / "requirements.lock.txt",
                        )
                    )
        claims.append(claim)
    return claims


def resolve_pointer(document, pointer: str):
    """Resolve a JSON pointer of the form '#/a/b/0/c'. Raises KeyError/IndexError when absent."""
    if not pointer.startswith("#/"):
        raise KeyError(pointer)
    node = document
    for token in pointer[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        else:
            node = node[token]
    return node
