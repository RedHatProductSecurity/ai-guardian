"""Security Instructions TUI panel — config view and rules preview."""

import json
import logging
from pathlib import Path
from typing import Any, Dict

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from ai_guardian.config.utils import get_config_dir, get_project_config_path

logger = logging.getLogger(__name__)


class SecurityInstructionsContent(Container):
    """Content widget for Security Instructions tab."""

    CSS = """
    SecurityInstructionsContent {
        height: 100%;
    }

    #si-header {
        margin: 1 0;
        padding: 1;
        background: $primary;
        color: $text;
    }

    .si-section {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    .si-section-title {
        margin: 0 0 1 0;
        font-weight: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Security Instructions[/bold]\n"
            "[dim]Security rules injected into agent context via systemMessage "
            "on UserPromptSubmit. Instructs the AI never to bypass security protections.[/dim]",
            id="si-header",
        )
        with VerticalScroll():
            with Container(classes="si-section"):
                yield Static("[bold]Configuration[/bold]", classes="si-section-title")
                yield Static("", id="si-status")

            with Container(classes="si-section"):
                yield Static(
                    "[bold]Built-in Rules Preview[/bold]", classes="si-section-title"
                )
                yield Static("", id="si-builtin-rules")

            with Container(classes="si-section"):
                yield Static("[bold]Custom Rules[/bold]", classes="si-section-title")
                yield Static("", id="si-custom-rules")

            with Container(classes="si-section"):
                yield Static(
                    "[dim]To edit security instructions, use the web console:\n"
                    "  ai-guardian web  →  Security Instructions page\n"
                    "Or edit ai-guardian.json directly (security_instructions section).[/dim]"
                )

    @property
    def _is_project_scope(self) -> bool:
        try:
            return self.app.config_scope == "project"
        except Exception:
            return False

    def _get_config_path(self) -> Path:
        if self._is_project_scope:
            project_path = get_project_config_path()
            if project_path:
                return project_path
            from ai_guardian.config.utils import _find_git_root

            root = _find_git_root() or Path.cwd()
            return root / ".ai-guardian" / "ai-guardian.json"
        return get_config_dir() / "ai-guardian.json"

    def on_mount(self) -> None:
        self.load_config()

    def refresh_content(self) -> None:
        self.load_config()

    def load_config(self) -> None:
        config_path = self._get_config_path()

        config: Dict[str, Any] = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                logger.warning("Failed to read config: %s", e)

        si = config.get("security_instructions", {})
        if not isinstance(si, dict):
            si = {}

        inject_on_prompt = si.get("inject_on_prompt", True)
        inject_trigger = si.get("inject_trigger", "first_per_session")
        custom_rules = si.get("custom_rules", [])
        replace_defaults = si.get("replace_defaults", False)

        enabled_str = "[green]Yes[/green]" if inject_on_prompt else "[red]No[/red]"
        trigger_labels = {
            "first_per_session": "First prompt per session + after blocks (default)",
            "every_prompt": "Every UserPromptSubmit",
            "after_block_only": "After a block event only",
        }
        trigger_str = trigger_labels.get(inject_trigger, inject_trigger)

        try:
            self.query_one("#si-status", Static).update(
                f"  Enabled:         {enabled_str}\n"
                f"  Inject trigger:  [cyan]{trigger_str}[/cyan]\n"
                f"  Replace defaults: {'[yellow]Yes[/yellow]' if replace_defaults else '[dim]No[/dim]'}\n"
                f"  Custom rules:    {len(custom_rules)} configured"
            )
        except Exception:
            pass

        self._load_builtin_rules()
        self._load_custom_rules(custom_rules, replace_defaults)

    def _load_builtin_rules(self) -> None:
        try:
            from ai_guardian.response_format import _SECURITY_SYSTEM_MESSAGE

            lines = _SECURITY_SYSTEM_MESSAGE.split("\n")
            formatted = "\n".join(
                (
                    f"  [dim]{line}[/dim]"
                    if line.startswith("-")
                    else f"  [bold]{line}[/bold]"
                )
                for line in lines
            )
            self.query_one("#si-builtin-rules", Static).update(formatted)
        except Exception as e:
            try:
                self.query_one("#si-builtin-rules", Static).update(
                    f"[red]Could not load built-in rules: {e}[/red]"
                )
            except Exception:
                pass

    def _load_custom_rules(self, custom_rules: list, replace_defaults: bool) -> None:
        try:
            if not custom_rules:
                text = "[dim]  No custom rules configured.[/dim]"
                if replace_defaults:
                    text += "\n  [yellow]Warning: replace_defaults=true with no custom rules means nothing will be injected.[/yellow]"
            else:
                prefix = "Replaces" if replace_defaults else "Appended to"
                lines = [f"  [dim]{prefix} built-in rules:[/dim]"]
                for rule in custom_rules:
                    lines.append(f"  [cyan]•[/cyan] {rule}")
                text = "\n".join(lines)
            self.query_one("#si-custom-rules", Static).update(text)
        except Exception:
            pass
