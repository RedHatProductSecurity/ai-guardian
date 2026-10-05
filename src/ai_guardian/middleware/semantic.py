"""Provider-payload normalization and semantic content scanning.

The supervisor contract gives the service a bounded body, not a provider
specific object model.  This module scans every textual leaf in JSON provider
payloads, including nested message, tool-result, tool-call, file, and shell
content, and writes replacements back to the same leaf without exposing raw
content in diagnostics.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, Mapping, Optional, Sequence

from ai_guardian.scanners.pipeline import scan_content
from ai_guardian.scanners.scan_result import ScanResult
from ai_guardian.scanners.secret_redactor import SecretRedactor

logger = logging.getLogger(__name__)

SECRET_OR_PII_TYPES = {
    "secret_detected",
    "pii_detected",
    "secret_redaction",
}


@dataclass(frozen=True)
class ContentFinding:
    """Audit-safe representation of one scanner category."""

    type: str
    label: str
    count: int = 1
    confidence: str = "medium"
    severity: str = "high"
    rule_id: str = ""


@dataclass
class ContentEvaluation:
    """Result of inspecting one semantic text segment or payload."""

    blocked: bool = False
    redacted_text: Optional[str] = None
    findings: list[ContentFinding] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    reason_code: str = ""
    error: bool = False

    @property
    def changed(self) -> bool:
        return self.redacted_text is not None


@dataclass(frozen=True)
class TextSegment:
    """A textual JSON leaf and its stable semantic path."""

    path: tuple[str, ...]
    text: str


@dataclass
class NormalizedPayload:
    """Parsed payload plus the segments that can be scanned and replaced."""

    raw_text: str
    parsed: Any = None
    is_json: bool = False
    segments: list[TextSegment] = field(default_factory=list)

    def with_replacements(self, replacements: Mapping[tuple[str, ...], str]) -> str:
        if not replacements:
            return self.raw_text
        if not self.is_json:
            return replacements.get(("body",), self.raw_text)
        if isinstance(self.parsed, str) and ("body",) in replacements:
            return json.dumps(
                replacements["body",], ensure_ascii=False, separators=(",", ":")
            )
        value = copy.deepcopy(self.parsed)
        for path, replacement in replacements.items():
            _set_path(value, path, replacement)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def normalize_payload(body: bytes | str) -> NormalizedPayload:
    """Decode a bounded body and expose all JSON string leaves.

    Non-JSON UTF-8 content remains a single ``body`` segment.  Binary data is
    intentionally not guessed or logged; callers decide whether the provider
    operation should fail closed for it.
    """

    if isinstance(body, bytes):
        text = body.decode("utf-8")
    else:
        text = body
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return NormalizedPayload(
            raw_text=text,
            parsed=None,
            is_json=False,
            segments=[TextSegment(("body",), text)] if text else [],
        )

    if isinstance(parsed, str):
        segments = [TextSegment(("body",), parsed)] if parsed else []
    else:
        segments = [
            TextSegment(path, value)
            for path, value in _iter_text_values(parsed)
            if value
        ]
    return NormalizedPayload(
        raw_text=text,
        parsed=parsed,
        is_json=True,
        segments=segments,
    )


def _iter_text_values(
    value: Any, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, child in value.items():
            # Keys are provider/schema metadata, not user content.  Values
            # include all known content forms without maintaining a brittle
            # provider-specific allow-list.
            yield from _iter_text_values(child, (*path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_text_values(child, (*path, str(index)))


def _set_path(value: Any, path: Sequence[str], replacement: str) -> None:
    if not path:
        return
    current = value
    for component in path[:-1]:
        if isinstance(current, list):
            current = current[int(component)]
        elif isinstance(current, dict):
            current = current[component]
        else:
            return
    leaf = path[-1]
    if isinstance(current, list):
        current[int(leaf)] = replacement
    elif isinstance(current, dict):
        current[leaf] = replacement


def _confidence(value: Any) -> str:
    if isinstance(value, (int, float)):
        if value >= 0.85:
            return "high"
        if value >= 0.6:
            return "medium"
        return "low"
    return "medium"


def _finding_from_result(result: ScanResult) -> ContentFinding:
    count = result.total_findings or (
        len(result.findings or []) if result.findings else 1
    )
    label = result.attack_type or result.violation_type.replace("_", " ")
    return ContentFinding(
        type=result.violation_type,
        label=label[:128],
        count=max(1, int(count)),
        confidence=_confidence(result.confidence),
        severity=result.severity or "high",
        rule_id=result.rule_id[:128],
    )


class SemanticContentScanner:
    """Run existing AI Guardian scanners against provider content."""

    def __init__(
        self,
        profile: Mapping[str, Any],
        *,
        scan_fn: Callable[..., list[ScanResult]] = scan_content,
        redactor_factory: Callable[..., SecretRedactor] = SecretRedactor,
    ) -> None:
        self.profile = copy.deepcopy(dict(profile))
        self.scan_fn = scan_fn
        self.redactor = redactor_factory(
            config=self.profile.get("secret_redaction", {}),
            pii_config=self.profile.get("scan_pii", {}),
        )

    def inspect_text(
        self,
        text: str,
        *,
        scanners: Iterable[str],
        redact: bool = False,
        filename: str = "middleware-content",
    ) -> ContentEvaluation:
        selected = set(scanners)
        if not text or not selected:
            return ContentEvaluation()
        scan_selected = set(selected)
        if "secret_redaction" in scan_selected:
            scan_selected.update({"secret_scanning", "scan_pii"})
        config = self._scanner_config(scan_selected)
        try:
            results = self.scan_fn(
                text,
                config=config,
                filename=filename,
                source_type="provider_content",
            )
        except Exception as exc:
            logger.warning("middleware semantic scan failed: %s", type(exc).__name__)
            return ContentEvaluation(
                blocked=True,
                reason_code="semantic_scan_error",
                error=True,
            )

        findings: list[ContentFinding] = []
        blocking_results: list[ScanResult] = []
        for result in results:
            if result.error_message and result.extra.get("scan_error"):
                logger.warning("middleware scanner returned an error result")
                return ContentEvaluation(
                    blocked=True,
                    findings=findings,
                    reason_code="semantic_scan_error",
                    error=True,
                )
            if not result.detected:
                continue
            findings.append(_finding_from_result(result))
            if result.should_block:
                blocking_results.append(result)

        redacted_text: Optional[str] = None
        should_redact = redact and (
            "secret_redaction" in selected
            or any(finding.type in SECRET_OR_PII_TYPES for finding in findings)
        )
        if should_redact:
            try:
                redaction = self.redactor.redact(text)
                candidate = redaction.get("redacted_text")
                if isinstance(candidate, str) and candidate != text:
                    redacted_text = candidate
                    if not any(
                        finding.type in SECRET_OR_PII_TYPES for finding in findings
                    ):
                        redactions = redaction.get("redactions")
                        findings.append(
                            ContentFinding(
                                type="secret_redaction",
                                label="sensitive content redacted",
                                count=(
                                    len(redactions)
                                    if isinstance(redactions, list) and redactions
                                    else 1
                                ),
                                severity="high",
                            )
                        )
            except Exception as exc:
                logger.warning(
                    "middleware response redaction failed: %s", type(exc).__name__
                )
                return ContentEvaluation(
                    blocked=True,
                    findings=findings,
                    reason_code="response_redaction_error",
                    error=True,
                )

        remaining_blocking = blocking_results
        if redacted_text is not None:
            remaining_blocking = [
                result
                for result in blocking_results
                if result.violation_type not in SECRET_OR_PII_TYPES
            ]

        return ContentEvaluation(
            blocked=bool(remaining_blocking),
            redacted_text=redacted_text,
            findings=findings,
            metadata={"finding_count": str(len(findings))} if findings else {},
            reason_code=("semantic_content_blocked" if remaining_blocking else ""),
        )

    def inspect_payload(
        self,
        body: bytes | str,
        *,
        scanners: Iterable[str],
        redact: bool = False,
        filename: str = "provider-payload",
    ) -> tuple[str, ContentEvaluation]:
        """Scan and optionally transform every textual payload segment."""

        normalized = normalize_payload(body)
        replacements: Dict[tuple[str, ...], str] = {}
        combined = ContentEvaluation()
        finding_count = 0
        for segment in normalized.segments:
            evaluation = self.inspect_text(
                segment.text,
                scanners=scanners,
                redact=redact,
                filename=f"{filename}:{'.'.join(segment.path)}",
            )
            combined.blocked = combined.blocked or evaluation.blocked
            combined.error = combined.error or evaluation.error
            combined.reason_code = combined.reason_code or evaluation.reason_code
            combined.findings.extend(evaluation.findings)
            finding_count += len(evaluation.findings)
            combined.metadata.update(
                {
                    key: value
                    for key, value in evaluation.metadata.items()
                    if key != "finding_count"
                }
            )
            if evaluation.redacted_text is not None:
                replacements[segment.path] = evaluation.redacted_text

        try:
            transformed = normalized.with_replacements(replacements)
        except (TypeError, ValueError, IndexError) as exc:
            logger.warning(
                "middleware payload replacement failed: %s", type(exc).__name__
            )
            combined.blocked = True
            combined.error = True
            combined.reason_code = "payload_transform_error"
            transformed = normalized.raw_text
        combined.redacted_text = (
            transformed if transformed != normalized.raw_text else None
        )
        if finding_count:
            combined.metadata["finding_count"] = str(finding_count)
        return transformed, combined

    def _scanner_config(self, selected: set[str]) -> Dict[str, Any]:
        config = copy.deepcopy(self.profile)
        for section in (
            "secret_scanning",
            "scan_pii",
            "prompt_injection",
            "context_poisoning",
            "supply_chain",
            "scan_offensive",
            "canary_detection",
            "config_file_scanning",
        ):
            if section not in selected and isinstance(config.get(section), dict):
                config[section]["enabled"] = False
        return config
