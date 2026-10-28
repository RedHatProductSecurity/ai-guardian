"""Synthetic, offline tests: suspected secrets are not known passwords."""

import json
import logging
from dataclasses import asdict
from unittest.mock import patch

import pytest

from ai_guardian.scanners.password_likelihood import (
    INCOMPLETE_MESSAGE,
    MAX_CANDIDATES,
    MAX_FINDINGS,
    MAX_INPUT_CHARS,
    analyze_password_likelihood,
    exclude_credential_overlaps,
    run_password_likelihood_scan,
    run_tool_input_password_scan,
    redact_password_likelihood,
)
from ai_guardian.scanners.scan_result import ScanResult

MIXED = "m7Q!t2R#v9L$x5N@"
ALNUM = "m7Qt2Rv9Lx5Nz8Ba"
PHRASES = [
    ("coppermeadoworbitlantern", "joined_word_like"),
    ("CopperMeadowOrbitLantern", "camelcase_passphrase"),
    ("copper-meadow-orbit-lantern", "separated_passphrase"),
    ("copper meadow orbit lantern", "spaced_passphrase"),
]


@pytest.mark.parametrize("value", [MIXED, ALNUM])
def test_unstructured_random_candidates_are_only_ambiguous(value):
    result = run_password_likelihood_scan(
        f"Someone pasted {value} here", config={"enabled": True, "action": "block"}
    )
    assert result.detected and not result.should_block
    assert result.findings[0]["confidence_class"] == "ambiguous"
    assert value not in repr(result)


@pytest.mark.parametrize(
    "value,kind", PHRASES + [(MIXED, "mixed_symbol"), (ALNUM, "random_alphanumeric")]
)
def test_contextual_candidate_spans_cover_the_entire_value(value, kind):
    text = f'Note: my passphrase is "{value}" today.'
    analysis = analyze_password_likelihood(text)
    assert len(analysis.findings) == 1
    span = analysis.findings[0]
    assert text[span.start : span.end] == value
    assert span.candidate_class == kind
    assert span.confidence_class == "contextual"
    assert not analysis.incomplete
    assert value not in json.dumps(asdict(analysis))


@pytest.mark.parametrize("value,kind", PHRASES)
def test_context_free_word_sequences_are_not_identified_as_passwords(value, kind):
    assert not analyze_password_likelihood(value).findings


@pytest.mark.parametrize(
    "text",
    [
        "ordinary source code and documentation",
        "someVeryLongApplicationIdentifier",
        "package_name_version_1.2.3",
        "https://example.org/AbCdEfGhIjKl12345678",
        "1a3b5c7d-2468-1357-90ab-123456789abc",
        "d4e5f6a7b8c90123456789abcdef0123456789abcdef0123456789abcdef0123",
        "data:image/png;base64,AbCdEfGhIjKl12345678==",
        "日本語の文章と識別子",
        "x" * 120,
        "1234567890123456",
    ],
)
def test_confusable_negatives(text):
    assert not analyze_password_likelihood(text).findings


@pytest.mark.parametrize(
    "value,expected",
    [
        ("copper meadow orbit lantern", "spaced_passphrase"),
        ("copper_meadow-orbit_lantern", "separated_passphrase"),
        ("a copper meadow orbit", "spaced_passphrase"),
        ("A" * 128, None),
        ("A" * 120 + " meadow orbit!", None),
        ("copper  meadow orbit", None),
        ("copper__meadow_orbit", None),
        ("copper-meadow-orbit-", None),
    ],
)
def test_delimited_phrase_validation_is_non_backtracking(value, expected):
    from ai_guardian.scanners.password_likelihood import _candidate_class

    assert _candidate_class(value, contextual=True) == expected


@pytest.mark.parametrize(
    "config", [{}, {"enabled": False}, {"enabled": "true"}, {"enabled": 1}]
)
def test_only_literal_opt_in_activates_detector(config):
    with patch(
        "ai_guardian.scanners.password_likelihood.analyze_password_likelihood"
    ) as analyze:
        assert run_password_likelihood_scan(MIXED, config=config) is None
        analyze.assert_not_called()


def test_repeated_contextual_spans_and_crlf_positions():
    text = f'password is "{MIXED}"\r\npassphrase is "{MIXED}"'
    spans = analyze_password_likelihood(text).findings
    assert len(spans) == 2
    assert [span.line_number for span in spans] == [1, 2]
    assert all(text[span.start : span.end] == MIXED for span in spans)


@pytest.mark.parametrize(
    "action,blocked",
    [
        ("ask", True),
        ("warn", False),
        ("block", True),
        ("bad", True),
        ("ask:warn", True),
    ],
)
def test_explicit_enforcement_mode(action, blocked):
    result = run_password_likelihood_scan(
        f'password is "{MIXED}"', config={"enabled": True, "action": action}
    )
    assert result.should_block is blocked


@pytest.mark.parametrize(
    "text",
    [
        "x" * (MAX_INPUT_CHARS + 1),
        "x" * 129,
        "word " * (MAX_CANDIDATES + 1),
        (MIXED + "\n") * (MAX_FINDINGS + 1),
    ],
)
def test_work_limits_are_explicit_and_require_approval_or_block_unless_warn(text):
    for action in ("ask", "warn", "block"):
        result = run_password_likelihood_scan(
            text, config={"enabled": True, "action": action}
        )
        assert result.extra["incomplete"]
        assert result.should_block is (action != "warn")
        assert result.error_message == INCOMPLETE_MESSAGE
        assert len(result.findings) <= MAX_FINDINGS


def test_exception_messages_and_tracebacks_never_escape(caplog):
    caplog.set_level(logging.WARNING, logger="ai_guardian")
    with patch(
        "ai_guardian.scanners.password_likelihood.analyze_password_likelihood",
        side_effect=ValueError(MIXED),
    ):
        result = run_password_likelihood_scan(
            MIXED, config={"enabled": True, "action": "block"}
        )
    assert result.should_block and not result.detected
    assert "Password-likelihood analysis failed; details withheld" in caplog.text
    assert MIXED not in caplog.text + repr(result)


def test_stronger_findings_are_preserved_and_only_full_coverage_deduplicates():
    text = f'password is "{MIXED}"; passphrase is "copper meadow orbit lantern"'
    result = run_password_likelihood_scan(
        text, config={"enabled": True, "action": "block"}
    )
    first = result.findings[0]
    strong = ScanResult(
        detected=True,
        violation_type="secret_detected",
        findings=[
            {
                "line_number": 1,
                "start_column": first["start_column"],
                "end_column": first["end_column"],
            }
        ],
    )
    filtered = exclude_credential_overlaps(result, [strong])
    assert strong.detected and strong.should_block
    assert filtered.total_findings == 1 and filtered.should_block
    assert filtered.findings[0]["candidate_class"] == "spaced_passphrase"
    strong.findings[0].pop("end_column")
    assert exclude_credential_overlaps(result, [strong]).total_findings == 2


def test_tool_values_are_not_json_escaped_and_null_does_not_end_traversal():
    config = {"enabled": True, "action": "block"}
    with patch(
        "ai_guardian.config.loaders._load_password_likelihood_config",
        return_value=(config, None),
    ):
        result = run_tool_input_password_scan(
            {"unused": None, "edits": [{"content": f'password is "{MIXED}"'}]}
        )
    assert result.detected and result.should_block
    assert MIXED not in repr(result)


def test_nested_cyclic_tool_payload_is_bounded_without_repr():
    payload = []
    payload.append(payload)
    with patch(
        "ai_guardian.config.loaders._load_password_likelihood_config",
        return_value=({"enabled": True, "action": "block"}, None),
    ):
        result = run_tool_input_password_scan(payload)
    assert not result.detected and result.should_block and result.extra["incomplete"]


def test_sanitizer_replaces_every_repetition_and_full_ambiguous_span():
    text = f'{MIXED}\npassword is "{MIXED}"\n{MIXED}'
    redacted, metadata = redact_password_likelihood(text, config={"enabled": True})
    assert len(metadata) == 3
    assert (
        MIXED not in redacted
        and MIXED[:4] not in redacted
        and MIXED[-4:] not in redacted
    )
    assert redacted.count("[SUSPECTED PASSWORD REDACTED]") == 3
    assert MIXED not in repr(metadata)


def test_sanitizer_merges_overlapping_intervals_without_leaving_suffixes():
    result = ScanResult(
        detected=True,
        violation_type="suspected_password",
        findings=[{"start": 5, "end": 14}, {"start": 2, "end": 10}],
    )
    with patch(
        "ai_guardian.scanners.password_likelihood.run_password_likelihood_scan",
        return_value=result,
    ):
        redacted, metadata = redact_password_likelihood("xxabcdefghijklzz")
    assert redacted == "xx[SUSPECTED PASSWORD REDACTED]zz"
    assert len(metadata) == 1


def test_sanitizer_withholds_unexamined_suffix_on_limit_even_in_warn_mode():
    redacted, _ = redact_password_likelihood(
        "x" * (MAX_INPUT_CHARS + 1), config={"enabled": True, "action": "warn"}
    )
    assert redacted == "[CONTENT WITHHELD: PASSWORD-LIKELIHOOD ANALYSIS INCOMPLETE]"


def test_crowded_line_bounds_overlap_work_and_preserves_safe_leading_findings():
    from ai_guardian.scanners import password_likelihood as module

    with patch.object(
        module, "_candidate_class", wraps=module._candidate_class
    ) as classify:
        result = analyze_password_likelihood((MIXED + " ") * (MAX_FINDINGS * 8))
    assert result.incomplete
    assert 0 < len(result.findings) <= MAX_FINDINGS
    assert classify.call_count <= MAX_FINDINGS + 1


def test_enabled_analysis_performs_no_network_subprocess_or_file_io():
    with (
        patch("socket.socket") as socket,
        patch("subprocess.Popen") as process,
        patch("builtins.open") as file_open,
        patch("pathlib.Path.open") as path_open,
    ):
        result = run_password_likelihood_scan(
            f'password is "{MIXED}"', config={"enabled": True}
        )
        assert result.detected
        for external in (socket, process, file_open, path_open):
            external.assert_not_called()
