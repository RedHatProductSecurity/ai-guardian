"""Bundled-engine recognition and false-positive regressions for #2558."""

import json
from base64 import b32decode, b32encode
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
import yaml

from ai_guardian.patterns import BUNDLED_FILES
from ai_guardian.patterns.toml_parser import load_and_compile
from ai_guardian.scanners.toml_patterns import TomlPatternsScanner
from tests.fixtures.nuget_sonar_tokens import (
    CREDENTIAL_CASES,
    CREDENTIAL_RULE_IDS,
    SONAR_TOKEN_TYPES,
    make_nuget_v4,
)


@pytest.fixture(scope="module")
def scanner():
    # Keep normal entropy/stopword defaults; never load user or server settings.
    return TomlPatternsScanner()


@pytest.fixture(scope="module")
def rules():
    return {
        rule.id: rule for rule in load_and_compile(BUNDLED_FILES["secrets"], "secrets")
    }


@pytest.mark.parametrize("seed", range(32))
def test_nuget_vendor_layout_detected(scanner, seed):
    token = make_nuget_v4(seed)
    identifier = b32decode(token[:20].upper() + "====")
    password = b32decode(token[20:].upper() + "======")
    assert len(token) == 46
    assert identifier[:2] == b"v4"
    assert len(identifier[2:]) == 10 and all(identifier[2:])
    assert UUID(bytes_le=password).version == 4
    assert any(f.rule_id == "nuget-api-key" for f in scanner.scan(token))


@pytest.mark.parametrize(
    "rule_id,description,token", CREDENTIAL_CASES, ids=[c[0] for c in CREDENTIAL_CASES]
)
@pytest.mark.parametrize(
    "template",
    (
        "{token}",
        "'{token}'",
        '"{token}"',
        "\n  {token}\n",
        '<add key="publish" value="{token}" />',
        '{{"value": "{token}"}}',
        'export CREDENTIAL="{token}"',
    ),
)
def test_scanner_detects_and_attributes_credentials(
    scanner, rule_id, description, token, template
):
    content = template.format(token=token)
    findings = [f for f in scanner.scan(content) if f.rule_id == rule_id]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.matched_text == token
    assert finding.description == description
    assert finding.category == "secrets"
    assert finding.line_number == content[: content.index(token)].count("\n") + 1
    assert (
        finding.start_column
        == content.index(token) - content.rfind("\n", 0, content.index(token)) - 1
    )
    assert finding.end_column == finding.start_column + len(token)


@pytest.mark.parametrize(
    "rule_id,description,token", CREDENTIAL_CASES, ids=[c[0] for c in CREDENTIAL_CASES]
)
def test_relevant_cli_contexts(scanner, rule_id, description, token):
    if rule_id == "nuget-api-key":
        commands = (
            f"dotnet nuget push Package.nupkg --api-key {token}",
            f"nuget push Package.nupkg -k '{token}'",
        )
    else:
        commands = (
            f"sonar-scanner -Dsonar.token={token}",
            f"mvn sonar:sonar -Dsonar.login='{token}'",
        )
    for command in commands:
        assert any(f.rule_id == rule_id for f in scanner.scan(command))


@pytest.mark.parametrize("case", ("upper", "mixed"))
@pytest.mark.parametrize(
    "rule_id,description,token", CREDENTIAL_CASES, ids=[c[0] for c in CREDENTIAL_CASES]
)
def test_ascii_case_handling(scanner, rule_id, description, token, case):
    if case == "upper":
        token = token.upper()
    else:
        token = "".join(c.upper() if i % 2 else c for i, c in enumerate(token))
    assert any(f.rule_id == rule_id for f in scanner.scan(token))


@pytest.mark.parametrize(
    "position,allowed", ((3, "abcdefghijklmnop"), (19, "aq"), (45, "aeimquy4"))
)
def test_nuget_fixed_bit_alternatives(scanner, position, allowed):
    token = make_nuget_v4()
    for char in allowed:
        candidate = token[:position] + char + token[position + 1 :]
        assert any(f.rule_id == "nuget-api-key" for f in scanner.scan(candidate))


@pytest.mark.parametrize(
    "position,char",
    (
        (3, "q"),
        (3, "z"),
        (19, "b"),
        (19, "7"),
        (45, "b"),
        (45, "7"),
        *((24, char) for char in "0189+/_-=İıſK"),
    ),
)
def test_nuget_rejects_invalid_fixed_bits_and_alphabet(scanner, rules, position, char):
    token = make_nuget_v4()
    candidate = token[:position] + char + token[position + 1 :]
    assert not rules["nuget-api-key"].compiled.search(candidate)
    assert not any(f.rule_id == "nuget-api-key" for f in scanner.scan(candidate))


@pytest.mark.parametrize("rule_id,prefix,description", SONAR_TOKEN_TYPES)
def test_sonar_compatible_extended_alphabet(scanner, rule_id, prefix, description):
    # MIT Betterleaks AlphaNumericExtended(40), not arbitrary-length base64.
    token = prefix + ("aB3_dE7-fG9=hJ2kL5mN8pQ4rS6tU0vW1xYz" + "1234")
    assert len(token) == 44
    assert any(f.rule_id == rule_id for f in scanner.scan(token))


@pytest.mark.parametrize("rule_id,prefix,description", SONAR_TOKEN_TYPES)
@pytest.mark.parametrize("char", ("+", "/", ".", ":", " ", "\n", "İ", "ı", "ſ", "K"))
def test_sonar_rejects_incompatible_alphabets(
    scanner, rules, rule_id, prefix, description, char
):
    body = sha256(b"synthetic-invalid-sonar").hexdigest()[:40]
    candidate = prefix + body[:20] + char + body[21:]
    assert not rules[rule_id].compiled.search(candidate)
    assert not any(f.rule_id == rule_id for f in scanner.scan(candidate))


@pytest.mark.parametrize(
    "rule_id,description,token", CREDENTIAL_CASES, ids=[c[0] for c in CREDENTIAL_CASES]
)
@pytest.mark.parametrize("affix", ("a", "9", "_", "-", "é"))
def test_adjacent_identifier_characters_are_not_tokens(
    scanner, rules, rule_id, description, token, affix
):
    for candidate in (affix + token, token + affix):
        assert not rules[rule_id].compiled.search(candidate)
        assert not any(f.rule_id == rule_id for f in scanner.scan(candidate))


@pytest.mark.parametrize(
    "rule_id,description,token", CREDENTIAL_CASES, ids=[c[0] for c in CREDENTIAL_CASES]
)
def test_wrong_lengths_and_truncation(scanner, rules, rule_id, description, token):
    for candidate in (token[:-1], token + "a", token[:15] + "...", token + "="):
        assert not rules[rule_id].compiled.search(candidate)
        assert not any(f.rule_id == rule_id for f in scanner.scan(candidate))


@pytest.mark.parametrize(
    "rule_id,description,token", CREDENTIAL_CASES, ids=[c[0] for c in CREDENTIAL_CASES]
)
def test_generic_assignments_still_detected(scanner, rule_id, description, token):
    ids = {f.rule_id for f in scanner.scan(f'export CREDENTIAL="{token}"')}
    assert rule_id in ids
    assert "exported-env-variable" in ids


def test_unprefixed_sonar_and_other_formats_not_added(scanner):
    for text in (
        sha256(b"synthetic-legacy-sonar").hexdigest()[:40],
        "squ_...",
        "sqp_...",
        "sqa_...",
        "oy2...",
        "spat_" + sha256(b"out-of-scope").hexdigest(),
    ):
        assert not CREDENTIAL_RULE_IDS.intersection(
            f.rule_id for f in scanner.scan(text)
        )


def test_low_entropy_values_filtered(scanner):
    candidates = ["oy2" + "a" * 43]
    candidates.extend(prefix + "a" * 40 for _, prefix, _ in SONAR_TOKEN_TYPES)
    for text in candidates:
        assert not CREDENTIAL_RULE_IDS.intersection(
            f.rule_id for f in scanner.scan(text)
        )


def test_legitimate_content_false_positive_corpus(scanner):
    """0/220 documents required; this is a bounded corpus, not a population estimate."""
    corpus_path = Path(__file__).parents[1] / "fixtures" / "nuget_sonar_benign.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    for index in range(100):
        digest = sha256(f"benign-artifact:{index}".encode()).digest()
        corpus.extend(
            (
                {
                    "name": f"artifact-checksum-{index}",
                    "content": f"sha256: {digest.hex()}",
                },
                {
                    "name": f"base32-identifier-{index}",
                    "content": f"build id: {b32encode(digest[:28]).decode().rstrip('=')}",
                },
            )
        )
    false_positives = [item["name"] for item in corpus if scanner.scan(item["content"])]
    assert len(corpus) == 220
    assert len(false_positives) / len(corpus) < 0.01, false_positives
    assert false_positives == []


@pytest.mark.parametrize(
    "filename,job",
    (("release-readiness.yml", "fresh-install"), ("smoke-tests.yml", "detection-scan")),
)
def test_ci_workflows_check_standalone_credential_attribution(filename, job):
    workflow_path = Path(__file__).parents[2] / ".github" / "workflows" / filename
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    step = next(
        step
        for step in workflow["jobs"][job]["steps"]
        if step["name"] == "Verify standalone NuGet V4 and Sonar tokens"
    )
    lines = step["run"].splitlines()
    assert lines[0] == "python - <<'PY'"
    assert lines[-1] == "PY"
    script = "\n".join(lines[1:-1])
    compile(script, str(workflow_path), "exec")
    assert "TomlPatternsScanner()" in script
    assert "from tests.fixtures.nuget_sonar_tokens import CREDENTIAL_CASES" in script
    assert "assert len(CREDENTIAL_CASES) == 4" in script
    assert "for rule_id, description, token in CREDENTIAL_CASES:" in script
    assert "finding.rule_id == rule_id" in script
    assert "finding.description == description" in script
    assert "finding.matched_text == token" in script
    assert "for finding in scanner.scan(token)" in script
