"""Merge hand-curated records with machine-written results into the published dist/."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .loader import ASPECT_UNITS, discover_claims, load_json, load_yaml, resolve_pointer, sha256
from .narrative import GENERATED_BANNER, render

VOLATILE_KEYS = {"generated_at"}


def _dump(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_claim(root: Path, claim) -> dict:
    record = load_yaml(claim.claim_file)
    reported = None
    reproduction_records = []
    for estimate_file in claim.estimate_files:
        estimate = load_yaml(estimate_file)
        if estimate["kind"] == "reported":
            reported = estimate
        else:
            reproduction_records.append((estimate_file, estimate))

    sources = [claim.claim_file, *claim.estimate_files]
    reproductions = []
    for estimate_file, estimate in reproduction_records:
        rid = estimate["reproduction_id"]
        repro_dir = claim.dir / "reproductions" / rid
        results = load_json(repro_dir / "results.json")
        run = load_json(repro_dir / "run.json")
        entrypoint = run["entrypoint"]
        sources += [repro_dir / "results.json", repro_dir / "run.json", repro_dir / entrypoint, repro_dir / "requirements.lock.txt"]
        figures = {}
        for aspect, pointer in estimate["figure_map"].items():
            figures[aspect] = {
                "value": resolve_pointer(results, pointer),
                "unit": ASPECT_UNITS[aspect],
                "source": f"claims/{claim.id}/reproductions/{rid}/results.json{pointer}",
            }
        reproductions.append(
            {
                "id": rid,
                "tool": estimate["tool"],
                "headline_scenario": estimate["headline_scenario"],
                "scenarios": estimate["scenarios"],
                "figures": figures,
                "deviations_from_reported": estimate.get("deviations_from_reported", []),
                "interpretation": estimate["interpretation"],
                "notes": estimate.get("notes", []),
                "results": results,
                "run": run,
                "artifacts": {
                    "code": f"claims/{claim.id}/reproductions/{rid}/{entrypoint}",
                    "results": f"claims/{claim.id}/reproductions/{rid}/results.json",
                    "run": f"claims/{claim.id}/reproductions/{rid}/run.json",
                    "lockfile": f"claims/{claim.id}/reproductions/{rid}/requirements.lock.txt",
                },
            }
        )

    comparisons = []
    reported_figures = (reported or {}).get("figures", {})
    for reproduction in reproductions:
        for aspect, figure in reproduction["figures"].items():
            if aspect in reported_figures:
                reported_value = reported_figures[aspect]["value"]
                comparisons.append(
                    {
                        "aspect": aspect,
                        "unit": figure["unit"],
                        "reported": reported_value,
                        "reproduced": figure["value"],
                        "ratio": round(figure["value"] / reported_value, 4) if reported_value else None,
                        "reproduction_id": reproduction["id"],
                    }
                )

    payload = {
        "schema_version": "1.0",
        "id": record["id"],
        "title": record["title"],
        "short_title": record["short_title"],
        "headline": record["headline"],
        "claim_type": record["claim_type"],
        "domain": record["domain"],
        "taxonomy": record["taxonomy"],
        "source": record["source"],
        "assertion": record["assertion"],
        "assumptions_as_reported": record["assumptions_as_reported"],
        "assessment": record["assessment"],
        "review": record["review"],
        "publication": record["publication"],
        "links": record.get("links", []),
        "reported": {"figures": reported_figures, "notes": (reported or {}).get("notes", [])},
        "reproductions": reproductions,
        "comparisons": comparisons,
        "provenance": {
            "build": {"tool": "qacclaims", "tool_version": __version__},
            "sources": [{"path": str(path.relative_to(root)), "sha256": sha256(path)} for path in sources],
        },
    }
    return payload


def attach_narrative(root: Path, claim, payload: dict) -> list[str]:
    """Render claims/<id>/narrative.md into the record. Returns unresolved-placeholder problems (empty = ok)."""
    summary, summary_problems = render(payload["assessment"]["summary_plain"], payload)
    if summary_problems:
        return [f"{claim.claim_file.relative_to(root)}: unresolved placeholder in summary_plain {item}" for item in summary_problems]
    payload["assessment"] = {**payload["assessment"], "summary_plain": summary}
    narrative_file = claim.dir / "narrative.md"
    if not narrative_file.exists():
        return []
    rendered, problems = render(narrative_file.read_text(encoding="utf-8"), payload)
    if problems:
        return [f"{narrative_file.relative_to(root)}: unresolved placeholder {item}" for item in problems]
    payload["narrative_markdown"] = rendered
    payload["provenance"]["sources"].append({"path": str(narrative_file.relative_to(root)), "sha256": sha256(narrative_file)})
    return []


def rendered_readme(payload: dict) -> str | None:
    if "narrative_markdown" not in payload:
        return None
    return GENERATED_BANNER + payload["narrative_markdown"].rstrip("\n") + "\n"


def build_all(root: Path, out_dir: Path, write_readmes: bool = True) -> dict[str, str]:
    """Write dist files under out_dir (and each claim's rendered README.md). Returns {relative path: sha256}."""
    written: dict[str, str] = {}
    index_entries = []
    for claim in discover_claims(root):
        payload = build_claim(root, claim)
        problems = attach_narrative(root, claim, payload)
        if problems:
            raise SystemExit("refusing to build: " + "; ".join(problems))
        readme = rendered_readme(payload)
        if readme is not None and write_readmes:
            (claim.dir / "README.md").write_text(readme, encoding="utf-8")
        target = out_dir / "claims" / f"{claim.id}.json"
        _dump(target, payload)
        digest = sha256(target)
        written[f"claims/{claim.id}.json"] = digest
        index_entries.append(
            {
                "id": payload["id"],
                "title": payload["title"],
                "short_title": payload["short_title"],
                "headline": payload["headline"],
                "domain": payload["domain"],
                "taxonomy": payload["taxonomy"],
                "claim_type": payload["claim_type"],
                "year": payload["source"]["year"],
                "publication_status": payload["publication"]["status"],
                "reproduction_status": payload["assessment"]["reproduction_status"],
                "path": f"claims/{claim.id}.json",
                "sha256": digest,
            }
        )
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # No git SHA inside dist/: the commit that contains dist/ is the version, and embedding
    # the SHA would make a committed dist/ permanently "stale" under --check.
    build_info = {"tool": "qacclaims", "tool_version": __version__}
    _dump(out_dir / "index.json", {"schema_version": "1.0", "generated_at": generated_at, "build": build_info, "claims": index_entries})
    written["index.json"] = sha256(out_dir / "index.json")
    _dump(out_dir / "manifest.json", {"schema_version": "1.0", "generated_at": generated_at, "build": build_info, "files": written})
    return written


def _strip_volatile(payload):
    if isinstance(payload, dict):
        return {k: _strip_volatile(v) for k, v in payload.items() if k not in VOLATILE_KEYS}
    if isinstance(payload, list):
        return [_strip_volatile(v) for v in payload]
    return payload


def check_fresh(root: Path, dist_dir: Path) -> list[str]:
    """Rebuild into a temp dir and report files whose content differs from dist_dir (ignoring timestamps)."""
    stale = []
    for claim in discover_claims(root):
        payload = build_claim(root, claim)
        if attach_narrative(root, claim, payload):
            continue  # validation reports unresolved placeholders; nothing to compare here
        readme = rendered_readme(payload)
        committed = claim.dir / "README.md"
        if readme is None:
            continue
        if not committed.exists() or committed.read_text(encoding="utf-8") != readme:
            stale.append(f"{committed.relative_to(root)}: out of date with narrative.md (run `qacclaims build`)")
    with tempfile.TemporaryDirectory() as tmp:
        fresh_dir = Path(tmp)
        build_all(root, fresh_dir, write_readmes=False)
        fresh_files = sorted(p.relative_to(fresh_dir) for p in fresh_dir.rglob("*.json"))
        committed_files = sorted(p.relative_to(dist_dir) for p in dist_dir.rglob("*.json")) if dist_dir.exists() else []
        for rel in sorted(set(fresh_files) | set(committed_files)):
            fresh_path, committed_path = fresh_dir / rel, dist_dir / rel
            if not committed_path.exists():
                stale.append(f"dist/{rel}: missing (run `qacclaims build`)")
            elif not fresh_path.exists():
                stale.append(f"dist/{rel}: no longer produced (run `qacclaims build`)")
            elif rel.name == "manifest.json":
                continue  # covered by the per-file comparisons below
            elif _strip_volatile(load_json(fresh_path)) != _strip_volatile(load_json(committed_path)):
                stale.append(f"dist/{rel}: out of date (run `qacclaims build`)")
    return stale
