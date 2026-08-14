#!/usr/bin/env python3
"""
Static file scanner for AI Guardian.

Scans repository files for security issues using all Phase 1-4 detectors:
- SSRF Protection (Phase 1)
- Unicode Attack Detection (Phase 2)
- Config File Scanner (Phase 3)
- Secret Redaction/Detection (Phase 4)
"""

import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
import fnmatch

# Import Phase 1-4 scanners
try:
    from ai_guardian.scanners.ssrf import SSRFProtector

    HAS_SSRF = True
except ImportError:
    HAS_SSRF = False

try:
    from ai_guardian.scanners.prompt_injection import (
        UnicodeAttackDetector,
        _offset_to_line_number,
        get_cached_unicode_detector,
    )

    HAS_UNICODE = True
except ImportError:
    HAS_UNICODE = False

try:
    from ai_guardian.scanners.config_scanner import check_config_file_threats

    HAS_CONFIG_SCANNER = True
except ImportError:
    HAS_CONFIG_SCANNER = False

try:
    from ai_guardian.reporting.sarif import (
        SARIFFormatter,
        create_ssrf_finding,
        create_unicode_finding,
        create_config_finding,
        create_secret_finding,
        create_pii_finding,
        create_prompt_injection_finding,
        create_supply_chain_finding,
        create_code_security_finding,
        create_offensive_language_finding,
        create_canary_detection_finding,
        create_exfil_detection_finding,
    )

    HAS_SARIF = True
except ImportError:
    HAS_SARIF = False

try:
    from ai_guardian import check_secrets
    from ai_guardian.scanners import secret_scanning as _secret_scanning_mod

    HAS_SECRET_SCANNER = True
except ImportError:
    HAS_SECRET_SCANNER = False

try:
    from ai_guardian import _scan_for_pii

    HAS_PII_SCANNER = True
except ImportError:
    HAS_PII_SCANNER = False

try:
    from ai_guardian.scanners.prompt_injection import (
        check_prompt_injection,
        PromptInjectionDetector,
        get_cached_detector,
    )

    HAS_PROMPT_INJECTION = True
except ImportError:
    HAS_PROMPT_INJECTION = False

try:
    from ai_guardian.scanners.image_scanner import ImageDetector, scan_image

    HAS_IMAGE_SCANNER = True
except ImportError:
    HAS_IMAGE_SCANNER = False

try:
    from ai_guardian.scanners.supply_chain import (
        SupplyChainScanner,
        check_supply_chain_threats,
    )

    HAS_SUPPLY_CHAIN = True
except ImportError:
    HAS_SUPPLY_CHAIN = False

try:
    from ai_guardian.scanners.canary_detection import (
        CanaryTokenScanner as _CanaryScanner,
    )

    HAS_CANARY_DETECTION = True
except ImportError:
    HAS_CANARY_DETECTION = False

try:
    from ai_guardian.scanners.exfil_detection import (
        ExfilDetectionScanner as _ExfilScanner,
    )

    HAS_EXFIL_DETECTION = True
except ImportError:
    HAS_EXFIL_DETECTION = False

try:
    from ai_guardian.scanners.offensive_language import (
        OffensiveLanguageScanner as _OffensiveLangScanner,
    )

    HAS_OFFENSIVE_LANGUAGE = True
except ImportError:
    HAS_OFFENSIVE_LANGUAGE = False

try:
    from ai_guardian.annotations import process_annotations
    from ai_guardian.config.loaders import _load_annotations_config
    from ai_guardian.config.utils import is_feature_enabled

    HAS_ANNOTATIONS = True
except ImportError:
    HAS_ANNOTATIONS = False

from ai_guardian.scanners.bandit_scanner import BanditScanner, BanditUnavailableError

logger = logging.getLogger(__name__)


def _get_line_snippet(
    content: str, line_number: int, max_length: int = 80
) -> Optional[str]:
    """Extract a single-line snippet from content at the given 1-based line number."""
    if not content or not line_number or line_number < 1:
        return None
    lines = content.split("\n")
    if line_number > len(lines):
        return None
    snippet = lines[line_number - 1].strip()
    if len(snippet) > max_length:
        snippet = snippet[:max_length] + "..."
    return snippet if snippet else None


def _parse_position_from_details(details: str) -> Optional[int]:
    """Extract character position from unicode detector details string."""
    if not details:
        return None
    match = re.search(r"at position (\d+)", details)
    return int(match.group(1)) if match else None


def _find_in_original(content: str, matched_text: Optional[str]) -> Optional[int]:
    """Find matched_text in original content and return 1-based line number.

    The detector may operate on AST-extracted content, so its line numbers
    don't map to the original file. Re-locate by searching original lines.
    """
    if not content or not matched_text:
        return None
    for i, line in enumerate(content.split("\n"), 1):
        if matched_text in line:
            return i
    return None


# Config file patterns (from Phase 3)
CONFIG_FILE_PATTERNS = [
    "CLAUDE.md",
    "AGENTS.md",
    ".cursorrules",
    "*.aider*",
    ".github/copilot-instructions.md",
    ".junie/guidelines.md",
    "ai-guardian.json",
    ".ai-guardian.json",
]


class FileScanner:
    """Static file scanner for security issues."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, verbose: bool = False):
        """
        Initialize file scanner.

        Args:
            config: AI Guardian configuration dict
            verbose: Enable verbose output
        """
        self.config = config or {}
        self.verbose = verbose
        self.findings: List[Dict[str, Any]] = []

        # Initialize scanners with feature-specific sub-configs.
        # Force action to "block" — scanner must never trigger interactive
        # ask dialogs (SSRFProtector.check() shows tkinter popups when
        # action is "ask").
        ssrf_cfg = dict(config.get("ssrf_protection", {}))
        ssrf_cfg["action"] = "block"
        self.ssrf_protector = SSRFProtector(ssrf_cfg) if HAS_SSRF else None
        self.unicode_detector = (
            get_cached_unicode_detector(config.get("prompt_injection", {}))
            if HAS_UNICODE
            else None
        )

        self._image_config: Optional[Dict[str, Any]] = None
        self._image_config_loaded = False

        code_cfg = config.get("code_scanning", {})
        code_enabled = code_cfg.get("enabled", True)
        if HAS_ANNOTATIONS:
            code_enabled = is_feature_enabled(code_cfg.get("enabled"), default=True)
        self._code_scanner = BanditScanner(code_cfg) if code_enabled else None
        self._code_scanner_unavailable: Optional[str] = None
        self._code_scan_skipped_count: int = 0

    _IMAGE_DEFAULTS: Dict[str, Any] = {
        "enabled": True,
        "max_image_size_mb": 10,
        "ignore_files": [],
        "qr_scanning": False,
        "face_detection": False,
        "min_confidence": 0.5,
    }

    def _get_image_config(self) -> Optional[Dict[str, Any]]:
        """Load image scanning config (cached per scanner instance)."""
        if not self._image_config_loaded:
            self._image_config_loaded = True
            if HAS_IMAGE_SCANNER:
                img_section = self.config.get("image_scanning")
                if img_section is None:
                    merged = dict(self._IMAGE_DEFAULTS)
                elif isinstance(img_section, dict):
                    merged = dict(self._IMAGE_DEFAULTS)
                    merged.update(img_section)
                else:
                    merged = None
                if merged and merged.get("enabled", True):
                    self._image_config = merged
        return self._image_config

    def _is_scannable_image(self, file_path: Path) -> bool:
        """Check if file is an image that should be OCR-scanned."""
        if not HAS_IMAGE_SCANNER:
            return False
        if self._get_image_config() is None:
            return False
        return ImageDetector.is_image_file(str(file_path))

    def scan_directory(
        self,
        path: str,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        config_only: bool = False,
        progress_callback=None,
        cancel_event=None,
        skip_hidden: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Scan directory for security issues.

        Args:
            path: Directory path to scan
            include_patterns: File patterns to include (glob style)
            exclude_patterns: File patterns to exclude (glob style)
            config_only: Only scan AI config files
            progress_callback: Optional callable(file_path, index, total)
            cancel_event: Optional threading.Event — set to stop scan early
            skip_hidden: Skip directories starting with '.' (default True)

        Returns:
            List of findings (partial if cancelled)
        """
        self.findings = []
        scan_path = Path(path).resolve()

        if not scan_path.exists():
            logger.error(f"Path does not exist: {path}")
            return self.findings

        if scan_path.is_file():
            if progress_callback:
                progress_callback(str(scan_path), 1, 1)
            if self._is_scannable_image(scan_path):
                self._scan_image_file(scan_path, scan_path.parent)
            else:
                self._scan_file(scan_path, scan_path.parent)
        else:
            files_to_scan = self._discover_files(
                scan_path,
                include_patterns,
                exclude_patterns,
                config_only,
                skip_hidden=skip_hidden,
            )

            if self.verbose:
                print(f"Scanning {len(files_to_scan)} files...")

            total = len(files_to_scan)
            for i, file_path in enumerate(files_to_scan):
                if cancel_event and cancel_event.is_set():
                    break
                if progress_callback:
                    progress_callback(str(file_path), i + 1, total)
                if self._is_scannable_image(file_path):
                    self._scan_image_file(file_path, scan_path)
                else:
                    self._scan_file(file_path, scan_path)

        return self.findings

    def scan_files(
        self,
        file_paths: List[Path],
        base_path: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Scan a specific list of files for security issues.

        Unlike scan_directory(), this skips file discovery and scans
        exactly the files provided. Used by diff-based scanning.

        Args:
            file_paths: List of file paths to scan
            base_path: Base path for relative path reporting (default: cwd)

        Returns:
            List of findings
        """
        self.findings = []
        base = base_path or Path.cwd()

        if self.verbose:
            print(f"Scanning {len(file_paths)} files...")

        for file_path in sorted(file_paths):
            resolved = Path(file_path).resolve()
            if not resolved.exists():
                if self.verbose:
                    logger.warning(f"File not found, skipping: {file_path}")
                continue
            if self._is_scannable_image(resolved):
                self._scan_image_file(resolved, base)
            else:
                self._scan_file(resolved, base)

        return self.findings

    def scan_text(
        self,
        text: str,
        source_label: str = "stdin",
    ) -> List[Dict[str, Any]]:
        """Scan arbitrary text content for security issues.

        Writes text to a temporary file so all scanners (including external
        engines like gitleaks) can process it, then replaces the temp path
        with source_label in findings.

        Args:
            text: Text content to scan
            source_label: Label for findings (e.g. "stdin", "inline")

        Returns:
            List of findings
        """
        self.findings = []

        if not text.strip():
            return self.findings

        tmp_fd, tmp_path_str = tempfile.mkstemp(
            suffix=".txt", prefix="ai-guardian-text-"
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(text)

            self._scan_file(tmp_path, tmp_path.parent)

            for finding in self.findings:
                fp = finding.get("file_path", "")
                if tmp_path_str in fp or tmp_path.name in fp:
                    finding["file_path"] = source_label
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass  # intentionally silent — best-effort operation

        return self.findings

    def _discover_files(
        self,
        base_path: Path,
        include_patterns: Optional[List[str]],
        exclude_patterns: Optional[List[str]],
        config_only: bool,
        skip_hidden: bool = True,
    ) -> List[Path]:
        """
        Discover files to scan.

        Uses os.walk() to prune excluded directories during traversal
        instead of rglob("*") which walks the entire tree first.

        Args:
            base_path: Base directory to search
            include_patterns: File patterns to include
            exclude_patterns: File patterns to exclude
            config_only: Only include config files
            skip_hidden: Skip directories starting with '.'

        Returns:
            List of file paths to scan
        """
        files: Set[Path] = set()

        default_excludes = [
            ".git/*",
            ".git/**/*",
            "__pycache__/*",
            "__pycache__/**/*",
            "*.pyc",
            "node_modules/*",
            "node_modules/**/*",
            ".venv/*",
            ".venv/**/*",
            "venv/*",
            "venv/**/*",
            "*.min.js",
            "*.map",
        ]

        exclude_patterns = (exclude_patterns or []) + default_excludes

        pruned_dirs = {
            ".git",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
        }

        for dirpath, dirnames, filenames in os.walk(base_path):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in pruned_dirs
                and not (skip_hidden and d.startswith("."))
                and not self._is_excluded_dir(d, dirpath, base_path, exclude_patterns)
            ]

            for fname in filenames:
                file_path = Path(dirpath) / fname
                if not file_path.is_file():
                    continue
                if self._is_excluded(file_path, base_path, exclude_patterns):
                    continue

                if config_only:
                    if any(fnmatch.fnmatch(fname, pat) for pat in CONFIG_FILE_PATTERNS):
                        files.add(file_path)
                elif include_patterns:
                    if any(
                        fnmatch.fnmatch(fname, pat)
                        or fnmatch.fnmatch(str(file_path.relative_to(base_path)), pat)
                        for pat in include_patterns
                    ):
                        files.add(file_path)
                else:
                    if self._is_text_file(file_path) or self._is_scannable_image(
                        file_path
                    ):
                        files.add(file_path)

        return sorted(files)

    def _is_excluded_dir(
        self,
        dirname: str,
        dirpath: str,
        base_path: Path,
        exclude_patterns: List[str],
    ) -> bool:
        """Check if a directory should be pruned during traversal."""
        try:
            rel = Path(dirpath, dirname).relative_to(base_path)
        except ValueError:
            return True
        rel_str = str(rel)
        for pattern in exclude_patterns:
            if fnmatch.fnmatch(rel_str, pattern.rstrip("/*")):
                return True
            if fnmatch.fnmatch(f"{rel_str}/x", pattern):
                return True
        return False

    def _is_excluded(
        self, file_path: Path, base_path: Path, exclude_patterns: List[str]
    ) -> bool:
        """
        Check if file should be excluded.

        Args:
            file_path: File to check
            base_path: Base scan directory
            exclude_patterns: Exclusion patterns

        Returns:
            True if file should be excluded
        """
        try:
            relative_path = file_path.relative_to(base_path)
        except ValueError:
            return True

        for pattern in exclude_patterns:
            if fnmatch.fnmatch(str(relative_path), pattern):
                return True
            if fnmatch.fnmatch(file_path.name, pattern):
                return True

        return False

    def _is_text_file(self, file_path: Path) -> bool:
        """
        Check if file is likely a text file.

        Args:
            file_path: File to check

        Returns:
            True if likely a text file
        """
        # Check extension
        text_extensions = {
            ".py",
            ".md",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".sh",
            ".bash",
            ".zsh",
            ".fish",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".html",
            ".css",
            ".xml",
            ".sql",
            ".go",
            ".rs",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".java",
            ".rb",
            ".php",
            ".pl",
            ".swift",
            ".kt",
            ".scala",
            ".r",
            ".m",
            ".mm",
            ".vim",
            ".el",
            ".lua",
            ".tcl",
            ".awk",
            ".sed",
            ".gradle",
            ".properties",
            ".conf",
            ".cfg",
            ".ini",
            ".env",
            ".gitignore",
            ".dockerignore",
            ".editorconfig",
        }

        if file_path.suffix.lower() in text_extensions:
            return True

        # Check for files without extensions that are likely text
        if not file_path.suffix and file_path.name in [
            "Dockerfile",
            "Makefile",
            "Rakefile",
            "Gemfile",
            "LICENSE",
            "README",
            "CHANGELOG",
            "AUTHORS",
        ]:
            return True

        return False

    def _scan_file(self, file_path: Path, base_path: Path) -> None:
        """
        Scan a single file for security issues.

        Args:
            file_path: File to scan
            base_path: Base scan directory (for relative paths)
        """
        try:
            # Get relative path for reporting
            try:
                relative_path = str(file_path.relative_to(base_path))
            except ValueError:
                relative_path = str(file_path)

            # Read file content
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception as e:
                if self.verbose:
                    logger.warning(f"Could not read {relative_path}: {e}")
                return

            # Skip empty files
            if not content.strip():
                return

            if self.verbose:
                print(f"Scanning: {relative_path}")

            # Apply annotation-based suppression for secrets/PII (#1237)
            secret_content = content
            pii_content = content
            if HAS_ANNOTATIONS:
                ann_config, _ = _load_annotations_config()
                if ann_config and is_feature_enabled(
                    ann_config.get("enabled"), default=True
                ):
                    content_all_sup, content_secret_sup, ann_info, _ = (
                        process_annotations(
                            content, file_path=str(file_path), config=ann_config
                        )
                    )
                    if ann_info:
                        pii_content = content_all_sup
                        secret_content = content_secret_sup

            # Check for config file threats (Phase 3)
            if self._is_config_file(file_path) and HAS_CONFIG_SCANNER:
                self._check_config_threats(relative_path, content)

            # Check for SSRF patterns (Phase 1)
            if self.ssrf_protector:
                self._check_ssrf(relative_path, content)

            # Check for Unicode attacks (Phase 2)
            if self.unicode_detector:
                self._check_unicode_attacks(relative_path, content)

            # Check for secrets (Phase 4) — uses annotation-suppressed content
            if HAS_SECRET_SCANNER:
                self._check_secrets(relative_path, secret_content, str(file_path))

            # Check for PII — uses annotation-suppressed content
            if HAS_PII_SCANNER:
                self._check_pii(relative_path, pii_content)

            # Check for prompt injection
            if HAS_PROMPT_INJECTION:
                self._check_prompt_injection(relative_path, content)

            # Check for supply chain threats
            if HAS_SUPPLY_CHAIN:
                self._check_supply_chain(str(file_path), content)

            # Check for offensive language
            if HAS_OFFENSIVE_LANGUAGE:
                self._check_offensive_language(relative_path, content)

            # Check for canary tokens
            if HAS_CANARY_DETECTION:
                self._check_canary_detection(relative_path, content)

            # Check for Python code security issues (Bandit)
            if self._code_scanner and file_path.suffix == ".py":
                self._check_code_security(relative_path, content)

            # Check for exfil behavior in shell scripts
            if HAS_EXFIL_DETECTION and file_path.suffix in {
                ".sh",
                ".bash",
                ".zsh",
                ".ksh",
                ".fish",
            }:
                self._check_exfil_detection(relative_path, content)

        except Exception as e:
            if self.verbose:
                logger.error(f"Error scanning {file_path}: {e}")

    def _scan_image_file(self, file_path: Path, base_path: Path) -> None:
        """Scan an image file via OCR and run security checkers on extracted text."""
        try:
            try:
                relative_path = str(file_path.relative_to(base_path))
            except ValueError:
                relative_path = str(file_path)

            img_config = self._get_image_config()
            if not img_config:
                return

            for pattern in img_config.get("ignore_files", []):
                if fnmatch.fnmatch(str(file_path), pattern) or fnmatch.fnmatch(
                    file_path.name, pattern
                ):
                    return

            try:
                file_size = file_path.stat().st_size
                max_size = img_config.get("max_image_size_mb", 10) * 1024 * 1024
                if file_size > max_size:
                    if self.verbose:
                        logger.info(f"Skipping oversized image: {relative_path}")
                    return
            except OSError:
                return

            try:
                with open(file_path, "rb") as f:
                    image_data = f.read()
            except Exception as e:
                if self.verbose:
                    logger.warning(f"Could not read image {relative_path}: {e}")
                return

            if self.verbose:
                print(f"Scanning image: {relative_path}")

            try:
                result = scan_image(image_data, img_config)
            except Exception as e:
                logger.warning(f"Image scanning error for {relative_path}: {e}")
                return

            extracted_text = result.extracted_text or ""
            if result.qr_texts:
                qr_text = "\n".join(result.qr_texts)
                extracted_text = (
                    f"{extracted_text}\n{qr_text}" if extracted_text else qr_text
                )

            if not extracted_text.strip():
                return

            if self.verbose:
                print(
                    f"  OCR extracted {len(extracted_text)} chars in {result.elapsed_ms:.0f}ms"
                )

            findings_before = len(self.findings)

            if self.ssrf_protector:
                self._check_ssrf(relative_path, extracted_text)

            if self.unicode_detector:
                self._check_unicode_attacks(relative_path, extracted_text)

            if HAS_SECRET_SCANNER:
                self._check_secrets(relative_path, extracted_text, str(file_path))

            if HAS_PII_SCANNER:
                self._check_pii(relative_path, extracted_text)

            if HAS_PROMPT_INJECTION:
                self._check_prompt_injection(relative_path, extracted_text)

            for finding in self.findings[findings_before:]:
                if "details" not in finding:
                    finding["details"] = {}
                finding["details"]["source_type"] = "image_ocr"
                finding["details"]["ocr_confidence"] = result.ocr_confidence

        except Exception as e:
            if self.verbose:
                logger.error(f"Error scanning image {file_path}: {e}")

    def _is_config_file(self, file_path: Path) -> bool:
        """Check if file is an AI config file."""
        file_name = file_path.name
        for pattern in CONFIG_FILE_PATTERNS:
            if fnmatch.fnmatch(file_name, pattern):
                return True
        return False

    def _check_config_threats(self, file_path: str, content: str) -> None:
        """Check config file for exfiltration threats."""
        try:
            is_malicious, reason, details = check_config_file_threats(
                file_path, content, self.config
            )
            if is_malicious:
                finding = create_config_finding(
                    pattern=details.get("pattern", "unknown"),
                    reason=reason,
                    file_path=file_path,
                    line_number=details.get("line_number"),
                    snippet=details.get("snippet"),
                )
                self.findings.append(finding)
                if self.verbose:
                    print(f"  [CONFIG] {reason}")
        except Exception as e:
            logger.warning(f"Error checking config threats: {e}")

    def _check_ssrf(self, file_path: str, content: str) -> None:
        """Check for SSRF patterns in file content."""
        try:
            # Check content as if it were a Bash command
            # This allows us to detect URLs in any context
            should_block, reason = self.ssrf_protector.check(
                "Bash", {"command": content}
            )

            if should_block:
                # Extract the problematic URL from the reason or content
                url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
                urls = re.findall(url_pattern, content)

                # Find which URL triggered the block
                for url in urls:
                    # Test each URL individually
                    url_should_block, url_reason = self.ssrf_protector.check(
                        "Bash", {"command": f"curl {url}"}
                    )
                    if url_should_block:
                        # Find line number
                        line_number = None
                        snippet = None
                        for i, line in enumerate(content.split("\n"), 1):
                            if url in line:
                                line_number = i
                                snippet = line.strip()
                                break

                        finding = create_ssrf_finding(
                            url=url,
                            reason=url_reason or reason,
                            file_path=file_path,
                            line_number=line_number,
                            snippet=snippet,
                        )
                        self.findings.append(finding)
                        if self.verbose:
                            print(f"  [SSRF] {url_reason or reason}: {url}")
        except Exception as e:
            logger.warning(f"Error checking SSRF: {e}")

    def _check_unicode_attacks(self, file_path: str, content: str) -> None:
        """Check for Unicode attacks in file content."""
        try:
            checks = [
                ("zero-width characters", self.unicode_detector.detect_zero_width),
                ("bidirectional override", self.unicode_detector.detect_bidi_override),
                ("homoglyphs", self.unicode_detector.detect_homoglyphs),
                ("tag characters", self.unicode_detector.detect_tag_chars),
            ]
            for attack_type, detect_fn in checks:
                is_attack, details = detect_fn(content)
                if is_attack:
                    line_number = None
                    snippet = None
                    position = _parse_position_from_details(details)
                    if position is not None:
                        line_number = _offset_to_line_number(content, position)
                        snippet = _get_line_snippet(content, line_number)
                    finding = create_unicode_finding(
                        attack_type=attack_type,
                        details=f"{attack_type.title()} detected: {details}",
                        file_path=file_path,
                        line_number=line_number,
                        snippet=snippet,
                    )
                    self.findings.append(finding)
                    if self.verbose:
                        print(f"  [UNICODE] {attack_type.title()} detected")

        except Exception as e:
            logger.warning(f"Error checking Unicode attacks: {e}")

    def _check_secrets(self, file_path: str, content: str, absolute_path: str) -> None:
        """Check for secrets using gitleaks/betterleaks."""
        try:
            secret_config = self.config.get("secret_scanning", {})
            if not secret_config.get("enabled", True):
                return

            has_secrets, error_message = check_secrets(
                content,
                filename=os.path.basename(file_path),
                file_path=absolute_path,
                allowlist_patterns=secret_config.get("allowlist_patterns"),
                ignore_files=secret_config.get("ignore_files"),
            )

            if has_secrets and error_message:
                all_findings = _secret_scanning_mod._last_secret_findings
                if all_findings:
                    for f in all_findings:
                        finding = create_secret_finding(
                            secret_type=f.get("rule_id") or "secret",
                            file_path=file_path,
                            line_number=f.get("line_number"),
                            start_column=f.get("start_column"),
                        )
                        self.findings.append(finding)
                else:
                    line_number = None
                    secret_type = "secret"
                    loc_match = re.search(r"Location: .*?:(\d+)", error_message)
                    if loc_match:
                        line_number = int(loc_match.group(1)) or None
                    type_match = re.search(
                        r"(?:Secret Type|Credential Type|PII Type): (.+)",
                        error_message,
                    )
                    if type_match:
                        secret_type = type_match.group(1).strip()
                    finding = create_secret_finding(
                        secret_type=secret_type,
                        file_path=file_path,
                        line_number=line_number,
                    )
                    self.findings.append(finding)
                if self.verbose:
                    count = len(all_findings) if all_findings else 1
                    print(f"  [SECRET] {count} secret(s) detected")
        except Exception as e:
            logger.warning(f"Error checking secrets: {e}")

    def _check_pii(self, file_path: str, content: str) -> None:
        """Check for personally identifiable information."""
        try:
            pii_config = self.config.get("scan_pii", {})
            if not pii_config.get("enabled", True):
                return

            has_pii, _redacted, redactions, _warning = _scan_for_pii(
                content, pii_config
            )

            if has_pii and redactions:
                pii_types_found = sorted({r.get("type", "unknown") for r in redactions})
                for pii_type in pii_types_found:
                    first_of_type = next(
                        (r for r in redactions if r.get("type") == pii_type), {}
                    )
                    line_number = first_of_type.get("line_number")
                    snippet = (
                        _get_line_snippet(content, line_number) if line_number else None
                    )
                    finding = create_pii_finding(
                        pii_type=pii_type,
                        file_path=file_path,
                        line_number=line_number,
                        snippet=snippet,
                    )
                    self.findings.append(finding)
                if self.verbose:
                    print(
                        f"  [PII] {len(redactions)} PII item(s) found: {', '.join(pii_types_found)}"
                    )
        except Exception as e:
            logger.warning(f"Error checking PII: {e}")

    def _check_prompt_injection(self, file_path: str, content: str) -> None:
        """Check for prompt injection patterns."""
        try:
            injection_config = self.config.get("prompt_injection", {})
            if not injection_config.get("enabled", True):
                return

            detector = get_cached_detector(injection_config)
            _should_block, error_message, detected = detector.detect(
                content,
                file_path=file_path,
                source_type="file_content",
            )

            if detected and error_message:
                line_number = _find_in_original(content, detector.last_matched_text)
                if line_number is None:
                    line_number = detector.last_line_number
                snippet = (
                    _get_line_snippet(content, line_number) if line_number else None
                )
                finding = create_prompt_injection_finding(
                    description=(
                        error_message.splitlines()[0]
                        if error_message
                        else "Prompt injection detected"
                    ),
                    file_path=file_path,
                    line_number=line_number,
                    snippet=snippet,
                    start_column=detector.last_start_column,
                    end_column=detector.last_end_column,
                )
                self.findings.append(finding)
                if self.verbose:
                    print(
                        f"  [PROMPT-INJECTION] {error_message.splitlines()[0] if error_message else 'Detected'}"
                    )
        except Exception as e:
            logger.warning(f"Error checking prompt injection: {e}")

    def _check_supply_chain(self, file_path: str, content: str) -> None:
        """Check agent config files for supply chain threats."""
        try:
            sc_config = self.config.get("supply_chain") if self.config else None
            is_malicious, reason, details = check_supply_chain_threats(
                file_path, content, sc_config
            )
            if is_malicious and details:
                finding = create_supply_chain_finding(
                    category=details.get("category", "unknown"),
                    reason=reason or "Supply chain threat detected",
                    file_path=file_path,
                    line_number=details.get("line_number"),
                    snippet=details.get("snippet"),
                )
                self.findings.append(finding)
                if self.verbose:
                    print(f"  [SUPPLY-CHAIN] {reason}")
        except Exception as e:
            logger.warning(f"Error checking supply chain: {e}")

    def _check_exfil_detection(self, file_path: str, content: str) -> None:
        """Check shell scripts for credential exfiltration patterns."""
        try:
            ed_config = self.config.get("exfil_detection") if self.config else None
            scanner = _ExfilScanner(ed_config)
            is_malicious, reason, details = scanner.scan(content, label=file_path)
            if is_malicious and details:
                if HAS_SARIF:
                    finding = create_exfil_detection_finding(
                        category=details.get("category", "unknown"),
                        reason=reason or "Credential exfiltration detected",
                        file_path=file_path,
                        line_number=details.get("line_number"),
                        start_column=details.get("start_column"),
                        snippet=details.get("snippet"),
                    )
                else:
                    finding = {
                        "rule_id": "EXFIL-DETECTION-001",
                        "level": "error",
                        "message": reason or "Credential exfiltration detected",
                        "file_path": file_path,
                        "line_number": details.get("line_number"),
                        "snippet": details.get("snippet"),
                    }
                self.findings.append(finding)
                if self.verbose:
                    print(f"  [EXFIL-DETECTION] {reason}")
        except Exception as e:
            logger.warning(f"Error checking exfil detection: {e}")

    def _check_code_security(self, file_path: str, content: str) -> None:
        """Check Python code for security issues using Bandit."""
        try:
            code_findings = self._code_scanner.scan(content, file_path=file_path)
            for f in code_findings:
                if HAS_SARIF:
                    finding = create_code_security_finding(
                        rule_id=f.rule_id,
                        description=f.description,
                        severity=f.severity,
                        confidence=f.confidence,
                        file_path=file_path,
                        line_number=f.line_number or None,
                        start_column=f.start_column,
                        snippet=f.snippet,
                    )
                else:
                    finding = {
                        "rule_id": f.rule_id,
                        "level": "error" if f.severity == "HIGH" else "warning",
                        "message": f"Code security issue ({f.severity}): {f.description}",
                        "file_path": file_path,
                        "line_number": f.line_number or None,
                        "snippet": f.snippet,
                    }
                self.findings.append(finding)
            if code_findings and self.verbose:
                print(f"  [CODE-SECURITY] {len(code_findings)} issue(s) found (bandit)")
        except BanditUnavailableError as e:
            self._code_scan_skipped_count += 1
            if self._code_scanner_unavailable is None:
                self._code_scanner_unavailable = str(e)
                if self.verbose:
                    print(f"  ⚠️  Code security scanner (Bandit) unavailable: {e}")
        except Exception as e:
            logger.warning(f"Error checking code security: {e}")

    def _check_offensive_language(self, file_path: str, content: str) -> None:
        """Check content for offensive language patterns."""
        try:
            ol_config = self.config.get("scan_offensive") if self.config else None
            if not ol_config:
                from ai_guardian.config.loaders import _load_offensive_language_config

                ol_config, _ = _load_offensive_language_config()
            if not ol_config or not ol_config.get("enabled", False):
                return
            scanner = _OffensiveLangScanner(ol_config)
            findings = scanner.scan(content, file_path=file_path)
            for f in findings:
                if HAS_SARIF:
                    finding = create_offensive_language_finding(
                        rule_id=f["rule_id"],
                        description=f["description"],
                        category=f["category_tag"],
                        suggestion=f.get("suggestion", ""),
                        file_path=file_path,
                        line_number=f.get("line_number"),
                        start_column=f.get("start_column"),
                        matched_text=f.get("matched_text", ""),
                    )
                else:
                    finding = {
                        "rule_id": f["rule_id"],
                        "level": "warning",
                        "message": f"Offensive language ({f['category_tag']}): {f['description']}",
                        "file_path": file_path,
                        "line_number": f.get("line_number"),
                        "suggestion": f.get("suggestion", ""),
                    }
                self.findings.append(finding)
            if findings and self.verbose:
                print(f"  [OFFENSIVE-LANGUAGE] {len(findings)} match(es) found")
        except Exception as e:
            logger.warning(f"Error checking offensive language: {e}")

    def _check_canary_detection(self, file_path: str, content: str) -> None:
        """Check content for user-registered canary tokens."""
        try:
            cd_config = self.config.get("canary_detection") if self.config else None
            if not cd_config:
                from ai_guardian.config.loaders import _load_canary_detection_config

                cd_config, _ = _load_canary_detection_config()
            if not cd_config or not cd_config.get("enabled", False):
                return
            if not cd_config.get("tokens"):
                return
            scanner = _CanaryScanner(cd_config)
            should_block, error_msg, details = scanner.scan(content, file_path)
            if details:
                matched_text = scanner.last_matched_text or ""
                token = scanner.last_matched_token or ""
                description = scanner.last_description or ""
                line_number = scanner.last_line_number
                start_column = scanner.last_start_column

                if HAS_SARIF:
                    finding = create_canary_detection_finding(
                        token=token,
                        description=description,
                        file_path=file_path,
                        line_number=line_number,
                        start_column=start_column,
                        matched_text=matched_text,
                    )
                else:
                    finding = {
                        "rule_id": "canary_detected",
                        "level": "error",
                        "message": f"Canary token detected: {description!r}",
                        "file_path": file_path,
                        "line_number": line_number,
                        "matched_text": matched_text,
                    }
                self.findings.append(finding)
                if self.verbose:
                    print(f"  [CANARY] canary token detected in {file_path}")
        except Exception as e:
            logger.warning(f"Error checking canary tokens: {e}")

    def scan_agent_configs(self) -> None:
        """Scan known agent configuration files for supply chain threats."""
        import glob as glob_mod
        from ai_guardian.scanners.supply_chain import (
            AGENT_CONFIG_PATHS_HOME,
            PLUGIN_PATHS_HOME,
        )

        home = os.path.expanduser("~")
        paths_to_scan = []

        for rel_path in AGENT_CONFIG_PATHS_HOME:
            full = os.path.join(home, rel_path)
            if "*" in full:
                paths_to_scan.extend(glob_mod.glob(full))
            elif os.path.isfile(full):
                paths_to_scan.append(full)

        for rel_path in PLUGIN_PATHS_HOME:
            full = os.path.join(home, rel_path)
            if "*" in full:
                paths_to_scan.extend(glob_mod.glob(full))
            elif os.path.isfile(full):
                paths_to_scan.append(full)

        for fpath in paths_to_scan:
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if content.strip():
                    self._check_supply_chain(fpath, content)
            except Exception as e:
                if self.verbose:
                    logger.warning(f"Could not read {fpath}: {e}")


def scan_command(args) -> int:
    """
    Handle the scan command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for issues found)
    """
    # Suppress internal logging to stderr unless --verbose (file logging unaffected)
    if not args.verbose:
        for handler in logging.getLogger("ai_guardian").handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                handler.setLevel(logging.CRITICAL + 1)

    # Load configuration
    if hasattr(args, "config") and args.config:
        config = {}
        try:
            with open(args.config, encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load config file: {e}", file=sys.stderr)
    else:
        from ai_guardian.config.loaders import load_scanner_config

        config = load_scanner_config()

    # Initialize scanner
    scanner = FileScanner(config=config, verbose=args.verbose)

    # Handle --text flag or stdin pipe
    text_input = getattr(args, "text", None)
    text_mode = False
    if text_input is not None:
        findings = scanner.scan_text(text_input, source_label="inline")
        text_mode = True
    elif args.path == "--" or (args.path is None and not sys.stdin.isatty()):
        stdin_text = sys.stdin.read()
        if not stdin_text.strip():
            print("No input received from stdin", file=sys.stderr)
            return 1
        findings = scanner.scan_text(stdin_text, source_label="stdin")
        text_mode = True

    if not text_mode:
        if args.path is None:
            args.path = "."

    if not text_mode:
        # Determine scan mode
        diff_mode = getattr(args, "diff", False)
        pr_number = getattr(args, "pr", None)
        mr_number = getattr(args, "mr", None)
        stdin_diff = getattr(args, "stdin_diff", False)
        changed_lines_only = getattr(args, "changed_lines_only", False)
        diff_flags = [
            diff_mode,
            pr_number is not None,
            mr_number is not None,
            stdin_diff,
        ]

        if sum(diff_flags) > 1:
            print(
                "Error: --diff, --pr, --mr, and --stdin-diff are mutually exclusive",
                file=sys.stderr,
            )
            return 1

        staged = getattr(args, "staged", False)

        if getattr(args, "base", None) and not diff_mode:
            print("Error: --base requires --diff", file=sys.stderr)
            return 1

        if staged and not diff_mode:
            print("Error: --staged requires --diff", file=sys.stderr)
            return 1

        if staged and getattr(args, "base", None):
            print("Error: --staged and --base are mutually exclusive", file=sys.stderr)
            return 1

        if changed_lines_only and not any(diff_flags):
            print(
                "Error: --changed-lines-only requires --diff, --pr, --mr, or --stdin-diff",
                file=sys.stderr,
            )
            return 1

        agent_configs = getattr(args, "agent_configs", False)
        if agent_configs:
            if not HAS_SUPPLY_CHAIN:
                print("Error: Supply chain scanner not available", file=sys.stderr)
                return 1
            scanner.scan_agent_configs()
            findings = scanner.findings
        if not agent_configs and any(diff_flags):
            # Diff-based scanning
            try:
                from ai_guardian.tools.diff_provider import (
                    DiffProviderError,
                    extract_file_contents_from_diff,
                    filter_findings_by_changed_lines,
                    get_changed_files_from_diff,
                    get_diff_unified,
                    get_mr_diff,
                    get_pr_diff,
                    get_staged_diff,
                    parse_unified_diff,
                )
            except ImportError as e:
                print(f"Error: Diff provider not available: {e}", file=sys.stderr)
                return 1

            try:
                if stdin_diff:
                    diff_text = sys.stdin.read()
                elif pr_number:
                    diff_text = get_pr_diff(pr_number, repo_path=args.path)
                elif mr_number:
                    diff_text = get_mr_diff(mr_number, repo_path=args.path)
                elif staged:
                    diff_text = get_staged_diff(repo_path=args.path)
                else:
                    base_ref = getattr(args, "base", None)
                    diff_text = get_diff_unified(base_ref=base_ref, repo_path=args.path)

                changed_files = get_changed_files_from_diff(diff_text)
                changed_lines = (
                    parse_unified_diff(diff_text) if changed_lines_only else None
                )

                if not changed_files:
                    if not getattr(args, "sarif_output", None) and not getattr(
                        args, "json_output", None
                    ):
                        print("No changed files found in diff.")
                    return 0

                is_remote = pr_number is not None or mr_number is not None

                if is_remote:
                    file_contents = extract_file_contents_from_diff(diff_text)
                    tmpdir = tempfile.mkdtemp(prefix="ai-guardian-scan-")
                    try:
                        tmp_base = Path(tmpdir)
                        file_paths = []
                        for rel_path, content in file_contents.items():
                            tmp_file = tmp_base / rel_path
                            tmp_file.parent.mkdir(parents=True, exist_ok=True)
                            tmp_file.write_text(content, encoding="utf-8")
                            file_paths.append(tmp_file)

                        if args.verbose:
                            print(
                                f"PR/MR scanning: {len(file_paths)} changed file(s) from remote diff"
                            )

                        findings = scanner.scan_files(
                            file_paths=file_paths, base_path=tmp_base
                        )
                    finally:
                        import shutil

                        shutil.rmtree(tmpdir, ignore_errors=True)
                else:
                    base = Path(args.path).resolve()
                    file_paths = [base / f for f in changed_files]

                    if args.verbose:
                        print(f"Diff scanning: {len(file_paths)} changed file(s)")

                    findings = scanner.scan_files(file_paths=file_paths, base_path=base)

                if changed_lines_only and changed_lines:
                    findings = filter_findings_by_changed_lines(findings, changed_lines)

            except DiffProviderError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
        elif not agent_configs:
            # Standard directory scanning
            findings = scanner.scan_directory(
                path=args.path,
                include_patterns=args.include if hasattr(args, "include") else None,
                exclude_patterns=args.exclude if hasattr(args, "exclude") else None,
                config_only=args.config_only if hasattr(args, "config_only") else False,
            )

    # Output results
    if args.sarif_output and HAS_SARIF:
        # SARIF output
        from ai_guardian import __version__

        formatter = SARIFFormatter(version=__version__)
        scan_path = args.path if args.path else ("inline" if text_mode else ".")
        formatter.write_sarif_file(findings, args.sarif_output, scan_path=scan_path)
        if args.verbose or not args.json_output:
            print(f"SARIF output written to: {args.sarif_output}")

    if args.json_output:
        # JSON output
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(findings, f, indent=2)
        if args.verbose or not args.sarif_output:
            print(f"JSON output written to: {args.json_output}")

    # Text output (default)
    if not args.sarif_output and not args.json_output:
        bandit_msg = getattr(scanner, "_code_scanner_unavailable", None)
        skipped = getattr(scanner, "_code_scan_skipped_count", 0)
        if bandit_msg:
            print(f"\n⚠️  Code security scanner (Bandit) unavailable: {bandit_msg}")
            print("    Reinstall: uv tool install --force ai-guardian")
            if skipped:
                print(f"    Code security scan SKIPPED for {skipped} file(s).")

        if findings:
            print("\n🛡️ AI Guardian Scan Results\n")
            print(f"Found {len(findings)} security issue(s):\n")
            for i, finding in enumerate(findings, 1):
                print(f"{i}. [{finding['rule_id']}] {finding['message']}")
                if finding.get("file_path"):
                    print(f"   File: {finding['file_path']}", end="")
                    if finding.get("line_number"):
                        if finding.get("start_column") is not None:
                            print(
                                f":{finding['line_number']}:{finding['start_column'] + 1}"
                            )
                        else:
                            print(f":{finding['line_number']}")
                    else:
                        print()
                if finding.get("snippet"):
                    print(f"   Code: {finding['snippet']}")
                print()
        else:
            if bandit_msg:
                print("✅ No other security issues detected")
            else:
                print("✅ No security issues detected")

    # Exit code
    if args.exit_code and findings:
        return 1
    return 0
