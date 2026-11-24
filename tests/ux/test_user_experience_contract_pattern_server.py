"""UX security contracts for remote pattern-server trust decisions."""

import hashlib
from unittest.mock import patch


def test_unpinned_remote_patterns_remain_inactive(tmp_path, monkeypatch):
    """
    USER EXPERIENCE: unpinned remote patterns are not silently trusted.

    The configured server may be reachable, but the scanner continues using
    its bundled baseline rather than activating unverifiable remote content.
    """
    from ai_guardian.patterns.server import PatternServerClient

    monkeypatch.setenv("AI_GUARDIAN_PATTERN_TOKEN", "synthetic-token")
    client = PatternServerClient(
        {
            "url": "https://patterns.example.com",
            "allow_untrusted_host": True,
            "cache": {"path": str(tmp_path / "patterns.toml")},
        }
    )
    with patch("ai_guardian.patterns.server.requests.get") as request:
        assert client._fetch_patterns() is False
        request.assert_not_called()


def test_verified_pattern_diagnostics_are_value_safe(tmp_path):
    """Operator diagnostics expose provenance without authentication material."""
    from ai_guardian.patterns.server import PatternServerClient

    content = b'[metadata]\nversion = "1.0.0"\n'
    client = PatternServerClient(
        {
            "url": "https://raw.githubusercontent.com",
            "patterns_endpoint": "/leaktk/patterns/main/bundle",
            "sha256": hashlib.sha256(content).hexdigest(),
            "cache": {"path": str(tmp_path / "patterns.toml")},
        }
    )
    with patch("ai_guardian.patterns.server.requests.get") as request:
        response = request.return_value
        response.status_code = 200
        response.content = content
        response.text = content.decode()
        assert client._fetch_patterns() is True

    info = client.verification_info()
    assert info["verification_state"] == "verified"
    assert info["source"].startswith("https://raw.githubusercontent.com")
    assert "token" not in str(info).lower()
