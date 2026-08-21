"""Tests for code_annotator module — batch annotation insertion logic."""

import os
import textwrap
from unittest.mock import patch

import pytest


class TestPlanAnnotations:
    def _make_finding(
        self,
        file_path="test.py",
        line_number=1,
        rule_id="SECRET-001",
        details=None,
    ):
        return {
            "rule_id": rule_id,
            "file_path": file_path,
            "line_number": line_number,
            "details": details or {},
            "level": "error",
            "message": "test finding",
        }

    def test_single_finding_inline_annotation(self, tmp_path):
        from ai_guardian.code_annotator import plan_annotations

        f = tmp_path / "test.py"
        f.write_text("x = 1\napi_key = 'secret'\ny = 2\n")

        finding = self._make_finding(
            file_path=str(f),
            line_number=2,
            rule_id="SECRET-001",
            details={"secret_type": "generic"},
        )

        result = plan_annotations([finding], set())
        assert result.total_files == 1
        assert result.total_annotations == 1

        plan = result.plans[0]
        assert "ai-guardian:allow secret_scanning" in plan.modified_content
        assert plan.annotations[0].annotation_type == "inline"

    def test_multiple_findings_bottom_to_top(self, tmp_path):
        from ai_guardian.code_annotator import plan_annotations

        f = tmp_path / "test.py"
        f.write_text("line1\nline2\nline3\nline4\n")

        findings = [
            self._make_finding(file_path=str(f), line_number=2, rule_id="SECRET-001"),
            self._make_finding(
                file_path=str(f), line_number=4, rule_id="PROMPT-INJECTION-001"
            ),
        ]

        result = plan_annotations(findings, set())
        assert result.total_annotations == 2

        plan = result.plans[0]
        lines = plan.modified_content.splitlines()
        line2_idx = 1
        line4_idx = 3
        assert "ai-guardian:allow secret_scanning" in lines[line2_idx]
        assert "ai-guardian:allow prompt_injection" in lines[line4_idx]

    def test_same_line_different_scanners_merged(self, tmp_path):
        from ai_guardian.code_annotator import plan_annotations

        f = tmp_path / "test.py"
        f.write_text("x = 1\nsensitive = 'data'\ny = 2\n")

        findings = [
            self._make_finding(file_path=str(f), line_number=2, rule_id="SECRET-001"),
            self._make_finding(file_path=str(f), line_number=2, rule_id="PII-001"),
        ]

        result = plan_annotations(findings, set())
        assert result.total_annotations == 1

        plan = result.plans[0]
        assert "ai-guardian:allow scan_pii,secret_scanning" in plan.modified_content

    def test_never_suppress_skipped(self, tmp_path):
        from ai_guardian.code_annotator import plan_annotations

        f = tmp_path / "test.py"
        f.write_text("x = 1\n")

        finding = self._make_finding(
            file_path=str(f), line_number=1, rule_id="UNICODE-001"
        )

        result = plan_annotations([finding], set())
        assert result.total_annotations == 0
        assert result.skipped_never_suppress == 1

    def test_high_freq_fingerprint_skipped(self, tmp_path):
        from ai_guardian.code_annotator import plan_annotations

        f = tmp_path / "test.py"
        f.write_text("x = 1\n")

        finding = self._make_finding(
            file_path=str(f),
            line_number=1,
            rule_id="SECRET-001",
            details={"secret_type": "generic"},
        )

        result = plan_annotations([finding], {("SECRET-001", "generic")})
        assert result.total_annotations == 0

    def test_unsupported_file_type_skipped(self, tmp_path):
        from ai_guardian.code_annotator import plan_annotations

        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}\n')

        finding = self._make_finding(
            file_path=str(f), line_number=1, rule_id="SECRET-001"
        )

        result = plan_annotations([finding], set())
        assert result.total_annotations == 0
        assert result.skipped_unsupported == 1

    def test_no_line_number_skipped(self, tmp_path):
        from ai_guardian.code_annotator import plan_annotations

        f = tmp_path / "test.py"
        f.write_text("x = 1\n")

        finding = self._make_finding(
            file_path=str(f), line_number=None, rule_id="SECRET-001"
        )

        result = plan_annotations([finding], set())
        assert result.total_annotations == 0
        assert result.skipped_no_location == 1

    def test_already_annotated_region_skipped(self, tmp_path):
        from ai_guardian.code_annotator import plan_annotations

        f = tmp_path / "test.py"
        f.write_text(
            "# ai-guardian:begin-allow\n"
            "api_key = 'secret'\n"
            "# ai-guardian:end-allow\n"
        )

        finding = self._make_finding(
            file_path=str(f), line_number=2, rule_id="SECRET-001"
        )

        result = plan_annotations([finding], set())
        assert result.total_annotations == 0
        assert result.skipped_annotated == 1

    def test_python_multiline_string_block_annotation(self, tmp_path):
        from ai_guardian.code_annotator import plan_annotations

        source = textwrap.dedent('''\
            x = 1
            msg = """
            SSN: 123-45-6789
            """
            y = 2
        ''')
        f = tmp_path / "test.py"
        f.write_text(source)

        finding = self._make_finding(file_path=str(f), line_number=3, rule_id="PII-001")

        result = plan_annotations([finding], set())
        assert result.total_annotations == 1

        plan = result.plans[0]
        assert plan.annotations[0].annotation_type == "block"
        assert "ai-guardian:begin-allow scan_pii" in plan.modified_content
        assert "ai-guardian:end-allow" in plan.modified_content

    def test_javascript_inline_annotation(self, tmp_path):
        from ai_guardian.code_annotator import plan_annotations

        f = tmp_path / "app.js"
        f.write_text("const key = 'secret';\nconst x = 1;\n")

        finding = self._make_finding(
            file_path=str(f), line_number=1, rule_id="SECRET-001"
        )

        result = plan_annotations([finding], set())
        assert result.total_annotations == 1

        plan = result.plans[0]
        assert "// ai-guardian:allow secret_scanning" in plan.modified_content


class TestApplyAnnotationPlan:
    def test_apply_writes_file(self, tmp_path):
        from ai_guardian.code_annotator import AnnotationPlan, apply_annotation_plan

        f = tmp_path / "test.py"
        f.write_text("original\n")

        plan = AnnotationPlan(
            file_path=str(f),
            annotations=[],
            original_content="original\n",
            modified_content="modified\n",
        )

        assert apply_annotation_plan(plan)
        assert f.read_text() == "modified\n"


class TestApplyAllPlans:
    def test_applies_multiple(self, tmp_path):
        from ai_guardian.code_annotator import AnnotationPlan, apply_all_plans

        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("orig1\n")
        f2.write_text("orig2\n")

        plans = [
            AnnotationPlan(
                file_path=str(f1),
                annotations=[],
                original_content="orig1\n",
                modified_content="mod1\n",
            ),
            AnnotationPlan(
                file_path=str(f2),
                annotations=[],
                original_content="orig2\n",
                modified_content="mod2\n",
            ),
        ]

        modified = apply_all_plans(plans)
        assert len(modified) == 2
        assert f1.read_text() == "mod1\n"
        assert f2.read_text() == "mod2\n"


class TestShowInteractiveDiff:
    def test_non_tty_returns_all(self):
        from ai_guardian.code_annotator import AnnotationPlan, show_interactive_diff

        plans = [
            AnnotationPlan(
                file_path="test.py",
                annotations=[],
                original_content="a\n",
                modified_content="b\n",
            )
        ]

        with patch("ai_guardian.code_annotator.sys") as mock_sys:
            mock_sys.stdin.isatty.return_value = False
            result = show_interactive_diff(plans)
            assert len(result) == len(plans)


class TestFormatPrBody:
    def test_generates_body(self):
        from ai_guardian.code_annotator import (
            AnnotationPlan,
            AnnotationResult,
            PlannedAnnotation,
            format_pr_body,
        )

        ann = PlannedAnnotation(
            line_number=5,
            scanner_types=["secret_scanning"],
            annotation_type="inline",
        )
        plan = AnnotationPlan(
            file_path="src/app.py",
            annotations=[ann],
            original_content="",
            modified_content="",
        )
        result = AnnotationResult(plans=[plan])

        body = format_pr_body(result)
        assert "src/app.py" in body
        assert "secret_scanning" in body
        assert "1 annotation" in body
