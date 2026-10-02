"""Unified visual theme for AI Guardian's native and web UI.

Single source of truth for colors, severity badges, violation icons,
and button semantics. Imported by tkinter and NiceGUI components.
"""

from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Theme presets
# ---------------------------------------------------------------------------
THEME_PRESETS = {
    "default": {
        "PRIMARY": "#1976D2",
        "SURFACE": "#1E1E1E",
        "SURFACE_ALT": "#1A1A2E",
        "TEXT": "#E0E0E0",
        "TEXT_MUTED": "#B0B0B0",
        "TEXT_DIM": "#888888",
        "SUCCESS": "#388E3C",
        "ERROR": "#D32F2F",
        "WARNING": "#F57C00",
        "CAUTION": "#FBC02D",
        "INFO": "#546E7A",
        "HIGHLIGHT_BG": "#2A3A00",
        "CODE_BG": "#2A2A2A",
        "ANNOTATION_FG": "#4EC9B0",
    },
    "classic_green": {
        "PRIMARY": "#76B900",
        "SURFACE": "#1A1A1A",
        "SURFACE_ALT": "#1A2E1A",
        "TEXT": "#E0E0E0",
        "TEXT_MUTED": "#A0B0A0",
        "TEXT_DIM": "#708070",
        "SUCCESS": "#4CAF50",
        "ERROR": "#E53935",
        "WARNING": "#FF9800",
        "CAUTION": "#FFCA28",
        "INFO": "#607D8B",
        "HIGHLIGHT_BG": "#2A3A00",
        "CODE_BG": "#252525",
        "ANNOTATION_FG": "#69F0AE",
    },
    "high_contrast": {
        "PRIMARY": "#FFFFFF",
        "SURFACE": "#000000",
        "SURFACE_ALT": "#0A0A0A",
        "TEXT": "#FFFFFF",
        "TEXT_MUTED": "#CCCCCC",
        "TEXT_DIM": "#AAAAAA",
        "SUCCESS": "#00FF00",
        "ERROR": "#FF4444",
        "WARNING": "#FFAA00",
        "CAUTION": "#FFDD00",
        "INFO": "#66BBFF",
        "HIGHLIGHT_BG": "#333300",
        "CODE_BG": "#111111",
        "ANNOTATION_FG": "#00FFCC",
    },
    "solarized": {
        "PRIMARY": "#268BD2",
        "SURFACE": "#002B36",
        "SURFACE_ALT": "#073642",
        "TEXT": "#93A1A1",
        "TEXT_MUTED": "#839496",
        "TEXT_DIM": "#657B83",
        "SUCCESS": "#859900",
        "ERROR": "#DC322F",
        "WARNING": "#CB4B16",
        "CAUTION": "#B58900",
        "INFO": "#2AA198",
        "HIGHLIGHT_BG": "#073642",
        "CODE_BG": "#073642",
        "ANNOTATION_FG": "#2AA198",
    },
}

# ---------------------------------------------------------------------------
# Active theme state
# ---------------------------------------------------------------------------
_active_theme = "default"

# ---------------------------------------------------------------------------
# Core palette (initialized from default preset)
# ---------------------------------------------------------------------------
PRIMARY = "#1976D2"
SURFACE = "#1E1E1E"
SURFACE_ALT = "#1A1A2E"
TEXT = "#E0E0E0"
TEXT_MUTED = "#B0B0B0"
TEXT_DIM = "#888888"

SUCCESS = "#388E3C"
ERROR = "#D32F2F"
WARNING = "#F57C00"
CAUTION = "#FBC02D"
INFO = "#546E7A"

HIGHLIGHT_BG = "#2A3A00"
CODE_BG = "#2A2A2A"
ANNOTATION_FG = "#4EC9B0"

# ---------------------------------------------------------------------------
# Severity → color mapping
# ---------------------------------------------------------------------------
SEVERITY_COLORS = {
    "critical": ERROR,
    "high": WARNING,
    "warning": CAUTION,
    "medium": CAUTION,
    "low": INFO,
    "info": INFO,
}

# ---------------------------------------------------------------------------
# Violation badges: type → {"color": hex, "icon": emoji}
# ---------------------------------------------------------------------------
VIOLATION_BADGES = {
    "secret_detected": {"color": ERROR, "icon": "\U0001f511"},
    "prompt_injection": {"color": WARNING, "icon": "\U0001f6e1️"},
    "pii_detected": {"color": CAUTION, "icon": "\U0001f512"},
    "ssrf_blocked": {"color": INFO, "icon": "\U0001f310"},
    "config_file_exfil": {"color": WARNING, "icon": "⚙️"},
    "context_poisoning": {"color": WARNING, "icon": "☠️"},
    "supply_chain": {"color": ERROR, "icon": "\U0001f4e6"},
    "directory_blocking": {"color": INFO, "icon": "\U0001f4c1"},
    "jailbreak_detected": {"color": ERROR, "icon": "\U0001f6a8"},
    "tool_permission": {"color": WARNING, "icon": "\U0001f527"},
    "secret_redaction": {"color": CAUTION, "icon": "✂️"},
    "secret_in_transcript": {"color": ERROR, "icon": "\U0001f511"},
    "pii_in_transcript": {"color": CAUTION, "icon": "\U0001f512"},
    "prompt_injection_in_transcript": {"color": WARNING, "icon": "\U0001f6e1️"},
    "annotation_suppressed": {"color": INFO, "icon": "✔️"},
    "image_secret_detected": {"color": ERROR, "icon": "\U0001f511"},
    "image_pii_detected": {"color": CAUTION, "icon": "\U0001f512"},
}

# ---------------------------------------------------------------------------
# Button semantic colors
# ---------------------------------------------------------------------------
BUTTON_COLORS = {
    "block": ERROR,
    "allow_once": SUCCESS,
    "allow_always": PRIMARY,
    "suppress_in_source": WARNING,
    "ignore_file": INFO,
    "view_file": None,
    "save": SUCCESS,
    "cancel": None,
}

# ---------------------------------------------------------------------------
# Quasar / NiceGUI adapter
# ---------------------------------------------------------------------------
_QUASAR_MAP = {
    ERROR: "red-8",
    WARNING: "orange-8",
    CAUTION: "amber-8",
    SUCCESS: "green-8",
    PRIMARY: "blue-8",
    INFO: "blue-grey-7",
}

# Badge icon→severity mapping (used by violation_badge)
_BADGE_SEVERITY_MAP = {
    "secret_detected": "ERROR",
    "prompt_injection": "WARNING",
    "pii_detected": "CAUTION",
    "ssrf_blocked": "INFO",
    "config_file_exfil": "WARNING",
    "context_poisoning": "WARNING",
    "supply_chain": "ERROR",
    "directory_blocking": "INFO",
    "jailbreak_detected": "ERROR",
    "tool_permission": "WARNING",
    "secret_redaction": "CAUTION",
    "secret_in_transcript": "ERROR",
    "pii_in_transcript": "CAUTION",
    "prompt_injection_in_transcript": "WARNING",
    "annotation_suppressed": "INFO",
    "image_secret_detected": "ERROR",
    "image_pii_detected": "CAUTION",
}

# Badge emoji mapping (static — doesn't change with theme)
_BADGE_ICONS = {
    "secret_detected": "\U0001f511",
    "prompt_injection": "\U0001f6e1️",
    "pii_detected": "\U0001f512",
    "ssrf_blocked": "\U0001f310",
    "config_file_exfil": "⚙️",
    "context_poisoning": "☠️",
    "supply_chain": "\U0001f4e6",
    "directory_blocking": "\U0001f4c1",
    "jailbreak_detected": "\U0001f6a8",
    "tool_permission": "\U0001f527",
    "secret_redaction": "✂️",
    "secret_in_transcript": "\U0001f511",
    "pii_in_transcript": "\U0001f512",
    "prompt_injection_in_transcript": "\U0001f6e1️",
    "annotation_suppressed": "✔️",
    "image_secret_detected": "\U0001f511",
    "image_pii_detected": "\U0001f512",
}


def _rebuild_derived():
    """Rebuild derived dicts after theme switch."""
    global SEVERITY_COLORS, VIOLATION_BADGES, BUTTON_COLORS, _QUASAR_MAP

    SEVERITY_COLORS.update(
        {
            "critical": ERROR,
            "high": WARNING,
            "warning": CAUTION,
            "medium": CAUTION,
            "low": INFO,
            "info": INFO,
        }
    )

    for vtype, sev_key in _BADGE_SEVERITY_MAP.items():
        color_val = globals()[sev_key]
        VIOLATION_BADGES[vtype] = {
            "color": color_val,
            "icon": _BADGE_ICONS[vtype],
        }

    BUTTON_COLORS.update(
        {
            "block": ERROR,
            "allow_once": SUCCESS,
            "allow_always": PRIMARY,
            "suppress_in_source": WARNING,
            "ignore_file": INFO,
            "view_file": None,
            "save": SUCCESS,
            "cancel": None,
        }
    )

    _QUASAR_MAP.clear()
    _QUASAR_MAP.update(
        {
            ERROR: "red-8",
            WARNING: "orange-8",
            CAUTION: "amber-8",
            SUCCESS: "green-8",
            PRIMARY: "blue-8",
            INFO: "blue-grey-7",
        }
    )


# ---------------------------------------------------------------------------
# Theme API
# ---------------------------------------------------------------------------
def set_active_theme(name: str) -> None:
    """Switch to a named theme preset, updating all module-level constants."""
    global _active_theme
    global PRIMARY, SURFACE, SURFACE_ALT, TEXT, TEXT_MUTED, TEXT_DIM
    global SUCCESS, ERROR, WARNING, CAUTION, INFO
    global HIGHLIGHT_BG, CODE_BG, ANNOTATION_FG

    if name not in THEME_PRESETS:
        raise ValueError(
            f"Unknown theme '{name}'. Available: {', '.join(THEME_PRESETS)}"
        )

    _active_theme = name
    palette = THEME_PRESETS[name]

    PRIMARY = palette["PRIMARY"]
    SURFACE = palette["SURFACE"]
    SURFACE_ALT = palette["SURFACE_ALT"]
    TEXT = palette["TEXT"]
    TEXT_MUTED = palette["TEXT_MUTED"]
    TEXT_DIM = palette["TEXT_DIM"]
    SUCCESS = palette["SUCCESS"]
    ERROR = palette["ERROR"]
    WARNING = palette["WARNING"]
    CAUTION = palette["CAUTION"]
    INFO = palette["INFO"]
    HIGHLIGHT_BG = palette["HIGHLIGHT_BG"]
    CODE_BG = palette["CODE_BG"]
    ANNOTATION_FG = palette["ANNOTATION_FG"]

    _rebuild_derived()


def get_active_theme() -> str:
    """Return the name of the currently active theme."""
    return _active_theme


def get_theme_names() -> list:
    """Return list of available theme preset names."""
    return list(THEME_PRESETS.keys())


def get_palette() -> dict:
    """Return the current active palette as a dict."""
    return dict(THEME_PRESETS[_active_theme])


def apply_quasar_theme() -> None:
    """Push current theme palette to NiceGUI/Quasar brand colors.

    Call on every page load and after theme changes. Requires NiceGUI context.
    """
    from nicegui import ui

    ui.colors(
        primary=PRIMARY,
        secondary=SURFACE_ALT,
        accent=INFO,
        positive=SUCCESS,
        negative=ERROR,
        warning=WARNING,
        info=CAUTION,
    )
    ui.add_css(f"""
        :root {{
            --ag-surface: {SURFACE};
            --ag-surface-alt: {SURFACE_ALT};
            --ag-text: {TEXT};
            --ag-text-muted: {TEXT_MUTED};
        }}
        body.body--dark {{
            background-color: {SURFACE} !important;
        }}
        .q-card {{
            background-color: {SURFACE_ALT} !important;
        }}
        """)


def quasar_color(hex_color: Optional[str]) -> str:
    """Map a theme hex color to the nearest Quasar color name."""
    if hex_color is None:
        return "grey"
    return _QUASAR_MAP.get(hex_color, "grey")


def quasar_severity(severity: str) -> str:
    """Map a severity level to a Quasar color name."""
    return quasar_color(SEVERITY_COLORS.get(severity, INFO))


def quasar_button(button_key: str) -> str:
    """Map a button semantic key to a Quasar color name."""
    return quasar_color(BUTTON_COLORS.get(button_key))


def violation_badge(violation_type: str) -> tuple:
    """Return (icon, color_hex) for a violation type."""
    badge = VIOLATION_BADGES.get(violation_type, {"color": INFO, "icon": "❓"})
    return badge["icon"], badge["color"]


# ---------------------------------------------------------------------------
# Image path resolution
# ---------------------------------------------------------------------------
def get_images_dir() -> Optional[Path]:
    """Resolve the images directory (works in dev layout and installed)."""
    pkg_dir = Path(__file__).resolve().parent
    candidates = [
        pkg_dir / "images",
        pkg_dir.parent.parent / "images",
    ]
    for d in candidates:
        if d.is_dir():
            return d
    return None


def get_image_path(name: str) -> Optional[Path]:
    """Get the path to a specific image file."""
    d = get_images_dir()
    if d is not None:
        p = d / name
        if p.exists():
            return p
    return None
