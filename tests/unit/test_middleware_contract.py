"""Regression checks for the shared OpenShell/Bifrost middleware contract."""

import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
CONTRACT = ROOT / "src/ai_guardian/middleware/contract.json"
FIXTURES = ROOT / "tests/fixtures/middleware_contract.json"


def test_contract_is_versioned_and_documents_adapter_boundaries():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert contract["contract"] == "ai-guardian.middleware"
    assert contract["version"] == 1
    assert contract["failure"]["default"] == "block"
    assert contract["failure"]["explicit_daemon_denial_always"] == "block"
    assert set(contract["adapters"]) == {"openshell", "bifrost"}


def test_shared_fixture_matrix_covers_required_outcomes():
    fixture = json.loads(FIXTURES.read_text(encoding="utf-8"))
    names = {case["name"] for case in fixture["cases"]}

    assert fixture["contract"] == "ai-guardian.middleware"
    assert fixture["version"] == 1
    assert names == {
        "allow",
        "deny",
        "pause",
        "daemon_unavailable",
        "malformed_verdict",
        "sensitive_field_exclusion",
    }
