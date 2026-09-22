"""Pluggable source-code inspection primitives.

The code-security pipeline accepts inspectors that produce the same normalized
finding model.  Bandit remains the default inspector; the built-in AST
inspector provides a dependency-free second implementation for Python code.
"""

from __future__ import annotations

import ast
import concurrent.futures
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
DEFAULT_INSPECTORS = ("bandit",)
DEFAULT_TIMEOUT_MS = 2000


class CodeInspectorUnavailableError(RuntimeError):
    """Raised when an inspector cannot run in the current environment."""


class CodeInspectorTimeoutError(RuntimeError):
    """Raised when an inspector exceeds its configured time limit."""


@dataclass
class CodeInspectionFinding:
    """Normalized finding returned by every code inspector."""

    rule_id: str
    description: str
    line_number: int
    severity: str
    confidence: str
    file_path: str
    end_line: Optional[int] = None
    start_column: Optional[int] = None
    end_column: Optional[int] = None
    snippet: Optional[str] = None
    inspector: str = ""

    @property
    def message(self) -> str:
        """Return the normalized human-readable finding message."""
        return self.description


@dataclass
class CodeInspectionResult:
    """Aggregate result for one source-code inspection pass."""

    findings: List[CodeInspectionFinding] = field(default_factory=list)
    inspectors: List[str] = field(default_factory=list)
    unavailable: Dict[str, str] = field(default_factory=dict)
    timed_out: List[str] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    @property
    def detected(self) -> bool:
        """Whether any configured inspector reported a finding."""
        return bool(self.findings)

    @property
    def degraded(self) -> bool:
        """Whether the inspection pass could not run every inspector."""
        return bool(self.unavailable or self.timed_out or self.errors)


class CodeInspector(ABC):
    """Interface implemented by source-code security inspectors."""

    name = "unknown"

    @property
    def available(self) -> bool:
        """Return whether this inspector's runtime dependencies are available."""
        return True

    @abstractmethod
    def scan(
        self, content: str, file_path: str = "unknown.py"
    ) -> List[CodeInspectionFinding]:
        """Inspect source content and return normalized findings."""

    def inspect(
        self, content: str, file_path: str = "unknown.py"
    ) -> List[CodeInspectionFinding]:
        """Alias for integrations that use ``inspect`` terminology."""
        return self.scan(content, file_path)


def is_code_finding_allowlisted(
    finding: CodeInspectionFinding,
    allowlist: Sequence[Dict[str, Any]],
    file_path: Optional[str] = None,
) -> bool:
    """Return whether a finding matches a code-inspection allowlist entry."""
    finding_path = file_path or finding.file_path
    for entry in allowlist or []:
        if not isinstance(entry, dict):
            continue
        entry_rule_id = entry.get("test_id") or entry.get("rule_id") or ""
        if entry_rule_id and entry_rule_id != finding.rule_id:
            continue
        entry_file = entry.get("file", "")
        if entry_file and not finding_path.startswith(entry_file):
            continue
        return True
    return False


def _severity_at_or_above(severity: str, threshold: str) -> bool:
    return SEVERITY_ORDER.get(severity.upper(), 0) >= SEVERITY_ORDER.get(
        threshold.upper(), SEVERITY_ORDER["MEDIUM"]
    )


def _source_snippet(lines: List[str], line_number: int) -> Optional[str]:
    if not line_number or line_number < 1 or line_number > len(lines):
        return None
    return lines[line_number - 1].strip()[:120]


def _call_name(node: ast.Call) -> str:
    value: Any = node.func
    parts: List[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _is_safe_yaml_load(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg != "Loader":
            continue
        value = keyword.value
        return isinstance(value, ast.Attribute) and value.attr == "SafeLoader"
    return False


def _ast_rule(node: ast.Call) -> Optional[tuple]:
    name = _call_name(node)
    if name in {"eval", "exec", "compile", "__import__"}:
        return (
            "AST001",
            "Dynamic code execution or import detected",
            "HIGH",
        )
    if name in {
        "pickle.load",
        "pickle.loads",
        "cPickle.load",
        "cPickle.loads",
        "marshal.load",
        "marshal.loads",
    }:
        return ("AST002", "Unsafe deserialization API detected", "HIGH")
    if name in {"yaml.load", "yaml.unsafe_load"} and not _is_safe_yaml_load(node):
        return ("AST003", "Unsafe YAML loading API detected", "MEDIUM")
    if name in {
        "subprocess.call",
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.check_call",
        "subprocess.check_output",
    }:
        if any(
            keyword.arg == "shell"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        ):
            return ("AST004", "Subprocess invocation enables shell execution", "HIGH")
    if name == "os.system":
        return ("AST005", "Operating-system command execution detected", "HIGH")
    return None


class AstCodeInspector(CodeInspector):
    """Dependency-free Python AST inspector for high-risk API usage."""

    name = "ast"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        threshold = str(self.config.get("severity_threshold", "MEDIUM"))
        self._threshold = threshold.upper()
        self._allowlist = self.config.get("allowlist", []) or []

    def scan(
        self, content: str, file_path: str = "unknown.py"
    ) -> List[CodeInspectionFinding]:
        if not content.strip():
            return []

        try:
            tree = ast.parse(content, filename=file_path)
        except (SyntaxError, TypeError, ValueError) as exc:
            logger.debug("AST code inspection skipped for %s: %s", file_path, exc)
            return []

        lines = content.splitlines()
        findings: List[CodeInspectionFinding] = []

        class Visitor(ast.NodeVisitor):
            def visit_Call(self, node: ast.Call) -> None:
                rule = _ast_rule(node)
                line_number = getattr(node, "lineno", 0) or 0
                line = lines[line_number - 1] if 0 < line_number <= len(lines) else ""
                if (
                    rule
                    and _severity_at_or_above(rule[2], self_outer._threshold)
                    and "ai-guardian:allow" not in line
                    and "# nosec" not in line
                ):
                    finding = CodeInspectionFinding(
                        rule_id=rule[0],
                        description=rule[1],
                        line_number=line_number,
                        end_line=getattr(node, "end_lineno", None),
                        start_column=getattr(node, "col_offset", None),
                        end_column=getattr(node, "end_col_offset", None),
                        severity=rule[2],
                        confidence="HIGH",
                        file_path=file_path,
                        snippet=_source_snippet(lines, line_number),
                        inspector=AstCodeInspector.name,
                    )
                    if not is_code_finding_allowlisted(
                        finding, self_outer._allowlist, file_path
                    ):
                        findings.append(finding)
                self.generic_visit(node)

        self_outer = self
        Visitor().visit(tree)
        return findings


def _bandit_factory(config: Dict[str, Any]) -> CodeInspector:
    from ai_guardian.scanners.bandit_scanner import BanditScanner

    return BanditScanner(config)


InspectorFactory = Callable[[Dict[str, Any]], CodeInspector]

INSPECTOR_FACTORIES: Dict[str, InspectorFactory] = {
    "bandit": _bandit_factory,
    "ast": AstCodeInspector,
}


def register_code_inspector(name: str, factory: InspectorFactory) -> None:
    """Register an inspector factory for use by ``CodeInspectionManager``."""
    normalized_name = name.strip().lower()
    if not normalized_name:
        raise ValueError("Inspector name cannot be empty")
    INSPECTOR_FACTORIES[normalized_name] = factory


class CodeInspectionManager:
    """Run configured inspectors and normalize their outcomes."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        inspector_factories: Optional[Dict[str, InspectorFactory]] = None,
    ):
        self.config = config or {}
        self.inspector_names = self._get_inspector_names(self.config)
        self.timeout_ms = self._get_timeout_ms(self.config)
        self._factories = dict(INSPECTOR_FACTORIES)
        if inspector_factories:
            self._factories.update(
                {
                    name.strip().lower(): factory
                    for name, factory in inspector_factories.items()
                }
            )

    @staticmethod
    def _get_inspector_names(config: Dict[str, Any]) -> List[str]:
        configured = config.get("inspectors", config.get("inspector"))
        if configured is None:
            configured = DEFAULT_INSPECTORS
        if isinstance(configured, str):
            configured = [configured]
        if not isinstance(configured, (list, tuple)):
            logger.warning("Invalid code_scanning.inspectors value; using Bandit")
            configured = DEFAULT_INSPECTORS

        names: List[str] = []
        for value in configured:
            name = str(value).strip().lower()
            if name and name not in names:
                names.append(name)
        return names

    @staticmethod
    def _get_timeout_ms(config: Dict[str, Any]) -> float:
        raw_timeout = config.get("timeout_ms")
        if raw_timeout is None and config.get("timeout_seconds") is not None:
            try:
                raw_timeout = float(config["timeout_seconds"]) * 1000
            except (TypeError, ValueError):
                raw_timeout = None
        if raw_timeout is None:
            return DEFAULT_TIMEOUT_MS
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid code_scanning.timeout_ms; using %sms", DEFAULT_TIMEOUT_MS
            )
            return DEFAULT_TIMEOUT_MS
        return max(timeout, 0.0)

    def _create_inspector(self, name: str) -> CodeInspector:
        factory = self._factories.get(name)
        if factory is None:
            raise CodeInspectorUnavailableError(f"Unknown code inspector: {name}")
        try:
            inspector = factory(self.config)
        except CodeInspectorUnavailableError:
            raise
        except (ImportError, ModuleNotFoundError) as exc:
            raise CodeInspectorUnavailableError(str(exc)) from exc

        if inspector is None:
            raise CodeInspectorUnavailableError(
                "Inspector factory returned no inspector"
            )
        available = getattr(inspector, "available", True)
        if callable(available):
            available = available()
        if not available:
            raise CodeInspectorUnavailableError(
                "Inspector dependencies are unavailable"
            )
        return inspector

    def _run_with_timeout(
        self, inspector: CodeInspector, content: str, file_path: str
    ) -> List[CodeInspectionFinding]:
        if self.timeout_ms <= 0:
            return inspector.scan(content, file_path=file_path)

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(inspector.scan, content, file_path)
        try:
            return future.result(timeout=self.timeout_ms / 1000)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise CodeInspectorTimeoutError(
                f"Inspector exceeded {self.timeout_ms:g}ms timeout"
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def scan(self, content: str, file_path: str = "unknown.py") -> CodeInspectionResult:
        started = time.monotonic()
        result = CodeInspectionResult(inspectors=list(self.inspector_names))
        if not content.strip() or not self.inspector_names:
            result.elapsed_ms = (time.monotonic() - started) * 1000
            return result

        for name in self.inspector_names:
            try:
                inspector = self._create_inspector(name)
            except CodeInspectorUnavailableError as exc:
                result.unavailable[name] = str(exc)
                logger.warning("Code inspector %s unavailable: %s", name, exc)
                continue
            except Exception as exc:
                result.errors[name] = str(exc)
                logger.warning("Code inspector %s failed to initialize: %s", name, exc)
                continue

            try:
                findings = self._run_with_timeout(inspector, content, file_path) or []
            except CodeInspectorTimeoutError as exc:
                result.timed_out.append(name)
                logger.warning("Code inspector %s timed out: %s", name, exc)
                continue
            except CodeInspectorUnavailableError as exc:
                result.unavailable[name] = str(exc)
                logger.warning("Code inspector %s unavailable: %s", name, exc)
                continue
            except Exception as exc:
                result.errors[name] = str(exc)
                logger.warning("Code inspector %s failed: %s", name, exc)
                continue

            for finding in findings:
                if not finding.inspector:
                    finding.inspector = name
                if not is_code_finding_allowlisted(
                    finding, self.config.get("allowlist", []) or [], file_path
                ):
                    result.findings.append(finding)

        result.elapsed_ms = (time.monotonic() - started) * 1000
        return result

    inspect = scan

    @classmethod
    def available_inspectors(cls) -> List[str]:
        """Return names currently registered with the inspection manager."""
        return sorted(INSPECTOR_FACTORIES)


# Both spellings are useful to callers: the manager operates on inspections,
# while the individual implementations are called inspectors.
CodeInspectorManager = CodeInspectionManager
ASTInspector = AstCodeInspector
AstInspector = AstCodeInspector
