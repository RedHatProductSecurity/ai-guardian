"""Tests for Web Console Security Dashboard page."""

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")


class TestDashboardImport:
    """Verify the dashboard module imports correctly."""

    def test_create_function_exists(self):
        from ai_guardian.web.pages.dashboard import create_dashboard_page

        assert callable(create_dashboard_page)

    def test_feature_groups_defined(self):
        from ai_guardian.web.pages.dashboard import FEATURE_GROUPS

        assert isinstance(FEATURE_GROUPS, list)
        assert len(FEATURE_GROUPS) > 0

    def test_feature_page_slugs_defined(self):
        from ai_guardian.web.pages.dashboard import FEATURE_PAGE_SLUGS

        assert isinstance(FEATURE_PAGE_SLUGS, dict)
        assert len(FEATURE_PAGE_SLUGS) > 0

    def test_audit_logging_page_imports(self):
        from ai_guardian.web.pages.audit_logging import create_audit_logging_page

        assert callable(create_audit_logging_page)


class TestFeaturePageSlugs:
    """Verify FEATURE_PAGE_SLUGS mapping is consistent with routes."""

    EXPECTED_SLUGS = {
        "secret_scanning": "secrets",
        "scan_pii": "scan-pii",
        "prompt_injection": "pi-detection",
        "ssrf_protection": "ssrf",
        "config_file_scanning": "config-scanner",
        "context_poisoning": "context-poisoning",
        "secret_redaction": "secret-redaction",
        "annotations": "annotations",
        "permissions": "permission-rules",
        "directory_rules": "directory-rules",
        "violation_logging": "violation-logging",
        "audit_logging": "audit-logging",
        "latency_tracking": "performance",
    }

    def test_all_expected_slugs_present(self):
        from ai_guardian.web.pages.dashboard import FEATURE_PAGE_SLUGS

        for key, slug in self.EXPECTED_SLUGS.items():
            assert key in FEATURE_PAGE_SLUGS, f"Missing slug for {key}"
            assert FEATURE_PAGE_SLUGS[key] == slug

    def test_no_slug_for_pageless_features(self):
        from ai_guardian.web.pages.dashboard import FEATURE_PAGE_SLUGS

        assert "image_scanning" not in FEATURE_PAGE_SLUGS
        assert "transcript_scanning" not in FEATURE_PAGE_SLUGS
        assert "security_instructions" not in FEATURE_PAGE_SLUGS
        assert "supply_chain" not in FEATURE_PAGE_SLUGS

    def test_all_feature_keys_in_groups(self):
        from ai_guardian.web.pages.dashboard import (
            FEATURE_GROUPS,
            FEATURE_PAGE_SLUGS,
        )

        all_keys = set()
        for _, features in FEATURE_GROUPS:
            for key, _, _ in features:
                all_keys.add(key)
        for key in FEATURE_PAGE_SLUGS:
            assert key in all_keys, f"Slug key {key} not in FEATURE_GROUPS"


class TestTuiCardPanelMap:
    """Verify TUI CARD_PANEL_MAP is consistent."""

    def test_card_panel_map_defined(self):
        from ai_guardian.tui.security_dashboard import CARD_PANEL_MAP

        assert isinstance(CARD_PANEL_MAP, dict)
        assert len(CARD_PANEL_MAP) > 0

    def test_expected_mappings(self):
        from ai_guardian.tui.security_dashboard import CARD_PANEL_MAP

        expected = {
            "secret-scanning-card": "panel-secrets",
            "scan-pii-card": "panel-scan-pii",
            "prompt-injection-card": "panel-pi-detection",
            "ssrf-card": "panel-ssrf",
            "config-scanner-card": "panel-config-scanner",
            "secret-redaction-card": "panel-secret-redaction",
            "annotations-card": "panel-annotations",
            "permissions-card": "panel-skills",
            "directory-rules-card": "panel-directory-rules",
            "violation-logging-card": "panel-violation-logging",
        }
        for card_id, panel_id in expected.items():
            assert card_id in CARD_PANEL_MAP
            assert CARD_PANEL_MAP[card_id] == panel_id

    def test_no_mapping_for_non_navigable_cards(self):
        from ai_guardian.tui.security_dashboard import CARD_PANEL_MAP

        assert "context-poisoning-card" not in CARD_PANEL_MAP
        assert "supply-chain-card" not in CARD_PANEL_MAP
        assert "image-scanning-card" not in CARD_PANEL_MAP
        assert "transcript-scanning-card" not in CARD_PANEL_MAP
        assert "security-instructions-card" not in CARD_PANEL_MAP
        assert "latency-tracking-card" not in CARD_PANEL_MAP

    def test_panel_ids_exist_in_nav_groups(self):
        from ai_guardian.tui.security_dashboard import CARD_PANEL_MAP
        from ai_guardian.tui.app import NAV_GROUPS

        all_panel_ids = set()
        for _, items in NAV_GROUPS:
            for _, panel_id in items:
                all_panel_ids.add(panel_id)
        for panel_id in CARD_PANEL_MAP.values():
            assert (
                panel_id in all_panel_ids
            ), f"Panel {panel_id} not found in NAV_GROUPS"
