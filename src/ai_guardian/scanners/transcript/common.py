"""Shared transcript scanning utilities.

Position tracking, dedup, fingerprinting, core scanning, and violation logging
used by all TranscriptAdapter implementations.
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple

from ai_guardian.config.utils import get_project_dir, get_state_dir, is_feature_enabled
from ai_guardian.constants import HookEvent, ViolationType
from ai_guardian.scanners.secret_scanning import check_secrets

import ai_guardian.scanners.secret_scanning as _secret_scanning_mod

logger = logging.getLogger(__name__)

try:
    from ai_guardian.violations.logger import ViolationLogger

    HAS_VIOLATION_LOGGER = True
except ImportError:
    HAS_VIOLATION_LOGGER = False


# ---------------------------------------------------------------------------
# Hook data extraction
# ---------------------------------------------------------------------------


def _get_transcript_path(hook_data: dict):
    """Extract transcript path from hook data across IDE types."""
    for field in (
        "transcript_path",
        "transcriptPath",
        "transcript",
        "conversation_path",
    ):
        path = hook_data.get(field)
        if path and isinstance(path, str):
            return path
    return None


# ---------------------------------------------------------------------------
# Position tracking
# ---------------------------------------------------------------------------


def _prune_stale_keys(data: dict) -> dict:
    """Remove entries whose keys are plain file paths that no longer exist.

    Prefixed keys (containing ``:``) are kept unconditionally.
    """
    return {k: v for k, v in data.items() if ":" in k or os.path.exists(k)}


def _load_transcript_positions() -> Dict[str, object]:
    """Load transcript scanning positions from state dir.

    Values are ints (byte offsets / timestamps) for JSONL and OpenCode,
    or lists of bubble-ID strings for Cursor.
    """
    state_dir = get_state_dir()
    pos_file = state_dir / "transcript_positions.json"
    try:
        with open(pos_file, "r", encoding="utf-8") as f:
            positions = json.load(f)
        if isinstance(positions, dict):
            return positions
    except FileNotFoundError:
        pass  # intentionally silent — file may not exist yet
    except Exception as e:
        logger.debug(f"Failed to load transcript positions: {e}")
    return {}


def _save_transcript_positions(positions: Dict[str, object]) -> None:
    """Save transcript scanning positions to state dir.

    Uses tempfile + ``os.replace`` for atomic write so a crash mid-write
    never leaves a truncated positions file.
    """
    import tempfile as _tf

    state_dir = get_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    pos_file = state_dir / "transcript_positions.json"
    try:
        fd, tmp_path = _tf.mkstemp(
            dir=str(state_dir), prefix=".transcript-pos-", suffix=".tmp"
        )
        closed = False
        try:
            os.write(fd, json.dumps(positions).encode("utf-8"))
            os.close(fd)
            closed = True
            os.replace(tmp_path, str(pos_file))
        except BaseException:
            if not closed:
                os.close(fd)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    except Exception as e:
        logger.debug(f"Failed to save transcript positions: {e}")


def _scan_with_position_tracking(
    pos_key: str,
    reader_fn: Callable,
    default_position: object = 0,
    init_position_fn: Optional[Callable] = None,
    label: str = "Transcript",
) -> str:
    """Handle position loading/saving for incremental transcript scanning.

    Args:
        pos_key: Key for position tracking (e.g., ``"cline:<task_id>"``).
        reader_fn: ``(last_position) -> (combined_text, new_position)``.
        default_position: Initial position passed to *reader_fn* on first
            scan when *init_position_fn* is not provided.
        init_position_fn: Optional ``() -> initial_position``.  When given,
            called on first scan instead of *reader_fn* to seed the position
            without reading content.
        label: Human-readable adapter name for debug logging.

    Returns:
        Combined text from new content, or ``""`` when there is nothing to
        scan (first scan or no new data).  Position is persisted
        automatically whenever it changes.
    """
    positions = _load_transcript_positions()

    if pos_key not in positions:
        if init_position_fn is not None:
            positions[pos_key] = init_position_fn()
        else:
            _, new_pos = reader_fn(default_position)
            positions[pos_key] = new_pos
        _save_transcript_positions(positions)
        logger.debug(f"{label} transcript first seen, initialized position")
        return ""

    last_pos = positions[pos_key]
    combined_text, new_pos = reader_fn(last_pos)

    if new_pos != last_pos:
        positions[pos_key] = new_pos
        _save_transcript_positions(positions)

    return combined_text


# ---------------------------------------------------------------------------
# Path discovery
# ---------------------------------------------------------------------------


def _get_most_recent_entry(
    directory: str,
    match_fn: Callable[[os.DirEntry], bool],
    label: str = "Transcript",
    mtime_fn: Optional[Callable[[os.DirEntry], float]] = None,
) -> Optional[Tuple[str, float]]:
    """Find the most recently modified entry in *directory* matching *match_fn*.

    Args:
        directory: Directory to scan with :func:`os.scandir`.
        match_fn: Predicate receiving an :class:`os.DirEntry`; return ``True``
            for entries that should be considered.
        label: Human-readable name for debug logging.
        mtime_fn: Optional function to extract mtime from a matched entry.
            Defaults to ``entry.stat().st_mtime``.

    Returns:
        ``(path, mtime)`` of the most recently modified matching entry,
        or ``None``.
    """
    best_mtime = -1.0
    best_path: Optional[str] = None
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if not match_fn(entry):
                    continue
                try:
                    mtime = mtime_fn(entry) if mtime_fn else entry.stat().st_mtime
                except OSError:
                    continue
                if mtime > best_mtime:
                    best_mtime = mtime
                    best_path = entry.path
    except OSError as e:
        logger.debug(f"{label} directory listing error: {e}")
        return None

    if best_path is None:
        return None
    return best_path, best_mtime


def _discover_path(
    env_var: str,
    default: str,
    check: Callable[[str], bool] = os.path.isdir,
    env_suffix: str = "",
) -> Optional[str]:
    """Discover a storage path via environment variable or platform default.

    Args:
        env_var: Environment variable to check first.
        default: Default path (expanded with :func:`os.path.expanduser`).
        check: Validation function (e.g., :func:`os.path.isdir`).
        env_suffix: Filename appended to the env-var value via
            :func:`os.path.join`.
    """
    custom = os.environ.get(env_var)
    if custom:
        path = os.path.join(custom, env_suffix) if env_suffix else custom
        if check(path):
            return path

    expanded = os.path.expanduser(default)
    if check(expanded):
        return expanded

    return None


# ---------------------------------------------------------------------------
# Shared JSONL incremental reader
# ---------------------------------------------------------------------------


def _read_jsonl_incremental(
    path: str,
    last_pos: int,
    extract_fn: Callable[[dict], str],
    label: str = "Transcript",
    strip_bom: bool = False,
) -> Tuple[str, int]:
    """Read a JSONL transcript file incrementally using byte-offset tracking.

    Uses ``f.seek()`` for O(1) skip to new content regardless of file size.
    Detects truncation via file-size comparison.

    Args:
        path: Path to the JSONL file.
        last_pos: Byte offset of the last read position.
        extract_fn: Per-adapter callable that extracts scannable text from
            a parsed JSON dict.
        label: Human-readable adapter name for debug logging.
        strip_bom: Strip a leading UTF-8 BOM when reading from offset 0.

    Returns:
        Tuple of (combined_new_text, new_byte_position).
    """
    try:
        file_size = os.path.getsize(path)
    except OSError as e:
        logger.debug(f"{label} transcript read error: {e}")
        return "", last_pos

    if file_size < last_pos:
        logger.debug(
            f"{label} transcript file truncated (size={file_size}, "
            f"last_pos={last_pos}), re-reading from start"
        )
        last_pos = 0

    if file_size <= last_pos:
        return "", last_pos

    try:
        with open(path, "rb") as f:
            f.seek(last_pos)
            new_bytes = f.read()
            new_pos = f.tell()
    except OSError as e:
        logger.debug(f"{label} transcript read error: {e}")
        return "", last_pos

    if strip_bom and last_pos == 0:
        new_bytes = new_bytes.removeprefix(b"\xef\xbb\xbf")

    new_content = new_bytes.decode("utf-8", errors="replace")

    texts = []
    for raw_line in new_content.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        extracted = extract_fn(entry)
        if extracted:
            texts.append(extracted)

    return "\n".join(texts), new_pos


# ---------------------------------------------------------------------------
# Shared JSONL scan orchestrator
# ---------------------------------------------------------------------------


def _scan_jsonl_incremental(
    transcript_path: str,
    pos_key: str,
    extract_fn: Callable[[dict], str],
    label: str = "Transcript",
    strip_bom: bool = False,
    secret_config: Optional[Dict] = None,
    pii_config: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    allowed_findings: Optional[set] = None,
) -> list:
    """Orchestrate incremental JSONL transcript scanning.

    Composes position tracking, JSONL reading, and content scanning into
    a single call.  Used by all JSONL-based transcript adapters.
    """
    combined_text = _scan_with_position_tracking(
        pos_key,
        reader_fn=lambda last_pos: _read_jsonl_incremental(
            transcript_path, last_pos, extract_fn, label, strip_bom
        ),
        init_position_fn=lambda: os.path.getsize(transcript_path),
        label=label,
    )

    if not combined_text:
        return []

    return _scan_transcript_text(
        combined_text,
        pos_key,
        secret_config,
        pii_config,
        hook_context,
        allowed_findings=allowed_findings,
    )


# ---------------------------------------------------------------------------
# Seen-findings dedup
# ---------------------------------------------------------------------------


def _load_seen_findings() -> Dict[str, Dict[str, str]]:
    """Load seen transcript findings from state dir.

    Returns:
        Dict mapping transcript keys to dicts of {fingerprint: iso_timestamp}.
    """
    state_dir = get_state_dir()
    sf_file = state_dir / "transcript_seen_findings.json"
    try:
        with open(sf_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass  # intentionally silent — file may not exist yet
    except Exception as e:
        logger.debug(f"Failed to load seen findings: {e}")
    return {}


def _save_seen_findings(seen: Dict[str, Dict[str, str]]) -> None:
    """Save seen transcript findings to state dir.

    Prunes stale file-path keys opportunistically (only called on dirty saves).
    """
    state_dir = get_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    sf_file = state_dir / "transcript_seen_findings.json"
    try:
        pruned = _prune_stale_keys(seen)
        with open(sf_file, "w", encoding="utf-8") as f:
            json.dump(pruned, f)
    except Exception as e:
        logger.debug(f"Failed to save seen findings: {e}")


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------


def _finding_fingerprint(finding_type: str, detail: str) -> str:
    # ai-guardian:begin-allow
    """Compute a short hash fingerprint for a transcript finding.

    Args:
        finding_type: Category such as "pii" or "secret"
        detail: Type-specific detail (e.g. "SSN:078-05-1120" or rule_id)

    Returns:
        First 16 hex chars of SHA-256 digest.
    """
    # ai-guardian:end-allow
    return hashlib.sha256(f"{finding_type}:{detail}".encode()).hexdigest()[:16]


def _extract_secret_type_from_error(error_msg: str) -> str:
    """Extract the secret type (rule_id) from a scanner error message."""
    match = re.search(r"Secret Type:\s*(.+)", error_msg)
    if match:
        return match.group(1).strip()
    return "unknown"


# ---------------------------------------------------------------------------
# Core scanning
# ---------------------------------------------------------------------------


def _scan_transcript_text(
    combined_text: str,
    transcript_key: str,
    secret_config: Optional[Dict] = None,
    pii_config: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    allowed_findings: Optional[set] = None,
) -> list:
    """Scan combined text for secrets and PII with deduplication.

    Shared by all transcript adapter implementations.

    Args:
        combined_text: Concatenated transcript text to scan.
        transcript_key: Key for dedup tracking (file path or prefixed ID).
        secret_config: Secret scanning config.
        pii_config: PII scanning config.
        hook_context: Optional context with session_id for correlation.
        allowed_findings: Optional set of fingerprints to skip.

    Returns:
        List of warning message strings.
    """
    warnings = []

    seen_all = _load_seen_findings()
    seen = seen_all.get(transcript_key, {})
    seen_count = len(seen)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # --- Secret scanning ---
    if secret_config is None or is_feature_enabled(
        secret_config.get("enabled") if secret_config else None,
        now,
        default=True,
    ):
        try:
            secret_allowlist = (
                secret_config.get("allowlist_patterns", []) if secret_config else []
            )
            has_secrets, secret_error = check_secrets(
                combined_text,
                "transcript",
                context={"ide_type": "transcript_scan", "hook_event": HookEvent.PROMPT},
                allowlist_patterns=secret_allowlist,
            )
            if has_secrets and secret_error:
                per_findings = _secret_scanning_mod._last_secret_findings or []
                if per_findings:
                    new_findings = []
                    for finding in per_findings:
                        rule_id = getattr(
                            finding, "rule_id", ""
                        ) or _extract_secret_type_from_error(secret_error)
                        fp = _finding_fingerprint("secret", rule_id)
                        if fp not in seen and fp not in (allowed_findings or ()):
                            new_findings.append((fp, rule_id))
                            seen[fp] = now_iso
                    if new_findings:
                        count = len(new_findings)
                        types = list(dict.fromkeys(r for _, r in new_findings))
                        noun = "SECRET" if count == 1 else "SECRETS"
                        verb = "was" if count == 1 else "were"
                        type_line = (
                            f"Type{'s' if count > 1 else ''}: {', '.join(types)}\n"
                            if types
                            else ""
                        )
                        warning_msg = (
                            f"\n{'='*70}\n"
                            f"🔍 {count} {noun} DETECTED IN CONVERSATION TRANSCRIPT\n"
                            f"{'='*70}\n"
                            f"{count} secret(s) {verb} found in your conversation history\n"
                            f"{type_line}"
                            f"(possibly from a ! shell command).\n"
                            f"The secret(s) have already been sent to the AI model.\n"
                            f"Recommended actions:\n"
                            f"  1. Rotate the exposed credential(s) immediately\n"
                            f"  2. Start a new session to limit further exposure\n"
                            f"  3. Review your shell history for other leaked secrets\n"
                            f"{'='*70}\n"
                        )
                        warnings.append(warning_msg)
                        _log_transcript_violation(
                            ViolationType.SECRET_IN_TRANSCRIPT,
                            transcript_key,
                            details={
                                "reason": secret_error,
                                "count": count,
                                "types": types,
                            },
                            hook_context=hook_context,
                        )
                else:
                    fp = _finding_fingerprint(
                        "secret", _extract_secret_type_from_error(secret_error)
                    )
                    if fp not in seen and fp not in (allowed_findings or ()):
                        warning_msg = (
                            f"\n{'='*70}\n"
                            f"🔍 SECRET DETECTED IN CONVERSATION TRANSCRIPT\n"
                            f"{'='*70}\n"
                            f"A secret was found in your conversation history\n"
                            f"(possibly from a ! shell command).\n"
                            f"The secret has already been sent to the AI model.\n"
                            f"Recommended actions:\n"
                            f"  1. Rotate the exposed credential immediately\n"
                            f"  2. Start a new session to limit further exposure\n"
                            f"  3. Review your shell history for other leaked secrets\n"
                            f"{'='*70}\n"
                        )
                        warnings.append(warning_msg)
                        _log_transcript_violation(
                            ViolationType.SECRET_IN_TRANSCRIPT,
                            transcript_key,
                            details={"reason": secret_error},
                            hook_context=hook_context,
                        )
                        seen[fp] = now_iso
        except Exception as e:
            logger.debug(f"Transcript secret scan error (fail-open): {e}")

    # --- PII scanning ---
    if pii_config and is_feature_enabled(pii_config.get("enabled"), now, default=True):
        try:
            from ai_guardian.hook_processing import _scan_for_pii

            has_pii, _, pii_redactions, _ = _scan_for_pii(combined_text, pii_config)
            if has_pii:
                new_redactions = []
                for r in pii_redactions:
                    pos = r.get("position", 0)
                    length = r.get("original_length", 0)
                    original_value = (
                        combined_text[pos : pos + length]
                        if length
                        else r.get("type", "")
                    )
                    fp = _finding_fingerprint("pii", f"{r['type']}:{original_value}")
                    if fp not in seen and fp not in (allowed_findings or ()):
                        new_redactions.append(r)
                        seen[fp] = now_iso

                if new_redactions:
                    pii_types = list(set(r["type"] for r in new_redactions))
                    warning_msg = (
                        f"\n{'='*70}\n"
                        f"🔍 PII DETECTED IN CONVERSATION TRANSCRIPT\n"
                        f"{'='*70}\n"
                        f"Found {len(new_redactions)} PII item(s): {', '.join(pii_types)}\n"
                        f"(possibly from a ! shell command).\n"
                        f"The PII has already been sent to the AI model.\n"
                        f"Recommended actions:\n"
                        f"  1. Assess the data exposure per your compliance policies\n"
                        f"  2. Start a new session to limit further exposure\n"
                        f"  3. Review your shell history for other leaked PII\n"
                        f"{'='*70}\n"
                    )
                    warnings.append(warning_msg)
                    _log_transcript_violation(
                        ViolationType.PII_IN_TRANSCRIPT,
                        transcript_key,
                        details={
                            "pii_types": pii_types,
                            "pii_count": len(new_redactions),
                        },
                        hook_context=hook_context,
                    )
        except Exception as e:
            logger.debug(f"Transcript PII scan error (fail-open): {e}")

    if len(seen) > seen_count:
        seen_all[transcript_key] = seen
        _save_seen_findings(seen_all)

    return warnings


# ---------------------------------------------------------------------------
# Violation logging
# ---------------------------------------------------------------------------


def _log_transcript_violation(
    violation_type: str,
    transcript_path: str,
    details: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
):
    """Log a violation detected in the conversation transcript."""
    if not HAS_VIOLATION_LOGGER:
        return
    try:
        hctx = hook_context or {}
        blocked_info = {
            "transcript_path": transcript_path,
            "source": "transcript",
        }
        if details:
            blocked_info.update(details)

        violation_ctx = {
            "ide_type": "unknown",
            "hook_event": HookEvent.PROMPT,
            "project_path": get_project_dir(),
        }
        if hctx.get("session_id"):
            violation_ctx["session_id"] = hctx["session_id"]

        from ai_guardian.scanners.scan_result import generate_violation_id

        vid = generate_violation_id()
        blocked_info["violation_id"] = vid
        violation_logger = ViolationLogger()
        violation_logger.log_violation(
            violation_type=violation_type,
            blocked=blocked_info,
            context=violation_ctx,
            suggestion={
                "action": "review_and_remediate",
                "warning": "Sensitive content was detected in the conversation transcript. "
                "It may have been entered via a ! shell command. "
                "The content has already been sent to the AI model. "
                "Rotate any exposed credentials and start a new session.",
            },
            severity="high",
            violation_id=vid,
        )
    except Exception as e:
        logger.error(f"Failed to log transcript violation: {e}")
