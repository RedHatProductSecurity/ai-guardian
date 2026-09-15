"""Tests for pinned scanner release asset discovery."""

from unittest import mock

import pytest

from scripts.check_scanner_versions import (
    check_existence,
    check_scanner_exists,
    expected_asset_name,
)


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


def test_check_existence_requires_both_linux_container_assets(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ai-guardian.scanners]\n"
        'secretlint = "13.0.5"\n'
        "[tool.ai-guardian.scanners.repos]\n"
        'secretlint = "secretlint/secretlint"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    response = mock.Mock(status_code=200)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "assets": [
            {
                "name": "secretlint-13.0.5-linux-x64",
                "browser_download_url": "https://github.com/test/secretlint-linux-x64",
                "size": 1024,
            }
        ]
    }

    with mock.patch(
        "scripts.check_scanner_versions.requests.get", return_value=response
    ) as mock_get:
        with pytest.raises(SystemExit) as exit_info:
            check_existence()

    assert exit_info.value.code == 1
    assert mock_get.call_count == 2
    output = capsys.readouterr().out
    assert "linux_x64" in output
    assert "linux_arm64" in output
    assert "secretlint-13.0.5-linux-arm64" in output
