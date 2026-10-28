"""Global-only password-likelihood controls follow the Console's auto-save UX."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")
from ai_guardian.web.pages import secrets


@pytest.mark.parametrize(
    "key,value",
    [
        ("enabled", True),
        ("enabled", False),
        ("action", "ask"),
        ("action", "warn"),
        ("action", "block"),
    ],
)
def test_field_save_preserves_current_other_field_and_unrelated_policy(key, value):
    current = {
        "unrelated": 7,
        "password_likelihood": {
            "enabled": False,
            "action": "block",
            "_comment_enabled": "keep",
        },
    }
    with (
        patch.object(secrets, "is_web_config_read_only", return_value=False),
        patch.object(secrets, "load_web_config_global", return_value=current),
        patch.object(secrets, "save_web_config", return_value=True) as save,
    ):
        assert secrets._save_password_likelihood_setting(key, value)
    persisted = save.call_args.args[0]
    assert persisted["unrelated"] == 7
    assert persisted["password_likelihood"] == {
        "enabled": value if key == "enabled" else False,
        "action": value if key == "action" else "block",
        "_comment_enabled": "keep",
    }
    assert save.call_args.kwargs == {"scope": "global"}


@pytest.mark.parametrize(
    "key,value",
    [
        ("enabled", "true"),
        ("enabled", 1),
        ("enabled", None),
        ("action", "bad"),
        ("action", None),
        ("unrelated", True),
    ],
)
def test_invalid_field_event_never_reads_or_saves_config(key, value):
    with (
        patch.object(secrets, "is_web_config_read_only", return_value=False),
        patch.object(secrets, "load_web_config_global") as load,
        patch.object(secrets, "save_web_config") as save,
    ):
        assert not secrets._save_password_likelihood_setting(key, value)
    load.assert_not_called()
    save.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,value,success",
    [("enabled", True, True), ("action", "warn", True), ("enabled", False, False)],
)
async def test_control_event_autosaves_only_changed_field_and_reports_result(
    key, value, success
):
    ui = MagicMock()
    save = MagicMock()
    io = AsyncMock(return_value=success)
    with (
        patch.object(secrets, "ui", ui),
        patch.object(secrets, "is_web_config_read_only", return_value=False),
        patch.object(secrets, "add_help_button"),
        patch.object(secrets, "field_help_icon"),
        patch.object(secrets, "_save_password_likelihood_setting", save),
        patch.object(secrets.run, "io_bound", io),
    ):
        secrets._render_password_likelihood({})
        io.assert_not_awaited()
        ui.button.assert_not_called()
        widget = (
            ui.checkbox.return_value if key == "enabled" else ui.select.return_value
        )
        await widget.on_value_change.call_args.args[0](SimpleNamespace(value=value))
    io.assert_awaited_once_with(save, key, value)
    ui.notify.assert_called_once_with(
        (
            "Global password-likelihood settings saved"
            if success
            else "Could not save global password-likelihood settings"
        ),
        type="positive" if success else "negative",
    )


@pytest.mark.asyncio
async def test_rapid_field_changes_are_serialized_in_one_card():
    ui = MagicMock()
    active = 0
    peak = 0
    changes = []

    async def persist(save, key, value):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)  # let the other event attempt its auto-save
        changes.append((key, value))
        active -= 1
        return True

    with (
        patch.object(secrets, "ui", ui),
        patch.object(secrets, "is_web_config_read_only", return_value=False),
        patch.object(secrets, "add_help_button"),
        patch.object(secrets, "field_help_icon"),
        patch.object(secrets.run, "io_bound", side_effect=persist),
    ):
        secrets._render_password_likelihood({})
        on_enable = ui.checkbox.return_value.on_value_change.call_args.args[0]
        on_action = ui.select.return_value.on_value_change.call_args.args[0]
        await asyncio.gather(
            on_enable(SimpleNamespace(value=True)),
            on_action(SimpleNamespace(value="block")),
        )
    assert peak == 1
    assert changes == [("enabled", True), ("action", "block")]
