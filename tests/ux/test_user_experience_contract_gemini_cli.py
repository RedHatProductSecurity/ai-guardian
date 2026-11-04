"""User-experience contracts for Gemini CLI hook behavior."""

import json
from contextlib import ExitStack
from unittest.mock import patch

from ai_guardian.hook_processing import process_hook_data
from ai_guardian.setup import IDESetup
from ai_guardian.tools.policy import ToolPolicyChecker


def test_gemini_native_shell_tool_uses_bash_policy_and_returns_deny():
    """
    USER EXPERIENCE: Gemini run_shell_command -> canonical Bash policy -> deny.

    Scenario:
    1. Gemini CLI sends a ``BeforeTool`` event for ``run_shell_command``.
    2. AI Guardian normalizes its command and evaluates the configured Bash rule.
    3. The hook returns Gemini's native deny decision before the command executes.

    Expected User Experience:
    - The command is denied by the Bash policy.
    - Gemini receives a structured ``decision: deny`` response.
    """
    hook_data = {
        "hook_event_name": "BeforeTool",
        "transcript_path": "/tmp/gemini-session.jsonl",
        "session_id": "gemini-session",
        "tool_name": "run_shell_command",
        "tool_input": {"command": "printf 'safe command'"},
    }
    policy = ToolPolicyChecker(
        config={
            "permissions": {
                "enabled": True,
                "rules": [{"matcher": "Bash", "mode": "deny", "patterns": ["*"]}],
            }
        }
    )

    loader_results = {
        "_load_pattern_server_config": None,
        "_load_prompt_injection_config": ({"enabled": False}, None),
        "_load_config_scanner_config": ({"enabled": False}, None),
        "_load_permissions_config": ({"enabled": True, "rules": []}, None),
        "_load_agent_config_protection_config": ({"enabled": False}, None),
        "_load_secret_scanning_config": ({"enabled": False}, None),
        "_load_secret_redaction_config": ({"enabled": False}, None),
        "_load_pii_config": ({"enabled": False}, None),
        "_load_transcript_scanning_config": ({"enabled": False}, None),
        "_load_annotations_config": ({"enabled": False}, None),
        "_load_image_scanning_config": ({"enabled": False}, None),
        "_load_security_instructions_config": ({"enabled": False}, None),
        "_load_context_poisoning_config": ({"enabled": False}, None),
        "_load_supply_chain_config": ({"enabled": False}, None),
        "_load_code_scanning_config": ({"enabled": False}, None),
        "_load_offensive_language_config": ({"enabled": False}, None),
        "_load_canary_detection_config": ({"enabled": False}, None),
        "_load_exfil_detection_config": ({"enabled": False}, None),
        "_get_on_scan_error_action": "allow",
    }
    with ExitStack() as patches:
        for name, value in loader_results.items():
            patches.enter_context(
                patch(f"ai_guardian.hook_processing.{name}", return_value=value)
            )
        patches.enter_context(
            patch("ai_guardian.hook_processing.ToolPolicyChecker", return_value=policy)
        )
        patches.enter_context(
            patch("ai_guardian.hook_processing._is_latency_enabled", return_value=False)
        )
        result = process_hook_data(hook_data)

    response = json.loads(result["output"])
    assert response["decision"] == "deny"
    assert "deny" in response["reason"].lower()


def test_gemini_setup_migrates_flat_hooks_and_preserves_other_commands(tmp_path):
    """
    USER EXPERIENCE: Gemini setup upgrades legacy hooks to the current settings schema.

    Scenario:
    1. The user has the older flat Gemini hook list and another tool's hook.
    2. They run the explicit Gemini setup/update action.
    3. AI Guardian writes event-keyed groups with command hook definitions.

    Expected User Experience:
    - The CLI receives a valid current Gemini `settings.json` structure.
    - AI Guardian is installed first, and the user's other command remains.
    """
    config_path = tmp_path / "settings.json"
    config_path.write_text(
        json.dumps(
            {
                "hooks": [
                    {
                        "event": "BeforeTool",
                        "matcher": ".*",
                        "command": "ai-guardian --ide gemini",
                    },
                    {
                        "event": "BeforeTool",
                        "matcher": ".*",
                        "command": "other-tool",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    setup = IDESetup()

    with (
        patch.object(setup, "get_config_path", return_value=str(config_path)),
        patch(
            "ai_guardian.setup.hooks._resolve_binary_path",
            return_value="/usr/local/bin/ai-guardian",
        ),
        patch.object(
            setup,
            "verify_gitleaks_installed",
            return_value=(True, "Gitleaks is installed"),
        ),
    ):
        success, message = setup.setup_ide_hooks("gemini")

    assert success, message
    config = json.loads(config_path.read_text(encoding="utf-8"))
    before_tool = config["hooks"]["BeforeTool"]
    assert (
        before_tool[0]["hooks"][0]["command"]
        == "/usr/local/bin/ai-guardian --ide gemini"
    )
    assert before_tool[0]["hooks"][0]["type"] == "command"
    assert before_tool[1]["hooks"][0]["command"] == "other-tool"
    assert isinstance(config["hooks"], dict)
