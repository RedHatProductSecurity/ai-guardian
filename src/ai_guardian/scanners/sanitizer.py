"""
Sanitizer - Redacts secrets, PII, and threats from text.

Designed for cleaning transcripts before sharing with other agents.
Uses hardcoded maximum detection — ignores user config, no allowlists.

Part of Issue #443: ai-guardian sanitize command.
Part of Issue #857: directory input with output directory.
"""

import fnmatch
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def get_sanitize_config():
    """Config for sanitize command — scan everything, ignore nothing."""
    return {
        "secret_scanning": {"enabled": True},
        "scan_pii": {
            "enabled": True,
            "pii_types": [
                "ssn",
                "credit_card",
                "phone",
                "email",
                "us_passport",
                "iban",
                "intl_phone",
            ],
            "allowlist_patterns": [],
            "ignore_files": [],
            "ignore_tools": [],
        },
    }


def _sanitize_unicode(text: str) -> tuple:
    """
    Strip dangerous unicode characters and replace homoglyphs.

    Returns:
        Tuple of (sanitized_text, list of changes made)
    """
    from ai_guardian.scanners.prompt_injection import UnicodeAttackDetector

    changes = []

    zero_width_set = set(UnicodeAttackDetector.ZERO_WIDTH_CHARS)
    bidi_set = set(UnicodeAttackDetector.BIDI_OVERRIDE_CHARS)

    homoglyph_map = {
        lookalike: latin
        for lookalike, latin in UnicodeAttackDetector.HOMOGLYPH_PATTERNS
    }

    result = []
    for char in text:
        code_point = ord(char)

        if char in zero_width_set:
            changes.append(
                {"type": "unicode_zero_width", "char": f"U+{code_point:04X}"}
            )
            continue

        if char in bidi_set:
            changes.append(
                {"type": "unicode_bidi_override", "char": f"U+{code_point:04X}"}
            )
            continue

        if (
            UnicodeAttackDetector.TAG_CHAR_START
            <= code_point
            <= UnicodeAttackDetector.TAG_CHAR_END
        ):
            changes.append({"type": "unicode_tag_char", "char": f"U+{code_point:05X}"})
            continue

        if char in homoglyph_map:
            latin = homoglyph_map[char]
            changes.append(
                {
                    "type": "unicode_homoglyph",
                    "char": f"U+{code_point:04X}",
                    "replaced_with": latin,
                }
            )
            result.append(latin)
            continue

        result.append(char)

    return "".join(result), changes


_PII_TYPES = frozenset(
    {
        "SSN",
        "Credit Card Number",
        "US Phone Number",
        "Email Address",
        "US Passport Number",
        "IBAN",
        "International Phone Number",
    }
)

_PI_DETECTOR_CONFIG = {
    "enabled": True,
    "sensitivity": "high",
    "allowlist_patterns": [],
    "ignore_files": [],
    "ignore_tools": [],
}


def _sanitize_prompt_injection(text: str, detector=None) -> tuple:
    """
    Detect and replace prompt injection patterns with [SANITIZED].

    Returns:
        Tuple of (sanitized_text, list of redactions)
    """
    from ai_guardian.scanners.prompt_injection import PromptInjectionDetector

    if detector is None:
        detector = PromptInjectionDetector(_PI_DETECTOR_CONFIG)

    redactions = []

    all_patterns = (
        detector._compiled_critical
        + detector._compiled_documentation
        + detector._compiled_jailbreak
        + detector._compiled_suspicious
    )

    redacted_regions = []
    replacements = []

    for pattern in all_patterns:
        for match in pattern.finditer(text):
            start, end = match.span()

            if any(
                rs <= start < re_ or rs < end <= re_ for rs, re_ in redacted_regions
            ):
                continue

            redacted_regions.append((start, end))
            replacements.append((start, end, match.group(0)))
            redactions.append(
                {
                    "type": "prompt_injection",
                    "matched_text": match.group(0)[:80],
                    "pattern": pattern.pattern[:60],
                }
            )

    for start, end, original in sorted(replacements, key=lambda x: x[0], reverse=True):
        text = text[:start] + "[SANITIZED]" + text[end:]

    return text, redactions


def sanitize_text(
    text: str, no_secrets: bool = False, no_pii: bool = False, no_threats: bool = False
) -> Dict:
    """
    Sanitize text by redacting secrets, PII, and threats.

    Args:
        text: Input text to sanitize
        no_secrets: Skip secret pattern redaction
        no_pii: Skip PII pattern redaction
        no_threats: Skip prompt injection and unicode attack neutralization

    Returns:
        Dict with sanitized_text, redactions list, and stats
    """
    if not text:
        return {
            "sanitized_text": "",
            "redactions": [],
            "stats": {
                "secrets": 0,
                "pii": 0,
                "prompt_injection": 0,
                "unicode": 0,
                "total": 0,
            },
        }

    sanitized = text
    all_redactions: List[Dict] = []
    stats = {"secrets": 0, "pii": 0, "prompt_injection": 0, "unicode": 0}

    # 1. Unicode attacks (strip invisible chars before pattern matching)
    if not no_threats:
        sanitized, unicode_changes = _sanitize_unicode(sanitized)
        stats["unicode"] = len(unicode_changes)
        all_redactions.extend(unicode_changes)

    # 2. Secrets + PII (via SecretRedactor)
    if not no_secrets or not no_pii:
        from ai_guardian.scanners.secret_redactor import SecretRedactor

        config = get_sanitize_config()

        pii_config = config["scan_pii"] if not no_pii else {"enabled": False}

        redactor = SecretRedactor(
            config={"enabled": True},
            pii_config=pii_config,
            pii_only=no_secrets,
        )

        result = redactor.redact(sanitized)
        sanitized = result["redacted_text"]

        for r in result.get("redactions", []):
            rtype = r.get("type", "")
            is_pii = rtype in _PII_TYPES
            if is_pii:
                stats["pii"] += 1
            else:
                stats["secrets"] += 1
            all_redactions.append(r)

    # 3. Prompt injection (detect and replace)
    if not no_threats:
        sanitized, pi_redactions = _sanitize_prompt_injection(sanitized)
        stats["prompt_injection"] = len(pi_redactions)
        all_redactions.extend(pi_redactions)

    stats["total"] = sum(stats.values())

    return {
        "sanitized_text": sanitized,
        "redactions": all_redactions,
        "stats": stats,
    }


def sanitize_text_batch(texts: List[str]) -> List[str]:
    """Batch-sanitize texts, reusing compiled patterns across all entries.

    Creates one ``SecretRedactor`` and one ``PromptInjectionDetector`` instance
    and applies them to every text, avoiding repeated TOML loads and regex
    compilations.  Returns sanitized strings in the same order as *texts*.
    """
    if not texts:
        return []

    from ai_guardian.scanners.prompt_injection import PromptInjectionDetector
    from ai_guardian.scanners.secret_redactor import SecretRedactor

    config = get_sanitize_config()
    redactor = SecretRedactor(
        config={"enabled": True},
        pii_config=config["scan_pii"],
    )
    detector = PromptInjectionDetector(_PI_DETECTOR_CONFIG)

    results = []
    for text in texts:
        if not text:
            results.append(text)
            continue

        sanitized = text

        sanitized, _ = _sanitize_unicode(sanitized)

        redact_result = redactor.redact(sanitized)
        sanitized = redact_result["redacted_text"]

        sanitized, _ = _sanitize_prompt_injection(sanitized, detector=detector)

        results.append(sanitized)

    return results


def _write_bytes(data: bytes, output_path: Optional[str]) -> None:
    """Write bytes to a file or stdout."""
    if output_path:
        with open(output_path, "wb") as f:
            f.write(data)
    else:
        sys.stdout.buffer.write(data)


_TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".txt",
    ".cfg",
    ".ini",
    ".toml",
    ".xml",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".bat",
    ".ps1",
    ".rb",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".env",
    ".properties",
    ".csv",
    ".tsv",
    ".log",
    ".conf",
    ".dockerfile",
    ".tf",
    ".hcl",
    ".r",
    ".R",
    ".swift",
    ".kt",
    ".scala",
    ".pl",
    ".pm",
    ".lua",
    ".ex",
    ".exs",
    ".erl",
    ".hs",
    ".ml",
    ".clj",
    ".vim",
    ".el",
    ".cmake",
    ".gradle",
    ".sbt",
    ".rake",
    ".gemspec",
    ".podspec",
    ".graphql",
    ".proto",
    ".rst",
    ".adoc",
    ".tex",
    ".bib",
}

_TEXT_FILENAMES = {
    "Makefile",
    "Dockerfile",
    "Jenkinsfile",
    "Vagrantfile",
    "Rakefile",
    "Gemfile",
    "Procfile",
    "Brewfile",
    "Taskfile",
    ".gitignore",
    ".dockerignore",
    ".editorconfig",
    ".eslintrc",
    ".prettierrc",
    ".babelrc",
    ".npmrc",
    ".yarnrc",
    ".flake8",
    ".pylintrc",
    ".rubocop.yml",
}

_SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".eggs",
    "dist",
    "build",
}


def _is_text_file(file_path: Path) -> bool:
    """Check if a file is a known text file by extension or name."""
    if file_path.name in _TEXT_FILENAMES:
        return True
    return file_path.suffix.lower() in _TEXT_EXTENSIONS


def _is_image_file(file_path: Path) -> bool:
    """Check if a file is an image (guarded for missing OCR deps)."""
    try:
        from ai_guardian.scanners.image_scanner import ImageDetector

        return ImageDetector.is_image_file(str(file_path))
    except ImportError:
        return False


def _matches_patterns(rel_path: str, filename: str, patterns: List[str]) -> bool:
    """Check if a file matches any of the given glob patterns."""
    for pattern in patterns:
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(filename, pattern):
            return True
    return False


def sanitize_directory(
    input_dir: Path,
    output_dir: Path,
    no_secrets: bool = False,
    no_pii: bool = False,
    no_threats: bool = False,
    no_images: bool = False,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
    redact_strategy: str = "blackout",
) -> Dict:
    """
    Sanitize all files in a directory, writing redacted output to output_dir.

    Preserves directory structure. Text files are redacted, image files are
    OCR-scanned and redacted (unless no_images), binary files are copied as-is.

    Returns:
        Summary dict with file counts, redaction stats, per-file details, and errors.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    text_count = 0
    image_count = 0
    binary_count = 0
    skipped_count = 0
    total_stats = {"secrets": 0, "pii": 0, "prompt_injection": 0, "unicode": 0}
    file_details: List[Dict] = []
    errors: List[str] = []

    for dirpath, dirnames, filenames in os.walk(input_dir):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for filename in sorted(filenames):
            file_path = Path(dirpath) / filename

            if file_path.is_symlink():
                skipped_count += 1
                continue

            rel_path = file_path.relative_to(input_dir)
            rel_str = str(rel_path)

            if exclude and _matches_patterns(rel_str, filename, exclude):
                skipped_count += 1
                continue

            if include and not _matches_patterns(rel_str, filename, include):
                skipped_count += 1
                continue

            dest = output_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)

            try:
                is_image = not no_images and _is_image_file(file_path)
                is_text = _is_text_file(file_path)

                if is_image:
                    stats = _sanitize_image_to_path(
                        str(file_path),
                        str(dest),
                        no_secrets=no_secrets,
                        no_pii=no_pii,
                        no_threats=no_threats,
                        redact_strategy=redact_strategy,
                    )
                    image_count += 1
                    for key in ("secrets", "pii", "prompt_injection", "unicode"):
                        total_stats[key] += stats.get(key, 0)
                    file_redactions = sum(
                        stats.get(k, 0)
                        for k in ("secrets", "pii", "prompt_injection", "unicode")
                    )
                    if file_redactions > 0:
                        file_details.append(
                            {
                                "file": rel_str,
                                "redactions": file_redactions,
                                "type": "image",
                            }
                        )

                elif is_text:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    result = sanitize_text(
                        content,
                        no_secrets=no_secrets,
                        no_pii=no_pii,
                        no_threats=no_threats,
                    )
                    dest.write_text(result["sanitized_text"], encoding="utf-8")
                    text_count += 1
                    stats = result["stats"]
                    for key in ("secrets", "pii", "prompt_injection", "unicode"):
                        total_stats[key] += stats.get(key, 0)
                    if stats["total"] > 0:
                        file_details.append(
                            {
                                "file": rel_str,
                                "redactions": stats["total"],
                                "type": "text",
                            }
                        )

                else:
                    shutil.copy2(str(file_path), str(dest))
                    binary_count += 1

            except Exception as e:
                errors.append(f"{rel_str}: {e}")

    total_redactions = sum(total_stats.values())
    return {
        "text_files": text_count,
        "image_files": image_count,
        "binary_files": binary_count,
        "skipped_files": skipped_count,
        "total_redactions": total_stats,
        "total_redaction_count": total_redactions,
        "file_details": file_details,
        "errors": errors,
    }


def _sanitize_image_to_path(
    input_path: str,
    output_path: str,
    no_secrets: bool = False,
    no_pii: bool = False,
    no_threats: bool = False,
    redact_strategy: str = "blackout",
) -> Dict:
    """Sanitize an image file writing to output_path. Returns stats dict."""
    try:
        from ai_guardian.scanners.image_scanner import (
            ImageRedactor,
            scan_image,
            TextRegion,
        )
    except ImportError:
        shutil.copy2(input_path, output_path)
        return {"secrets": 0, "pii": 0, "prompt_injection": 0, "unicode": 0}

    try:
        with open(input_path, "rb") as f:
            image_data = f.read()
    except Exception:
        shutil.copy2(input_path, output_path)
        return {"secrets": 0, "pii": 0, "prompt_injection": 0, "unicode": 0}

    img_config = {"min_confidence": 0.5, "max_image_size_mb": 50, "qr_scanning": True}
    result = scan_image(image_data, img_config)

    stats = {"secrets": 0, "pii": 0, "prompt_injection": 0, "unicode": 0}

    if not result.text_regions:
        _write_bytes(image_data, output_path)
        return stats

    regions_to_redact: List = []
    for region in result.text_regions:
        san = sanitize_text(
            region.text, no_secrets=no_secrets, no_pii=no_pii, no_threats=no_threats
        )
        if san["stats"]["total"] > 0:
            regions_to_redact.append(region)
            for key in ("secrets", "pii", "prompt_injection", "unicode"):
                stats[key] += san["stats"][key]

    for qr_text in result.qr_texts:
        san = sanitize_text(
            qr_text, no_secrets=no_secrets, no_pii=no_pii, no_threats=no_threats
        )
        for key in ("secrets", "pii", "prompt_injection", "unicode"):
            stats[key] += san["stats"][key]

    if not regions_to_redact:
        _write_bytes(image_data, output_path)
        return stats

    ext = os.path.splitext(input_path)[1].lower()
    fmt_map = {
        ".png": "PNG",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".bmp": "BMP",
        ".tiff": "TIFF",
        ".tif": "TIFF",
        ".webp": "WEBP",
        ".gif": "GIF",
    }
    output_format = fmt_map.get(ext, "PNG")

    redactor = ImageRedactor(method=redact_strategy)
    redacted_bytes = redactor.redact_regions(
        image_data, regions_to_redact, output_format=output_format
    )
    _write_bytes(redacted_bytes, output_path)

    return stats


def _sanitize_image(input_path: str, args) -> int:
    """Sanitize an image file: OCR text regions, redact those containing secrets/PII."""
    try:
        from ai_guardian.scanners.image_scanner import (
            ImageRedactor,
            OCREngine,
            scan_image,
            TextRegion,
        )
    except ImportError:
        print(
            "Error: Image scanning dependencies not available (rapidocr-onnxruntime, Pillow).",
            file=sys.stderr,
        )
        return 1

    try:
        with open(input_path, "rb") as f:
            image_data = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        return 1

    img_config = {"min_confidence": 0.5, "max_image_size_mb": 50, "qr_scanning": True}
    result = scan_image(image_data, img_config)

    output_path = getattr(args, "output", None)

    if not result.text_regions:
        _write_bytes(image_data, output_path)
        if args.summary:
            msg = "No text detected in image — output unchanged"
            if output_path:
                msg += f" (copied to {output_path})"
            print(msg, file=sys.stderr)
        return 0

    regions_to_redact: List[TextRegion] = []
    total_stats = {
        "secrets": 0,
        "pii": 0,
        "prompt_injection": 0,
        "unicode": 0,
        "total": 0,
    }

    for region in result.text_regions:
        san = sanitize_text(
            region.text,
            no_secrets=args.no_secrets,
            no_pii=args.no_pii,
            no_threats=args.no_threats,
        )
        if san["stats"]["total"] > 0:
            regions_to_redact.append(region)
            for key in ("secrets", "pii", "prompt_injection", "unicode"):
                total_stats[key] += san["stats"][key]

    for qr_text in result.qr_texts:
        san = sanitize_text(
            qr_text,
            no_secrets=args.no_secrets,
            no_pii=args.no_pii,
            no_threats=args.no_threats,
        )
        if san["stats"]["total"] > 0:
            for key in ("secrets", "pii", "prompt_injection", "unicode"):
                total_stats[key] += san["stats"][key]

    total_stats["total"] = sum(
        total_stats[k] for k in ("secrets", "pii", "prompt_injection", "unicode")
    )

    if not regions_to_redact:
        _write_bytes(image_data, output_path)
        if args.summary:
            msg = "No redactions needed"
            if output_path:
                msg += f" (copied to {output_path})"
            print(msg, file=sys.stderr)
        return 0

    import os

    ext = os.path.splitext(input_path)[1].lower()
    fmt_map = {
        ".png": "PNG",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".bmp": "BMP",
        ".tiff": "TIFF",
        ".tif": "TIFF",
        ".webp": "WEBP",
        ".gif": "GIF",
    }
    output_format = fmt_map.get(ext, "PNG")

    strategy = getattr(args, "redact_strategy", "blackout") or "blackout"
    redactor = ImageRedactor(method=strategy)
    redacted_bytes = redactor.redact_regions(
        image_data, regions_to_redact, output_format=output_format
    )

    _write_bytes(redacted_bytes, output_path)

    if args.summary:
        parts = []
        if total_stats["secrets"]:
            parts.append(f"{total_stats['secrets']} secret(s)")
        if total_stats["pii"]:
            parts.append(f"{total_stats['pii']} PII item(s)")
        if total_stats["prompt_injection"]:
            parts.append(f"{total_stats['prompt_injection']} prompt injection(s)")
        if total_stats["unicode"]:
            parts.append(f"{total_stats['unicode']} unicode threat(s)")
        print(
            f"Sanitized image: {len(regions_to_redact)} region(s) redacted — {', '.join(parts)}",
            file=sys.stderr,
        )

    if args.exit_code and total_stats["total"] > 0:
        return 1
    return 0


def _sanitize_directory_command(args) -> int:
    """Handle the sanitize CLI command when input is a directory."""
    input_dir = Path(args.input).resolve()

    output_dir_str = getattr(args, "output_dir", None)
    if not output_dir_str:
        print(
            "Error: --output-dir is required when input is a directory.",
            file=sys.stderr,
        )
        return 1

    output_file = getattr(args, "output", None)
    if output_file:
        print(
            "Error: Use --output-dir (not -o/--output) for directory input.",
            file=sys.stderr,
        )
        return 1

    output_dir = Path(output_dir_str).resolve()

    try:
        output_dir.relative_to(input_dir)
        print(
            "Error: Output directory cannot be inside the input directory.",
            file=sys.stderr,
        )
        return 1
    except ValueError:
        pass  # intentionally silent — invalid value uses default

    force = getattr(args, "force", False)
    if output_dir.exists() and not force:
        print(f"Error: Output directory already exists: {output_dir}", file=sys.stderr)
        print("Use --force to write to an existing directory.", file=sys.stderr)
        return 1

    result = sanitize_directory(
        input_dir=input_dir,
        output_dir=output_dir,
        no_secrets=args.no_secrets,
        no_pii=args.no_pii,
        no_threats=args.no_threats,
        no_images=getattr(args, "no_images", False),
        include=getattr(args, "include", None),
        exclude=getattr(args, "exclude", None),
        redact_strategy=getattr(args, "redact_strategy", "blackout") or "blackout",
    )

    if args.summary:
        total = result["text_files"] + result["image_files"] + result["binary_files"]
        print(f"\nSanitized {total} files:", file=sys.stderr)

        text_redactions = sum(
            d["redactions"] for d in result["file_details"] if d["type"] == "text"
        )
        img_redactions = sum(
            d["redactions"] for d in result["file_details"] if d["type"] == "image"
        )
        print(
            f"  Text files: {result['text_files']} ({text_redactions} redactions)",
            file=sys.stderr,
        )
        if result["image_files"] > 0:
            print(
                f"  Image files: {result['image_files']} ({img_redactions} redactions)",
                file=sys.stderr,
            )
        if result["binary_files"] > 0:
            print(
                f"  Binary files: {result['binary_files']} (copied as-is)",
                file=sys.stderr,
            )
        if result["skipped_files"] > 0:
            print(f"  Skipped: {result['skipped_files']}", file=sys.stderr)
        print(f"Output: {output_dir}/", file=sys.stderr)

        if result["file_details"]:
            print(file=sys.stderr)
            for detail in result["file_details"]:
                if detail["type"] == "image":
                    _labels = {
                        "blur": "blurred",
                        "blackout": "blacked out",
                        "pixelate": "pixelated",
                    }
                    strategy = (
                        getattr(args, "redact_strategy", "blackout") or "blackout"
                    )
                    rtype = f"regions {_labels.get(strategy, 'redacted')}"
                else:
                    rtype = "redacted"
                print(
                    f"  {detail['file']:<40} ({detail['redactions']} {rtype})",
                    file=sys.stderr,
                )

        if result["errors"]:
            print(f"\nErrors ({len(result['errors'])}):", file=sys.stderr)
            for err in result["errors"]:
                print(f"  {err}", file=sys.stderr)

    if args.exit_code and result["total_redaction_count"] > 0:
        return 1

    return 0


def sanitize_command(args) -> int:
    """
    Handle the sanitize CLI command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 = clean or redacted, 1 = redactions found with --exit-code)
    """
    # Suppress all logging — stdout must be only the sanitized text
    logging.disable(logging.CRITICAL)

    # Directory input — delegate to directory handler
    if hasattr(args, "input") and args.input and Path(args.input).is_dir():
        return _sanitize_directory_command(args)

    # Reject --output-dir for single file input
    if getattr(args, "output_dir", None):
        print(
            "Error: --output-dir is only valid when input is a directory.",
            file=sys.stderr,
        )
        return 1

    # Check if input is an image file
    if hasattr(args, "input") and args.input:
        try:
            from ai_guardian.scanners.image_scanner import ImageDetector

            if ImageDetector.is_image_file(args.input):
                return _sanitize_image(args.input, args)
        except ImportError:
            pass  # intentionally silent — optional dependency

    # Read input
    if hasattr(args, "input") and args.input:
        try:
            with open(args.input, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except FileNotFoundError:
            print(f"Error: File not found: {args.input}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            return 1
    else:
        if sys.stdin.isatty():
            print(
                "Error: No input provided. Pipe text via stdin or provide a file argument.",
                file=sys.stderr,
            )
            print("Usage: echo 'text' | ai-guardian sanitize", file=sys.stderr)
            print("   or: ai-guardian sanitize <file>", file=sys.stderr)
            return 1
        text = sys.stdin.read()

    result = sanitize_text(
        text,
        no_secrets=args.no_secrets,
        no_pii=args.no_pii,
        no_threats=args.no_threats,
    )

    # Write sanitized text to output file or stdout
    output_path = getattr(args, "output", None)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result["sanitized_text"])
    else:
        sys.stdout.write(result["sanitized_text"])

    # stderr: optional summary
    if args.summary:
        stats = result["stats"]
        if stats["total"] > 0:
            parts = []
            if stats["secrets"]:
                parts.append(f"{stats['secrets']} secret(s)")
            if stats["pii"]:
                parts.append(f"{stats['pii']} PII item(s)")
            if stats["prompt_injection"]:
                parts.append(f"{stats['prompt_injection']} prompt injection(s)")
            if stats["unicode"]:
                parts.append(f"{stats['unicode']} unicode threat(s)")
            print(f"Sanitized: {', '.join(parts)}", file=sys.stderr)
        else:
            print("No redactions needed", file=sys.stderr)

    # exit code
    if args.exit_code and result["stats"]["total"] > 0:
        return 1

    return 0
