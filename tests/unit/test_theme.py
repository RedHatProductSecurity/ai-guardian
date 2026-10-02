"""Tests for the unified theme module (Issue #1288) and theme presets (Issue #1299)."""

import re

import pytest

from ai_guardian import theme
from ai_guardian.theme import (
    PRIMARY,
    SUCCESS,
    ERROR,
    WARNING,
    CAUTION,
    INFO,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    TEXT_MUTED,
    TEXT_DIM,
    CODE_BG,
    HIGHLIGHT_BG,
    ANNOTATION_FG,
    SEVERITY_COLORS,
    VIOLATION_BADGES,
    BUTTON_COLORS,
    THEME_PRESETS,
    quasar_color,
    quasar_severity,
    quasar_button,
    violation_badge,
    get_images_dir,
    get_image_path,
    set_active_theme,
    get_active_theme,
    get_theme_names,
    get_palette,
)

HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

PALETTE_KEYS = [
    "PRIMARY",
    "SURFACE",
    "SURFACE_ALT",
    "TEXT",
    "TEXT_MUTED",
    "TEXT_DIM",
    "SUCCESS",
    "ERROR",
    "WARNING",
    "CAUTION",
    "INFO",
    "HIGHLIGHT_BG",
    "CODE_BG",
    "ANNOTATION_FG",
]


@pytest.fixture(autouse=True)
def _reset_theme():
    """Reset to default theme after each test."""
    yield
    set_active_theme("default")


class TestPaletteConstants:
    """All palette constants must be valid 6-digit hex colors."""

    @pytest.mark.parametrize(
        "name,value",
        [
            ("PRIMARY", PRIMARY),
            ("SUCCESS", SUCCESS),
            ("ERROR", ERROR),
            ("WARNING", WARNING),
            ("CAUTION", CAUTION),
            ("INFO", INFO),
            ("SURFACE", SURFACE),
            ("SURFACE_ALT", SURFACE_ALT),
            ("TEXT", TEXT),
            ("TEXT_MUTED", TEXT_MUTED),
            ("TEXT_DIM", TEXT_DIM),
            ("CODE_BG", CODE_BG),
            ("HIGHLIGHT_BG", HIGHLIGHT_BG),
            ("ANNOTATION_FG", ANNOTATION_FG),
        ],
    )
    def test_valid_hex(self, name, value):
        assert HEX_PATTERN.match(value), f"{name}={value} is not a valid hex color"


class TestSeverityColors:
    """Severity color mapping coverage."""

    @pytest.mark.parametrize(
        "sev", ["critical", "high", "warning", "medium", "low", "info"]
    )
    def test_all_severities_mapped(self, sev):
        assert sev in SEVERITY_COLORS
        assert HEX_PATTERN.match(SEVERITY_COLORS[sev])


class TestViolationBadges:
    """Violation badge mapping coverage."""

    KNOWN_TYPES = [
        "secret_detected",
        "prompt_injection",
        "pii_detected",
        "ssrf_blocked",
        "config_file_exfil",
        "context_poisoning",
        "supply_chain",
        "directory_blocking",
        "jailbreak_detected",
        "tool_permission",
        "secret_redaction",
        "secret_in_transcript",
        "pii_in_transcript",
        "prompt_injection_in_transcript",
        "annotation_suppressed",
        "image_secret_detected",
        "image_pii_detected",
    ]

    @pytest.mark.parametrize("vtype", KNOWN_TYPES)
    def test_all_violation_types_mapped(self, vtype):
        assert vtype in VIOLATION_BADGES
        badge = VIOLATION_BADGES[vtype]
        assert "color" in badge
        assert "icon" in badge
        assert HEX_PATTERN.match(badge["color"])
        assert len(badge["icon"]) > 0

    def test_violation_badge_helper(self):
        icon, color = violation_badge("secret_detected")
        assert icon == "\U0001f511"
        assert color == theme.ERROR

    def test_unknown_violation_type_fallback(self):
        icon, color = violation_badge("unknown_type_xyz")
        assert icon == "❓"
        assert color == theme.INFO


class TestButtonColors:
    """Button color mapping."""

    @pytest.mark.parametrize(
        "key",
        ["block", "allow_once", "allow_always", "suppress_in_source", "ignore_file"],
    )
    def test_action_buttons_have_colors(self, key):
        assert key in BUTTON_COLORS
        assert BUTTON_COLORS[key] is not None
        assert HEX_PATTERN.match(BUTTON_COLORS[key])

    def test_view_file_is_neutral(self):
        assert BUTTON_COLORS["view_file"] is None

    def test_cancel_is_neutral(self):
        assert BUTTON_COLORS["cancel"] is None


class TestQuasarAdapters:
    """Quasar color mapping functions."""

    def test_quasar_color_known(self):
        assert quasar_color(theme.ERROR) == "red-8"
        assert quasar_color(theme.SUCCESS) == "green-8"
        assert quasar_color(theme.PRIMARY) == "blue-8"

    def test_quasar_color_none(self):
        assert quasar_color(None) == "grey"

    def test_quasar_color_unknown(self):
        assert quasar_color("#123456") == "grey"

    def test_quasar_severity(self):
        assert quasar_severity("critical") == "red-8"
        assert quasar_severity("high") == "orange-8"
        assert quasar_severity("low") == "blue-grey-7"

    def test_quasar_button(self):
        assert quasar_button("block") == "red-8"
        assert quasar_button("allow_once") == "green-8"
        assert quasar_button("view_file") == "grey"


class TestImagePaths:
    """Image path resolution in development layout."""

    def test_images_dir_exists(self):
        d = get_images_dir()
        assert d is not None
        assert d.is_dir()

    def test_get_tray_icon(self):
        p = get_image_path("tray-icon-32.png")
        assert p is not None
        assert p.exists()

    def test_get_nonexistent_image(self):
        p = get_image_path("does-not-exist.png")
        assert p is None


# -----------------------------------------------------------------------
# Theme Presets (Issue #1299)
# -----------------------------------------------------------------------


class TestThemePresets:
    """Theme preset definitions and completeness."""

    def test_at_least_three_presets(self):
        assert len(THEME_PRESETS) >= 3

    def test_default_preset_exists(self):
        assert "default" in THEME_PRESETS

    def test_expected_presets(self):
        names = get_theme_names()
        assert "default" in names
        assert "classic_green" in names
        assert "high_contrast" in names
        assert "solarized" in names

    @pytest.mark.parametrize("preset_name", list(THEME_PRESETS.keys()))
    def test_all_palette_keys_present(self, preset_name):
        preset = THEME_PRESETS[preset_name]
        for key in PALETTE_KEYS:
            assert key in preset, f"{preset_name} missing key {key}"

    @pytest.mark.parametrize("preset_name", list(THEME_PRESETS.keys()))
    def test_all_values_valid_hex(self, preset_name):
        preset = THEME_PRESETS[preset_name]
        for key in PALETTE_KEYS:
            assert HEX_PATTERN.match(
                preset[key]
            ), f"{preset_name}.{key}={preset[key]} invalid hex"

    def test_default_preset_matches_original_constants(self):
        p = THEME_PRESETS["default"]
        assert p["PRIMARY"] == "#1976D2"
        assert p["SURFACE"] == "#1E1E1E"
        assert p["SUCCESS"] == "#388E3C"
        assert p["ERROR"] == "#D32F2F"


class TestThemeSwitching:
    """Runtime theme switching via set_active_theme / get_active_theme."""

    def test_default_active_theme(self):
        assert get_active_theme() == "default"

    def test_set_and_get(self):
        set_active_theme("classic_green")
        assert get_active_theme() == "classic_green"

    def test_set_updates_module_globals(self):
        set_active_theme("classic_green")
        assert theme.PRIMARY == "#76B900"
        assert theme.SURFACE == "#1A1A1A"

    def test_set_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown theme"):
            set_active_theme("nonexistent_theme")

    def test_get_palette_returns_current(self):
        set_active_theme("solarized")
        p = get_palette()
        assert p["PRIMARY"] == "#268BD2"
        assert p["SURFACE"] == "#002B36"

    def test_get_theme_names_returns_list(self):
        names = get_theme_names()
        assert isinstance(names, list)
        assert len(names) >= 3

    def test_switch_rebuilds_severity_colors(self):
        set_active_theme("classic_green")
        assert SEVERITY_COLORS["critical"] == theme.ERROR
        assert SEVERITY_COLORS["critical"] == "#E53935"

    def test_switch_rebuilds_violation_badges(self):
        set_active_theme("high_contrast")
        badge = VIOLATION_BADGES["secret_detected"]
        assert badge["color"] == theme.ERROR
        assert badge["color"] == "#FF4444"

    def test_switch_rebuilds_button_colors(self):
        set_active_theme("solarized")
        assert BUTTON_COLORS["block"] == theme.ERROR
        assert BUTTON_COLORS["allow_always"] == theme.PRIMARY

    def test_switch_rebuilds_quasar_map(self):
        set_active_theme("classic_green")
        assert quasar_color(theme.PRIMARY) == "blue-8"
        assert quasar_color(theme.ERROR) == "red-8"

    def test_violation_badge_after_switch(self):
        set_active_theme("high_contrast")
        icon, color = violation_badge("secret_detected")
        assert icon == "\U0001f511"
        assert color == "#FF4444"

    def test_quasar_severity_after_switch(self):
        set_active_theme("solarized")
        result = quasar_severity("critical")
        assert result == "red-8"

    def test_round_trip_back_to_default(self):
        set_active_theme("classic_green")
        assert theme.PRIMARY == "#76B900"
        set_active_theme("default")
        assert theme.PRIMARY == "#1976D2"
        assert get_active_theme() == "default"


class TestHighContrastWCAG:
    """High contrast preset meets WCAG AA minimum contrast ratios."""

    @staticmethod
    def _relative_luminance(hex_color: str) -> float:
        r, g, b = (
            int(hex_color[1:3], 16) / 255,
            int(hex_color[3:5], 16) / 255,
            int(hex_color[5:7], 16) / 255,
        )

        def linearize(c):
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)

    @classmethod
    def _contrast_ratio(cls, fg: str, bg: str) -> float:
        l1 = cls._relative_luminance(fg)
        l2 = cls._relative_luminance(bg)
        lighter = max(l1, l2)
        darker = min(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)

    @pytest.mark.parametrize(
        "color_key",
        ["TEXT", "PRIMARY", "SUCCESS", "ERROR", "WARNING"],
    )
    def test_wcag_aa_against_surface(self, color_key):
        hc = THEME_PRESETS["high_contrast"]
        ratio = self._contrast_ratio(hc[color_key], hc["SURFACE"])
        assert ratio >= 4.5, (
            f"high_contrast.{color_key} ({hc[color_key]}) vs SURFACE "
            f"({hc['SURFACE']}): ratio {ratio:.1f} < 4.5 (WCAG AA)"
        )
