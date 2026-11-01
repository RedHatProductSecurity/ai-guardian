"""Bundled-engine coverage for the credential formats reviewed in #2632."""

from pathlib import Path

import pytest
import yaml

from ai_guardian.scanners.toml_patterns import TomlPatternsScanner
from tests.fixtures.research_secret_tokens import CREDENTIAL_CASES, LOW_ENTROPY_CASES


@pytest.fixture(scope="module")
def scanner():
    return TomlPatternsScanner()


@pytest.mark.parametrize(
    "rule_id,description,token",
    CREDENTIAL_CASES,
    ids=[case[0] for case in CREDENTIAL_CASES],
)
def test_standalone_synthetic_credentials_are_detected_and_attributed(
    scanner, rule_id, description, token
):
    findings = [
        finding for finding in scanner.scan(token) if finding.rule_id == rule_id
    ]

    assert len(findings) == 1
    assert findings[0].matched_text == token
    assert findings[0].description == description
    assert findings[0].category == "secrets"


@pytest.mark.parametrize(
    "rule_id,description,token",
    CREDENTIAL_CASES,
    ids=[case[0] for case in CREDENTIAL_CASES],
)
def test_invalid_format_marker_is_not_accepted(scanner, rule_id, description, token):
    if rule_id.startswith("tailscale-"):
        malformed = token.replace("CNTRL-", "CNTXL-", 1)
    else:
        malformed = token[:-1] + "!" + token[-1]

    assert not any(finding.rule_id == rule_id for finding in scanner.scan(malformed))


@pytest.mark.parametrize("rule_id,token", LOW_ENTROPY_CASES)
def test_low_entropy_placeholder_shape_is_filtered(scanner, rule_id, token):
    assert not any(finding.rule_id == rule_id for finding in scanner.scan(token))


@pytest.mark.parametrize(
    "filename,job",
    (("release-readiness.yml", "fresh-install"), ("smoke-tests.yml", "detection-scan")),
)
def test_ci_workflows_verify_standalone_research_credentials(filename, job):
    workflow_path = Path(__file__).parents[2] / ".github" / "workflows" / filename
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    step = next(
        step
        for step in workflow["jobs"][job]["steps"]
        if step["name"] == "Verify standalone research credentials"
    )
    lines = step["run"].splitlines()
    assert lines[0] == "python - <<'PY'"
    assert lines[-1] == "PY"
    script = "\n".join(lines[1:-1])
    compile(script, str(workflow_path), "exec")
    assert (
        "from tests.fixtures.research_secret_tokens import CREDENTIAL_CASES" in script
    )
    assert "assert len(CREDENTIAL_CASES) == 8" in script
    assert "finding.rule_id == rule_id" in script
    assert "finding.description == description" in script
    assert "finding.matched_text == token" in script
