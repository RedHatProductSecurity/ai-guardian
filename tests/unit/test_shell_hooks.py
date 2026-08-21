"""Tests for config-driven shell hooks around GuardedAgent callbacks (#2087)."""

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ai_guardian.config.loaders import _load_sdk_hooks

# ============================================================================
# _load_sdk_hooks tests
# ============================================================================


class TestLoadSdkHooks:
    """Tests for config loading of shell hooks."""

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_no_config(self, mock_load):
        mock_load.return_value = (None, None)
        assert _load_sdk_hooks("agent") == {}

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_no_sdk_section(self, mock_load):
        mock_load.return_value = ({"prompt_injection": {}}, None)
        assert _load_sdk_hooks("agent") == {}

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_global_hooks_only(self, mock_load):
        mock_load.return_value = (
            {
                "sdk": {
                    "hooks": {
                        "before_call": {"pre_command": "bash audit.sh"},
                        "post_run": {"post_command": "bash cleanup.sh"},
                    }
                }
            },
            None,
        )
        result = _load_sdk_hooks(None)
        assert result["before_call"] == {"pre_command": "bash audit.sh"}
        assert result["post_run"] == {"post_command": "bash cleanup.sh"}

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_profile_hooks_override_global(self, mock_load):
        mock_load.return_value = (
            {
                "sdk": {
                    "hooks": {
                        "before_call": {"pre_command": "bash global.sh"},
                    },
                    "agents": {
                        "my-agent": {
                            "hooks": {
                                "before_call": {"pre_command": "bash override.sh"},
                            }
                        }
                    },
                }
            },
            None,
        )
        result = _load_sdk_hooks("my-agent")
        assert result["before_call"]["pre_command"] == "bash override.sh"

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_profile_hooks_merge_with_global(self, mock_load):
        mock_load.return_value = (
            {
                "sdk": {
                    "hooks": {
                        "before_call": {"pre_command": "bash global-pre.sh"},
                    },
                    "agents": {
                        "*": {
                            "hooks": {
                                "before_call": {
                                    "post_command": "bash wildcard-post.sh"
                                },
                            }
                        }
                    },
                }
            },
            None,
        )
        result = _load_sdk_hooks("unknown-agent")
        assert result["before_call"]["pre_command"] == "bash global-pre.sh"
        assert result["before_call"]["post_command"] == "bash wildcard-post.sh"

    @patch("ai_guardian.config.loaders._load_config_file")
    def test_wildcard_and_named_profile_merge(self, mock_load):
        mock_load.return_value = (
            {
                "sdk": {
                    "agents": {
                        "*": {
                            "hooks": {
                                "post_run": {"post_command": "bash log.sh"},
                            }
                        },
                        "special": {
                            "hooks": {
                                "before_call": {"pre_command": "bash approve.sh"},
                            }
                        },
                    }
                }
            },
            None,
        )
        result = _load_sdk_hooks("special")
        assert result["post_run"] == {"post_command": "bash log.sh"}
        assert result["before_call"] == {"pre_command": "bash approve.sh"}


# ============================================================================
# GuardedAgent shell hook execution tests
# ============================================================================


def _make_agent_response(content_blocks, stop_reason="end_turn", usage=None):
    usage = usage or SimpleNamespace(input_tokens=100, output_tokens=50)
    return SimpleNamespace(
        content=content_blocks,
        stop_reason=stop_reason,
        usage=usage,
    )


def _make_agent(shell_hooks=None, **kwargs):
    from ai_guardian.integrations.anthropic.agent import GuardedAgent

    mock_create = MagicMock()
    mock_messages = SimpleNamespace(create=mock_create)
    mock_client = SimpleNamespace(messages=mock_messages)

    defaults = {
        "model": "claude-sonnet-5",
        "tools": ["bash"],
        "client": mock_client,
    }
    defaults.update(kwargs)
    agent = GuardedAgent(**defaults)
    if shell_hooks is not None:
        agent._shell_hooks = shell_hooks
    return agent, mock_client


class TestShellHookExecution:
    """Tests for _exec_hook and _run_shell_hook."""

    def test_exec_hook_no_hooks_configured(self):
        agent, _ = _make_agent(shell_hooks={})
        assert agent._exec_hook("before_call", "pre", 1) is True

    def test_exec_hook_no_matching_hook_point(self):
        agent, _ = _make_agent(shell_hooks={"post_run": {"post_command": "bash x.sh"}})
        assert agent._exec_hook("before_call", "pre", 1) is True

    def test_exec_hook_no_matching_phase(self):
        agent, _ = _make_agent(
            shell_hooks={"before_call": {"post_command": "bash x.sh"}}
        )
        assert agent._exec_hook("before_call", "pre", 1) is True

    @patch("subprocess.run")
    def test_exec_hook_success(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0, stderr="")
        agent, _ = _make_agent(
            shell_hooks={"before_call": {"pre_command": "bash audit.sh"}}
        )
        assert agent._exec_hook("before_call", "pre", 1) is True
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["shell"] is True
        stdin_json = json.loads(call_kwargs.kwargs["input"])
        assert stdin_json["hook"] == "before_call"
        assert stdin_json["phase"] == "pre"
        assert stdin_json["turn"] == 1

    @patch("subprocess.run")
    def test_exec_hook_nonzero_exit_returns_false(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=1, stderr="denied")
        agent, _ = _make_agent(
            shell_hooks={"before_call": {"pre_command": "bash gate.sh"}}
        )
        assert agent._exec_hook("before_call", "pre", 1) is False

    @patch("subprocess.run")
    def test_exec_hook_timeout_returns_false(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 30)
        agent, _ = _make_agent(
            shell_hooks={"before_call": {"pre_command": "bash slow.sh"}}
        )
        assert agent._exec_hook("before_call", "pre", 1) is False

    @patch("subprocess.run")
    def test_exec_hook_exception_returns_false(self, mock_run):
        mock_run.side_effect = OSError("not found")
        agent, _ = _make_agent(
            shell_hooks={"before_call": {"pre_command": "bash missing.sh"}}
        )
        assert agent._exec_hook("before_call", "pre", 1) is False

    @patch("subprocess.run")
    def test_context_includes_agent_name_and_model(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0, stderr="")
        agent, _ = _make_agent(
            name="my-agent",
            shell_hooks={"pre_run": {"pre_command": "bash x.sh"}},
        )
        agent._exec_hook("pre_run", "pre", 0)
        stdin_json = json.loads(mock_run.call_args.kwargs["input"])
        assert stdin_json["agent_name"] == "my-agent"
        assert stdin_json["model"] == "claude-sonnet-5"

    @patch("subprocess.run")
    def test_context_default_agent_name(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0, stderr="")
        agent, _ = _make_agent(
            shell_hooks={"pre_run": {"pre_command": "bash x.sh"}},
        )
        agent._exec_hook("pre_run", "pre", 0)
        stdin_json = json.loads(mock_run.call_args.kwargs["input"])
        assert stdin_json["agent_name"] == "agent"


class TestShellHookIntegration:
    """Tests for shell hooks integrated into run() and _run_loop_inner()."""

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    @patch("subprocess.run")
    def test_pre_run_abort_prevents_run(self, mock_run, mock_monitor):
        mock_run.return_value = SimpleNamespace(returncode=1, stderr="blocked")
        agent, client = _make_agent(
            shell_hooks={"pre_run": {"pre_command": "bash gate.sh"}}
        )
        result = agent.run("hello")
        assert result["stop_reason"] == "hook_abort"
        assert result["output"] == ""
        client.messages.create.assert_not_called()

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    @patch("subprocess.run")
    def test_pre_run_success_allows_run(self, mock_run, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        mock_run.return_value = SimpleNamespace(returncode=0, stderr="")
        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )
        agent, client = _make_agent(
            shell_hooks={"pre_run": {"pre_command": "bash setup.sh"}}
        )
        client.messages.create.return_value = response
        result = agent.run("hello")
        assert result["stop_reason"] == "end_turn"
        assert result["output"] == "Done"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    @patch("subprocess.run")
    def test_before_call_abort_stops_loop(self, mock_run, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            stdin_data = json.loads(kwargs.get("input", "{}"))
            if stdin_data.get("hook") == "before_call":
                return SimpleNamespace(returncode=1, stderr="rejected")
            return SimpleNamespace(returncode=0, stderr="")

        mock_run.side_effect = side_effect
        agent, client = _make_agent(
            shell_hooks={"before_call": {"pre_command": "bash approve.sh"}}
        )
        result = agent.run("hello")
        assert result["stop_reason"] == "hook_abort"
        client.messages.create.assert_not_called()

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    @patch("subprocess.run")
    def test_after_call_abort_stops_loop(self, mock_run, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        def side_effect(*args, **kwargs):
            stdin_data = json.loads(kwargs.get("input", "{}"))
            if (
                stdin_data.get("hook") == "after_call"
                and stdin_data.get("phase") == "pre"
            ):
                return SimpleNamespace(returncode=1, stderr="rejected")
            return SimpleNamespace(returncode=0, stderr="")

        mock_run.side_effect = side_effect
        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Hello")],
            stop_reason="end_turn",
        )
        agent, client = _make_agent(
            shell_hooks={"after_call": {"pre_command": "bash validate.sh"}}
        )
        client.messages.create.return_value = response
        result = agent.run("hello")
        assert result["stop_reason"] == "hook_abort"

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    @patch("subprocess.run")
    def test_post_run_hooks_execute(self, mock_run, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        hook_calls = []

        def side_effect(*args, **kwargs):
            stdin_data = json.loads(kwargs.get("input", "{}"))
            hook_calls.append((stdin_data.get("hook"), stdin_data.get("phase")))
            return SimpleNamespace(returncode=0, stderr="")

        mock_run.side_effect = side_effect
        response = _make_agent_response(
            [SimpleNamespace(type="text", text="Done")],
            stop_reason="end_turn",
        )
        agent, client = _make_agent(
            shell_hooks={
                "post_run": {
                    "pre_command": "bash pre.sh",
                    "post_command": "bash post.sh",
                }
            }
        )
        client.messages.create.return_value = response
        result = agent.run("hello")
        assert result["stop_reason"] == "end_turn"
        assert ("post_run", "pre") in hook_calls
        assert ("post_run", "post") in hook_calls

    @patch("ai_guardian.integrations.anthropic.agent.monitor")
    @patch("subprocess.run")
    def test_on_turn_abort_stops_loop(self, mock_run, mock_monitor):
        mock_session = MagicMock()
        mock_monitor.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_monitor.return_value.__exit__ = MagicMock(return_value=False)

        def side_effect(*args, **kwargs):
            stdin_data = json.loads(kwargs.get("input", "{}"))
            if stdin_data.get("hook") == "on_turn" and stdin_data.get("phase") == "pre":
                return SimpleNamespace(returncode=1, stderr="halt")
            return SimpleNamespace(returncode=0, stderr="")

        mock_run.side_effect = side_effect
        agent, client = _make_agent(
            shell_hooks={"on_turn": {"pre_command": "bash check.sh"}}
        )
        result = agent.run("hello")
        assert result["stop_reason"] == "hook_abort"
        client.messages.create.assert_not_called()

    def test_hook_abort_result_structure(self):
        from ai_guardian.integrations.anthropic.agent import GuardedAgent

        result = GuardedAgent._hook_abort_result()
        assert result["stop_reason"] == "hook_abort"
        assert result["output"] == ""
        assert result["messages"] == []
        assert result["compaction_count"] == 0
        assert "input_tokens" in result["usage"]
