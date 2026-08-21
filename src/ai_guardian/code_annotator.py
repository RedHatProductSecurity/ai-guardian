"""Batch annotation engine for init-project --scan --annotate.

Plans and applies inline ai-guardian:allow annotations around
below-threshold scan findings, with scanner type qualifiers.
"""

import difflib
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ai_guardian.annotations import get_suppressed_lines
from ai_guardian.scan_analyzer import (
    NEVER_SUPPRESS,
    _scanner_for_rule_id,
    fingerprint_finding,
)
from ai_guardian.tui.source_annotator import (
    find_enclosing_multiline_string,
    get_comment_prefix,
    write_annotated_source,
)

logger = logging.getLogger(__name__)


@dataclass
class PlannedAnnotation:
    """A single annotation to insert in a source file."""

    line_number: int
    scanner_types: List[str]
    annotation_type: str
    block_range: Optional[Tuple[int, int]] = None


@dataclass
class AnnotationPlan:
    """Plan for annotating a single file."""

    file_path: str
    annotations: List[PlannedAnnotation]
    original_content: str
    modified_content: str


@dataclass
class AnnotationResult:
    """Result of batch annotation planning."""

    plans: List[AnnotationPlan] = field(default_factory=list)
    skipped_unsupported: int = 0
    skipped_annotated: int = 0
    skipped_never_suppress: int = 0
    skipped_no_location: int = 0
    skipped_no_scanner: int = 0

    @property
    def total_annotations(self) -> int:
        return sum(len(p.annotations) for p in self.plans)

    @property
    def total_files(self) -> int:
        return len(self.plans)


def plan_annotations(
    findings: List[Dict[str, Any]],
    high_freq_fingerprints: Set[Tuple[str, str]],
) -> AnnotationResult:
    """Plan annotations for below-threshold findings.

    Filters out high-frequency findings (config-level suppression),
    NEVER_SUPPRESS rule_ids, and findings in already-annotated regions.
    Groups remaining findings by file and builds annotation plans.
    """
    result = AnnotationResult()

    by_file: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for finding in findings:
        rule_id = finding.get("rule_id", "")

        if rule_id in NEVER_SUPPRESS:
            result.skipped_never_suppress += 1
            continue

        fp = fingerprint_finding(finding)
        if fp in high_freq_fingerprints:
            continue

        line_number = finding.get("line_number")
        if not line_number:
            result.skipped_no_location += 1
            continue

        file_path = finding.get("file_path")
        if not file_path:
            result.skipped_no_location += 1
            continue

        scanner_type = _scanner_for_rule_id(rule_id)
        if not scanner_type:
            result.skipped_no_scanner += 1
            continue

        prefix = get_comment_prefix(file_path)
        if prefix is None:
            result.skipped_unsupported += 1
            continue

        by_file[file_path].append(finding)

    for file_path, file_findings in sorted(by_file.items()):
        plan = _plan_file_annotations(file_path, file_findings, result)
        if plan is not None:
            result.plans.append(plan)

    return result


def _plan_file_annotations(
    file_path: str,
    findings: List[Dict[str, Any]],
    result: AnnotationResult,
) -> Optional[AnnotationPlan]:
    """Build annotation plan for a single file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        logger.warning("Cannot read %s — skipping annotations", file_path)
        return None

    suppressed, _, _, _ = get_suppressed_lines(content)

    prefix = get_comment_prefix(file_path)
    if prefix is None:
        return None

    by_line: Dict[int, Set[str]] = defaultdict(set)
    for finding in findings:
        line_number = finding.get("line_number")
        if not line_number:
            continue

        line_idx = line_number - 1
        if line_idx in suppressed:
            result.skipped_annotated += 1
            continue

        scanner_type = _scanner_for_rule_id(finding.get("rule_id", ""))
        if scanner_type:
            by_line[line_number].add(scanner_type)

    if not by_line:
        return None

    annotations = []
    for line_number, scanner_types in sorted(by_line.items()):
        sorted_types = sorted(scanner_types)
        multiline = find_enclosing_multiline_string(file_path, line_number)

        if multiline is not None:
            start, end = multiline
            annotations.append(
                PlannedAnnotation(
                    line_number=line_number,
                    scanner_types=sorted_types,
                    annotation_type="block",
                    block_range=(start, end),
                )
            )
        else:
            annotations.append(
                PlannedAnnotation(
                    line_number=line_number,
                    scanner_types=sorted_types,
                    annotation_type="inline",
                )
            )

    annotations.sort(key=lambda a: a.line_number, reverse=True)

    merged = _merge_overlapping_blocks(annotations)

    modified = _apply_annotations(content, merged, prefix)

    return AnnotationPlan(
        file_path=file_path,
        annotations=merged,
        original_content=content,
        modified_content=modified,
    )


def _merge_overlapping_blocks(
    annotations: List[PlannedAnnotation],
) -> List[PlannedAnnotation]:
    """Merge block annotations that cover the same range."""
    merged: List[PlannedAnnotation] = []
    seen_blocks: Dict[Tuple[int, int], PlannedAnnotation] = {}

    for ann in annotations:
        if ann.annotation_type == "block" and ann.block_range is not None:
            key = ann.block_range
            if key in seen_blocks:
                existing = seen_blocks[key]
                for st in ann.scanner_types:
                    if st not in existing.scanner_types:
                        existing.scanner_types.append(st)
                existing.scanner_types.sort()
            else:
                seen_blocks[key] = ann
                merged.append(ann)
        else:
            merged.append(ann)

    merged.sort(key=lambda a: a.line_number, reverse=True)
    return merged


def _apply_annotations(
    content: str,
    annotations: List[PlannedAnnotation],
    prefix: str,
) -> str:
    """Apply annotations to content, bottom-to-top."""
    lines = content.splitlines(keepends=True)

    for ann in annotations:
        type_str = ",".join(ann.scanner_types)

        if ann.annotation_type == "block" and ann.block_range is not None:
            start, end = ann.block_range
            indent = (
                _get_indentation(lines[start - 1]) if start - 1 < len(lines) else ""
            )
            begin_line = f"{indent}{prefix} ai-guardian:begin-allow {type_str}\n"
            end_line = f"{indent}{prefix} ai-guardian:end-allow\n"
            lines.insert(end, end_line)
            lines.insert(start - 1, begin_line)
        else:
            idx = ann.line_number - 1
            if 0 <= idx < len(lines):
                line = lines[idx]
                stripped = line.rstrip("\n\r")
                eol = line[len(stripped) :]
                marker = f"  {prefix} ai-guardian:allow {type_str}"
                lines[idx] = stripped + marker + eol

    return "".join(lines)


def _get_indentation(line: str) -> str:
    """Extract leading whitespace from a line."""
    return line[: len(line) - len(line.lstrip())]


def apply_annotation_plan(plan: AnnotationPlan) -> bool:
    """Apply a single file's annotation plan by writing the modified content."""
    return write_annotated_source(plan.file_path, plan.modified_content)


def apply_all_plans(plans: List[AnnotationPlan]) -> List[str]:
    """Apply all annotation plans. Returns list of modified file paths."""
    modified = []
    for plan in plans:
        if apply_annotation_plan(plan):
            modified.append(plan.file_path)
        else:
            logger.warning("Failed to write annotations to %s", plan.file_path)
    return modified


def show_interactive_diff(plans: List[AnnotationPlan]) -> List[AnnotationPlan]:
    """Show per-file diffs interactively, return accepted plans."""
    if not sys.stdin.isatty():
        return plans

    accepted = []
    for plan in plans:
        orig_lines = plan.original_content.splitlines(keepends=True)
        mod_lines = plan.modified_content.splitlines(keepends=True)

        diff = list(
            difflib.unified_diff(
                orig_lines,
                mod_lines,
                fromfile=f"a/{plan.file_path}",
                tofile=f"b/{plan.file_path}",
                lineterm="",
            )
        )

        if not diff:
            continue

        print(f"\n{'=' * 60}")
        print(f"File: {plan.file_path}")
        print(f"Annotations: {len(plan.annotations)}")
        print(f"{'=' * 60}")
        for line in diff:
            print(line)

        try:
            response = input("\n[A]ccept / [S]kip / [Q]uit? ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if response in ("a", "accept", ""):
            accepted.append(plan)
        elif response in ("q", "quit"):
            break

    return accepted


def format_pr_body(result: AnnotationResult) -> str:
    """Generate PR/MR body describing the annotations."""
    lines = [
        "## Summary",
        "",
        "Auto-generated inline annotations for ai-guardian false positive suppression.",
        "",
        f"- **Files annotated**: {result.total_files}",
        f"- **Annotations inserted**: {result.total_annotations}",
    ]

    if result.skipped_annotated:
        lines.append(f"- Skipped (already annotated): {result.skipped_annotated}")
    if result.skipped_unsupported:
        lines.append(f"- Skipped (unsupported file type): {result.skipped_unsupported}")

    lines.append("")
    lines.append("### Annotated files")
    lines.append("")

    scanner_types_seen: Set[str] = set()
    for plan in result.plans:
        ann_count = len(plan.annotations)
        lines.append(
            f"- `{plan.file_path}` ({ann_count} annotation{'s' if ann_count != 1 else ''})"
        )
        for ann in plan.annotations:
            scanner_types_seen.update(ann.scanner_types)

    if scanner_types_seen:
        lines.append("")
        lines.append("### Scanner types")
        lines.append("")
        for st in sorted(scanner_types_seen):
            lines.append(f"- `{st}`")

    lines.append("")
    lines.append("---")
    lines.append("Generated by `ai-guardian init-project --scan --annotate`")

    return "\n".join(lines)
