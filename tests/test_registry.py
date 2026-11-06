"""End-to-end checks of the registry rules against the committed claims."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from qacclaims.build import build_all
from qacclaims.loader import find_root, load_json, load_schema
from qacclaims.validate import validate_all
from jsonschema import Draft202012Validator

ROOT = find_root(Path(__file__).resolve().parent)
CLAIM = ROOT / "claims" / "femoco-low-2025"
REPRO = CLAIM / "reproductions" / "qdk-sossa-2026-11"


def errors(root):
    return [str(p) for p in validate_all(root) if p.level == "error"]


@pytest.fixture
def scratch_root(tmp_path):
    for name in ("schemas", "claims"):
        shutil.copytree(ROOT / name, tmp_path / name)
    return tmp_path


def test_committed_registry_is_valid():
    assert errors(ROOT) == []


def test_hand_edited_results_are_rejected(scratch_root):
    results_path = scratch_root / "claims/femoco-low-2025/reproductions/qdk-sossa-2026-11/results.json"
    results = load_json(results_path)
    results["physical"][1]["physical_qubits"] += 1
    results_path.write_text(json.dumps(results, indent=2) + "\n")
    assert any("results_sha256" in e for e in errors(scratch_root))


def test_numbers_are_forbidden_in_reproduction_records(scratch_root):
    path = scratch_root / "claims/femoco-low-2025/estimates/reproduction-qdk-sossa-2026-11.yaml"
    record = yaml.safe_load(path.read_text())
    record["notes"] = record.get("notes", []) + ["looks fine"]
    record["interpretation"]["statement"] += " (see note)"
    record["deviations_from_reported"].append({"aspect": "timing model", "reported": "stated explicitly", "used": "tool default", "why": "no parameter for it in the tool"})
    path.write_text(yaml.safe_dump(record))
    assert errors(scratch_root) == []  # strings are fine
    record["tool"]["url"] = "https://example.org"
    record["figure_map"]["t_count"] = "#/logical/t_count"
    record["interpretation"]["statement"] = record["interpretation"]["statement"]
    record["notes"].append(5)  # a bare number
    path.write_text(yaml.safe_dump(record))
    assert any("may not contain numbers" in e or "is not of type" in e for e in errors(scratch_root))


def test_pointer_must_resolve(scratch_root):
    path = scratch_root / "claims/femoco-low-2025/estimates/reproduction-qdk-sossa-2026-11.yaml"
    record = yaml.safe_load(path.read_text())
    record["figure_map"]["physical_qubits"] = "#/physical/9/physical_qubits"
    path.write_text(yaml.safe_dump(record))
    assert any("does not resolve" in e for e in errors(scratch_root))


def test_published_requires_review(scratch_root):
    path = scratch_root / "claims/femoco-low-2025/claim.yaml"
    record = yaml.safe_load(path.read_text())
    record["publication"] = {"status": "published"}
    path.write_text(yaml.safe_dump(record, allow_unicode=True))
    assert any("first_published" in e for e in errors(scratch_root))
    record["review"]["approved_by"] = []
    path.write_text(yaml.safe_dump(record, allow_unicode=True))
    assert any("approved_by" in e for e in errors(scratch_root))


def test_lockfile_must_pin_tool_versions(scratch_root):
    lock = scratch_root / "claims/femoco-low-2025/reproductions/qdk-sossa-2026-11/requirements.lock.txt"
    lock.write_text(lock.read_text().replace("qdk-chemistry==", "qdk-chemistry==0.0.0+"))
    assert any("qdk-chemistry" in e and "lockfile" in e for e in errors(scratch_root))


def test_build_output_matches_schemas(tmp_path):
    build_all(ROOT, tmp_path)
    index = load_json(tmp_path / "index.json")
    Draft202012Validator(load_schema(ROOT, "index")).validate(index)
    claim = load_json(tmp_path / "claims" / "femoco-low-2025.json")
    aspects = {c["aspect"]: c for c in claim["comparisons"]}
    assert aspects["physical_qubits"]["ratio"] == pytest.approx(claim["reproductions"][0]["figures"]["physical_qubits"]["value"] / 3.2e6, abs=5e-5)
    assert claim["reproductions"][0]["figures"]["physical_qubits"]["source"].endswith("#/physical/1/physical_qubits")


def test_narrative_placeholders_must_resolve(scratch_root):
    narrative = scratch_root / "claims/femoco-low-2025/narrative.md"
    narrative.write_text(narrative.read_text() + "\n\nBogus: {{ reported.figures.nonexistent.value | n }}\n")
    assert any("unresolved placeholder" in e for e in errors(scratch_root))


def test_hand_edited_readme_is_stale(scratch_root):
    from qacclaims.build import check_fresh
    readme = scratch_root / "claims/femoco-low-2025/README.md"
    readme.write_text(readme.read_text() + "\nhand edit\n")
    assert any("README.md" in line for line in check_fresh(scratch_root, scratch_root / "dist"))


def test_narrative_filters():
    from qacclaims.narrative import render
    text, problems = render("{{ a | n }} {{ b | sci }} {{ c | million }} {{ d | hours }} {{ e | x }} {{ items[k=v].z | g }}",
                            {"a": 1081, "b": 356382604, "c": 3443392, "d": 41364.9, "e": 4.2556, "items": [{"k": "v", "z": 0.001}]})
    assert problems == []
    assert text == "1,081 3.56 × 10⁸ 3.44 million 11.5 hours 4.3× 0.001"


def test_reproduction_needs_exactly_one_entrypoint(scratch_root):
    repro = scratch_root / "claims/femoco-low-2025/reproductions/qdk-sossa-2026-11"
    (repro / "reproduce.py").write_text("print('second entry point')\n")
    assert any("exactly one of notebook.ipynb or reproduce.py" in e for e in errors(scratch_root))


def test_script_reproduction_runs_and_records_its_entrypoint(tmp_path):
    import sys
    from qacclaims.execute import execute

    repro = tmp_path / "claims" / "demo" / "reproductions" / "script-demo"
    repro.mkdir(parents=True)
    (repro / "reproduce.py").write_text(
        "import json\n"
        "json.dump({'producer': {'entrypoint': 'reproduce.py'}, 'value': 6 * 7}, open('results.json', 'w'))\n"
    )
    (repro / "requirements.lock.txt").write_text("PyYAML==6.0.3\n")
    diffs, _ = execute(tmp_path, repro, python=sys.executable, write=True, operator="Test Runner")
    assert diffs == []
    run = load_json(repro / "run.json")
    assert run["entrypoint"] == "reproduce.py"
    assert load_json(repro / "results.json")["value"] == 42
    diffs, _ = execute(tmp_path, repro, python=sys.executable)
    assert diffs == []
