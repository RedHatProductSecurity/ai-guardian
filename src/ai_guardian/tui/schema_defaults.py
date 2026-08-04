#!/usr/bin/env python3
"""
Schema Defaults Utility

Loads default values from the JSON schema and provides helpers
for Console panels to display defaults and highlight changed values.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ai_guardian.tui.widgets import sanitize_enabled_value

logger = logging.getLogger(__name__)


class _MissingSentinel:
    """Sentinel for 'no default defined' (distinct from None/False)."""

    def __repr__(self) -> str:
        return "<MISSING>"

    def __bool__(self) -> bool:
        return False


_MISSING = _MissingSentinel()


class SchemaDefaults:
    """Singleton that loads and caches JSON schema defaults."""

    _instance: Optional["SchemaDefaults"] = None
    _schema: Optional[Dict[str, Any]] = None

    @classmethod
    def get(cls) -> "SchemaDefaults":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._load()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None
        cls._schema = None

    def _load(self) -> None:
        schema_path = (
            Path(__file__).parent.parent / "schemas" / "ai-guardian-config.schema.json"
        )
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                self._schema = json.load(f)
        except Exception:
            self._schema = {}

    def _follow_ref(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """Follow a $ref pointer to its target definition."""
        ref = node.get("$ref", "")
        if ref.startswith("#/definitions/"):
            def_name = ref[len("#/definitions/") :]
            resolved = self._schema.get("definitions", {}).get(def_name)
            if resolved is not None:
                return resolved
        return node

    def _resolve_path(self, dotted_path: str) -> Optional[Dict[str, Any]]:
        """Resolve a dotted path to its schema property definition."""
        if not self._schema:
            return None
        parts = dotted_path.split(".")
        node = self._schema
        for part in parts:
            node = self._follow_ref(node)
            props = node.get("properties", {})
            if part in props:
                node = props[part]
            else:
                defs = node.get("definitions", {})
                if part in defs:
                    node = defs[part]
                else:
                    return None
        return self._follow_ref(node)

    def get_default(self, dotted_path: str) -> Any:
        """Get the default value for a dotted schema path.

        Returns _MISSING if path doesn't exist or has no default.
        """
        prop = self._resolve_path(dotted_path)
        if prop is None:
            return _MISSING
        if "default" in prop:
            return prop["default"]
        return _MISSING

    def get_description(self, dotted_path: str) -> Optional[str]:
        """Get the description for a dotted schema path."""
        prop = self._resolve_path(dotted_path)
        if prop is None:
            return None
        return prop.get("description")

    def is_default(self, dotted_path: str, current_value: Any) -> bool:
        """Check if current_value matches the schema default."""
        default = self.get_default(dotted_path)
        if default is _MISSING:
            return True
        return current_value == default


def select_options_with_default(
    options: List[Tuple[str, str]],
    schema_path: str,
) -> List[Tuple[str, str]]:
    """Mark the default option in a Select widget's choices.

    Appends ' (default)' to the label of the matching option.
    """
    defaults = SchemaDefaults.get()
    default_val = defaults.get_default(schema_path)
    if default_val is _MISSING:
        return list(options)
    result = []
    for label, value in options:
        if value == default_val and "(default)" not in label:
            result.append((f"{label} (default)", value))
        else:
            result.append((label, value))
    return result


def default_indicator(schema_path: str) -> str:
    """Return rich-text default indicator for a field.

    For booleans: '(default: on)' / '(default: off)'
    For other types: '(default: <value>)'
    Returns empty string if no default defined.
    """
    defaults = SchemaDefaults.get()
    default_val = defaults.get_default(schema_path)
    if default_val is _MISSING:
        return ""
    if isinstance(default_val, bool):
        text = "on" if default_val else "off"
    elif isinstance(default_val, list):
        if not default_val:
            text = "none"
        else:
            text = ", ".join(str(v) for v in default_val)
    else:
        text = str(default_val)
    return f"[dim](default: {text})[/dim]"


def default_placeholder(schema_path: str) -> str:
    """Return default value as string for Input placeholder."""
    defaults = SchemaDefaults.get()
    default_val = defaults.get_default(schema_path)
    if default_val is _MISSING:
        return ""
    return str(default_val)


class SchemaDefaultsMixin:
    """Mixin for config panels to show schema defaults and highlight changes.

    Subclasses define:
        SCHEMA_SECTION: str — dotted path prefix (e.g. 'ssrf_protection')
        SCHEMA_FIELDS: list of (widget_id, field_name, widget_type) tuples
    """

    SCHEMA_SECTION: str = ""
    SCHEMA_FIELDS: List[Tuple[str, str, str]] = []

    def _apply_default_indicators(self, config_section: Dict[str, Any]) -> None:
        """Update CSS classes on widgets based on whether values differ from defaults."""
        schema = SchemaDefaults.get()
        for widget_id, field_name, _widget_type in self.SCHEMA_FIELDS:
            path = (
                f"{self.SCHEMA_SECTION}.{field_name}"
                if self.SCHEMA_SECTION
                else field_name
            )
            default_val = schema.get_default(path)
            if default_val is _MISSING:
                continue
            current_val = config_section.get(field_name, default_val)
            is_changed = current_val != default_val
            try:
                widget = self.query_one(f"#{widget_id}")
                if is_changed:
                    widget.add_class("changed-from-default")
                else:
                    widget.remove_class("changed-from-default")
            except Exception:
                pass

    def _get_section_default(self, field_name: str) -> Any:
        """Get schema default for a field in this panel's section."""
        path = (
            f"{self.SCHEMA_SECTION}.{field_name}" if self.SCHEMA_SECTION else field_name
        )
        return SchemaDefaults.get().get_default(path)

    def _update_default_indicator(
        self, widget_id: str, field_name: str, new_value: Any
    ) -> None:
        """Update the changed-from-default class for a single widget after save."""
        default_val = self._get_section_default(field_name)
        if default_val is _MISSING:
            return
        try:
            widget = self.query_one(f"#{widget_id}")
            if new_value != default_val:
                widget.add_class("changed-from-default")
            else:
                widget.remove_class("changed-from-default")
        except Exception:
            pass


class ConfigSaveMixin:
    """Mixin providing config load/save helpers for TUI panels.

    Subclasses set CONFIG_SECTION (e.g. "prompt_injection") and inherit
    _is_project_scope / _get_config_path for scope-aware path resolution.
    """

    CONFIG_SECTION: str = ""

    @property
    def _is_project_scope(self) -> bool:
        try:
            return self.app.config_scope == "project"
        except Exception:
            return False

    def _get_config_path(self) -> Path:
        from ai_guardian.config.utils import get_config_dir, get_project_config_path

        if self._is_project_scope:
            project_path = get_project_config_path()
            if project_path:
                return project_path
            from ai_guardian.config.utils import _find_git_root

            root = _find_git_root() or Path.cwd()
            return root / ".ai-guardian" / "ai-guardian.json"
        return get_config_dir() / "ai-guardian.json"

    def _load_full_config(self, *, config_path: Optional[Path] = None) -> dict:
        path = config_path or self._get_config_path()
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.debug("Config load failed (%s): %s", path, e)
        return {}

    def _write_full_config(
        self,
        config: dict,
        *,
        config_path: Optional[Path] = None,
        backup: bool = False,
    ) -> bool:
        path = config_path or self._get_config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if backup and path.exists():
                shutil.copy2(path, path.with_suffix(".json.bak"))
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            logger.debug("Config write failed (%s): %s", path, e)
            return False

    def _save_config_field(
        self,
        field: str,
        value: Any,
        *,
        section: Optional[str] = None,
        config_path: Optional[Path] = None,
        backup: bool = False,
    ) -> bool:
        sect = section if section is not None else self.CONFIG_SECTION
        try:
            path = config_path or self._get_config_path()
            config = self._load_full_config(config_path=path)
            target = _ensure_section(config, sect)
            if field == "enabled":
                value = sanitize_enabled_value(value)
            target[field] = value
            return self._write_full_config(config, config_path=path, backup=backup)
        except Exception as e:
            logger.debug("Config field save failed (%s.%s): %s", sect, field, e)
            return False

    def _save_config_updates(
        self,
        updates: Dict[str, Any],
        *,
        section: Optional[str] = None,
        config_path: Optional[Path] = None,
        backup: bool = False,
    ) -> bool:
        sect = section if section is not None else self.CONFIG_SECTION
        try:
            path = config_path or self._get_config_path()
            config = self._load_full_config(config_path=path)
            target = _ensure_section(config, sect)
            if "enabled" in updates:
                updates["enabled"] = sanitize_enabled_value(updates["enabled"])
            target.update(updates)
            return self._write_full_config(config, config_path=path, backup=backup)
        except Exception as e:
            logger.debug("Config updates save failed (%s): %s", sect, e)
            return False

    def _add_config_list_item(
        self,
        field: str,
        value: str,
        input_widget=None,
        *,
        section: Optional[str] = None,
    ) -> bool:
        """Append a value to a list field, with dedup check.

        Clears input_widget and calls self.load_config() on success.
        """
        sect = section if section is not None else self.CONFIG_SECTION
        try:
            config = self._load_full_config()
            target = _ensure_section(config, sect)
            if field not in target:
                target[field] = []
            if value in target[field]:
                self.app.notify("Already in list", severity="warning")
                return False
            target[field].append(value)
            if self._write_full_config(config):
                if input_widget is not None:
                    input_widget.value = ""
                self.load_config()
                self.app.notify(f"Added to {field}: {value}", severity="success")
                return True
            self.app.notify(f"Error adding to {field}", severity="error")
            return False
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")
            return False


def _ensure_section(config: dict, section: str) -> dict:
    """Ensure nested section exists and return the innermost dict.

    Supports dot-separated paths like "permissions.auto_directory_rules".
    Empty/None section returns config root.
    """
    if not section:
        return config
    parts = [p for p in section.split(".") if p]
    node = config
    for part in parts:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    return node


def save_global_config_field(
    section: str,
    field: str,
    value: Any,
    *,
    config_dir: Optional[Path] = None,
) -> Tuple[bool, Optional[str]]:
    """Save a single field to the global config (no class instance needed).

    Returns (success, error_message).
    """
    if config_dir is None:
        from ai_guardian.config.utils import get_config_dir

        config_dir = get_config_dir()
    path = config_dir / "ai-guardian.json"
    try:
        config: dict = {}
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                config = json.load(f)
        target = _ensure_section(config, section)
        target[field] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return True, None
    except Exception as e:
        return False, str(e)
