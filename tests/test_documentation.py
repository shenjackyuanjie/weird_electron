"""Keep Markdown, install manifests and executable source examples aligned."""
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from packaging.requirements import Requirement

from power_engine.contracts import MicrogridConfig

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_relative_document_links_exist(path):
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    for target in re.findall(r"!?\[[^\]]*\]\(([^\s)]+)\)", text):
        link = urlsplit(target)
        if link.scheme or link.netloc or not link.path:
            continue
        destination = (path.parent / unquote(link.path)).resolve()
        assert destination.is_relative_to(ROOT), (path, target)
        assert destination.exists(), (path, target)


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_documented_python_snippets_compile(path):
    snippets = re.findall(r"```python\s*\n(.*?)```", path.read_text(encoding="utf-8"), re.S)
    for number, snippet in enumerate(snippets):
        compile(snippet, f"{path.name}:snippet-{number}", "exec")


def manifest_lines(name):
    return [line.split("#", 1)[0].strip()
            for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip() and not line.lstrip().startswith("-r ")]


def test_runtime_dependency_pins_match_install_metadata():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert {str(Requirement(s)) for s in manifest_lines("requirements.txt")} == {
        str(Requirement(s)) for s in project["project"]["dependencies"]
    }


def test_build_tool_pin_matches_development_environment():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build = {str(Requirement(s)) for s in project["build-system"]["requires"]}
    dev = {str(Requirement(s)) for s in manifest_lines("requirements-dev.txt")}
    assert build <= dev


def test_example_config_matches_current_defaults():
    cfg = MicrogridConfig.model_validate_json(
        (ROOT / "examples/demo-config.json").read_text(encoding="utf-8")
    )
    assert cfg == MicrogridConfig()


@pytest.mark.integration
@pytest.mark.parametrize("policy", ["optimizer", "baseline"])
def test_documented_local_loop_runs_with_real_ac(policy):
    from examples.local_loop import run_demo

    result = run_demo(policy)
    assert result["complete"]
    assert result["completed_intervals"] == 6
    assert result["executed_constraint_violations"] == 0
    json.dumps(result, allow_nan=False)


@pytest.mark.integration
def test_documented_manual_json_chain_runs_with_real_ac():
    from examples.manual_dispatch import run_manual

    result = run_manual()
    assert 1 <= len(result["attempts"]) <= 2
    assert result["accepted"]["status"] == "accepted"
    assert result["receipt"]["status"] == "applied"
    assert result["receipt"]["request_id"] == "manual-example"
    assert result["receipt"]["validation"]["pass"]
    assert result["execution_audit"]["passed"]
    json.dumps(result, allow_nan=False)
