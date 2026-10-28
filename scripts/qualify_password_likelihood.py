"""Offline #2612 qualification; print aggregate measurements, never sample values.

Run from the source checkout with the project environment. No dependency install,
real configuration, vault, network, candidate output or persisted corpus is used.
Actual host model-boundary qualification is a separate, still-manual gate.
"""

import argparse
import json
import platform
import statistics
import sys
import time
import tracemalloc
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_guardian.scanners.password_likelihood import analyze_password_likelihood
from tests.fixtures.password_likelihood_corpus import HELD_OUT_SEED, cases

# Declared BEFORE recording qualification results; do not silently tune to pass.
BUDGETS = {
    "minimum_recall_per_supported_class": 0.95,
    "maximum_benign_advisory_rate_per_class": 0.01,
    "maximum_benign_contextual_rate_per_class": 0.001,
    "minimum_contextual_precision_balanced_synthetic": 0.99,
    "p95_4k_ms": 25,
    "worst_bounded_input_ms": 250,
    "peak_traced_bytes": 8 * 1024 * 1024,
}


def qualify(samples=1000, include_repository=True):
    counts = defaultdict(
        lambda: dict(samples=0, characters=0, detections=0, contextual=0, incomplete=0)
    )
    positives = set()
    contextual_positives = set()
    for label, text, positive, contextual in cases(samples):
        if positive:
            positives.add(label)
        if contextual:
            contextual_positives.add(label)
        _measure_case(counts[label], text)

    # Fixed reviewed source/prose files, not arbitrary user directories/config.
    # Windows are unlabelled real-world samples: manual adjudication remains a
    # release gate; do not turn assumed-clean repository data into precision.
    repository_counts = defaultdict(
        lambda: dict(samples=0, characters=0, detections=0, contextual=0, incomplete=0)
    )
    if include_repository:
        for relative in (
            "src/ai_guardian/config/display.py",
            "src/ai_guardian/constants.py",
            "src/ai_guardian/ui/forms.py",
            "docs/README.md",
            "docs/MODAL_PROVIDERS.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            label = "source" if relative.endswith(".py") else "documentation"
            for offset in range(0, len(text), 4096):
                _measure_case(repository_counts[label], text[offset : offset + 4096])

    failures = []
    for label, count in counts.items():
        rate = count["detections"] / count["samples"]
        count["detection_rate"] = rate
        if label in positives:
            if rate < BUDGETS["minimum_recall_per_supported_class"]:
                failures.append(label + ": recall")
        else:
            if rate > BUDGETS["maximum_benign_advisory_rate_per_class"]:
                failures.append(label + ": advisory false positives")
            if (
                count["contextual"] / count["samples"]
                > BUDGETS["maximum_benign_contextual_rate_per_class"]
            ):
                failures.append(label + ": contextual false positives")
        if count["incomplete"]:
            failures.append(label + ": incomplete")

    true_contextual = sum(counts[label]["contextual"] for label in contextual_positives)
    false_contextual = sum(
        c["contextual"] for label, c in counts.items() if label not in positives
    )
    precision = true_contextual / max(1, true_contextual + false_contextual)
    if precision < BUDGETS["minimum_contextual_precision_balanced_synthetic"]:
        failures.append("contextual precision")

    typical = ("ordinary application text and identifier_123\n" * 100)[:4096]
    times = []
    for _ in range(100):
        start = time.perf_counter()
        analyze_password_likelihood(typical)
        times.append((time.perf_counter() - start) * 1000)
    p95 = sorted(times)[94]
    worst_ms = 0.0
    peak = 0
    for text in (
        "x" * 262144,
        "日本語" * 87381,
        "word " * 52428,
        "line\n" * 52428,
        'password is "' + "x" * 262000,
        'password is "AmberCedarIvoryMarble" ' * 2000,
        "m7Q!t2R#v9L$x5N@ " * 10000,
    ):
        start = time.perf_counter()
        analyze_password_likelihood(text)
        worst_ms = max(worst_ms, (time.perf_counter() - start) * 1000)
        tracemalloc.start()
        analyze_password_likelihood(text)
        peak = max(peak, tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()
    performance = dict(
        p95_4k_ms=p95,
        median_4k_ms=statistics.median(times),
        worst_bounded_input_ms=worst_ms,
        peak_traced_bytes=peak,
    )
    for key in ("p95_4k_ms", "worst_bounded_input_ms", "peak_traced_bytes"):
        if performance[key] > BUDGETS[key]:
            failures.append(key)
    return dict(
        seed=HELD_OUT_SEED,
        python=platform.python_version(),
        platform=platform.system(),
        budgets=BUDGETS,
        synthetic_classes=dict(counts),
        contextual_precision_balanced_synthetic=precision,
        repository_windows_unadjudicated=dict(repository_counts),
        performance=performance,
        synthetic_and_performance_gate_passed=not failures,
        failures=failures,
        release_qualification="PENDING: independently adjudicated benign corpus and live pre-model host evidence",
    )


def _measure_case(count, text):
    analysis = analyze_password_likelihood(text)
    count["samples"] += 1
    count["characters"] += len(text)
    count["detections"] += bool(analysis.findings)
    count["contextual"] += any(
        f.confidence_class == "contextual" for f in analysis.findings
    )
    count["incomplete"] += analysis.incomplete


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=1000)
    args = parser.parse_args()
    if not 100 <= args.samples <= 10000:
        parser.error("--samples must be between 100 and 10000")
    report = qualify(args.samples)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["synthetic_and_performance_gate_passed"] else 1)
