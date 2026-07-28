"""
Secret validation — check if detected secrets are still active.

After pattern-match detection, optionally validates secrets against their
provider API to determine if they're still active. This dramatically
reduces false positives for rotated/expired/revoked credentials.

Result categories:
    - verified:   secret is active → block
    - unverified: no validator for this rule ID, or network error → block (current behavior)
    - inactive:   secret is revoked/expired → warn only (configurable)

Privacy note: validation sends the detected secret to the provider's API.
Requires explicit opt-in via secret_scanning.validate_secrets: true.

See: https://github.com/RedHatProductSecurity/ai-guardian/issues/971
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Default timeout for validation HTTP requests (milliseconds)
DEFAULT_VALIDATION_TIMEOUT_MS = 3000


class ValidationStatus(str, Enum):
    """Result of secret validation against provider API."""

    VERIFIED = "verified"  # Secret is active → block
    INACTIVE = "inactive"  # Secret is revoked/expired → warn only
    UNVERIFIED = "unverified"  # No validator or network error → block (default)


@dataclass
class ValidationResult:
    """Result of validating a single secret."""

    status: ValidationStatus
    rule_id: str
    message: str = ""
    response_code: Optional[int] = None
    elapsed_ms: float = 0.0


# ---------------------------------------------------------------------------
# Built-in validators
#
# Standard services have deterministic endpoints — no user config required.
# The rule_id from pattern detection maps to a validator function.
# ---------------------------------------------------------------------------


def _http_validate(
    rule_id: str,
    label: str,
    url: str,
    headers: Dict[str, str],
    secret: str,
    timeout_s: float,
    *,
    method: str = "GET",
    check_body: Optional[Callable] = None,
) -> ValidationResult:
    """Shared HTTP validation: 200 = VERIFIED, else INACTIVE, exception = UNVERIFIED.

    Args:
        check_body: Optional callable(resp) -> ValidationResult for APIs that
                    need response body inspection (e.g., Slack).  Called only
                    when status_code == 200.  Return None to fall through to
                    the default VERIFIED result.
    """
    try:
        req_fn = requests.post if method == "POST" else requests.get
        resp = req_fn(url, headers=headers, timeout=timeout_s)
        if resp.status_code == 200:
            if check_body:
                body_result = check_body(resp)
                if body_result is not None:
                    return body_result
            return ValidationResult(
                status=ValidationStatus.VERIFIED,
                rule_id=rule_id,
                message=f"{label} is active",
                response_code=resp.status_code,
            )
        return ValidationResult(
            status=ValidationStatus.INACTIVE,
            rule_id=rule_id,
            message=f"{label} returned {resp.status_code}",
            response_code=resp.status_code,
        )
    except requests.RequestException as e:
        logger.warning(f"{label} validation failed: {type(e).__name__}")
        return ValidationResult(
            status=ValidationStatus.UNVERIFIED,
            rule_id=rule_id,
            message=f"Network error: {e}",
        )


def _validate_github_token(secret: str, timeout_s: float) -> ValidationResult:
    return _http_validate(
        "github-personal-token",
        "GitHub token",
        "https://api.github.com/user",
        {"Authorization": f"token {secret}", "User-Agent": "ai-guardian-validator"},
        secret,
        timeout_s,
    )


def _validate_openai_key(secret: str, timeout_s: float) -> ValidationResult:
    return _http_validate(
        "openai-api-key",
        "OpenAI API key",
        "https://api.openai.com/v1/models",
        {"Authorization": f"Bearer {secret}"},
        secret,
        timeout_s,
    )


def _validate_anthropic_key(secret: str, timeout_s: float) -> ValidationResult:
    return _http_validate(
        "anthropic-api-key",
        "Anthropic API key",
        "https://api.anthropic.com/v1/models",
        {"x-api-key": secret, "anthropic-version": "2023-06-01"},
        secret,
        timeout_s,
    )


def _validate_slack_token(secret: str, timeout_s: float) -> ValidationResult:
    def _check_slack_body(resp):
        data = resp.json()
        if not data.get("ok"):
            return ValidationResult(
                status=ValidationStatus.INACTIVE,
                rule_id="slack-token",
                message=f"Slack token invalid: {data.get('error', 'unknown')}",
                response_code=resp.status_code,
            )
        return None

    return _http_validate(
        "slack-token",
        "Slack token",
        "https://slack.com/api/auth.test",
        {"Authorization": f"Bearer {secret}"},
        secret,
        timeout_s,
        method="POST",
        check_body=_check_slack_body,
    )


def _validate_gitlab_token(secret: str, timeout_s: float) -> ValidationResult:
    return _http_validate(
        "gitlab-personal-token",
        "GitLab token",
        "https://gitlab.com/api/v4/user",
        {"PRIVATE-TOKEN": secret},
        secret,
        timeout_s,
    )


def _validate_npm_token(secret: str, timeout_s: float) -> ValidationResult:
    return _http_validate(
        "npm-token",
        "npm token",
        "https://registry.npmjs.org/-/whoami",
        {"Authorization": f"Bearer {secret}"},
        secret,
        timeout_s,
    )


# ---------------------------------------------------------------------------
# Built-in validator registry
#
# Maps rule_id → validator function.  Multiple rule_ids may share the same
# validator (e.g. all GitHub token types use the same /user endpoint).
# ---------------------------------------------------------------------------

ValidatorFn = Callable[[str, float], ValidationResult]

BUILTIN_VALIDATORS: Dict[str, ValidatorFn] = {
    # GitHub tokens (all types use the same endpoint)
    "github-personal-token": _validate_github_token,
    "github-oauth-token": _validate_github_token,
    "github-refresh-token": _validate_github_token,
    "github-secret-token": _validate_github_token,
    # OpenAI
    "openai-api-key": _validate_openai_key,
    "openai-project-key": _validate_openai_key,
    # Anthropic
    "anthropic-api-key": _validate_anthropic_key,
    # Slack
    "slack-token": _validate_slack_token,
    # GitLab
    "gitlab-personal-token": _validate_gitlab_token,
    # npm
    "npm-token": _validate_npm_token,
}


# ---------------------------------------------------------------------------
# Custom validators from TOML rules
#
# For custom toml-patterns rules, validation config lives on the rule itself:
#
#   [[rules]]
#   id = "internal-api-key"
#   regex = '''INTERNAL_KEY=([a-zA-Z0-9]{32})'''
#   live_validation = { url = "https://internal.corp.com/verify",
#                       auth = "bearer", expect = 200 }
#
# The `live_validation` field (distinct from the existing `validation` field
# which is for false-positive reduction) configures liveness checking.
# ---------------------------------------------------------------------------


@dataclass
class CustomValidatorConfig:
    """Configuration for a custom secret validator from TOML rules."""

    url: str
    auth: str = "bearer"  # "bearer", "header", "basic", "query"
    expect: int = 200  # Expected HTTP status for active secret
    method: str = "GET"  # HTTP method
    header_name: str = "Authorization"  # Custom header name for auth="header"


def _build_custom_validator(
    config: CustomValidatorConfig, rule_id: str = "custom"
) -> ValidatorFn:
    """Build a validator function from custom TOML config."""

    def _validate(secret: str, timeout_s: float) -> ValidationResult:
        try:
            headers = {}
            params = {}

            if config.auth == "bearer":
                headers["Authorization"] = f"Bearer {secret}"
            elif config.auth == "header":
                headers[config.header_name] = secret
            elif config.auth == "query":
                params["token"] = secret
            # basic auth is handled via requests auth= param

            kwargs = {
                "headers": headers,
                "timeout": timeout_s,
            }
            if params:
                kwargs["params"] = params
            if config.auth == "basic":
                kwargs["auth"] = (secret, "")

            try:
                from ai_guardian.scanners.ssrf import SSRFProtector

                protector = SSRFProtector()
                is_ssrf, reason, _is_immutable = protector._check_url(config.url)
                if is_ssrf:
                    logger.warning(
                        "Custom validation URL blocked by SSRF protection: %s", reason
                    )
                    return ValidationResult(
                        status=ValidationStatus.UNVERIFIED,
                        rule_id=rule_id,
                        message=f"Validation URL blocked: {reason}",
                    )
            except ImportError:
                pass  # intentionally silent — optional dependency

            resp = requests.request(config.method, config.url, **kwargs)

            if resp.status_code == config.expect:
                return ValidationResult(
                    status=ValidationStatus.VERIFIED,
                    rule_id=rule_id,
                    message=f"Custom validation: secret is active (HTTP {resp.status_code})",
                    response_code=resp.status_code,
                )
            return ValidationResult(
                status=ValidationStatus.INACTIVE,
                rule_id=rule_id,
                message=f"Custom validation: HTTP {resp.status_code} (expected {config.expect})",
                response_code=resp.status_code,
            )
        except requests.RequestException as e:
            logger.warning(
                f"Custom validation failed for {config.url.split('?')[0]}: {type(e).__name__}"
            )
            return ValidationResult(
                status=ValidationStatus.UNVERIFIED,
                rule_id=rule_id,
                message=f"Network error: {e}",
            )

    return _validate


def parse_custom_validator(rule: dict) -> Optional[Tuple[str, ValidatorFn]]:
    """Parse a custom validator from a TOML rule dict.

    Args:
        rule: Dict from TOML [[rules]] with optional 'live_validation' key.

    Returns:
        Tuple of (rule_id, validator_fn) or None if no live_validation config.
    """
    live_val = rule.get("live_validation")
    if not live_val or not isinstance(live_val, dict):
        return None

    url = live_val.get("url")
    if not url:
        logger.warning(
            f"Rule '{rule.get('id', '?')}' has live_validation without url — skipping"
        )
        return None

    config = CustomValidatorConfig(
        url=url,
        auth=live_val.get("auth", "bearer"),
        expect=live_val.get("expect", 200),
        method=live_val.get("method", "GET"),
        header_name=live_val.get("header_name", "Authorization"),
    )

    rule_id = rule.get("id", "custom")
    validator = _build_custom_validator(config, rule_id=rule_id)
    return rule_id, validator


# ---------------------------------------------------------------------------
# SecretValidator — main orchestrator
# ---------------------------------------------------------------------------


class SecretValidator:
    """Orchestrates secret validation against provider APIs.

    Usage:
        validator = SecretValidator(config={
            "validate_secrets": True,
            "validation_timeout_ms": 3000,
            "on_inactive": "warn",
        })

        # After detecting secrets, validate them:
        results = validator.validate_secrets(secrets, content)

        # Check which secrets are inactive:
        for result in results:
            if result.status == ValidationStatus.INACTIVE:
                # Don't block, just warn
                pass
    """

    def __init__(
        self, config: Optional[Dict] = None, custom_rules: Optional[List[dict]] = None
    ):
        """Initialize the secret validator.

        Args:
            config: Secret scanning config dict with validation options:
                - validate_secrets: bool (default False)
                - validation_timeout_ms: int (default 3000)
                - on_inactive: str "warn" or "allow" (default "warn")
            custom_rules: Optional list of TOML rule dicts that may contain
                          'live_validation' config for custom validators.
        """
        self._config = config or {}
        self._enabled = self._config.get("validate_secrets", False)
        self._timeout_ms = self._config.get(
            "validation_timeout_ms", DEFAULT_VALIDATION_TIMEOUT_MS
        )
        self._on_inactive = self._config.get("on_inactive", "warn")

        # Build validator registry: built-in + custom
        self._validators: Dict[str, ValidatorFn] = dict(BUILTIN_VALIDATORS)

        # Register custom validators from TOML rules
        if custom_rules:
            for rule in custom_rules:
                result = parse_custom_validator(rule)
                if result:
                    rule_id, validator_fn = result
                    self._validators[rule_id] = validator_fn
                    logger.info(f"Registered custom validator for rule '{rule_id}'")

    @property
    def enabled(self) -> bool:
        """Whether secret validation is enabled."""
        return self._enabled

    @property
    def on_inactive(self) -> str:
        """Action to take for inactive secrets: 'warn' or 'allow'."""
        return self._on_inactive

    @property
    def timeout_seconds(self) -> float:
        """Validation timeout in seconds."""
        return self._timeout_ms / 1000.0

    def has_validator(self, rule_id: str) -> bool:
        """Check if a validator exists for the given rule ID."""
        return rule_id in self._validators

    def validate_secret(self, rule_id: str, secret_value: str) -> ValidationResult:
        """Validate a single secret against its provider API.

        Args:
            rule_id: The rule ID that detected this secret (e.g. "github-personal-token")
            secret_value: The actual secret value to validate

        Returns:
            ValidationResult with status, message, and timing info
        """
        if not self._enabled:
            return ValidationResult(
                status=ValidationStatus.UNVERIFIED,
                rule_id=rule_id,
                message="Validation disabled",
            )

        validator_fn = self._validators.get(rule_id)
        if not validator_fn:
            return ValidationResult(
                status=ValidationStatus.UNVERIFIED,
                rule_id=rule_id,
                message=f"No validator for rule '{rule_id}'",
            )

        start = time.monotonic()
        result = validator_fn(secret_value, self.timeout_seconds)
        result.rule_id = rule_id
        result.elapsed_ms = (time.monotonic() - start) * 1000
        return result

    def validate_secrets(
        self,
        secrets: List[dict],
        content: str,
    ) -> List[ValidationResult]:
        """Validate multiple detected secrets in parallel.

        Args:
            secrets: List of secret dicts with 'rule_id' and position info.
                     Each dict should have at least:
                     - rule_id: str
                     - line_number: int
                     Optionally:
                     - secret: str (the matched text — may be redacted)
            content: The full content that was scanned (used to extract
                     secret values from line positions when 'secret' field
                     is redacted or missing).

        Returns:
            List of ValidationResult objects, one per input secret.
            Results preserve order of the input list.
        """
        if not self._enabled:
            return [
                ValidationResult(
                    status=ValidationStatus.UNVERIFIED,
                    rule_id=s.get("rule_id", "unknown"),
                    message="Validation disabled",
                )
                for s in secrets
            ]

        results: List[Optional[ValidationResult]] = [None] * len(secrets)
        content_lines = content.splitlines() if content else []

        # Determine which secrets have validators and extract their values
        tasks = []  # (index, rule_id, secret_value)
        for i, secret_info in enumerate(secrets):
            rule_id = secret_info.get("rule_id", "")
            if not self.has_validator(rule_id):
                results[i] = ValidationResult(
                    status=ValidationStatus.UNVERIFIED,
                    rule_id=rule_id,
                    message=f"No validator for rule '{rule_id}'",
                )
                continue

            # Extract secret value — prefer the matched text, fall back to line content
            secret_value = secret_info.get("secret") or secret_info.get("matched_text")
            if not secret_value or secret_value.startswith("[REDACTED"):
                line_num = secret_info.get("line_number", 0)
                if 0 < line_num <= len(content_lines):
                    secret_value = content_lines[line_num - 1].strip()

            if not secret_value:
                results[i] = ValidationResult(
                    status=ValidationStatus.UNVERIFIED,
                    rule_id=rule_id,
                    message="Could not extract secret value for validation",
                )
                continue

            tasks.append((i, rule_id, secret_value))

        # Run validations in parallel with thread pool
        if tasks:
            with ThreadPoolExecutor(max_workers=min(len(tasks), 4)) as pool:
                future_to_index = {}
                for idx, rule_id, secret_value in tasks:
                    future = pool.submit(self.validate_secret, rule_id, secret_value)
                    future_to_index[future] = idx

                for future in as_completed(future_to_index):
                    idx = future_to_index[future]
                    try:
                        results[idx] = future.result()
                    except Exception as e:
                        rule_id = secrets[idx].get("rule_id", "unknown")
                        logger.warning(
                            f"Validation error for {rule_id}: {type(e).__name__}"
                        )
                        results[idx] = ValidationResult(
                            status=ValidationStatus.UNVERIFIED,
                            rule_id=rule_id,
                            message=f"Validation error: {e}",
                        )

        # Fill any remaining None slots (shouldn't happen, but safety)
        for i, r in enumerate(results):
            if r is None:
                results[i] = ValidationResult(
                    status=ValidationStatus.UNVERIFIED,
                    rule_id=secrets[i].get("rule_id", "unknown"),
                    message="Validation skipped",
                )

        return results

    def filter_inactive(
        self,
        secrets: List[dict],
        validation_results: List[ValidationResult],
    ) -> Tuple[List[dict], List[dict]]:
        """Separate secrets into active and inactive based on validation results.

        Args:
            secrets: Original list of secret dicts
            validation_results: Corresponding validation results

        Returns:
            Tuple of (active_secrets, inactive_secrets).
            - active_secrets: verified + unverified → should be blocked
            - inactive_secrets: inactive → warn only (based on on_inactive config)
        """
        active = []
        inactive = []

        for secret, result in zip(secrets, validation_results):
            if result.status == ValidationStatus.INACTIVE:
                inactive.append(secret)
                logger.info(f"Secret '{result.rule_id}' is inactive: {result.message}")
            else:
                active.append(secret)
                if result.status == ValidationStatus.VERIFIED:
                    logger.warning(
                        f"Secret '{result.rule_id}' is VERIFIED ACTIVE: {result.message}"
                    )

        return active, inactive
