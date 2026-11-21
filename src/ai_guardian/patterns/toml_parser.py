"""
TOML pattern file parser and rule compiler.

Loads pattern rules from TOML files and compiles them into Python objects
for fast in-memory matching. Supports multiple match types: regex, literal,
cidr, range, and glob.

Go RE2 regex compatibility is validated at load time — patterns using
Python-only features (e.g., \\p{L}) are rejected with a warning.
"""

import ipaddress
import logging
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


logger = logging.getLogger(__name__)

VALID_MATCH_TYPES = {"regex", "literal", "cidr", "range", "glob"}

RE2_INCOMPATIBLE_PATTERNS = [
    (r"\\p\{", "Unicode property escapes (\\p{...}) are not supported in Go RE2"),
    (
        r"\\P\{",
        "Negated Unicode property escapes (\\P{...}) are not supported in Go RE2",
    ),
    (r"\(\?<[!=]", "Lookbehinds are not supported in Go RE2"),
    (r"\(\?>", "Atomic groups are not supported in Go RE2"),
    (r"\(\?\(", "Conditional patterns are not supported in Go RE2"),
]


@dataclass
class CompiledRule:
    """A single compiled pattern rule ready for matching.

    Attributes:
        id: Unique rule identifier (e.g., "openai-api-key")
        match_type: One of: regex, literal, cidr, range, glob
        compiled: The compiled matcher object:
            - regex: re.Pattern
            - literal: tuple (source_char, target_char)
            - cidr: ipaddress.IPv4Network or IPv6Network
            - range: tuple (start_int, end_int)
            - glob: str (raw glob pattern)
        category: Rule category (secret, pii, prompt_injection, unicode, config_exfil, ssrf)
        metadata: Additional fields from TOML (description, redaction_strategy, etc.)
    """

    id: str
    match_type: str
    compiled: Any
    category: str
    metadata: dict = field(default_factory=dict)


def validate_re2_compatible(pattern: str) -> Tuple[bool, Optional[str]]:
    """Check if a regex pattern is compatible with Go RE2.

    Args:
        pattern: Regex pattern string

    Returns:
        (is_compatible, reason) — reason is None if compatible
    """
    for incompatible_re, reason in RE2_INCOMPATIBLE_PATTERNS:
        if re.search(incompatible_re, pattern):
            return False, reason
    return True, None


def validate_regex_safety(pattern: str) -> Tuple[bool, Optional[str]]:
    """Reject regex structures that can trigger catastrophic backtracking.

    Python's ``re`` engine is backtracking-based, while TOML rules may come from
    user or pattern-server configuration. Reject nested repetitions and repeated
    alternations before a rule can reach the scanner. The check is deliberately
    conservative: a false negative could turn untrusted content into a CPU
    denial-of-service, while a false positive only disables one custom rule.
    """
    if len(pattern) > 4096:
        return False, "regex exceeds the maximum supported length"

    try:
        from re import _parser as regex_parser  # type: ignore[attr-defined]
    except ImportError:  # pragma: no cover - compatibility with older Python
        import sre_parse as regex_parser

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            parsed = regex_parser.parse(pattern, 0)
    except (re.error, TypeError, ValueError):
        # Syntax errors are reported by the normal compiler with a more useful
        # position; this helper only decides whether valid syntax is safe.
        return True, None

    repeat_names = {"MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"}
    max_repeat = getattr(regex_parser, "MAXREPEAT", 2**32 - 1)

    def has_branch(tokens: Any) -> bool:
        for operation, argument in tokens:
            name = getattr(operation, "name", str(operation))
            if name == "BRANCH":
                return True
            if name == "SUBPATTERN" and has_branch(argument[-1]):
                return True
            if name in repeat_names and has_branch(argument[-1]):
                return True
        return False

    def has_unsafe_repeat(tokens: Any, inside_repeat: bool = False) -> bool:
        for operation, argument in tokens:
            name = getattr(operation, "name", str(operation))
            if name in repeat_names:
                _, maximum, body = argument
                unbounded = maximum == max_repeat
                if (inside_repeat and unbounded) or (unbounded and has_branch(body)):
                    return True
                if has_unsafe_repeat(body, inside_repeat=inside_repeat or unbounded):
                    return True
            elif name == "SUBPATTERN":
                if has_unsafe_repeat(argument[-1], inside_repeat):
                    return True
            elif name == "BRANCH":
                if any(
                    has_unsafe_repeat(branch, inside_repeat) for branch in argument[1]
                ):
                    return True
        return False

    if has_unsafe_repeat(parsed):
        return False, "regex contains nested or ambiguous repetition"
    return True, None


def _compile_regex(raw: dict, *, enforce_regex_safety: bool = True) -> re.Pattern:
    """Compile a regex rule, validating RE2 compatibility."""
    pattern = raw.get("regex", "")
    if not pattern:
        raise ValueError(f"Rule {raw.get('id', '?')}: regex field is empty")

    if enforce_regex_safety:
        safe, safety_reason = validate_regex_safety(pattern)
        if not safe:
            raise ValueError(f"Unsafe regex: {safety_reason}")

    if raw.get("re2_compat", True):
        is_re2, reason = validate_re2_compatible(pattern)
        if not is_re2:
            logger.warning(
                f"Rule {raw.get('id', '?')}: RE2-incompatible regex rejected: {reason}. "
                f"Pattern: {pattern[:80]}..."
            )
            raise ValueError(f"RE2-incompatible regex: {reason}")
    else:
        logger.debug(
            f"Rule {raw.get('id', '?')}: RE2 compat check skipped (re2_compat=false)"
        )

    flags = 0
    raw_flags = raw.get("flags", "")
    if "i" in raw_flags or raw.get("case_insensitive", False):
        flags |= re.IGNORECASE
    if "m" in raw_flags or raw.get("multiline", False):
        flags |= re.MULTILINE
    if "s" in raw_flags or raw.get("dotall", False):
        flags |= re.DOTALL

    try:
        return re.compile(pattern, flags)
    except re.error as e:
        raise ValueError(f"Rule {raw.get('id', '?')}: invalid regex: {e}") from e


def _compile_literal(raw: dict) -> Tuple[str, str]:
    """Compile a literal match rule (character mapping)."""
    source = raw.get("source", "")
    target = raw.get("target", "")
    if not source:
        raise ValueError(f"Rule {raw.get('id', '?')}: literal rule missing 'source'")
    return (source, target)


def _compile_cidr(raw: dict) -> Any:
    """Compile a CIDR rule into an ipaddress network object."""
    cidr = raw.get("cidr", "")
    if not cidr:
        raise ValueError(f"Rule {raw.get('id', '?')}: cidr field is empty")
    try:
        return ipaddress.ip_network(cidr, strict=False)
    except ValueError as e:
        raise ValueError(f"Rule {raw.get('id', '?')}: invalid CIDR: {e}") from e


def _compile_range(raw: dict) -> Tuple[int, int]:
    """Compile a range rule into an integer tuple."""
    start = raw.get("start")
    end = raw.get("end")
    if start is None or end is None:
        raise ValueError(
            f"Rule {raw.get('id', '?')}: range rule missing 'start' or 'end'"
        )
    return (int(start), int(end))


def _compile_glob(raw: dict) -> str:
    """Compile a glob pattern (stored as raw string)."""
    pattern = raw.get("glob", "")
    if not pattern:
        raise ValueError(f"Rule {raw.get('id', '?')}: glob field is empty")
    return pattern


_COMPILERS: Dict[str, Callable[..., Any]] = {
    "regex": _compile_regex,
    "literal": _compile_literal,
    "cidr": _compile_cidr,
    "range": _compile_range,
    "glob": _compile_glob,
}

RESERVED_FIELDS = {
    "id",
    "match_type",
    "regex",
    "source",
    "target",
    "cidr",
    "start",
    "end",
    "glob",
    "flags",
    "case_insensitive",
    "multiline",
    "dotall",
}


def compile_rule(
    raw: dict, category: str, *, enforce_regex_safety: bool = True
) -> CompiledRule:
    """Compile a raw TOML rule dict into a CompiledRule.

    Args:
        raw: Dictionary from TOML [[rules]] entry
        category: Category name (e.g., "secret", "pii")

    Returns:
        CompiledRule with compiled matcher and metadata

    Raises:
        ValueError: If the rule is invalid or has unsupported match_type
    """
    rule_id = raw.get("id", "unknown")
    match_type = raw.get("match_type", "regex")

    if match_type not in VALID_MATCH_TYPES:
        raise ValueError(f"Rule {rule_id}: unsupported match_type '{match_type}'")

    compiler = _COMPILERS[match_type]
    if match_type == "regex":
        compiled = compiler(raw, enforce_regex_safety=enforce_regex_safety)
    else:
        compiled = compiler(raw)

    metadata = {k: v for k, v in raw.items() if k not in RESERVED_FIELDS}

    if "skip_file_types" in metadata and isinstance(metadata["skip_file_types"], list):
        metadata["skip_file_types"] = frozenset(metadata["skip_file_types"])

    return CompiledRule(
        id=rule_id,
        match_type=match_type,
        compiled=compiled,
        category=category,
        metadata=metadata,
    )


def load_toml_file(path: Path) -> List[dict]:
    """Parse a TOML file and return the list of raw rule dicts.

    The TOML file must contain a top-level ``[[rules]]`` array.

    Args:
        path: Path to the TOML file

    Returns:
        List of raw rule dictionaries

    Raises:
        FileNotFoundError: If the file does not exist
        ValueError: If the TOML is invalid or has no rules
    """
    if not path.exists():
        raise FileNotFoundError(f"Pattern file not found: {path}")

    with open(path, "rb") as f:
        data = tomllib.load(f)

    rules = data.get("rules", [])
    if not isinstance(rules, list):
        raise ValueError(f"Pattern file {path}: 'rules' must be an array")

    return rules


def load_and_compile(path: Path, category: str) -> List[CompiledRule]:
    """Load a TOML file and compile all rules.

    Invalid rules are skipped with a warning (fail-open).

    Args:
        path: Path to the TOML file
        category: Category to assign to all rules

    Returns:
        List of successfully compiled rules
    """
    raw_rules = load_toml_file(path)
    compiled = []
    bundled_data_dir = Path(__file__).parent / "data"
    enforce_regex_safety = path.resolve().parent != bundled_data_dir.resolve()
    for raw in raw_rules:
        try:
            rule = compile_rule(
                raw, category, enforce_regex_safety=enforce_regex_safety
            )
            compiled.append(rule)
        except ValueError as e:
            logger.warning(f"Skipping invalid rule in {path}: {e}")
    logger.debug(
        f"Loaded {len(compiled)}/{len(raw_rules)} rules from {path.name} ({category})"
    )
    return compiled
