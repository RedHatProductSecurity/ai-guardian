"""
TOML-based pattern loading for ai-guardian.

Provides PatternCache for pre-compiled pattern matching across all
security features: secrets, PII, prompt injection, unicode attacks,
config exfiltration, and SSRF protection.

Patterns are loaded from bundled TOML files and optionally from
pattern servers, then compiled once into Python objects (re.Pattern,
ipaddress networks, dict lookups) for fast in-memory matching.
"""

from pathlib import Path

from ai_guardian.patterns.cache import PatternCache
from ai_guardian.patterns.toml_parser import CompiledRule, load_toml_file, compile_rule

DATA_DIR = Path(__file__).parent / "data"

BUNDLED_FILES = {
    "secrets": DATA_DIR / "secrets.toml",
    "pii": DATA_DIR / "pii.toml",
    "prompt_injection": DATA_DIR / "prompt-injection.toml",
    "context_poisoning": DATA_DIR / "context-poisoning.toml",
    "unicode": DATA_DIR / "unicode.toml",
    "config_exfil": DATA_DIR / "config-exfil.toml",
    "ssrf": DATA_DIR / "ssrf.toml",
    "supply_chain": DATA_DIR / "supply-chain.toml",
    "stopwords": DATA_DIR / "stopwords.toml",
    "offensive_profanity": DATA_DIR / "offensive-profanity.toml",
    "offensive_slurs": DATA_DIR / "offensive-slurs.toml",
    "offensive_inclusive_language": DATA_DIR / "offensive-inclusive-language.toml",
}

import logging
from typing import Any, Callable, List, TypeVar

_logger = logging.getLogger(__name__)
T = TypeVar("T")


def load_bundled_rules(
    category: str,
    transform: Callable[[List[dict]], T],
    fallback: T,
    feature_name: str = "",
) -> T:
    """Load rules from a bundled TOML file with fallback on error.

    Args:
        category: Key in BUNDLED_FILES (e.g., "secrets", "pii")
        transform: Callable that converts raw rule dicts into the desired format
        fallback: Value to return if the TOML file is missing or unparseable
        feature_name: Label for log messages
    """
    try:
        toml_path = BUNDLED_FILES.get(category)
        if toml_path and toml_path.exists():
            raw_rules = load_toml_file(toml_path)
            result = transform(raw_rules)
            _logger.debug(
                f"{feature_name}: Loaded {len(result)} rules from {category}.toml"
            )
            return result
        else:
            _logger.error(
                f"Bundled {category}.toml not found — patterns directory may be missing from install"
            )
            return fallback
    except Exception as e:
        _logger.error(f"Failed to load {category}.toml: {e}")
        return fallback


__all__ = [
    "PatternCache",
    "CompiledRule",
    "load_toml_file",
    "compile_rule",
    "DATA_DIR",
    "BUNDLED_FILES",
    "load_bundled_rules",
]
