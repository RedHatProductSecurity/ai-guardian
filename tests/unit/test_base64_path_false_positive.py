"""Tests that Base64 alone is not treated as a secret."""

import pytest

from ai_guardian.patterns.validators import base64_not_file_path
from ai_guardian.scanners.toml_patterns import TomlPatternsScanner


class TestBase64NotFilePathCompatibility:
    @pytest.mark.parametrize(
        "value",
        [
            "key /Users/user/projects/application/config/secrets/default",
            "key /home/user/projects/application/config/secrets/default",
            r"key C:\Users\dev\projects\application\config\secrets\default",
            "key ./src/application/config/secrets/default",
            "key ../application/config/secrets/default",
            "credential=/opt/application/config/keys/production/default/active",
            "password: /var/lib/application/secrets/storage/path/default",
            "/Users/user/projects/application/config/secrets/default",
            "KEY /Users/user/projects/application/config/secrets/default",
        ],
    )
    def test_file_paths_are_rejected(self, value):
        assert not base64_not_file_path(value)

    @pytest.mark.parametrize(
        "value",
        [
            "key ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop",
            "token=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop==",
            'secret "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop"',
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop",
            "key ",
        ],
    )
    def test_non_paths_are_accepted(self, value):
        assert base64_not_file_path(value)

    def test_contextual_base64_value_is_accepted(self):
        assert base64_not_file_path("key ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop")


class TestBase64IsNotASecretByItself:
    def test_contextual_base64_is_not_flagged_by_toml_rules(self):
        scanner = TomlPatternsScanner()
        content = "key ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop"
        assert scanner.scan(content) == []

    def test_very_long_base64_is_not_flagged_by_length_alone(self):
        scanner = TomlPatternsScanner()
        content = "A" * 128
        assert scanner.scan(content) == []
