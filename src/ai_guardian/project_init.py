"""
Project initialization with language auto-discovery.

Detects programming languages in a project and generates a project-level
ai-guardian config with prompt injection allowlist patterns. Only generates
entries for identifiers that actually trigger the current detection patterns.

Usage:
    ai-guardian init-project              # Human-readable output
    ai-guardian init-project --dry-run    # Show without writing
    ai-guardian init-project --json       # Machine-readable JSON
    ai-guardian init-project --force      # Overwrite existing config
"""

import json
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ai_guardian.patterns.language import (
    LANGUAGE_REGISTRY,
    SKIP_DIRS,
    LanguageDefinition,
)

logger = logging.getLogger(__name__)

MAX_SCAN_FILES = 10_000
MAX_SCAN_DEPTH = 20

HTML_EXTENSIONS = frozenset({".html", ".htm", ".xhtml"})
HTML_IGNORE_GLOBS = ["**/*.html", "**/*.htm", "**/*.xhtml"]


@dataclass
class DetectedLanguage:
    """A language detected in the project."""

    definition: LanguageDefinition
    matched_files: int = 0
    matched_configs: List[str] = field(default_factory=list)


@dataclass
class AllowlistEntry:
    """An allowlist pattern generated for a language identifier."""

    pattern: str
    language: str
    identifier: str


@dataclass
class InitResult:
    """Result of the init-project command."""

    project_dir: Path
    detected_languages: List[DetectedLanguage] = field(default_factory=list)
    allowlist_entries: List[AllowlistEntry] = field(default_factory=list)
    ignore_files_entries: List[str] = field(default_factory=list)
    config_path: Optional[Path] = None
    config_created: bool = False
    config_existed: bool = False
    dry_run: bool = False
    scan_analysis: Optional[Any] = None
    merged_config: Optional[Dict] = None
    aiguardignore_path: Optional[Path] = None
    aiguardignore_created: bool = False
    exclude_patterns: List[str] = field(default_factory=list)


class ProjectInitializer:
    """Detects languages and generates project-level ai-guardian config."""

    def __init__(self, project_dir: Optional[Path] = None):
        self.project_dir = Path(project_dir) if project_dir else Path.cwd()
        self._last_suppressor = None

    def detect_languages(self) -> List[DetectedLanguage]:
        ext_to_langs: Dict[str, List[LanguageDefinition]] = {}
        for lang in LANGUAGE_REGISTRY:
            for ext in lang.file_extensions:
                ext_to_langs.setdefault(ext, []).append(lang)

        found: Dict[str, DetectedLanguage] = {}
        files_scanned = 0

        for lang in LANGUAGE_REGISTRY:
            for cfg_file in lang.config_files:
                cfg_path = self.project_dir / cfg_file
                if cfg_path.is_file():
                    if lang.name not in found:
                        found[lang.name] = DetectedLanguage(definition=lang)
                    found[lang.name].matched_configs.append(cfg_file)

        for dirpath, dirnames, filenames in os.walk(self.project_dir):
            depth = Path(dirpath).relative_to(self.project_dir).parts
            if len(depth) > MAX_SCAN_DEPTH:
                dirnames.clear()
                continue

            dirnames[:] = [
                d
                for d in dirnames
                if d not in SKIP_DIRS and not d.endswith(".egg-info")
            ]

            for filename in filenames:
                files_scanned += 1
                if files_scanned > MAX_SCAN_FILES:
                    break

                ext = Path(filename).suffix.lower()
                if ext in ext_to_langs:
                    for lang in ext_to_langs[ext]:
                        if lang.name not in found:
                            found[lang.name] = DetectedLanguage(definition=lang)
                        found[lang.name].matched_files += 1

            if files_scanned > MAX_SCAN_FILES:
                break

        return sorted(found.values(), key=lambda d: d.definition.name)

    def generate_allowlist(
        self, languages: List[DetectedLanguage]
    ) -> Tuple[List[AllowlistEntry], List[str]]:
        from ai_guardian.scanners.prompt_injection import PromptInjectionDetector

        detector = PromptInjectionDetector({"enabled": True})

        entries: List[AllowlistEntry] = []
        seen_patterns: Set[str] = set()
        needs_html_ignore = False

        for lang in languages:
            for identifier in lang.definition.identifiers:
                _, _, detected_file = detector.detect(
                    identifier, source_type="file_content"
                )
                _, _, detected_prompt = detector.detect(
                    identifier, source_type="user_prompt"
                )

                if not (detected_file or detected_prompt):
                    continue

                if any(
                    identifier.startswith(tag)
                    for tag in ("<script", "<iframe", "<object", "<embed", "<img")
                ):
                    needs_html_ignore = True
                    continue

                if identifier not in seen_patterns:
                    seen_patterns.add(identifier)
                    entries.append(
                        AllowlistEntry(
                            pattern=identifier,
                            language=lang.definition.name,
                            identifier=identifier,
                        )
                    )

        ignore_files: List[str] = []
        if needs_html_ignore:
            has_html = any(
                ext in HTML_EXTENSIONS
                for lang in languages
                for ext in lang.definition.file_extensions
            )
            if has_html:
                ignore_files = list(HTML_IGNORE_GLOBS)

        return entries, ignore_files

    def generate_config(
        self,
        entries: List[AllowlistEntry],
        ignore_files: List[str],
    ) -> Dict:
        config: Dict = {}

        if entries or ignore_files:
            pi_config: Dict = {}
            if entries:
                pi_config["allowlist_patterns"] = [e.pattern for e in entries]
            if ignore_files:
                pi_config["ignore_files"] = ignore_files
            config["prompt_injection"] = pi_config

        return config

    def write_config(
        self,
        config: Dict,
        force: bool = False,
        merge: bool = False,
        dry_run: bool = False,
    ) -> Tuple[Path, bool, bool]:
        config_dir = self.project_dir / ".ai-guardian"
        config_path = config_dir / "ai-guardian.json"
        existed = config_path.is_file()

        if dry_run:
            return config_path, False, existed

        if existed and not force and not merge:
            return config_path, False, existed

        if existed and (force or merge):
            backup_path = config_path.with_suffix(".json.backup")
            shutil.copy2(config_path, backup_path)
            logger.info("Backed up existing config to %s", backup_path)

        if existed and merge:
            from ai_guardian.scan_analyzer import merge_and_write_config

            merge_and_write_config(config_path, config)
            return config_path, True, existed

        config_dir.mkdir(parents=True, exist_ok=True)

        output = json.dumps(config, indent=2) + "\n"
        config_path.write_text(output, encoding="utf-8")

        return config_path, True, existed

    def scan_project(
        self,
        threshold: int = 10,
        progressive: bool = True,
        exclude_patterns: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Run FileScanner with all scanners enabled and suppressions stripped."""
        from ai_guardian.scanners.file_scanner import FileScanner
        from ai_guardian.scan_analyzer import (
            ProgressiveSuppressor,
            _build_discovery_config,
        )

        config = _build_discovery_config(str(self.project_dir))
        scanner = FileScanner(config=config, verbose=False)
        suppressor = ProgressiveSuppressor(threshold) if progressive else None
        findings = scanner.scan_directory(
            str(self.project_dir),
            exclude_patterns=exclude_patterns,
            finding_filter=suppressor,
        )
        self._last_suppressor = suppressor
        return findings

    def _load_aiguardignore_excludes(self) -> List[str]:
        """Load exclude paths from existing .aiguardignore.toml."""
        try:
            from ai_guardian.aiguardignore import load_aiguardignore

            config = load_aiguardignore(project_root=self.project_dir)
            if config is None:
                return []
            paths = list(config.global_paths)
            for scanner_paths in config.scanner_paths.values():
                for p in scanner_paths:
                    if p not in paths:
                        paths.append(p)
            return paths
        except Exception:
            return []

    def analyze_scan(self, findings: List[Dict], threshold: int = 10, suppressor=None):
        from ai_guardian.scan_analyzer import build_recommendations

        return build_recommendations(
            findings, threshold=threshold, suppressor=suppressor
        )

    def merge_configs(self, language_config: Dict, scan_config: Dict) -> Dict:
        """Deep-merge language-detection config with scan-derived config."""
        merged = dict(language_config)
        for section, values in scan_config.items():
            if section not in merged:
                merged[section] = dict(values)
            else:
                existing = dict(merged[section])
                merged[section] = existing
                for key, val in values.items():
                    if key in existing and isinstance(val, list):
                        combined = list(existing[key])
                        for item in val:
                            if item not in combined:
                                combined.append(item)
                        existing[key] = combined
                    else:
                        existing[key] = val
        return merged

    def write_aiguardignore(
        self,
        paths_dict: Dict[str, List[str]],
        dry_run: bool = False,
    ) -> Tuple[Path, bool]:
        """Write .aiguardignore.toml from recommended ignore paths."""
        toml_path = self.project_dir / ".aiguardignore.toml"

        if dry_run:
            return toml_path, False

        try:
            from ai_guardian.aiguardignore import (
                SCHEMA_HEADER,
                SCANNER_TYPES,
                _load_toml_data,
                _validate_paths,
            )

            try:
                import tomli_w
            except ImportError:
                import logging

                logging.getLogger(__name__).warning(
                    "tomli_w not available for writing .aiguardignore.toml"
                )
                return toml_path, False

            data = _load_toml_data(toml_path) if toml_path.is_file() else {}
            changed = False

            for scanner_type, patterns in paths_dict.items():
                if scanner_type not in SCANNER_TYPES:
                    continue
                for pattern in patterns:
                    validated = _validate_paths([pattern])
                    if not validated:
                        continue
                    pattern = validated[0]
                    if pattern in ("*", "**", "**/*"):
                        continue
                    scanner_section = data.setdefault(scanner_type, {})
                    al_section = scanner_section.setdefault("allowlist", {})
                    paths_list = al_section.setdefault("paths", [])
                    if pattern not in paths_list:
                        paths_list.append(pattern)
                        changed = True

            if not changed:
                return toml_path, False

            import os
            import tempfile

            is_new = not toml_path.is_file()
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.project_dir), suffix=".aiguardignore.tmp"
            )
            try:
                with os.fdopen(fd, "wb") as f:
                    if is_new:
                        f.write(SCHEMA_HEADER.encode("utf-8"))
                        f.write(b"\n")
                    tomli_w.dump(data, f)
                os.replace(tmp_path, str(toml_path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass  # intentionally silent — cleanup
                raise

            from ai_guardian.aiguardignore import reset_cache

            reset_cache()
            return toml_path, True
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                "Failed to write .aiguardignore.toml: %s", e
            )
            return toml_path, False

    def run(
        self,
        force: bool = False,
        merge: bool = False,
        dry_run: bool = False,
        scan: bool = False,
        threshold: int = 10,
        progressive: bool = True,
        confirm_callback=None,
        exclude_patterns: Optional[List[str]] = None,
    ) -> InitResult:
        result = InitResult(project_dir=self.project_dir, dry_run=dry_run)

        result.detected_languages = self.detect_languages()

        entries, ignore_files = [], []
        if result.detected_languages:
            entries, ignore_files = self.generate_allowlist(result.detected_languages)
        result.allowlist_entries = entries
        result.ignore_files_entries = ignore_files
        language_config = self.generate_config(entries, ignore_files)

        if scan:
            effective_excludes = list(exclude_patterns or [])
            effective_excludes.extend(self._load_aiguardignore_excludes())
            result.exclude_patterns = effective_excludes
            findings = self.scan_project(
                threshold=threshold,
                progressive=progressive,
                exclude_patterns=effective_excludes or None,
            )
            analysis = self.analyze_scan(
                findings, threshold=threshold, suppressor=self._last_suppressor
            )
            if self._last_suppressor:
                analysis.suppressed_count += self._last_suppressor.suppressed_count
            result.scan_analysis = analysis
            scan_config = analysis.recommended_config
            merged = self.merge_configs(language_config, scan_config)
        else:
            merged = language_config

        result.merged_config = merged

        if not merged:
            return result

        if confirm_callback is not None and not confirm_callback(result):
            return result

        config_path, created, existed = self.write_config(
            merged, force=force, merge=merge, dry_run=dry_run
        )
        result.config_path = config_path
        result.config_created = created
        result.config_existed = existed

        if (
            scan
            and result.scan_analysis
            and result.scan_analysis.recommended_ignore_paths
        ):
            aiguardignore_path, aiguardignore_created = self.write_aiguardignore(
                result.scan_analysis.recommended_ignore_paths,
                dry_run=dry_run,
            )
            result.aiguardignore_path = aiguardignore_path
            result.aiguardignore_created = aiguardignore_created

        return result


def _format_evidence(lang: DetectedLanguage) -> str:
    parts = []
    if lang.matched_configs:
        parts.append(", ".join(lang.matched_configs))
    if lang.matched_files > 0:
        ext_list = ", ".join(lang.definition.file_extensions[:3])
        parts.append(f"{lang.matched_files} {ext_list} files")
    return " | ".join(parts) if parts else "detected"


def _print_scan_analysis(analysis) -> None:
    """Print scan analysis section."""
    print()
    print("Scan Analysis")
    print("=" * 40)
    print(f"Found: {analysis.total_findings} findings")
    print()

    if not analysis.high_frequency_clusters:
        print("No high-frequency patterns found.")
        print("None of the findings appear often enough to be false positives.")
        return

    print("High-frequency patterns (likely false positives):")
    for cluster in analysis.high_frequency_clusters:
        label = cluster.sub_type if cluster.sub_type else cluster.rule_id
        print(
            f"  - {cluster.rule_id}/{label}: {cluster.file_count} files ({cluster.total_count} occurrences)"
        )
    print()

    if analysis.directories_to_ignore:
        print("Directories with only false positives:")
        for d in analysis.directories_to_ignore:
            print(
                f"  - {d.directory}/ ({d.total_findings} findings, all high-frequency)"
            )
        print()

    if analysis.recommended_config:
        print("Proposed config (ai-guardian.json):")
        for section, values in sorted(analysis.recommended_config.items()):
            for key, val in values.items():
                if isinstance(val, list):
                    print(f"  {section}.{key}: {len(val)} entries")
        print()

    if analysis.recommended_ignore_paths:
        print("Proposed .aiguardignore.toml:")
        for scanner, paths in sorted(analysis.recommended_ignore_paths.items()):
            for p in paths:
                print(f"  [{scanner}.allowlist] {p}")
        print()

    remaining = analysis.total_findings - analysis.suppressed_count
    if analysis.total_findings > 0:
        pct = (analysis.suppressed_count * 100) // analysis.total_findings
        print(
            f"Would suppress: {analysis.suppressed_count} of {analysis.total_findings} findings ({pct}%)"
        )
        print(f"Remaining findings to review: {remaining}")


def _print_exclude_patterns(exclude_patterns: List[str]) -> None:
    """Print effective exclude patterns."""
    if not exclude_patterns:
        return
    print("Excluded paths:")
    for pattern in exclude_patterns:
        print(f"  - {pattern}")
    print()


def _print_result(result: InitResult) -> None:
    print("AI Guardian Project Initializer")
    print("=" * 40)
    print()
    print(f"Scanning: {result.project_dir}")
    print()

    _print_exclude_patterns(result.exclude_patterns)

    if result.detected_languages:
        print("Detected languages:")
        for lang in result.detected_languages:
            evidence = _format_evidence(lang)
            print(f"  - {lang.definition.name} ({evidence})")
        print()

    if result.scan_analysis:
        _print_scan_analysis(result.scan_analysis)

    if not result.scan_analysis and not result.detected_languages:
        print("No programming languages detected.")
        print("Tip: Run from a project root containing source files.")
        return

    if (
        not result.scan_analysis
        and not result.allowlist_entries
        and not result.ignore_files_entries
    ):
        print("No allowlist entries needed.")
        print("None of the detected languages' identifiers trigger")
        print("current prompt injection detection patterns.")
        return

    if result.allowlist_entries or result.ignore_files_entries:
        print("Generated entries:")
        if result.allowlist_entries:
            by_lang: Dict[str, List[AllowlistEntry]] = {}
            for entry in result.allowlist_entries:
                by_lang.setdefault(entry.language, []).append(entry)
            for lang_name, lang_entries in sorted(by_lang.items()):
                print(f"  {lang_name} allowlist_patterns:")
                for entry in lang_entries:
                    print(f"    - {entry.pattern}")

        if result.ignore_files_entries:
            print("  prompt_injection.ignore_files:")
            for pattern in result.ignore_files_entries:
                print(f"    - {pattern}")
        print()

    if result.dry_run:
        print("[dry-run] Would write to:", result.config_path)
        if result.scan_analysis and result.scan_analysis.recommended_ignore_paths:
            print("[dry-run] Would write to:", result.aiguardignore_path)
        return

    if result.config_existed and not result.config_created:
        return

    if result.config_created:
        print(f"Created: {result.config_path}")
        count = len(result.allowlist_entries)
        ignore_count = len(result.ignore_files_entries)
        parts = []
        if count:
            parts.append(f"{count} allowlist pattern{'s' if count != 1 else ''}")
        if ignore_count:
            parts.append(
                f"{ignore_count} ignore_files entr{'ies' if ignore_count != 1 else 'y'}"
            )
        if parts:
            print(f"  {', '.join(parts)}")

    if result.aiguardignore_created:
        print(f"Created: {result.aiguardignore_path}")


def _print_json(result: InitResult) -> None:
    output: Dict[str, Any] = {
        "project_dir": str(result.project_dir),
        "detected_languages": [
            {
                "name": lang.definition.name,
                "matched_files": lang.matched_files,
                "matched_configs": lang.matched_configs,
            }
            for lang in result.detected_languages
        ],
        "allowlist_entries": [
            {
                "pattern": e.pattern,
                "language": e.language,
                "identifier": e.identifier,
            }
            for e in result.allowlist_entries
        ],
        "ignore_files_entries": result.ignore_files_entries,
        "config_path": str(result.config_path) if result.config_path else None,
        "config_created": result.config_created,
        "config_existed": result.config_existed,
        "dry_run": result.dry_run,
        "exclude_patterns": result.exclude_patterns,
    }

    if result.scan_analysis:
        analysis = result.scan_analysis
        output["scan_analysis"] = {
            "total_findings": analysis.total_findings,
            "total_files_scanned": analysis.total_files_scanned,
            "high_frequency_clusters": [
                {
                    "rule_id": c.rule_id,
                    "sub_type": c.sub_type,
                    "file_count": c.file_count,
                    "total_count": c.total_count,
                    "sample_files": c.sample_files,
                }
                for c in analysis.high_frequency_clusters
            ],
            "directories_to_ignore": [
                {
                    "directory": d.directory,
                    "total_findings": d.total_findings,
                    "high_frequency_findings": d.high_frequency_findings,
                    "all_high_frequency": d.all_high_frequency,
                }
                for d in analysis.directories_to_ignore
            ],
            "recommended_config": analysis.recommended_config,
            "recommended_ignore_paths": analysis.recommended_ignore_paths,
            "suppressed_count": analysis.suppressed_count,
            "remaining_count": analysis.total_findings - analysis.suppressed_count,
        }
        output["aiguardignore_path"] = (
            str(result.aiguardignore_path) if result.aiguardignore_path else None
        )
        output["aiguardignore_created"] = result.aiguardignore_created

    print(json.dumps(output, indent=2))


def _ask_existing_config(config_path) -> str:
    """Ask user how to handle existing config."""
    if not sys.stdin.isatty():
        return "skip"
    print(f"\nConfig already exists: {config_path}")
    try:
        response = input("[M]erge / [O]verwrite / [S]kip? ").strip().lower()
        if response in ("m", "merge"):
            return "merge"
        if response in ("o", "overwrite"):
            return "overwrite"
        return "skip"
    except (EOFError, KeyboardInterrupt):
        print()
        return "skip"


def _confirm_write() -> bool:
    """Ask user to confirm writing config files."""
    if not sys.stdin.isatty():
        return False
    try:
        response = input("\nWrite configuration? [Y/n] ").strip().lower()
        return response in ("", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def init_project_command(args) -> int:
    """CLI entry point for init-project command."""
    project_dir = Path(getattr(args, "dir", ".")).resolve()
    force = getattr(args, "force", False)
    merge = getattr(args, "merge", False)
    dry_run = getattr(args, "dry_run", False)
    json_output = getattr(args, "json", False)
    scan = getattr(args, "scan", False)
    threshold = getattr(args, "threshold", 10)
    progressive = not getattr(args, "exact", False)
    exclude_patterns = getattr(args, "exclude", []) or []

    if not project_dir.is_dir():
        print(f"Error: Not a directory: {project_dir}", file=sys.stderr)
        return 1

    if threshold < 1:
        print("Error: --threshold must be >= 1", file=sys.stderr)
        return 1

    def _interactive_confirm(result_so_far):
        """Show analysis and prompt before writing."""
        if result_so_far.detected_languages:
            print("Detected languages:")
            for lang in result_so_far.detected_languages:
                evidence = _format_evidence(lang)
                print(f"  - {lang.definition.name} ({evidence})")
            print()
        if result_so_far.scan_analysis:
            _print_scan_analysis(result_so_far.scan_analysis)
            analysis = result_so_far.scan_analysis
            if (
                not analysis.recommended_config
                and not analysis.recommended_ignore_paths
                and not result_so_far.allowlist_entries
                and not result_so_far.ignore_files_entries
            ):
                print("\nNo configuration needed.")
                return False
        return _confirm_write()

    initializer = ProjectInitializer(project_dir)

    if scan and not dry_run and not json_output:
        print("AI Guardian Project Initializer")
        print("=" * 40)
        print()
        print(f"Scanning: {project_dir}")
        effective = list(exclude_patterns)
        effective.extend(initializer._load_aiguardignore_excludes())
        _print_exclude_patterns(effective)
        print("Running full scan (this may take a moment)...")
        print()
    confirm_cb = (
        _interactive_confirm if (scan and not dry_run and not json_output) else None
    )
    result = initializer.run(
        force=force,
        merge=merge,
        dry_run=dry_run,
        scan=scan,
        threshold=threshold,
        progressive=progressive,
        confirm_callback=confirm_cb,
        exclude_patterns=exclude_patterns or None,
    )

    if json_output:
        _print_json(result)
    else:
        _print_result(result)

    if result.config_existed and not result.config_created and not dry_run:
        if json_output:
            return 1
        choice = _ask_existing_config(result.config_path)
        if choice in ("m", "merge"):
            initializer.write_config(result.merged_config or {}, merge=True)
            print(f"Config merged into {result.config_path}")
        elif choice in ("o", "overwrite"):
            initializer.write_config(result.merged_config or {}, force=True)
            print(f"Config overwritten at {result.config_path}")
        else:
            print("Skipped.")
            return 1

    return 0


_language_fp_cache: Dict[str, tuple] = {}
_LANGUAGE_FP_CACHE_TTL = 300.0


def get_language_allowlist_patterns(
    project_dir: str, scanner_name: str = "prompt_injection"
) -> List[str]:
    """Return auto-detected allowlist patterns for a project and scanner.

    Scans the project root for language marker files (pyproject.toml, go.mod,
    etc.) and returns known false positive patterns for the detected languages.
    Results are cached per project_dir with a 5-minute TTL.  The cache stores
    patterns for *all* scanner keys so that ``detect_languages()`` only runs
    once per TTL regardless of how many scanners request overlays.
    """
    cached = _language_fp_cache.get(project_dir)
    if cached is not None:
        all_patterns, ts = cached
        if (time.monotonic() - ts) < _LANGUAGE_FP_CACHE_TTL:
            return list(all_patterns.get(scanner_name, []))

    if not project_dir:
        _language_fp_cache[project_dir] = ({}, time.monotonic())
        return []

    try:
        initializer = ProjectInitializer(Path(project_dir))
        languages = initializer.detect_languages()
    except Exception:
        _language_fp_cache[project_dir] = ({}, time.monotonic())
        return []

    all_patterns: Dict[str, List[str]] = {}
    lang_names: List[str] = []
    for lang in languages:
        for key, fp_list in lang.definition.false_positive_patterns.items():
            validated: List[str] = []
            for p in fp_list:
                try:
                    re.compile(p)
                    validated.append(p)
                except re.error:
                    logger.warning(
                        "Invalid regex in %s false_positive_patterns[%s]: %s",
                        lang.definition.name,
                        key,
                        p,
                    )
            if validated:
                existing = all_patterns.get(key, [])
                all_patterns[key] = existing + validated

        if scanner_name in lang.definition.false_positive_patterns:
            lang_names.append(lang.definition.name)

    for key in all_patterns:
        all_patterns[key] = list(dict.fromkeys(all_patterns[key]))

    _language_fp_cache[project_dir] = (all_patterns, time.monotonic())

    result = all_patterns.get(scanner_name, [])
    if result:
        logger.info(
            "Auto-detected %s project — suppressing %d %s false positive patterns",
            ", ".join(lang_names),
            len(result),
            scanner_name,
        )

    return list(result)
