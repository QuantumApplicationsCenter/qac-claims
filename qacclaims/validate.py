"""Schema validation plus the cross-file rules that keep the registry honest."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import best_match

from .narrative import render
from .loader import (
    ASPECT_UNITS,
    ClaimDir,
    discover_claims,
    load_json,
    load_schema,
    load_yaml,
    resolve_pointer,
    sha256,
)


@dataclass
class Problem:
    path: str
    message: str
    level: str = "error"

    def __str__(self) -> str:
        return f"[{self.level}] {self.path}: {self.message}"


def _schema_problems(instance, schema: dict, path: str) -> list[Problem]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    problems = []
    for error in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in error.absolute_path) or "<root>"
        message = error.message
        if error.context:
            closest = best_match(error.context)
            inner = "/".join(str(p) for p in closest.absolute_path) or "<root>"
            message = f"{message}; closest cause at {inner}: {closest.message}"
        problems.append(Problem(f"{path}#{where}", message))
    return problems


def _numeric_leaves(node, trail: str = "") -> list[str]:
    found = []
    if isinstance(node, bool):
        return found
    if isinstance(node, (int, float)):
        found.append(trail or "<root>")
    elif isinstance(node, dict):
        for key, value in node.items():
            found.extend(_numeric_leaves(value, f"{trail}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_numeric_leaves(value, f"{trail}/{index}"))
    return found


def _notebook_is_executed(path: Path) -> bool:
    try:
        notebook = load_json(path)
    except Exception:
        return False
    return any(cell.get("outputs") for cell in notebook.get("cells", []) if cell.get("cell_type") == "code")


def _lock_pins(lockfile: Path) -> dict[str, str]:
    pins = {}
    for line in lockfile.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;]+)", line.strip())
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - stop at the first hop
        return None


def _doi_resolves(doi: str) -> bool:
    """A DOI resolves if doi.org answers with a redirect (publisher landing pages often block bots)."""
    request = urllib.request.Request(f"https://doi.org/{doi}", method="HEAD", headers={"User-Agent": "qacclaims"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=15) as response:
            return 200 <= response.status < 400
    except urllib.error.HTTPError as error:
        return 300 <= error.code < 400
    except Exception:
        return False


def validate_claim(root: Path, claim: ClaimDir, schemas: dict[str, dict], online: bool = False) -> list[Problem]:
    rel = lambda p: str(p.relative_to(root))  # noqa: E731
    problems: list[Problem] = []

    if not claim.claim_file.exists():
        return [Problem(rel(claim.dir), "missing claim.yaml")]
    record = load_yaml(claim.claim_file)
    problems += _schema_problems(record, schemas["claim"], rel(claim.claim_file))
    if problems:
        return problems

    if record["id"] != claim.id:
        problems.append(Problem(rel(claim.claim_file), f"id '{record['id']}' must equal directory name '{claim.id}'"))

    # --- estimates ---------------------------------------------------------
    reported = None
    reproductions: list[tuple[Path, dict]] = []
    for estimate_file in claim.estimate_files:
        estimate = load_yaml(estimate_file)
        est_problems = _schema_problems(estimate, schemas["estimate"], rel(estimate_file))
        problems += est_problems
        if isinstance(estimate, dict) and estimate.get("kind") == "reproduction":
            numeric = _numeric_leaves(estimate)
            if numeric:
                problems.append(Problem(rel(estimate_file), f"reproduction records may not contain numbers (found at {', '.join(numeric[:5])}); numbers come only from results.json"))
        if est_problems:
            continue
        if estimate["claim_id"] != claim.id:
            problems.append(Problem(rel(estimate_file), f"claim_id '{estimate['claim_id']}' does not match '{claim.id}'"))
        if estimate["kind"] == "reported":
            if reported is not None:
                problems.append(Problem(rel(estimate_file), "more than one reported estimate"))
            reported = estimate
        else:
            reproductions.append((estimate_file, estimate))
    if reported is None:
        problems.append(Problem(rel(claim.dir / "estimates"), "no reported estimate (estimates/reported.yaml)"))

    # --- reproductions -----------------------------------------------------
    repro_dirs = {r.id: r for r in claim.reproductions}
    seen_repro_ids = set()
    for estimate_file, estimate in reproductions:
        rid = estimate["reproduction_id"]
        seen_repro_ids.add(rid)
        expected_results = f"reproductions/{rid}/results.json"
        if estimate["results_file"] != expected_results:
            problems.append(Problem(rel(estimate_file), f"results_file must be '{expected_results}'"))
        repro = repro_dirs.get(rid)
        if repro is None:
            problems.append(Problem(rel(estimate_file), f"reproduction directory reproductions/{rid}/ is missing"))
            continue
        if len(repro.entrypoints) != 1:
            problems.append(Problem(rel(repro.dir), "needs exactly one of notebook.ipynb or reproduce.py"))
        for required in (repro.results, repro.run, repro.lockfile):
            if not required.exists():
                problems.append(Problem(rel(required), "missing"))
        entrypoint = repro.entrypoint
        if entrypoint is None or not all(p.exists() for p in (repro.results, repro.run, repro.lockfile)):
            continue

        results = load_json(repro.results)
        problems += _schema_problems(results, schemas["results"], rel(repro.results))
        run = load_json(repro.run)
        problems += _schema_problems(run, schemas["run"], rel(repro.run))
        if any(p.level == "error" and p.path.startswith((rel(repro.results), rel(repro.run))) for p in problems):
            continue

        if results["claim_id"] != claim.id or results["reproduction_id"] != rid:
            problems.append(Problem(rel(repro.results), "claim_id/reproduction_id do not match the directory"))
        if run["reproduction_id"] != rid:
            problems.append(Problem(rel(repro.run), "reproduction_id does not match the directory"))
        logical = results["logical"]
        if logical["toffoli_count"] != logical["ccz_count"] + logical["ccix_count"]:
            problems.append(Problem(rel(repro.results), "logical.toffoli_count must equal ccz_count + ccix_count"))

        if entrypoint.suffix == ".ipynb" and not _notebook_is_executed(entrypoint):
            problems.append(Problem(rel(entrypoint), "notebook has no outputs; commit the executed copy"))
        if run.get("entrypoint") != entrypoint.name or results["producer"]["entrypoint"] != entrypoint.name:
            problems.append(Problem(rel(repro.run), f"run.json and results.json must name the entry point {entrypoint.name}"))
        for file, key in ((entrypoint, "entrypoint_sha256"), (repro.results, "results_sha256"), (repro.lockfile, "lockfile_sha256")):
            if sha256(file) != run[key]:
                problems.append(Problem(rel(repro.run), f"{key} does not match {file.name} (re-run `qacclaims execute --write`)"))

        pins = _lock_pins(repro.lockfile)
        for package, version in results["tooling"]["packages"].items():
            pinned = pins.get(package.lower().replace("_", "-"))
            if pinned is None:
                problems.append(Problem(rel(repro.lockfile), f"{package} is not pinned in the lockfile"))
            elif pinned != version:
                problems.append(Problem(rel(repro.lockfile), f"{package}=={pinned} in lockfile but results.json records {version}"))

        scenario_ids = [s["scenario_id"] for s in results["physical"]]
        described = set(estimate["scenarios"])
        if described != set(scenario_ids):
            problems.append(Problem(rel(estimate_file), f"scenarios must describe exactly the results.json scenarios {sorted(scenario_ids)} (has {sorted(described)})"))
        if estimate["headline_scenario"] not in scenario_ids:
            problems.append(Problem(rel(estimate_file), f"headline_scenario '{estimate['headline_scenario']}' not in results.json physical scenarios {scenario_ids}"))
        headline_index = scenario_ids.index(estimate["headline_scenario"]) if estimate["headline_scenario"] in scenario_ids else None
        for aspect, pointer in estimate["figure_map"].items():
            try:
                value = resolve_pointer(results, pointer)
            except (KeyError, IndexError, ValueError):
                problems.append(Problem(rel(estimate_file), f"figure_map.{aspect}: pointer {pointer} does not resolve in results.json"))
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(Problem(rel(estimate_file), f"figure_map.{aspect}: pointer {pointer} is not a number"))
            physical_match = re.match(r"^#/physical/(\d+)/", pointer)
            if physical_match and headline_index is not None and int(physical_match.group(1)) != headline_index:
                problems.append(Problem(rel(estimate_file), f"figure_map.{aspect}: points at physical[{physical_match.group(1)}] but headline_scenario is physical[{headline_index}]"))

    for rid in repro_dirs:
        if rid not in seen_repro_ids:
            problems.append(Problem(rel(repro_dirs[rid].dir), "reproduction directory has no estimates/*.yaml record describing it"))

    # --- claim-level consistency -------------------------------------------
    assessment = record["assessment"]
    if assessment["reproduction_status"] != "not_attempted" and not reproductions:
        problems.append(Problem(rel(claim.claim_file), f"reproduction_status '{assessment['reproduction_status']}' requires at least one reproduction record"))
    if assessment["reproduction_status"] == "not_attempted" and reproductions:
        problems.append(Problem(rel(claim.claim_file), "reproduction_status is 'not_attempted' but reproduction records exist"))
    reported_aspects = set((reported or {}).get("figures", {}).keys())
    mapped_aspects = {aspect for _, estimate in reproductions for aspect in estimate["figure_map"]}
    for finding in assessment["findings"]:
        if finding["verdict"] != "not_compared" and finding["aspect"] not in (reported_aspects & mapped_aspects):
            problems.append(Problem(rel(claim.claim_file), f"finding '{finding['aspect']}' has verdict '{finding['verdict']}' but the aspect is not present in both the reported figures and a reproduction figure_map"))
    publication = record["publication"]
    review = record["review"]
    if publication["status"] == "published":
        if not review["approved_by"]:
            problems.append(Problem(rel(claim.claim_file), "publication.status 'published' requires review.approved_by"))
        if not review["reviewed_by"]:
            problems.append(Problem(rel(claim.claim_file), "publication.status 'published' requires review.reviewed_by"))
        if "first_published" not in publication:
            problems.append(Problem(rel(claim.claim_file), "publication.status 'published' requires publication.first_published"))
    if record["source"].get("year") and "first_published" in publication and publication["first_published"][:4] < str(record["source"]["year"]):
        problems.append(Problem(rel(claim.claim_file), "first_published precedes the source year"))

    narrative_file = claim.dir / "narrative.md"
    readme_file = claim.dir / "README.md"
    if readme_file.exists() and not narrative_file.exists():
        problems.append(Problem(rel(readme_file), "README.md is generated from narrative.md; write narrative.md instead"))
    if narrative_file.exists() and not any(p.level == "error" for p in problems):
        from .build import build_claim  # local import: build depends on loader only

        _, unresolved = render(narrative_file.read_text(encoding="utf-8"), build_claim(root, claim))
        _, unresolved_summary = render(record["assessment"]["summary_plain"], build_claim(root, claim))
        unresolved = unresolved + unresolved_summary
        for item in unresolved:
            problems.append(Problem(rel(narrative_file), f"unresolved placeholder {item}"))

    if online and record["source"].get("doi"):
        if not _doi_resolves(record["source"]["doi"]):
            problems.append(Problem(rel(claim.claim_file), f"DOI {record['source']['doi']} did not resolve", level="warning"))

    return problems


def validate_all(root: Path, online: bool = False) -> list[Problem]:
    schemas = {name: load_schema(root, name) for name in ("claim", "estimate", "results", "run")}
    problems: list[Problem] = []
    claims = discover_claims(root)
    if not claims:
        problems.append(Problem("claims/", "no claims found"))
    for claim in claims:
        problems += validate_claim(root, claim, schemas, online=online)
    return problems
