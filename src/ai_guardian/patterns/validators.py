"""
Validation functions for pattern matching results.

These validators run post-match to reduce false positives. A regex match
alone may be insufficient — for example, credit card numbers must pass
Luhn checksum, and IBANs must pass mod-97 validation.

Extracted from SecretRedactor for shared use by PatternCache.
"""

import logging
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

logger = logging.getLogger(__name__)


MIN_STOPWORD_LENGTH = 3


def shannon_entropy(text: str) -> float:
    """Calculate Shannon entropy of a string in bits per character.

    Returns 0.0 for empty strings or single-character strings.
    Random alphanumeric strings score ~4.7; repeated characters score 0.0.
    """
    if not text:
        return 0.0
    length = len(text)
    counts = Counter(text)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def luhn_check(number_str: str, min_digits: int = 13, max_digits: int = 19) -> bool:
    """Validate a number string using the Luhn algorithm.

    Args:
        number_str: String containing digits to validate
        min_digits: Minimum digit count (default: 13 for credit cards)
        max_digits: Maximum digit count (default: 19)

    Returns:
        True if the number passes Luhn validation
    """
    digits = [int(d) for d in number_str if d.isdigit()]
    if len(digits) < min_digits or len(digits) > max_digits:
        return False
    checksum = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def iban_check(iban_str: str) -> bool:
    """Validate an IBAN using the mod-97 algorithm.

    Args:
        iban_str: IBAN string to validate

    Returns:
        True if the IBAN passes mod-97 validation
    """
    iban = iban_str.replace(" ", "").upper()
    if len(iban) < 15 or len(iban) > 34:
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = ""
    for ch in rearranged:
        if ch.isdigit():
            numeric += ch
        elif ch.isalpha():
            numeric += str(ord(ch) - ord("A") + 10)
        else:
            return False
    return int(numeric) % 97 == 1


VALID_CC_PREFIXES = (
    "4",
    "51",
    "52",
    "53",
    "54",
    "55",
    "2221",
    "2222",
    "2223",
    "2224",
    "2225",
    "2226",
    "2227",
    "2228",
    "2229",
    "223",
    "224",
    "225",
    "226",
    "227",
    "228",
    "229",
    "23",
    "24",
    "25",
    "26",
    "270",
    "271",
    "2720",
    "34",
    "37",
    "6011",
    "65",
    "644",
    "645",
    "646",
    "647",
    "648",
    "649",
    "35",
    "30",
    "36",
    "38",
    "39",
)


def credit_card_check(number_str: str) -> bool:
    """Validate a credit card number using Luhn + IIN/BIN prefix check.

    Args:
        number_str: String containing digits (may include spaces/dashes)

    Returns:
        True if passes both Luhn checksum AND has a valid card network prefix
    """
    digits_only = re.sub(r"[- ]", "", number_str)
    if not luhn_check(digits_only):
        return False
    if not digits_only.startswith(VALID_CC_PREFIXES):
        return False
    return True


def aadhaar_check(number_str: str) -> bool:
    """Validate an Indian Aadhaar number beyond the regex format check.

    Args:
        number_str: String containing digits with optional spaces/dashes

    Returns:
        True if the number looks like a plausible Aadhaar number
    """
    digits = re.sub(r"[- ]", "", number_str)
    if len(digits) != 12 or not digits.isdigit():
        return False
    if digits[0] in ("0", "1"):
        return False
    if len(set(digits)) == 1:
        return False
    return True


def _is_file_path(value: str, *, allow_single_segment_absolute: bool = False) -> bool:
    """Check if a value looks like a filesystem path."""
    if value.startswith("/") and ("/" in value[1:] or allow_single_segment_absolute):
        return _has_path_like_segments(value.split("/"))
    if (
        len(value) >= 3
        and value[0].isalpha()
        and value[1] == ":"
        and value[2] in ("/", "\\")
    ):
        rest = value[2:].replace("\\", "/")
        return _has_path_like_segments(rest.split("/"))
    if value.startswith("./") or value.startswith("../"):
        return _has_path_like_segments(value.split("/"))
    return False


def _has_path_like_segments(parts: list) -> bool:
    """Check if split path segments look like directory/file names, not base64."""
    for p in parts:
        if p == "" or p in (".", ".."):
            continue
        if not all(c.isalnum() or c in "-_." for c in p):
            return False
    return True


_PLACEHOLDER_RE = re.compile(
    r"^(?:"
    r"(?:your|my|example|replace|insert|enter|put|test|fake|dummy|sample|placeholder|changeme)[-_]"
    r"|"
    r".*[-_](?:here|placeholder|example|changeme)$"
    r")",
    re.IGNORECASE,
)


def _is_placeholder(value: str) -> bool:
    """Check if a value looks like a documentation placeholder."""
    return bool(_PLACEHOLDER_RE.search(value))


_CONTAINER_IMAGE_RE = re.compile(
    r"^(?:localhost|[\w.-]+\.(?:io|com|net|org|dev|cloud|local))"
    r"/[\w./-]+(?::[\w./-]+)?$",
)


def _is_container_image(value: str) -> bool:
    """Check if a value looks like a container image reference."""
    return bool(_CONTAINER_IMAGE_RE.match(value))


_ALL_CAPS_UNDERSCORES_RE = re.compile(r"^[A-Z0-9]+(?:_[A-Z0-9]+)+$")
_ENV_SECRET_NAME_RE = re.compile(
    r"(?:^|_)(?:(?:API|ACCESS|PRIVATE|CLIENT|DB|DATABASE)_?)?"
    r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?|AUTH(?:ORIZATION)?)(?:_|$)",
    re.IGNORECASE,
)
_ENV_NAME_AT_END_RE = re.compile(r"([A-Z][A-Z0-9_]*)\s*$")


def env_not_false_positive(matched_text: str) -> bool:
    """Return False (skip) if the env var value is a filesystem path,
    starts with underscore (Python identifier), looks like a placeholder,
    an ALL_CAPS_IDENTIFIER (programming constant), or is a container
    image reference. Numeric values are skipped unless the variable name
    identifies a credential field.
    """
    eq_pos = matched_text.find("=")
    if eq_pos < 0:
        return True
    name_match = _ENV_NAME_AT_END_RE.search(matched_text[:eq_pos])
    variable_name = name_match.group(1) if name_match else ""
    value = matched_text[eq_pos + 1 :].strip().strip("'\"")
    if not value:
        return True
    if value.isdecimal() and not _ENV_SECRET_NAME_RE.search(variable_name):
        return False
    if value.startswith("_"):
        return False
    if _is_placeholder(value):
        return False
    if _ALL_CAPS_UNDERSCORES_RE.match(value):
        return False
    if _is_container_image(value):
        return False
    return not _is_file_path(value, allow_single_segment_absolute=True)


def password_not_false_positive(matched_text: str) -> bool:
    """Return False (skip) if the password value is a placeholder,
    container image, or file path. Unlike env_not_false_positive, does
    not skip underscore-prefixed or ALL_CAPS values since those could
    be real passwords in explicit password=/secret= fields.
    """
    eq_pos = matched_text.find("=")
    if eq_pos < 0:
        return True
    value = matched_text[eq_pos + 1 :].strip().strip("'\"")
    if not value:
        return True
    if _is_placeholder(value):
        return False
    if _is_container_image(value):
        return False
    return not _is_file_path(value)


_BRACKET_PLACEHOLDER_RE = re.compile(
    r"^\[(?:HIDDEN|REDACTED|PASSWORD|MASKED|REMOVED|SECRET|CENSORED)\]$",
    re.IGNORECASE,
)

_ANGLE_PLACEHOLDER_RE = re.compile(
    r"^<[a-z0-9_-]+>$",
    re.IGNORECASE,
)

_REPEATED_CHAR_RE = re.compile(r"^(.)\1{5,}$")

_CONNECTION_URI_RE = re.compile(
    r"(?:mongodb|mysql|postgres(?:ql)?|redis)://[^:]*:([^@]+)@",
    re.IGNORECASE,
)


def _is_connection_placeholder(password: str) -> bool:
    """Check if a connection string password is a documentation placeholder."""
    if _BRACKET_PLACEHOLDER_RE.match(password):
        return True
    if _ANGLE_PLACEHOLDER_RE.match(password):
        return True
    if _REPEATED_CHAR_RE.match(password):
        return True
    return _is_placeholder(password)


def connection_not_placeholder(matched_text: str) -> bool:
    """Return False (skip) if the connection string password is a placeholder."""
    m = _CONNECTION_URI_RE.search(matched_text)
    if not m:
        return True
    password = m.group(1)
    if _is_connection_placeholder(password):
        return False
    return True


_NEVER_MATCH_RE = re.compile(r"(?!)")


def _build_token_prefix_re() -> re.Pattern:
    """Build token prefix regex from secrets.toml at module load time.

    Collects token prefixes (falling back to keywords) from all rules
    with validation="token_not_placeholder" and compiles them into a
    single alternation anchored at ^.

    Cannot use load_bundled_rules/BUNDLED_FILES here — circular import:
    __init__ → cache → validators → __init__.
    """
    secrets_toml = Path(__file__).parent / "data" / "secrets.toml"
    if not secrets_toml.exists():
        logger.warning("secrets.toml not found; token prefix RE will be empty")
        return _NEVER_MATCH_RE

    try:
        with open(secrets_toml, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        logger.warning(f"Failed to load secrets.toml for token prefixes: {e}")
        return _NEVER_MATCH_RE

    prefixes = [
        kw
        for rule in data.get("rules", [])
        if rule.get("validation") == "token_not_placeholder"
        for kw in (rule.get("token_prefixes") or rule.get("keywords", []))
    ]
    if not prefixes:
        return _NEVER_MATCH_RE

    unique = sorted(set(prefixes), key=len, reverse=True)
    escaped = [re.escape(p) for p in unique]
    return re.compile(r"^(?:" + "|".join(escaped) + ")")


_TOKEN_PREFIX_RE = _build_token_prefix_re()

_REPEATED_CHAR_TOKEN_RE = re.compile(r"^(.)\1{7,}$")

_TEMPLATE_SYNTAX_RE = re.compile(r"<[^>]+>|\$\{[^}]+\}|\{\{[^}]+\}\}")


def _is_token_placeholder(body: str) -> bool:
    """Check if a token body (after prefix) is a documentation placeholder."""
    if not body:
        return False
    if _REPEATED_CHAR_TOKEN_RE.match(body):
        return True
    if _is_placeholder(body):
        return True
    if _ALL_CAPS_UNDERSCORES_RE.match(body):
        return True
    if _TEMPLATE_SYNTAX_RE.search(body):
        return True
    return False


def token_not_placeholder(matched_text: str) -> bool:
    """Return False (skip) if the token value is a placeholder."""
    m = _TOKEN_PREFIX_RE.match(matched_text)
    if not m:
        return True
    body = matched_text[m.end() :]
    if _is_token_placeholder(body):
        return False
    return True


def load_stopwords(config: Optional[Dict] = None) -> List[str]:
    """Load bundled stopwords and merge with user-configured stopwords.

    Args:
        config: Secret scanning config dict (may contain "stopwords" list)

    Returns:
        Deduplicated list of lowercase stopword strings (min length 3)
    """
    from ai_guardian.patterns import BUNDLED_FILES

    stopwords: List[str] = []
    path = BUNDLED_FILES.get("stopwords")
    if path and path.exists():
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            words = data.get("stopwords", {}).get("words", [])
            seen: set = set()
            for w in words:
                if isinstance(w, str) and len(w) >= MIN_STOPWORD_LENGTH:
                    low = w.lower()
                    if low not in seen:
                        seen.add(low)
                        stopwords.append(low)
        except Exception as e:
            logger.warning(f"Failed to load bundled stopwords: {e}")

    if config:
        user_stopwords = config.get("stopwords", [])
        if user_stopwords:
            extra = [
                w.lower()
                for w in user_stopwords
                if isinstance(w, str) and len(w) >= MIN_STOPWORD_LENGTH
            ]
            existing = set(stopwords)
            stopwords.extend(w for w in extra if w not in existing)

    return stopwords


def filter_findings_by_stopwords_entropy(
    secrets: list,
    stopwords: List[str],
    min_entropy: Optional[float] = 3.0,
) -> Tuple[list, int, int]:
    """Filter SecretMatch objects by stopwords and entropy.

    Args:
        secrets: List of SecretMatch objects (with .secret and .category attrs)
        stopwords: Lowercase stopword strings for substring matching
        min_entropy: Minimum Shannon entropy threshold (None to disable)

    Returns:
        (filtered_list, stopword_filtered_count, entropy_filtered_count)
    """
    filtered = []
    sw_count = 0
    ent_count = 0
    for s in secrets:
        matched_text = getattr(s, "secret", None)
        category = getattr(s, "category", "secrets")
        if matched_text and stopwords and category == "secrets":
            matched_lower = matched_text.lower()
            if any(sw in matched_lower for sw in stopwords):
                sw_count += 1
                continue
        if matched_text and min_entropy is not None and category == "secrets":
            if shannon_entropy(matched_text) < min_entropy:
                ent_count += 1
                continue
        filtered.append(s)
    return filtered, sw_count, ent_count


def filter_findings_dicts_by_stopwords_entropy(
    findings: List[Dict],
    stopwords: List[str],
    min_entropy: Optional[float] = 3.0,
) -> Tuple[List[Dict], int, int]:
    """Filter finding dicts by stopwords and entropy.

    Args:
        findings: List of dicts with "matched_text" key
        stopwords: Lowercase stopword strings for substring matching
        min_entropy: Minimum Shannon entropy threshold (None to disable)

    Returns:
        (filtered_list, stopword_filtered_count, entropy_filtered_count)
    """
    filtered = []
    sw_count = 0
    ent_count = 0
    for f in findings:
        matched_text = f.get("matched_text")
        if matched_text and stopwords:
            matched_lower = matched_text.lower()
            if any(sw in matched_lower for sw in stopwords):
                sw_count += 1
                continue
        if matched_text and min_entropy is not None:
            if shannon_entropy(matched_text) < min_entropy:
                ent_count += 1
                continue
        filtered.append(f)
    return filtered, sw_count, ent_count


# --- SHA/Hash false-positive filter (Issue #1378) ---

_HASH_HEX_LENGTHS = frozenset({32, 40, 64, 96, 128})

_HEX_ONLY_RE = re.compile(r"^[a-fA-F0-9]+$")

_HASH_CONTEXT_KEYWORDS = frozenset(
    {
        "sha256",
        "sha512",
        "sha1",
        "sha384",
        "sha-256",
        "sha-512",
        "sha-1",
        "sha-384",
        "md5",
        "checksum",
        "digest",
        "hash",
        "fingerprint",
        "integrity",
        "sha256sum",
        "sha512sum",
        "sha1sum",
        "md5sum",
        "subresource",
        "sri",
    }
)


def is_hash_value(matched_text: str, line_text: Optional[str] = None) -> bool:
    """Check if matched_text is a SHA/MD5 hash value in a hash context.

    Returns True (suppress) when BOTH conditions hold:
    1. matched_text is exactly 32/40/64/96/128 hex characters
    2. The surrounding line contains a hash-related keyword
    """
    if not matched_text:
        return False

    clean = matched_text.strip().strip("'\"")

    # Env-variable patterns capture KEY=VALUE — extract value after =
    if "=" in clean:
        clean = clean.split("=", 1)[1]

    if len(clean) not in _HASH_HEX_LENGTHS:
        return False
    if not _HEX_ONLY_RE.match(clean):
        return False

    if not line_text:
        return False

    line_lower = line_text.lower()
    return any(kw in line_lower for kw in _HASH_CONTEXT_KEYWORDS)


def filter_findings_by_hash(
    secrets: list,
    content: Optional[str] = None,
) -> Tuple[list, int]:
    """Filter SecretMatch objects that are SHA/MD5 hash false positives.

    Returns:
        (filtered_list, hash_filtered_count)
    """
    if not content:
        return secrets, 0

    lines = content.splitlines()
    filtered = []
    hash_count = 0

    for s in secrets:
        matched_text = getattr(s, "secret", None)
        line_number = getattr(s, "line_number", 0)
        category = getattr(s, "category", "secrets")

        if (
            matched_text
            and category in ("secrets", None)
            and 0 < line_number <= len(lines)
        ):
            line_text = lines[line_number - 1]
            if is_hash_value(matched_text, line_text):
                hash_count += 1
                continue

        filtered.append(s)

    return filtered, hash_count


def filter_findings_dicts_by_hash(
    findings: List[Dict],
    content: Optional[str] = None,
) -> Tuple[List[Dict], int]:
    """Filter finding dicts that are SHA/MD5 hash false positives.

    Returns:
        (filtered_list, hash_filtered_count)
    """
    if not content:
        return findings, 0

    lines = content.splitlines()
    filtered = []
    hash_count = 0

    for f in findings:
        matched_text = f.get("matched_text")
        line_number = f.get("line_number", 0) or 0

        if matched_text and 0 < line_number <= len(lines):
            line_text = lines[line_number - 1]
            if is_hash_value(matched_text, line_text):
                hash_count += 1
                continue

        filtered.append(f)

    return filtered, hash_count


_BASE64_CONTEXT_PREFIX_RE = re.compile(
    r"^(?:secret|key|token|password|credential)[\s\"'=:]+",
    re.IGNORECASE,
)


def base64_not_file_path(matched_text: str) -> bool:
    """Return False (skip) if the base64 'secret' part is actually a file path."""
    m = _BASE64_CONTEXT_PREFIX_RE.match(matched_text)
    if m:
        value = matched_text[m.end() :]
    else:
        value = matched_text
    value = value.strip().strip("'\"")
    if not value:
        return True
    return not _is_file_path(value)


VALIDATOR_REGISTRY: dict = {
    "luhn": luhn_check,
    "iban": iban_check,
    "credit_card": credit_card_check,
    "aadhaar": aadhaar_check,
    "env_not_false_positive": env_not_false_positive,
    "env_not_file_path": env_not_false_positive,
    "password_not_false_positive": password_not_false_positive,
    "base64_not_file_path": base64_not_file_path,
    "connection_not_placeholder": connection_not_placeholder,
    "token_not_placeholder": token_not_placeholder,
}


def get_validator(name: str) -> Optional[Callable]:
    """Look up a validator function by name.

    Args:
        name: Validator name as specified in TOML rules (e.g., "luhn", "iban")

    Returns:
        Validator callable, or None if not found
    """
    validator = VALIDATOR_REGISTRY.get(name)
    if validator is None:
        logger.warning(f"Unknown validator: {name}")
    return validator
