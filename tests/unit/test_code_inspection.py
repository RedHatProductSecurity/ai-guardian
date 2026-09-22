"""Tests for the pluggable code-inspection interface (Issue #2303)."""

import time

import pytest

from ai_guardian.hook_events.scanners import run_code_security_scan
from ai_guardian.scanners.file_scanner import FileScanner
from ai_guardian.scanners.code_inspection import (
    AstCodeInspector,
    CodeInspectionManager,
    CodeInspector,
    CodeInspectionFinding,
)

EVAL_CODE = "result = eval(user_input)\n"
PICKLE_CODE = "import pickle\nvalue = pickle.loads(data)\n"


class SlowInspector(CodeInspector):
    name = "slow"

    def scan(self, content, file_path="unknown.py"):
        time.sleep(0.05)
        return []


class UnavailableInspector(CodeInspector):
    name = "missing"

    @property
    def available(self):
        return False

    def scan(self, content, file_path="unknown.py"):
        return []


class FailingInspector(CodeInspector):
    name = "failing"

    def scan(self, content, file_path="unknown.py"):
        raise RuntimeError("inspector failure")


class TestAstInspector:
    def test_returns_normalized_findings(self):
        findings = AstCodeInspector().scan(EVAL_CODE, "example.py")

        assert len(findings) == 1
        finding = findings[0]
        assert isinstance(finding, CodeInspectionFinding)
        assert finding.rule_id == "AST001"
        assert finding.inspector == "ast"
        assert finding.file_path == "example.py"
        assert finding.line_number == 1
        assert finding.start_column == 9

    def test_allowlist_suppresses_ast_rule(self):
        inspector = AstCodeInspector({"allowlist": [{"rule_id": "AST001"}]})

        assert inspector.scan(EVAL_CODE, "example.py") == []

    def test_safe_yaml_loader_is_not_reported(self):
        content = "import yaml\nvalue = yaml.load(data, Loader=yaml.SafeLoader)\n"

        assert AstCodeInspector({"severity_threshold": "LOW"}).scan(content) == []


class TestCodeInspectionManager:
    def test_runs_configured_ast_inspector(self):
        result = CodeInspectionManager({"inspectors": ["ast"]}).scan(
            PICKLE_CODE, "example.py"
        )

        assert result.detected
        assert result.inspectors == ["ast"]
        assert result.findings[0].rule_id == "AST002"
        assert result.findings[0].inspector == "ast"
        assert not result.degraded

    def test_default_configuration_preserves_bandit(self):
        result = CodeInspectionManager().scan(EVAL_CODE, "example.py")

        assert result.inspectors == ["bandit"]
        assert result.findings
        assert all(f.inspector == "bandit" for f in result.findings)

    def test_unknown_inspector_is_reported_without_raising(self):
        result = CodeInspectionManager({"inspectors": ["not-installed"]}).scan(
            EVAL_CODE, "example.py"
        )

        assert result.findings == []
        assert result.unavailable == {
            "not-installed": "Unknown code inspector: not-installed"
        }
        assert result.degraded

    def test_unavailable_inspector_is_reported_without_raising(self):
        result = CodeInspectionManager(
            {"inspectors": ["missing"]},
            inspector_factories={"missing": lambda config: UnavailableInspector()},
        ).scan(EVAL_CODE, "example.py")

        assert result.findings == []
        assert result.unavailable["missing"] == "Inspector dependencies are unavailable"

    def test_timeout_is_reported_and_does_not_raise(self):
        result = CodeInspectionManager(
            {"inspectors": ["slow"], "timeout_ms": 1},
            inspector_factories={"slow": lambda config: SlowInspector()},
        ).scan(EVAL_CODE, "example.py")

        assert result.findings == []
        assert result.timed_out == ["slow"]
        assert result.degraded

    def test_inspector_errors_are_reported_and_do_not_raise(self):
        result = CodeInspectionManager(
            {"inspectors": ["failing"]},
            inspector_factories={"failing": lambda config: FailingInspector()},
        ).scan(EVAL_CODE, "example.py")

        assert result.findings == []
        assert result.errors == {"failing": "inspector failure"}


class TestCodeSecurityRunner:
    @pytest.mark.parametrize("action", ["block", "warn", "log-only"])
    def test_preserves_action_for_hook_policy_pipeline(self, action):
        result = run_code_security_scan(
            EVAL_CODE,
            "example.py",
            config={"enabled": True, "action": action, "inspectors": ["ast"]},
        )

        assert result.detected
        assert result.should_block is True
        assert result.extra["action"] == action
        assert result.extra["all_findings"]

    def test_clean_result_includes_inspection_status(self):
        result = run_code_security_scan(
            "value = 1\n",
            "example.py",
            config={"enabled": True, "inspectors": ["ast"]},
        )

        assert result.detected is False
        assert result.extra["inspectors"] == ["ast"]
        assert result.extra["unavailable"] == {}

    def test_file_scan_preserves_inspector_in_sarif_finding(self):
        scanner = FileScanner(
            {"code_scanning": {"enabled": True, "inspectors": ["ast"]}}
        )

        scanner._check_code_security("example.py", EVAL_CODE)

        assert scanner.findings
        assert scanner.findings[0]["details"]["scanner"] == "ast"
