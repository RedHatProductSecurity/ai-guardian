"""
Pattern server response parsers.

Each pattern server can serve patterns in a different format. The parser
registry maps format names to parser classes that normalize server
responses into the ai-guardian internal rule dict format.

Supported formats:
- ai-guardian: Native TOML format (same as bundled pattern files)
- gitleaks: Gitleaks TOML format (Go RE2 regex, different field names)

Extensible: add new parsers by subclassing PatternServerParser and
registering in PARSER_REGISTRY.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PatternServerParser(ABC):
    """Base class for pattern server response parsers."""

    format_name: str = "unknown"

    @abstractmethod
    def parse(self, raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse server response into normalized rule dicts.

        Args:
            raw_data: Parsed TOML/JSON data from the pattern server

        Returns:
            List of rule dicts in ai-guardian internal format, ready
            for PatternCache.load_rules()
        """
        pass


class AIGuardianParser(PatternServerParser):
    """Parser for native ai-guardian TOML format.

    The server response uses the same format as bundled pattern files:
    [[rules]] entries with id, match_type, regex, etc.
    """

    format_name = "ai-guardian"

    def parse(self, raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        rules = raw_data.get("rules", [])
        if not isinstance(rules, list):
            logger.warning("ai-guardian parser: 'rules' is not a list")
            return []
        logger.debug(f"ai-guardian parser: parsed {len(rules)} rules")
        return rules


class GitleaksParser(PatternServerParser):
    """Parser for gitleaks TOML format.

    Converts gitleaks-style rules to ai-guardian internal format:
    - gitleaks 'regex' → ai-guardian 'regex'
    - gitleaks 'secretGroup' → ai-guardian metadata
    - gitleaks 'keywords' → ai-guardian 'keywords'
    - gitleaks 'description' → ai-guardian 'description'
    - Adds match_type="regex" and redaction_strategy defaults
    """

    format_name = "gitleaks"

    def parse(self, raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        rules = raw_data.get("rules", [])
        if not isinstance(rules, list):
            logger.warning("gitleaks parser: 'rules' is not a list")
            return []

        converted = []
        for rule in rules:
            try:
                ag_rule = {
                    "id": rule.get("id", rule.get("description", "unknown")),
                    "match_type": "regex",
                    "regex": rule.get("regex", ""),
                    "description": rule.get("description", ""),
                    "redaction_strategy": "preserve_prefix_suffix",
                    "keywords": rule.get("keywords", []),
                }
                if "secretGroup" in rule:
                    ag_rule["secretGroup"] = rule["secretGroup"]
                if "entropy" in rule:
                    ag_rule["entropy"] = rule["entropy"]
                if rule.get("regex"):
                    converted.append(ag_rule)
            except Exception as e:
                logger.warning(f"gitleaks parser: skipping rule: {e}")

        logger.debug(f"gitleaks parser: converted {len(converted)}/{len(rules)} rules")
        return converted


PARSER_REGISTRY: Dict[str, type] = {
    "ai-guardian": AIGuardianParser,
    "gitleaks": GitleaksParser,
}


def get_parser(format_name: str) -> Optional[PatternServerParser]:
    """Look up and instantiate a parser by format name.

    Args:
        format_name: Format identifier (e.g., "ai-guardian", "gitleaks")

    Returns:
        Instantiated parser, or None if format is unknown
    """
    parser_cls = PARSER_REGISTRY.get(format_name)
    if parser_cls is None:
        logger.warning(f"Unknown pattern server format: {format_name}")
        return None
    return parser_cls()


def list_formats() -> List[str]:
    """Return list of supported format names."""
    return list(PARSER_REGISTRY.keys())
