"""Tests for pinned scanner release asset discovery."""

from unittest import mock

import pytest

from scripts.check_scanner_versions import check_scanner_exists, expected_asset_name


@pytest.mark.parametrize(
    ("scanner", "version", "platform", "expected"),
    [
        (
            "secretlint",
            "13.0.5",
            "linux_x64",
            "secretlint-13.0.5-linux-x64",
        ),
        (
            "secretlint",
            "13.0.5",
            "windows_x64",
            "secretlint-13.0.5-windows-x64.exe",
        ),
        (
            "gitguardian",
            "1.54.0",
            "linux_x64",
            "ggshield-1.54.0-x86_64-unknown-linux-gnu.tar.gz",
        ),
        (
            "gitguardian",
            "1.54.0",
            "linux_arm64",
            "ggshield-1.54.0-aarch64-unknown-linux-gnu.tar.gz",
        ),
        (
            "gitguardian",
            "1.54.0",
            "darwin_arm64",
            "ggshield-1.54.0-arm64-apple-darwin.tar.gz",
        ),
        (
            "gitguardian",
            "1.54.0",
            "windows_x64",
            "ggshield-1.54.0-x86_64-pc-windows-msvc.zip",
        ),
    ],
)
def test_expected_asset_name(scanner, version, platform, expected):
    assert expected_asset_name(scanner, version, platform) == expected


@pytest.mark.parametrize(
    ("scanner", "version", "platform"),
    [
        ("secretlint", "13.0.5", "linux_x64"),
        ("gitguardian", "1.54.0", "linux_arm64"),
    ],
)
@mock.patch("scripts.check_scanner_versions.requests.get")
def test_check_scanner_exists_matches_release_asset(
    mock_get, scanner, version, platform
):
    asset_name = expected_asset_name(scanner, version, platform)
    response = mock.Mock(status_code=200)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "assets": [
            {
                "name": asset_name,
                "browser_download_url": f"https://github.com/test/{asset_name}",
                "size": 1024 * 1024,
            }
        ]
    }
    mock_get.return_value = response

    result = check_scanner_exists(
        f"owner/{scanner}", version, scanner, platform=platform
    )

    assert result["exists"]
    assert result["download_url"] == f"https://github.com/test/{asset_name}"
