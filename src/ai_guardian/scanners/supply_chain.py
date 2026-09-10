"""
Supply Chain Scanner Module

Detects malicious patterns in agent configuration files — hooks, MCP server
configs, and plugin files. Catches download-and-execute chains, obfuscation,
env var hijacking, network exfiltration, reverse shells, and plugin-specific
threats.

Design:
- Path-aware: only scans files matching known agent config patterns
- Self-allowlisted: never flags ai-guardian's own plugin files
- TOML-backed patterns with hardcoded fallbacks
- Returns 3-tuple (should_block, error_msg, details) matching config_scanner API
"""

import fnmatch
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from ai_guardian.config.utils import is_feature_enabled
from ai_guardian.ide_paths import (
    get_explicit_ide_config_path,
    resolve_ide_config_path,
    resolve_ide_mcp_path,
    resolve_opencode_config,
)

logger = logging.getLogger(__name__)

AGENT_CONFIG_PATHS_HOME = [
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".cursor/hooks.json",
    ".github/hooks/hooks.json",
    ".codex/hooks.json",
    ".codeium/windsurf/hooks.json",
    ".gemini/settings.json",
    ".augment/settings.json",
]

AGENT_CONFIG_PATHS_PROJECT = [
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/commands/*.md",
    ".cursor/hooks.json",
    ".github/hooks/hooks.json",
]

PLUGIN_PATHS_HOME = [
    ".config/opencode/plugins/*.ts",
    ".aider-desk/extensions/*/index.ts",
]

SELF_ALLOWLIST = [
    "ai-guardian.ts",
    "ai-guardian/index.ts",
]


def get_agent_config_paths(include_plugins: bool = True) -> List[str]:
    """Return default and relocated agent config/plugin path patterns.

    The static patterns remain the compatibility baseline. Dynamic paths add
    the user-level locations selected by documented IDE environment variables
    so supply-chain checks follow setup and MCP verification.
    """
    paths: List[str] = []

    def add(path: Optional[str]) -> None:
        if not path:
            return
        expanded = os.path.expanduser(str(path)).replace("\\", "/")
        if expanded not in paths:
            paths.append(expanded)

    home = os.path.expanduser("~").replace("\\", "/")
    patterns = AGENT_CONFIG_PATHS_HOME + (PLUGIN_PATHS_HOME if include_plugins else [])
    for pattern in patterns:
        add(f"{home}/{pattern}")

    hook_specs = (
        ("claude", "~/.claude/settings.json", "settings.json", ()),
        ("claude", "~/.claude/settings.local.json", "settings.local.json", ()),
        ("cursor", "~/.cursor/hooks.json", "hooks.json", ()),
        ("copilot", "~/.github/hooks/hooks.json", "hooks.json", ("hooks",)),
        ("codex", "~/.codex/hooks.json", "hooks.json", ()),
        ("gemini", "~/.gemini/settings.json", "settings.json", ()),
    )
    for ide_type, default_path, filename, env_subdir in hook_specs:
        add(
            resolve_ide_config_path(
                ide_type,
                default_path,
                filename=filename,
                env_subdir=env_subdir,
            )
        )

    if include_plugins:
        plugin_specs = (
            ("opencode", "~/.config/opencode/plugins", "*.ts", ("plugins",)),
            ("aiderdesk", "~/.aider-desk/extensions", "*/index.ts", ("extensions",)),
            ("openclaw", "~/.openclaw/plugins", "*/index.ts", ("plugins",)),
        )
        for ide_type, default_path, filename, env_subdir in plugin_specs:
            add(
                resolve_ide_config_path(
                    ide_type,
                    default_path,
                    filename=filename,
                    env_subdir=env_subdir,
                )
            )

    mcp_specs = (
        ("claude", "~/.claude.json"),
        ("cursor", "~/.cursor/mcp.json"),
        ("codex", "~/.codex/config.toml"),
        ("windsurf", "~/.windsurf/mcp.json"),
        ("gemini", "~/.gemini/settings.json"),
        ("cline", "~/.cline/mcp_settings.json"),
        ("zoocode", "~/.cline/mcp_settings.json"),
        ("augment", "~/.augment/settings.json"),
        ("kiro", "~/.kiro/settings.json"),
        ("junie", "~/.junie/mcp.json"),
        ("aiderdesk", "~/.aider-desk/settings.json"),
        ("openclaw", "~/.openclaw/settings.json"),
    )
    for ide_type, default_path in mcp_specs:
        add(str(resolve_ide_mcp_path(ide_type, default_path) or ""))
    add(str(resolve_opencode_config()))

    add(str(get_explicit_ide_config_path("openclaw") or ""))
    add(str(get_explicit_ide_config_path("crush") or ""))
    return paths


_PATTERN_CATEGORIES = {
    "download_and_execute": [
        (r"curl\s+.*\|\s*(?:ba)?sh", "curl piped to shell"),
        (r"wget\s+.*\|\s*(?:ba)?sh", "wget piped to shell"),
        (r"curl\s+.*\|\s*python", "curl piped to python"),
        (r"curl\s+.*\|\s*node\s*-", "curl piped to node"),
        (r"curl\s+.*\|\s*perl", "curl piped to perl"),
        (r"fetch\s+.*\|\s*(?:ba)?sh", "fetch piped to shell"),
    ],
    "obfuscation": [
        (r"\beval\s*\(", "eval() call"),
        (r'\beval\s+["\']', "eval with string"),
        (r"base64\s+(?:-d|--decode)", "base64 decode"),
        (r"\$\(.*base64", "base64 in subshell"),
        (r"echo\s+.*\|\s*base64.*\|\s*(?:ba)?sh", "echo base64 piped to shell"),
        (r"printf\s+.*\\x[0-9a-f]", "printf hex escapes"),
        (r'python\s+-c\s+[\'"]import\s+base64', "python base64 one-liner"),
    ],
    "env_hijacking": [
        (r"\bLD_PRELOAD=", "LD_PRELOAD hijack"),
        (r"\bDYLD_INSERT_LIBRARIES=", "DYLD_INSERT_LIBRARIES hijack"),
        (r"\bNODE_OPTIONS=.*--require", "NODE_OPTIONS --require hijack"),
        (r"\bPYTHONSTARTUP=", "PYTHONSTARTUP hijack"),
        (r"\bPYTHONPATH=.*:/tmp", "PYTHONPATH /tmp hijack"),
        (r"\bPATH=.*:/tmp", "PATH /tmp hijack"),
        (r"\bhttp_proxy=", "http_proxy hijack"),
        (r"\bHTTPS_PROXY=", "HTTPS_PROXY hijack"),
    ],
    "network_exfil": [
        (r"curl\s+.*--data.*\$", "curl POST with variable data"),
        (r"curl\s+.*-d\s+.*\$", "curl -d with variable data"),
        (r"curl\s+.*POST", "curl POST request"),
        (r"wget\s+--post", "wget POST request"),
        (r"nc\s+(?:-e|--exec)", "netcat exec"),
        (r"ncat\s+(?:-e|--exec)", "ncat exec"),
        (r"socat\s+EXEC", "socat EXEC"),
    ],
    "mcp_suspicious": [
        (r"npx\s+.*https?://", "npx with URL"),
        (r"npx\s+-y\s+@[^/]+/", "npx -y scoped package"),
        (r'node\s+-e\s+[\'"]', "node -e inline code"),
        (r'python\s+-c\s+[\'"]', "python -c inline code"),
        (r"uvx\s+.*https?://", "uvx with URL"),
    ],
    "config_key_hijacking": [
        (r'"apiKeyHelper"\s*:', "apiKeyHelper key"),
        (r'"awsAuthRefresh"\s*:', "awsAuthRefresh key"),
        (r'"preCommand"\s*:\s*".*curl', "preCommand with curl"),
        (r'"command"\s*:\s*".*eval', "command with eval"),
        (r'"command"\s*:\s*".*base64', "command with base64"),
    ],
    "reverse_shell": [
        (r"/dev/tcp/", "/dev/tcp reverse shell"),
        (r"bash\s+-i\s+>&", "bash interactive reverse shell"),
        (r"mkfifo\s+/tmp", "mkfifo reverse shell pipe"),
        (r"\btelnet\s+\d+\.\d+", "telnet to IP"),
    ],
    "plugin_dangerous": [
        (r'require\s*\(\s*[\'"]child_process[\'"]\)', "require child_process"),
        (r'import.*from\s+[\'"]child_process[\'"]', "import child_process"),
        (r'require\s*\(\s*[\'"]net[\'"]\)', "require net"),
        (r'require\s*\(\s*[\'"]http[\'"]', "require http"),
        (r"\.exec\s*\(", ".exec() call"),
        (r"\.execSync\s*\(", ".execSync() call"),
        (r"process\.env\[", "process.env[] access"),
    ],
}

_compiled_patterns: Optional[Dict[str, List[Tuple[re.Pattern, str]]]] = None


def _compile_patterns() -> Dict[str, List[Tuple[re.Pattern, str]]]:
    global _compiled_patterns
    if _compiled_patterns is not None:
        return _compiled_patterns

    try:
        from ai_guardian.patterns import load_bundled_rules

        def _transform(raw_rules):
            by_group: Dict[str, List[Tuple[re.Pattern, str]]] = {}
            for rule in raw_rules:
                group = rule.get("group", "unknown")
                regex = rule.get("regex", "")
                desc = rule.get("description", "")
                if regex:
                    try:
                        compiled = re.compile(regex, re.IGNORECASE)
                        by_group.setdefault(group, []).append((compiled, desc))
                    except re.error:
                        logger.warning("Invalid supply chain pattern: %s", regex)
            return by_group

        result = load_bundled_rules(
            "supply_chain", _transform, {}, "Supply chain scanner"
        )
        if result:
            _compiled_patterns = result
            return _compiled_patterns
    except Exception as e:
        logger.debug("TOML load failed, using hardcoded patterns: %s", e)

    _compiled_patterns = {}
    for category, patterns in _PATTERN_CATEGORIES.items():
        compiled = []
        for regex, desc in patterns:
            try:
                compiled.append((re.compile(regex, re.IGNORECASE), desc))
            except re.error:
                logger.warning("Invalid hardcoded supply chain pattern: %s", regex)
        _compiled_patterns[category] = compiled
    return _compiled_patterns


def _is_plugin_file(file_path: str) -> bool:
    lower = file_path.lower()
    return lower.endswith((".ts", ".js"))


def _is_self_allowlisted(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/")
    for pattern in SELF_ALLOWLIST:
        if normalized.endswith(pattern):
            return True
    return False


def _matches_path_pattern(file_path: str, pattern: str) -> bool:
    normalized = file_path.replace("\\", "/")
    if "*" in pattern:
        return fnmatch.fnmatch(normalized, f"*/{pattern}") or fnmatch.fnmatch(
            normalized, pattern
        )
    return normalized.endswith(f"/{pattern}") or normalized == pattern


class SupplyChainScanner:
    """Detects supply chain threats in agent configuration files."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.enabled = config.get("enabled", True)
        if isinstance(self.enabled, dict):
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            self.enabled = is_feature_enabled(self.enabled, now, default=True)

        self.action = config.get("action", "block")
        self.scan_hooks = config.get("scan_hooks", True)
        self.scan_mcp_configs = config.get("scan_mcp_configs", True)
        self.scan_plugins = config.get("scan_plugins", True)

        raw_allowlist = config.get("allowlist_paths", [])
        self.allowlist_paths: List[str] = []
        for path in raw_allowlist:
            if isinstance(path, str) and path:
                expanded = os.path.expanduser(path)
                self.allowlist_paths.append(expanded.replace("\\", "/"))

        self.last_matched_pattern: Optional[str] = None
        self.last_matched_text: Optional[str] = None
        self.last_category: Optional[str] = None
        self.last_line_number: Optional[int] = None
        self.last_start_column: Optional[int] = None
        self.last_end_column: Optional[int] = None
        self.findings: List[Dict[str, Any]] = []

    def is_agent_config(self, file_path: str) -> bool:
        if not file_path:
            return False

        for pattern in get_agent_config_paths(include_plugins=self.scan_plugins):
            if _matches_path_pattern(file_path, pattern):
                return True

        for pattern in AGENT_CONFIG_PATHS_PROJECT:
            if _matches_path_pattern(file_path, pattern):
                return True

        return False

    def _is_allowlisted(self, file_path: str) -> bool:
        normalized = file_path.replace("\\", "/")
        for allowed in self.allowlist_paths:
            if normalized == allowed or normalized.endswith(f"/{allowed}"):
                return True
            if "*" in allowed and fnmatch.fnmatch(normalized, allowed):
                return True
        return False

    def scan_content(
        self, content: str, label: str = "user_prompt"
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Scan content for supply chain threats without path checks.

        Use for UserPromptSubmit where content is pasted without a file context.
        Scans all non-plugin categories (plugin patterns need a .ts/.js file).
        """
        self.last_matched_pattern = None
        self.last_matched_text = None
        self.last_category = None
        self.last_line_number = None
        self.last_start_column = None
        self.last_end_column = None
        self.findings = []

        if not self.enabled or not content or not content.strip():
            return False, None, None

        patterns = _compile_patterns()
        categories = [
            "download_and_execute",
            "obfuscation",
            "env_hijacking",
            "network_exfil",
            "mcp_suspicious",
            "config_key_hijacking",
            "reverse_shell",
        ]
        return self._match_patterns(content, label, patterns, categories)

    def scan(
        self, file_path: str, content: str
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Scan file content for supply chain threats (path-aware).

        Returns:
            (should_block, error_message, details)
        """
        self.last_matched_pattern = None
        self.last_matched_text = None
        self.last_category = None
        self.last_line_number = None
        self.last_start_column = None
        self.last_end_column = None
        self.findings = []

        if not self.enabled:
            return False, None, None

        if not content or not content.strip():
            return False, None, None

        if not self.is_agent_config(file_path):
            return False, None, None

        if _is_self_allowlisted(file_path):
            return False, None, None

        if self._is_allowlisted(file_path):
            return False, None, None

        patterns = _compile_patterns()
        is_plugin = _is_plugin_file(file_path)

        categories_to_scan = []
        if self.scan_hooks:
            categories_to_scan.extend(
                [
                    "download_and_execute",
                    "obfuscation",
                    "env_hijacking",
                    "network_exfil",
                    "config_key_hijacking",
                    "reverse_shell",
                ]
            )
        if self.scan_mcp_configs:
            categories_to_scan.append("mcp_suspicious")
        if self.scan_plugins and is_plugin:
            categories_to_scan.append("plugin_dangerous")

        return self._match_patterns(content, file_path, patterns, categories_to_scan)

    def _match_patterns(
        self,
        content: str,
        label: str,
        patterns: Dict[str, List[Tuple[re.Pattern, str]]],
        categories: List[str],
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        lines = content.split("\n")

        for category in categories:
            category_patterns = patterns.get(category, [])
            for compiled_re, description in category_patterns:
                match = compiled_re.search(content)
                if match:
                    line_number = content[: match.start()].count("\n") + 1
                    matched_text = match.group(0)
                    snippet = (
                        lines[line_number - 1].strip()
                        if line_number <= len(lines)
                        else ""
                    )

                    line_start = content.rfind("\n", 0, match.start()) + 1
                    start_column = match.start() - line_start
                    end_column = match.end() - line_start

                    error_msg = (
                        f"Supply chain threat blocked: {description} "
                        f"in {os.path.basename(label)} (line {line_number})"
                    )
                    self.findings.append(
                        {
                            "category": category,
                            "pattern": description,
                            "matched_text": matched_text,
                            "matched_pattern": compiled_re.pattern,
                            "line_number": line_number,
                            "start_column": start_column,
                            "end_column": end_column,
                            "snippet": snippet,
                            "file_path": label,
                            "error_message": error_msg,
                        }
                    )

        if not self.findings:
            return False, None, None

        first = self.findings[0]
        self.last_matched_pattern = first["pattern"]
        self.last_matched_text = first["matched_text"]
        self.last_category = first["category"]
        self.last_line_number = first["line_number"]
        self.last_start_column = first["start_column"]
        self.last_end_column = first["end_column"]

        details = {
            k: v
            for k, v in first.items()
            if k not in ("error_message", "matched_pattern")
        }
        details["total_findings"] = len(self.findings)

        if self.action == "block":
            return True, first["error_message"], details
        elif self.action == "log-only":
            return False, None, details
        else:
            warn_msg = (
                f"Supply chain threat detected in {os.path.basename(label)} "
                f"(warn mode) - execution allowed"
            )
            return False, warn_msg, details


def check_supply_chain_threats(
    file_path: str,
    content: str,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Convenience function matching check_config_file_threats API."""
    scanner = SupplyChainScanner(config)
    return scanner.scan(file_path, content)
