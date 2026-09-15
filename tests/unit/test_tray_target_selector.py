"""Tests for tray target selector TUI app and CLI handler."""

import sys
from unittest import mock


from ai_guardian.tui.tray_target_selector import TrayTargetSelectorApp, _target_label


class TestTargetLabel:
    """Tests for the _target_label display formatter."""

    def test_container_with_different_name(self):
        t = {
            "name": "my-project",
            "runtime": "container",
            "container_engine": "podman",
            "container_name": "sandbox-1",
        }
        assert _target_label(t) == "my-project (container: sandbox-1)"

    def test_container_with_same_name(self):
        t = {
            "name": "sandbox-1",
            "runtime": "container",
            "container_engine": "docker",
            "container_name": "sandbox-1",
        }
        assert _target_label(t) == "sandbox-1 (container)"

    def test_container_without_container_name(self):
        t = {
            "name": "my-daemon",
            "runtime": "container",
            "container_engine": "podman",
            "container_name": None,
        }
        assert _target_label(t) == "my-daemon (container)"

    def test_container_without_engine(self):
        t = {
            "name": "d",
            "runtime": "container",
            "container_engine": None,
            "container_name": "c1",
        }
        assert _target_label(t) == "d (container: c1)"

    def test_openshell_backing_container_uses_logical_runtime(self):
        t = {
            "name": "ag-test",
            "runtime": "container",
            "runtime_type": "openshell",
            "container_name": "openshell-default--ag-test-id",
        }
        assert _target_label(t) == "ag-test (openshell)"

    def test_local_target(self):
        t = {"name": "my-mac", "runtime": "local"}
        assert _target_label(t) == "my-mac (local)"

    def test_kubernetes_with_pod(self):
        t = {"name": "staging", "runtime": "kubernetes", "pod_name": "guardian-abc"}
        assert _target_label(t) == "staging (k8s: guardian-abc)"

    def test_kubernetes_without_pod(self):
        t = {"name": "staging", "runtime": "kubernetes"}
        assert _target_label(t) == "staging (k8s)"

    def test_manual_target(self):
        t = {"name": "remote", "runtime": "manual"}
        assert _target_label(t) == "remote (manual)"

    def test_unknown_runtime(self):
        t = {"name": "x", "runtime": "other"}
        assert _target_label(t) == "x (other)"

    def test_missing_name(self):
        t = {"runtime": "local"}
        assert _target_label(t) == "unknown (local)"


class TestTrayTargetSelectorApp:
    """Tests for TrayTargetSelectorApp construction."""

    def test_stores_targets(self):
        targets = [{"name": "a", "runtime": "local"}]
        app = TrayTargetSelectorApp(targets=targets)
        assert app._targets == targets

    def test_empty_targets(self):
        app = TrayTargetSelectorApp(targets=[])
        assert app._targets == []


class TestHandleTrayTargetSelect:
    """Tests for _handle_tray_target_select CLI handler."""

    def test_rejects_invalid_json(self):
        from ai_guardian.cli_handlers import _handle_tray_target_select

        args = mock.MagicMock()
        args.targets = "not valid json"
        result = _handle_tray_target_select(args)
        assert result == 1

    def test_rejects_non_array(self):
        from ai_guardian.cli_handlers import _handle_tray_target_select

        args = mock.MagicMock()
        args.targets = '{"name": "not-an-array"}'
        result = _handle_tray_target_select(args)
        assert result == 1

    def test_rejects_non_tty(self):
        from ai_guardian.cli_handlers import _handle_tray_target_select

        args = mock.MagicMock()
        args.targets = '[{"name": "a", "runtime": "local"}]'
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            result = _handle_tray_target_select(args)
        assert result == 1
