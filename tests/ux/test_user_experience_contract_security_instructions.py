"""UX contracts for model-visible security instruction delivery (#2864)."""

import json
from pathlib import Path
from unittest.mock import patch

import ai_guardian


def _process(payload, state_dir):
    with (
        patch("ai_guardian.session_state.get_state_dir", return_value=Path(state_dir)),
        patch(
            "ai_guardian.hook_processing._load_security_instructions_config",
            return_value=(None, None),
        ),
        patch(
            "ai_guardian.config.loaders._load_secret_redaction_config",
            return_value=(None, None),
        ),
        patch(
            "ai_guardian.hook_processing._load_pattern_server_config",
            return_value=None,
        ),
    ):
        result = ai_guardian.process_hook_data(payload)
    return json.loads(result["output"] or "{}")


def test_codex_receives_rules_in_model_context(tmp_path):
    """
    USER EXPERIENCE: Codex prompt hook -> security rules reach model context.

    Codex uses the Claude-compatible hook response and documents
    ``hookSpecificOutput.additionalContext`` as model-visible context.
    """
    output = _process(
        {
            "hook_event_name": "UserPromptSubmit",
            "_ide_type": "codex",
            "model": "gpt-5-codex",
            "session_id": "codex-security-rules",
            "prompt": "Hello",
        },
        tmp_path,
    )

    assert "SECURITY RULES" in output["systemMessage"]
    assert "SECURITY RULES" in output["hookSpecificOutput"]["additionalContext"]


def test_opencode_does_not_claim_model_context_injection(tmp_path):
    """
    USER EXPERIENCE: OpenCode prompt hook -> no silent model-context claim.

    OpenCode's V1/V2 plugin callbacks can replace prompts and tool results, but
    they do not expose a separate model-context response field for rules.
    """
    output = _process(
        {
            "hook_event_name": "message.submit",
            "hook_source": "opencode",
            "opencode_version": "1.19.0",
            "session_id": "opencode-security-rules",
            "cwd": "/tmp/project",
            "prompt": "Hello",
        },
        tmp_path,
    )

    assert "SECURITY RULES" not in json.dumps(output)


def test_kilo_does_not_claim_model_context_injection(tmp_path):
    """
    USER EXPERIENCE: Kilo prompt hook -> no silent model-context claim.

    Kilo's V1 callback exposes mutable message parts, not a model-context
    response field; blocked prompts remain handled by the existing replacement.
    """
    output = _process(
        {
            "hook_event_name": "UserPromptSubmit",
            "hook_source": "kilo",
            "kilo_plugin_api": "v1",
            "session_id": "kilo-security-rules",
            "cwd": "/tmp/project",
            "prompt": "Hello",
        },
        tmp_path,
    )

    assert "SECURITY RULES" not in json.dumps(output)
