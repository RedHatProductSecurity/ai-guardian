"""
Scan finding analyzer for init-project --scan.

Clusters FileScanner findings by (rule_id, sub_type), identifies
high-frequency patterns as likely false positives, and generates
config recommendations for ai-guardian.json and .aiguardignore.toml.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    import threading

from ai_guardian.constants import RULE_ID_LABELS, RULE_ID_TO_SCANNER


@dataclass
class ScanPipelineResult:
    """Result of run_scan_pipeline."""

    language_names: List[str]
    findings_count: int
    analysis: ScanAnalysisResult
    merged_config: Dict[str, Any]
    project_dir: str


_SUPPRESSION_KEYS = frozenset(
    {
        "allowlist_patterns",
        "allowlist_paths",
        "allowlist",
        "ignore_files",
        "ignore_tools",
        "ignore_paths",
    }
)


def _build_discovery_config(project_dir: str) -> Dict[str, Any]:
    """Build a config that enables all scanners and strips suppressions.

    Used by run_scan_pipeline so the analyzer sees every possible violation
    regardless of existing user config.  Returns a deep copy so the
    original loaded config is never mutated.
    """
    from ai_guardian.config.loaders import _SCANNER_MERGE_SECTIONS, load_scanner_config

    config = copy.deepcopy(load_scanner_config(project_root=project_dir))
    for section_key in _SCANNER_MERGE_SECTIONS:
        section = config.get(section_key)
        if section is None:
            config[section_key] = {"enabled": True}
            continue
        section["enabled"] = True
        for key in _SUPPRESSION_KEYS:
            section.pop(key, None)
    return config


def run_scan_pipeline(
    project_dir: str,
    threshold: int,
    cancel_event: "threading.Event",
    on_phase: Optional[Callable[[str], None]] = None,
    on_file_progress: Optional[Callable[[str, int, int], None]] = None,
    skip_hidden: bool = True,
) -> Optional[ScanPipelineResult]:
    """Run the full scan-and-analyze pipeline.

    Returns *None* when *cancel_event* is set, otherwise a
    :class:`ScanPipelineResult`.
    """
    from ai_guardian.project_init import ProjectInitializer
    from ai_guardian.scanners.file_scanner import FileScanner

    _phase = on_phase or (lambda _msg: None)

    initializer = ProjectInitializer(Path(project_dir))

    _phase("Detecting languages...")
    languages = initializer.detect_languages()
    if cancel_event.is_set():
        return None

    _phase("Generating allowlist...")
    allowlist_entries, ignore_files = initializer.generate_allowlist(languages)
    if cancel_event.is_set():
        return None

    language_config = initializer.generate_config(allowlist_entries, ignore_files)

    _phase("Scanning files...")
    scan_config = _build_discovery_config(str(initializer.project_dir))
    scanner = FileScanner(config=scan_config, verbose=False)
    findings = scanner.scan_directory(
        str(initializer.project_dir),
        progress_callback=on_file_progress,
        cancel_event=cancel_event,
        skip_hidden=skip_hidden,
    )
    if cancel_event.is_set():
        return None

    _phase(f"Analyzing {len(findings)} findings...")
    analysis = initializer.analyze_scan(findings, threshold=threshold)
    merged_config = initializer.merge_configs(
        language_config, analysis.recommended_config
    )

    return ScanPipelineResult(
        language_names=[lang.definition.name for lang in languages],
        findings_count=len(findings),
        analysis=analysis,
        merged_config=merged_config,
        project_dir=str(project_dir),
    )


def _deep_merge_configs(existing: Dict, new_config: Dict) -> Dict:
    """Deep-merge *new_config* into *existing*, deduplicating list values."""
    merged = dict(existing)
    for section, values in new_config.items():
        if section not in merged:
            merged[section] = dict(values)
        else:
            target = dict(merged[section])
            merged[section] = target
            for key, val in values.items():
                if key in target and isinstance(val, list):
                    combined = list(target[key])
                    for item in val:
                        if item not in combined:
                            combined.append(item)
                    target[key] = combined
                else:
                    target[key] = val
    return merged


def merge_and_write_config(config_path: Path, new_config: Dict) -> None:
    """Deep-merge *new_config* into an existing JSON config file.

    Uses atomic config update with file locking when available.
    List values are merged with deduplication; scalar values are overwritten.
    """
    try:
        from ai_guardian.config.writer import _atomic_config_update

        config_path.parent.mkdir(parents=True, exist_ok=True)

        def updater(config):
            merged = _deep_merge_configs(config, new_config)
            config.clear()
            config.update(merged)
            return False, f"Merged scan config into {config_path}"

        _atomic_config_update(config_path, updater)
    except ImportError:
        existing = {}
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                existing = json.load(f)

        merged = _deep_merge_configs(existing, new_config)

        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            shutil.copy2(config_path, config_path.with_suffix(".json.backup"))
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
            f.write("\n")


_BANDIT_RULE_ID = re.compile(r"^B\d+")
_OFFENSIVE_LANGUAGE_PREFIXES = re.compile(r"^(profanity|slur|inclusive)-")

_RULE_ID_PATTERNS: List[Tuple["re.Pattern[str]", str]] = [
    (_BANDIT_RULE_ID, "code_scanning"),
    (_OFFENSIVE_LANGUAGE_PREFIXES, "offensive_language"),
]

_SCANNER_TO_CONFIG_SECTION = {
    "offensive_language": "scan_offensive",
}

NEVER_SUPPRESS = frozenset({"SSRF-001", "UNICODE-001", "canary_detected"})

MAX_SAMPLE_FILES = 5

# --- Fingerprinting ---

_FINGERPRINT_DETAIL_KEY = {
    "SECRET-001": "secret_type",
    "PII-001": "pii_type",
    "SUPPLY-CHAIN-001": "category",
    "EXFIL-DETECTION-001": "category",
    "SSRF-001": "reason",
}


@dataclass
class FindingCluster:
    """A group of findings sharing the same fingerprint."""

    rule_id: str
    sub_type: str
    file_count: int = 0
    total_count: int = 0
    sample_files: List[str] = field(default_factory=list)


@dataclass
class DirectoryAnalysis:
    """Analysis of a first-level directory's findings."""

    directory: str
    total_findings: int = 0
    high_frequency_findings: int = 0

    @property
    def all_high_frequency(self) -> bool:
        return (
            self.total_findings > 0
            and self.total_findings == self.high_frequency_findings
        )


@dataclass
class ScanAnalysisResult:
    """Complete analysis output."""

    total_findings: int = 0
    total_files_scanned: int = 0
    clusters: List[FindingCluster] = field(default_factory=list)
    high_frequency_clusters: List[FindingCluster] = field(default_factory=list)
    directories_to_ignore: List[DirectoryAnalysis] = field(default_factory=list)
    recommended_config: Dict[str, Any] = field(default_factory=dict)
    recommended_ignore_paths: Dict[str, List[str]] = field(default_factory=dict)
    suppressed_count: int = 0


def fingerprint_finding(finding: Dict[str, Any]) -> Tuple[str, str]:
    """Extract (rule_id, sub_type) from a finding dict."""
    rule_id = finding.get("rule_id", "")
    details = finding.get("details", {})

    detail_key = _FINGERPRINT_DETAIL_KEY.get(rule_id)
    if detail_key:
        return (rule_id, details.get(detail_key, "unknown"))

    if rule_id == "PROMPT-INJECTION-001":
        matched = details.get("matched_text") or details.get("matched_pattern")
        if matched:
            return (rule_id, matched)
        return (rule_id, _normalize_pi_description(details.get("description", "")))
    if rule_id == "CONFIG-001":
        return (rule_id, details.get("pattern", details.get("category", "unknown")))
    if _OFFENSIVE_LANGUAGE_PREFIXES.match(rule_id):
        return (rule_id, details.get("category", "unknown"))

    return (rule_id, "")


def _normalize_pi_description(desc: str) -> str:
    """Normalize a PI description to a canonical pattern key.

    Strips varying parts (file names, line numbers) and keeps the
    detection category.
    """
    first_line = desc.split("\n")[0].strip() if desc else ""
    first_line = re.sub(r"\s+at line \d+", "", first_line)
    first_line = re.sub(r"\s+in .+$", "", first_line)
    return first_line


def cluster_findings(findings: List[Dict[str, Any]]) -> List[FindingCluster]:
    """Group findings by fingerprint."""
    groups: Dict[Tuple[str, str], Dict] = defaultdict(
        lambda: {"files": set(), "count": 0, "sample_files": []}
    )

    for finding in findings:
        fp = fingerprint_finding(finding)
        g = groups[fp]
        g["count"] += 1
        file_path = finding.get("file_path") or ""
        if file_path and file_path not in g["files"]:
            g["files"].add(file_path)
            if len(g["sample_files"]) < MAX_SAMPLE_FILES:
                g["sample_files"].append(file_path)

    clusters = []
    for (rule_id, sub_type), g in sorted(groups.items()):
        clusters.append(
            FindingCluster(
                rule_id=rule_id,
                sub_type=sub_type,
                file_count=len(g["files"]),
                total_count=g["count"],
                sample_files=g["sample_files"],
            )
        )

    return clusters


def analyze_directories(
    findings: List[Dict[str, Any]],
    high_freq_fingerprints: Set[Tuple[str, str]],
) -> List[DirectoryAnalysis]:
    """Analyze first-level directories for ignore recommendations."""
    dir_stats: Dict[str, Dict] = defaultdict(lambda: {"total": 0, "high_freq": 0})

    for finding in findings:
        file_path = finding.get("file_path") or ""
        if not file_path:
            continue

        parts = PurePosixPath(file_path).parts
        if not parts:
            continue
        top_dir = parts[0] if len(parts) > 1 else ""
        if not top_dir:
            continue

        fp = fingerprint_finding(finding)
        stats = dir_stats[top_dir]
        stats["total"] += 1
        if fp in high_freq_fingerprints:
            stats["high_freq"] += 1

    analyses = []
    for directory, stats in sorted(dir_stats.items()):
        analyses.append(
            DirectoryAnalysis(
                directory=directory,
                total_findings=stats["total"],
                high_frequency_findings=stats["high_freq"],
            )
        )

    return analyses


# --- Scanner routing ---


def _scanner_for_rule_id(rule_id: str) -> Optional[str]:
    """Map a rule_id to its scanner type. Returns None for never-suppress rules."""
    if rule_id in NEVER_SUPPRESS:
        return None
    scanner = RULE_ID_TO_SCANNER.get(rule_id)
    if scanner:
        return scanner
    for pattern, scanner_name in _RULE_ID_PATTERNS:
        if pattern.match(rule_id):
            return scanner_name
    return None


def _can_generate_config(rule_id: str) -> bool:
    """Check if a rule_id's scanner supports config generation."""
    if rule_id in NEVER_SUPPRESS:
        return False
    scanner = _scanner_for_rule_id(rule_id)
    return scanner is not None and scanner in _SCANNER_CONFIG_SPEC


# --- Config builders ---


def _build_escaped_patterns(
    section: Dict[str, Any],
    key: str,
    clusters: List[FindingCluster],
) -> None:
    """Build allowlist_patterns from escaped sub_type values."""
    entries = section.setdefault(key, [])
    seen = set(entries)
    for c in clusters:
        pattern = re.escape(c.sub_type)
        if pattern not in seen:
            seen.add(pattern)
            entries.append(pattern)


def _build_dir_globs(
    section: Dict[str, Any],
    key: str,
    clusters: List[FindingCluster],
) -> None:
    """Build path globs from sample file directories."""
    entries = section.setdefault(key, [])
    seen = set(entries)
    for c in clusters:
        for fp in c.sample_files:
            dir_part = str(PurePosixPath(fp).parent)
            if dir_part == ".":
                continue
            pattern = f"{dir_part}/**"
            if pattern not in seen:
                seen.add(pattern)
                entries.append(pattern)


def _build_rule_allowlist(
    section: Dict[str, Any],
    key: str,
    clusters: List[FindingCluster],
) -> None:
    """Build allowlist from rule IDs (Bandit format)."""
    rules = section.setdefault(key, [])
    seen_ids: Set[str] = {r["test_id"] for r in rules if "test_id" in r}
    for c in clusters:
        if c.rule_id not in seen_ids:
            seen_ids.add(c.rule_id)
            rules.append({"test_id": c.rule_id})


def _build_ssrf_config(
    section: Dict[str, Any],
    key: str,
    clusters: List[FindingCluster],
) -> None:
    """Enable allow_localhost when SSRF clusters contain localhost findings."""
    _LOCALHOST_MARKERS = {"localhost", "127.0.0.1", "::1"}
    for c in clusters:
        reason = c.sub_type.lower()
        if any(m in reason for m in _LOCALHOST_MARKERS):
            section["allow_localhost"] = True
            return


_BuilderFn = Callable[[Dict[str, Any], str, List[FindingCluster]], None]

_SCANNER_CONFIG_SPEC: Dict[str, Tuple[str, _BuilderFn]] = {
    "secret_scanning": ("allowlist_patterns", _build_escaped_patterns),
    "prompt_injection": ("allowlist_patterns", _build_escaped_patterns),
    "exfil_detection": ("allowlist_patterns", _build_escaped_patterns),
    "supply_chain": ("allowlist_paths", _build_dir_globs),
    "config_file_scanning": ("ignore_files", _build_dir_globs),
    "code_scanning": ("allowlist", _build_rule_allowlist),
    "ssrf_protection": ("allow_localhost", _build_ssrf_config),
}


# --- Recommendation engine ---


def build_recommendations(
    findings: List[Dict[str, Any]],
    threshold: int = 10,
) -> ScanAnalysisResult:
    """Analyze findings and build suppression recommendations."""
    clusters = cluster_findings(findings)

    high_freq = [
        c
        for c in clusters
        if c.file_count >= threshold and _can_generate_config(c.rule_id)
    ]

    high_freq_fps: Set[Tuple[str, str]] = {(c.rule_id, c.sub_type) for c in high_freq}

    dir_analyses = analyze_directories(findings, high_freq_fps)
    dirs_to_ignore = [d for d in dir_analyses if d.all_high_frequency]

    dir_scanner_map: Dict[str, Set[str]] = defaultdict(set)
    for finding in findings:
        fp = finding.get("file_path") or ""
        parts = PurePosixPath(fp).parts
        if parts and len(parts) > 1:
            scanner = _scanner_for_rule_id(finding.get("rule_id", ""))
            if scanner:
                dir_scanner_map[parts[0]].add(scanner)

    config = _build_config(high_freq)

    ssrf_clusters = [c for c in clusters if c.rule_id == "SSRF-001"]
    if ssrf_clusters:
        ssrf_section = config.setdefault("ssrf_protection", {})
        _build_ssrf_config(ssrf_section, "allow_localhost", ssrf_clusters)

    ignore_paths = _build_ignore_paths(dirs_to_ignore, dir_scanner_map)

    suppressed = sum(c.total_count for c in high_freq)

    all_files = {f.get("file_path") for f in findings if f.get("file_path")}

    return ScanAnalysisResult(
        total_findings=len(findings),
        total_files_scanned=len(all_files),
        clusters=clusters,
        high_frequency_clusters=high_freq,
        directories_to_ignore=dirs_to_ignore,
        recommended_config=config,
        recommended_ignore_paths=ignore_paths,
        suppressed_count=suppressed,
    )


def _build_config(high_freq_clusters: List[FindingCluster]) -> Dict[str, Any]:
    """Build ai-guardian.json config sections from high-frequency clusters."""
    config: Dict[str, Any] = {}

    by_scanner: Dict[str, List[FindingCluster]] = defaultdict(list)
    for cluster in high_freq_clusters:
        scanner = _scanner_for_rule_id(cluster.rule_id)
        if scanner:
            by_scanner[scanner].append(cluster)

    for scanner, clusters_list in sorted(by_scanner.items()):
        spec = _SCANNER_CONFIG_SPEC.get(scanner)
        if not spec:
            continue
        config_key = _SCANNER_TO_CONFIG_SECTION.get(scanner, scanner)
        section = config.setdefault(config_key, {})
        key, builder_fn = spec
        builder_fn(section, key, clusters_list)

    return config


def _build_ignore_paths(
    dirs_to_ignore: List[DirectoryAnalysis],
    dir_scanner_map: Dict[str, Set[str]],
) -> Dict[str, List[str]]:
    """Build .aiguardignore.toml paths from directory analysis."""
    ignore_paths: Dict[str, List[str]] = defaultdict(list)

    for dir_analysis in dirs_to_ignore:
        dir_name = dir_analysis.directory
        pattern = f"{dir_name}/**"

        for scanner in sorted(dir_scanner_map.get(dir_name, set())):
            if pattern not in ignore_paths[scanner]:
                ignore_paths[scanner].append(pattern)

    return dict(ignore_paths)
