"""Frozen-seed quality gates; not a claim of population precision/recall."""

from collections import defaultdict

from ai_guardian.scanners.password_likelihood import analyze_password_likelihood
from tests.fixtures.password_likelihood_corpus import cases


def test_held_out_synthetic_classes_meet_declared_budgets():
    counts = defaultdict(lambda: [0, 0])
    for label, text, positive, _ in cases(1000):
        result = analyze_password_likelihood(text)
        counts[label][0] += bool(result.findings)
        counts[label][1] += 1
        assert not result.incomplete, label
        if not positive:
            assert not any(
                f.confidence_class == "contextual" for f in result.findings
            ), label
    for label, (detected, total) in counts.items():
        if label.startswith(("standalone_", "contextual_")):
            assert detected / total >= 0.95, (label, detected, total)
        else:
            assert detected / total <= 0.01, (label, detected, total)
