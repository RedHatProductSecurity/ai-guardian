"""Tests for scanner registry (Phase 3, Issue #1253)."""

import pytest

from ai_guardian.constants import HookEvent, ViolationType
from ai_guardian.scanners.scan_result import ScanResult
from ai_guardian.scanners.scanner_registry import (
    ScannerEntry,
    ScannerName,
    ScannerRegistry,
    get_default_registry,
    reset_default_registry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _dummy_scan(*args, **kwargs):
    return ScanResult.clean("test")


@pytest.fixture()
def registry():
    return ScannerRegistry()


@pytest.fixture()
def sample_entry():
    return ScannerEntry(
        name=ScannerName.SECRET,
        run_fn=_dummy_scan,
        violation_type=ViolationType.SECRET_DETECTED,
        hook_events={HookEvent.PRE_TOOL_USE, HookEvent.PROMPT},
        order=70,
    )


# ---------------------------------------------------------------------------
# ScannerRegistry basic operations
# ---------------------------------------------------------------------------


class TestScannerRegistryBasics:
    def test_register_and_get(self, registry, sample_entry):
        registry.register(sample_entry)
        assert registry.get(ScannerName.SECRET) is sample_entry

    def test_get_missing_returns_none(self, registry):
        assert registry.get(ScannerName.SECRET) is None

    def test_len(self, registry, sample_entry):
        assert len(registry) == 0
        registry.register(sample_entry)
        assert len(registry) == 1

    def test_contains(self, registry, sample_entry):
        assert ScannerName.SECRET not in registry
        registry.register(sample_entry)
        assert ScannerName.SECRET in registry

    def test_register_overwrites(self, registry, sample_entry):
        registry.register(sample_entry)
        replacement = ScannerEntry(
            name=ScannerName.SECRET,
            run_fn=_dummy_scan,
            violation_type=ViolationType.SECRET_DETECTED,
            hook_events={HookEvent.PROMPT},
            order=99,
        )
        registry.register(replacement)
        assert len(registry) == 1
        assert registry.get(ScannerName.SECRET).order == 99


# ---------------------------------------------------------------------------
# Pipeline filtering
# ---------------------------------------------------------------------------


class TestGetPipeline:
    def test_filters_by_hook_event(self, registry, sample_entry):
        registry.register(sample_entry)
        assert len(registry.get_pipeline(HookEvent.PRE_TOOL_USE, has_content=True)) == 1
        assert (
            len(registry.get_pipeline(HookEvent.POST_TOOL_USE, has_content=True)) == 0
        )

    def test_filters_by_content_requirement(self, registry):
        entry = ScannerEntry(
            name=ScannerName.PII,
            run_fn=_dummy_scan,
            violation_type=ViolationType.PII_DETECTED,
            hook_events={HookEvent.PROMPT},
            requires_content=True,
            order=80,
        )
        registry.register(entry)
        assert len(registry.get_pipeline(HookEvent.PROMPT, has_content=True)) == 1
        assert len(registry.get_pipeline(HookEvent.PROMPT, has_content=False)) == 0

    def test_filters_by_file_path_requirement(self, registry):
        entry = ScannerEntry(
            name=ScannerName.CONFIG_FILE,
            run_fn=_dummy_scan,
            violation_type=ViolationType.CONFIG_FILE_EXFIL,
            hook_events={HookEvent.PRE_TOOL_USE},
            requires_content=True,
            requires_file_path=True,
            order=60,
        )
        registry.register(entry)
        pipeline = registry.get_pipeline(
            HookEvent.PRE_TOOL_USE, has_content=True, has_file_path=False
        )
        assert len(pipeline) == 0
        pipeline = registry.get_pipeline(
            HookEvent.PRE_TOOL_USE, has_content=True, has_file_path=True
        )
        assert len(pipeline) == 1

    def test_filters_by_command_requirement(self, registry):
        entry = ScannerEntry(
            name=ScannerName.BASH_EXFIL,
            run_fn=_dummy_scan,
            violation_type=ViolationType.CONFIG_FILE_EXFIL,
            hook_events={HookEvent.PRE_TOOL_USE},
            requires_content=False,
            requires_command=True,
            order=5,
        )
        registry.register(entry)
        assert (
            len(registry.get_pipeline(HookEvent.PRE_TOOL_USE, has_command=False)) == 0
        )
        assert len(registry.get_pipeline(HookEvent.PRE_TOOL_USE, has_command=True)) == 1


# ---------------------------------------------------------------------------
# Pipeline ordering
# ---------------------------------------------------------------------------


class TestPipelineOrdering:
    def test_ordered_by_order_field(self, registry):
        entries = [
            ScannerEntry(
                name=ScannerName.PII,
                run_fn=_dummy_scan,
                violation_type=ViolationType.PII_DETECTED,
                hook_events={HookEvent.PROMPT},
                order=80,
            ),
            ScannerEntry(
                name=ScannerName.PROMPT_INJECTION,
                run_fn=_dummy_scan,
                violation_type=ViolationType.PROMPT_INJECTION,
                hook_events={HookEvent.PROMPT},
                order=10,
            ),
            ScannerEntry(
                name=ScannerName.SECRET,
                run_fn=_dummy_scan,
                violation_type=ViolationType.SECRET_DETECTED,
                hook_events={HookEvent.PROMPT},
                order=70,
            ),
        ]
        for e in entries:
            registry.register(e)

        pipeline = registry.get_pipeline(HookEvent.PROMPT, has_content=True)
        names = [e.name for e in pipeline]
        assert names == [
            ScannerName.PROMPT_INJECTION,
            ScannerName.SECRET,
            ScannerName.PII,
        ]


# ---------------------------------------------------------------------------
# Default registry
# ---------------------------------------------------------------------------


class TestDefaultRegistry:
    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_default_registry()
        yield
        reset_default_registry()

    def test_has_all_thirteen_scanners(self):
        reg = get_default_registry()
        assert len(reg) == 13
        for name in ScannerName:
            assert reg.get(name) is not None, f"Missing scanner: {name}"

    def test_singleton(self):
        assert get_default_registry() is get_default_registry()

    def test_reset_clears_singleton(self):
        first = get_default_registry()
        reset_default_registry()
        second = get_default_registry()
        assert first is not second

    def test_prompt_event_content_pipeline(self):
        """PROMPT with content should include PI, CP, OL, canary, secret, PII."""
        reg = get_default_registry()
        pipeline = reg.get_pipeline(HookEvent.PROMPT, has_content=True)
        names = {e.name for e in pipeline}
        assert ScannerName.PROMPT_INJECTION in names
        assert ScannerName.CONTEXT_POISONING in names
        assert ScannerName.OFFENSIVE_LANGUAGE in names
        assert ScannerName.CANARY_DETECTION in names
        assert ScannerName.SECRET in names
        assert ScannerName.PII in names
        # Supply chain should NOT be in PROMPT
        assert ScannerName.SUPPLY_CHAIN not in names
        # Config file needs file_path
        assert ScannerName.CONFIG_FILE not in names

    def test_pretooluse_content_pipeline(self):
        """PRE_TOOL_USE with content + file_path should include supply chain and config_file."""
        reg = get_default_registry()
        pipeline = reg.get_pipeline(
            HookEvent.PRE_TOOL_USE, has_content=True, has_file_path=True
        )
        names = {e.name for e in pipeline}
        assert ScannerName.SUPPLY_CHAIN in names
        assert ScannerName.CONFIG_FILE in names
        assert ScannerName.CODE_SECURITY in names

    def test_pretooluse_bash_pipeline(self):
        """PRE_TOOL_USE with command should include bash_exfil and exfil_detection."""
        reg = get_default_registry()
        pipeline = reg.get_pipeline(HookEvent.PRE_TOOL_USE, has_command=True)
        names = {e.name for e in pipeline}
        assert ScannerName.BASH_EXFIL in names
        assert ScannerName.EXFIL_DETECTION in names

    def test_permission_request_uses_pretool_security_pipeline(self):
        """PermissionRequest must retain the security scanners used for tools."""
        reg = get_default_registry()
        content_names = {
            entry.name
            for entry in reg.get_pipeline(
                HookEvent.PERMISSION_REQUEST,
                has_content=True,
                has_file_path=True,
            )
        }
        command_names = {
            entry.name
            for entry in reg.get_pipeline(
                HookEvent.PERMISSION_REQUEST,
                has_command=True,
            )
        }

        assert ScannerName.SECRET in content_names
        assert ScannerName.CONFIG_FILE in content_names
        assert ScannerName.DIRECTORY in content_names
        assert ScannerName.BASH_EXFIL in command_names
        assert ScannerName.EXFIL_DETECTION in command_names

    def test_posttooluse_pipeline(self):
        """POST_TOOL_USE should include PI, CP, OL, secret, PII."""
        reg = get_default_registry()
        pipeline = reg.get_pipeline(HookEvent.POST_TOOL_USE, has_content=True)
        names = {e.name for e in pipeline}
        assert ScannerName.PROMPT_INJECTION in names
        assert ScannerName.CONTEXT_POISONING in names
        assert ScannerName.OFFENSIVE_LANGUAGE in names
        assert ScannerName.SECRET in names
        assert ScannerName.PII in names
        # These should NOT be in PostToolUse
        assert ScannerName.SUPPLY_CHAIN not in names
        assert ScannerName.CANARY_DETECTION not in names
        assert ScannerName.BASH_EXFIL not in names

    def test_session_events_empty_pipeline(self):
        """SESSION_START/SESSION_END/STOP should have no scanners in pipeline."""
        reg = get_default_registry()
        for event in (HookEvent.SESSION_START, HookEvent.SESSION_END, HookEvent.STOP):
            pipeline = reg.get_pipeline(
                event, has_content=True, has_file_path=True, has_command=True
            )
            assert len(pipeline) == 0, f"Unexpected scanners for {event}"

    def test_content_pipeline_order(self):
        """Content scanners should follow the expected order."""
        reg = get_default_registry()
        pipeline = reg.get_pipeline(
            HookEvent.PRE_TOOL_USE,
            has_content=True,
            has_file_path=True,
            has_command=True,
        )
        names = [e.name for e in pipeline]
        expected_order = [
            ScannerName.IMAGE,
            ScannerName.BASH_EXFIL,
            ScannerName.EXFIL_DETECTION,
            ScannerName.CODE_SECURITY,
            ScannerName.PROMPT_INJECTION,
            ScannerName.CONTEXT_POISONING,
            ScannerName.SUPPLY_CHAIN,
            ScannerName.OFFENSIVE_LANGUAGE,
            ScannerName.CANARY_DETECTION,
            ScannerName.CONFIG_FILE,
            ScannerName.SECRET,
            ScannerName.PII,
            ScannerName.DIRECTORY,
        ]
        assert names == expected_order

    def test_each_scanner_has_valid_violation_type(self):
        reg = get_default_registry()
        for name in ScannerName:
            entry = reg.get(name)
            assert isinstance(entry.violation_type, ViolationType)

    def test_each_scanner_has_callable_run_fn(self):
        reg = get_default_registry()
        for name in ScannerName:
            entry = reg.get(name)
            assert callable(entry.run_fn)

    # Phase 4: post-scan filter metadata tests

    def test_new_fields_have_defaults(self):
        """New Phase 4 fields have defaults so existing code is unaffected."""
        entry = ScannerEntry(
            name=ScannerName.SECRET,
            run_fn=_dummy_scan,
            violation_type=ViolationType.SECRET_DETECTED,
            hook_events={HookEvent.PRE_TOOL_USE},
        )
        assert entry.supports_ask_mode is True
        assert entry.config_section == ""
        assert entry.violation_severity == "high"
        assert entry.violation_suggestion is None

    def test_all_scanners_have_config_section(self):
        reg = get_default_registry()
        for name in ScannerName:
            entry = reg.get(name)
            assert entry.config_section, f"{name} missing config_section"

    def test_exfil_scanners_no_ask_mode(self):
        reg = get_default_registry()
        no_ask = {
            ScannerName.BASH_EXFIL,
            ScannerName.EXFIL_DETECTION,
            ScannerName.IMAGE,
        }
        for name in no_ask:
            entry = reg.get(name)
            assert not entry.supports_ask_mode, f"{name} should not support ask mode"

    def test_most_scanners_have_violation_suggestion(self):
        reg = get_default_registry()
        for name in ScannerName:
            entry = reg.get(name)
            if name not in (ScannerName.BASH_EXFIL, ScannerName.IMAGE):
                assert (
                    entry.violation_suggestion is not None
                ), f"{name} missing violation_suggestion"
