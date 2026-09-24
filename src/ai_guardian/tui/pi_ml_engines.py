#!/usr/bin/env python3
"""
ML Prompt Injection Engines Panel

Configure ML engines, execution strategy, fallback, and consensus threshold
for prompt injection detection.
"""

import json

import subprocess
import sys

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Input, Label, Select, Static, TextArea

from ai_guardian.config.utils import get_config_dir
from ai_guardian.tui.schema_defaults import ConfigSaveMixin
from ai_guardian.tui.console_settings import load_editor_theme

VALID_ML_ENGINE_TYPES = {"llm-guard"}


class PIMLEnginesContent(ConfigSaveMixin, Container):
    CONFIG_SECTION = "prompt_injection"
    """Content widget for ML Prompt Injection Engines panel."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save Engines", show=True),
        Binding("ctrl+r", "reload", "Reload", show=True),
    ]

    CSS = """
    PIMLEnginesContent {
        height: 100%;
    }

    #ml-engines-header {
        height: auto;
        padding: 1;
        background: $primary;
        color: $text;
    }

    .section {
        margin: 1 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    .section-title {
        margin: 0 0 1 0;
        font-weight: bold;
    }

    .setting-row {
        margin: 0.5 0;
        height: auto;
        align: left middle;
    }

    .setting-row Label {
        margin: 0 2 0 0;
        width: auto;
    }

    #ml-engines-editor {
        height: 1fr;
        min-height: 10;
        border: solid $primary;
    }

    #ml-editor-status {
        height: auto;
        padding: 0 1;
        background: $surface;
    }

    .status-valid {
        color: $success;
    }

    .status-invalid {
        color: $error;
    }

    .info-box {
        margin: 1 0;
        padding: 1;
        background: $surface;
        border: solid $primary;
    }

    #ml-threshold-input {
        width: 10;
    }

    #ml-threshold-row {
        display: none;
    }

    #ml-threshold-row.visible {
        display: block;
    }

    .wizard-step {
        margin: 0 0 1 0;
        height: auto;
        align: left middle;
    }

    .wizard-step Button {
        margin: 0 0 0 2;
        min-width: 20;
    }

    #ml-wizard-status {
        margin: 1 0 0 0;
        padding: 0 1;
    }

    #ml-editor-note {
        margin: 0 0 1 0;
        color: $warning;
    }

    #ml-editor-note.hidden {
        display: none;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]ML Prompt Injection Engines[/bold]  "
            "[dim]Ctrl+S[/dim] Save  "
            "[dim]Ctrl+R[/dim] Reload",
            id="ml-engines-header",
        )

        with VerticalScroll():
            # Setup wizard
            with Container(classes="section"):
                yield Static("[bold]ML Engine Setup[/bold]", classes="section-title")

                with Horizontal(classes="wizard-step"):
                    yield Static("", id="ml-step1-icon", markup=True)
                    yield Static("", id="ml-step1-label", markup=True)
                    yield Button(
                        "Install onnxruntime",
                        id="ml-btn-install",
                        variant="primary",
                    )

                with Horizontal(classes="wizard-step"):
                    yield Static("", id="ml-step2-icon", markup=True)
                    yield Static("", id="ml-step2-label", markup=True)
                    yield Button(
                        "Download Model",
                        id="ml-btn-download",
                        variant="primary",
                    )

                with Horizontal(classes="wizard-step"):
                    yield Static("", id="ml-step3-icon", markup=True)
                    yield Static("", id="ml-step3-label", markup=True)

                with Horizontal(classes="wizard-step"):
                    yield Static("", id="ml-step4-icon", markup=True)
                    yield Static("", id="ml-step4-label", markup=True)
                    yield Button(
                        "Go to Detector Settings",
                        id="ml-btn-detector",
                        variant="default",
                    )

                yield Static("", id="ml-wizard-status", markup=True)

            # Strategy
            with Container(classes="section"):
                yield Static("[bold]Execution Strategy[/bold]", classes="section-title")
                yield Static("[dim]How multiple ML engines combine results.[/dim]")
                with Horizontal(classes="setting-row"):
                    yield Label("Strategy:")
                    yield Select(
                        [
                            ("any-match (default — flag if ANY detects)", "any-match"),
                            ("first-match (use first engine result)", "first-match"),
                            ("consensus (flag if N engines agree)", "consensus"),
                        ],
                        value="any-match",
                        id="ml-strategy-select",
                        allow_blank=False,
                    )
                with Horizontal(classes="setting-row", id="ml-threshold-row"):
                    yield Label("Consensus threshold:")
                    yield Input(
                        value="2",
                        type="integer",
                        id="ml-threshold-input",
                    )

            # Fallback
            with Container(classes="section"):
                yield Static("[bold]Fallback on Error[/bold]", classes="section-title")
                yield Static("[dim]Action when ML detection is unavailable.[/dim]")
                with Horizontal(classes="setting-row"):
                    yield Label("Fallback:")
                    yield Select(
                        [
                            ("heuristic (default — pattern detection)", "heuristic"),
                            ("block (fail closed)", "block"),
                            ("allow (fail open)", "allow"),
                        ],
                        value="heuristic",
                        id="ml-fallback-select",
                        allow_blank=False,
                    )

            # Engines editor
            yield Static("[bold]ML Engines[/bold]  [dim](edit JSON below)[/dim]")
            yield Static(
                "⚠  Complete Steps 1-2 before configuring engines.",
                id="ml-editor-note",
            )

            theme = load_editor_theme()
            yield TextArea(
                "[]",
                language="json",
                theme=theme,
                show_line_numbers=True,
                tab_behavior="indent",
                id="ml-engines-editor",
            )

            yield Static("", id="ml-editor-status")

            # Reference
            with Container(classes="info-box"):
                yield Static("ML engine configuration reference", markup=False)
                yield Static(
                    "Each engine requires 'type' and 'model' fields.\n\n"
                    "Example:\n"
                    "[\n"
                    "  {\n"
                    '    "type": "llm-guard",\n'
                    '    "model": "protectai/deberta-v3-base-prompt-injection-v2",\n'
                    '    "threshold": 0.85\n'
                    "  }\n"
                    "]\n\n"
                    "Valid engine types: llm-guard\n"
                    "threshold: 0.0-1.0 (default 0.85)\n\n"
                    "Requires: onnxruntime\n"
                    "Download models: ai-guardian ml download",
                    markup=False,
                )

    def on_mount(self) -> None:
        self.load_config()

    def on_show(self) -> None:
        self._apply_saved_theme()

    def refresh_content(self) -> None:
        self._apply_saved_theme()
        self.load_config()

    def _apply_saved_theme(self) -> None:
        try:
            editor = self.query_one("#ml-engines-editor", TextArea)
            theme = load_editor_theme()
            if editor.theme != theme:
                editor.theme = theme
        except Exception:
            pass

    def load_config(self) -> None:
        config_dir = get_config_dir()
        config_path = config_dir / "ai-guardian.json"

        config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                self.app.notify(f"Error loading config: {e}", severity="error")
                return

        pi = config.get("prompt_injection", {})
        if not isinstance(pi, dict):
            pi = {}

        engines = pi.get("ml_engines", [])
        strategy = pi.get("ml_strategy", "any-match")
        threshold = pi.get("consensus_threshold", 2)
        fallback = pi.get("fallback_on_error", "heuristic")
        detector = pi.get("detector", "heuristic")

        try:
            self.query_one("#ml-strategy-select", Select).value = strategy
        except Exception:
            pass

        try:
            self.query_one("#ml-threshold-input", Input).value = str(threshold)
        except Exception:
            pass

        try:
            self.query_one("#ml-fallback-select", Select).value = fallback
        except Exception:
            pass

        self._update_threshold_visibility(strategy)

        engines_json = json.dumps(engines, indent=2) if engines else "[]"
        try:
            editor = self.query_one("#ml-engines-editor", TextArea)
            editor.load_text(engines_json)
            self._update_status(engines_json)
        except Exception:
            pass

        self._update_wizard(engines, detector)

    def _update_wizard(self, engines: list, detector: str) -> None:
        try:
            from ai_guardian.scanners.ml_detection import (
                is_ml_available,
                list_registered_models,
            )

            deps_ok = is_ml_available()
            models = list_registered_models()
            model_ok = bool(models) and all(m.get("downloaded") for m in models)
        except Exception:
            deps_ok = False
            models = []
            model_ok = False

        engines_count = len(engines) if isinstance(engines, list) else 0
        config_ok = engines_count > 0
        detector_ok = detector in ("ml", "hybrid")

        # Step 1: Dependencies
        try:
            icon1 = self.query_one("#ml-step1-icon", Static)
            label1 = self.query_one("#ml-step1-label", Static)
            btn_install = self.query_one("#ml-btn-install", Button)
            if deps_ok:
                icon1.update("[green]✅[/green]")
                label1.update("Step 1: Dependencies — onnxruntime installed")
                btn_install.display = False
            else:
                icon1.update("[yellow]⚠️[/yellow]")
                label1.update("Step 1: Dependencies — onnxruntime not installed")
                btn_install.display = True
        except Exception:
            pass

        # Step 2: Model
        try:
            icon2 = self.query_one("#ml-step2-icon", Static)
            label2 = self.query_one("#ml-step2-label", Static)
            btn_download = self.query_one("#ml-btn-download", Button)
            if model_ok:
                icon2.update("[green]✅[/green]")
                label2.update("Step 2: Model — downloaded")
                btn_download.display = False
            else:
                icon2.update("[yellow]⚠️[/yellow]")
                label2.update("Step 2: Model — not downloaded")
                btn_download.display = True
        except Exception:
            pass

        # Step 3: Configuration
        try:
            icon3 = self.query_one("#ml-step3-icon", Static)
            label3 = self.query_one("#ml-step3-label", Static)
            if config_ok:
                icon3.update("[green]✅[/green]")
                label3.update(
                    f"Step 3: Configuration — {engines_count} engine(s) configured"
                )
            else:
                icon3.update("[yellow]⚠️[/yellow]")
                label3.update("Step 3: Configuration — no engines configured")
        except Exception:
            pass

        # Step 4: Detector
        try:
            icon4 = self.query_one("#ml-step4-icon", Static)
            label4 = self.query_one("#ml-step4-label", Static)
            btn_detector = self.query_one("#ml-btn-detector", Button)
            if detector_ok:
                icon4.update("[green]✅[/green]")
                label4.update(f"Step 4: Detector — set to '{detector}'")
                btn_detector.display = False
            else:
                icon4.update("[yellow]⚠️[/yellow]")
                label4.update(
                    f"Step 4: Detector — set to '{detector}', change to 'ml' or 'hybrid'"
                )
                btn_detector.display = True
        except Exception:
            pass

        # Overall status
        try:
            status_widget = self.query_one("#ml-wizard-status", Static)
            if deps_ok and model_ok and config_ok and detector_ok:
                status_widget.update("[green bold]Status: READY[/green bold]")
            else:
                reasons = []
                if not deps_ok:
                    reasons.append("dependency missing")
                if not model_ok:
                    reasons.append("model not downloaded")
                if not config_ok:
                    reasons.append("no engines configured")
                if not detector_ok:
                    reasons.append("detector not set to ml/hybrid")
                status_widget.update(
                    f"[yellow bold]Status: NOT READY ({', '.join(reasons)})[/yellow bold]"
                )
        except Exception:
            pass

        # Editor note visibility
        try:
            note = self.query_one("#ml-editor-note", Static)
            if deps_ok and model_ok:
                note.add_class("hidden")
            else:
                note.remove_class("hidden")
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "ml-btn-install":
            self._install_onnxruntime()
        elif bid == "ml-btn-download":
            self._download_model()
        elif bid == "ml-btn-detector":
            self._navigate_to_detector()

    @work(thread=True, name="install-onnxruntime", exit_on_error=False)
    def _install_onnxruntime(self) -> None:
        self.app.call_from_thread(
            self.app.notify, "Installing onnxruntime...", severity="information"
        )
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "onnxruntime"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                self.app.call_from_thread(
                    self.app.notify,
                    "onnxruntime installed successfully",
                    severity="information",
                )
            else:
                self.app.call_from_thread(
                    self.app.notify,
                    f"Install failed: {result.stderr.strip()[:200]}",
                    severity="error",
                )
        except Exception as e:
            self.app.call_from_thread(
                self.app.notify, f"Install error: {e}", severity="error"
            )
        finally:
            self.app.call_from_thread(self.load_config)

    @work(thread=True, name="download-ml-model", exit_on_error=False)
    def _download_model(self) -> None:
        self.app.call_from_thread(
            self.app.notify, "Downloading ML model...", severity="information"
        )
        try:
            from ai_guardian.scanners.ml_detection import download_model

            download_model()
            self.app.call_from_thread(
                self.app.notify, "Model downloaded successfully", severity="information"
            )
        except Exception as e:
            self.app.call_from_thread(
                self.app.notify, f"Download failed: {e}", severity="error"
            )
        finally:
            self.app.call_from_thread(self.load_config)

    def _navigate_to_detector(self) -> None:
        try:
            from textual.widgets import ContentSwitcher

            switcher = self.app.query_one("#panels", ContentSwitcher)
            switcher.current = "panel-pi-detection"
        except Exception:
            self.app.notify(
                "Navigate to Prompt Injection Detection in the sidebar",
                severity="information",
            )

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "ml-engines-editor":
            self._update_status(event.text_area.text)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "ml-strategy-select":
            value = str(event.value)
            self._update_threshold_visibility(value)
            self._save_strategy(value)
        elif event.select.id == "ml-fallback-select":
            self._save_fallback(str(event.value))

    def _update_threshold_visibility(self, strategy: str) -> None:
        try:
            row = self.query_one("#ml-threshold-row")
            if strategy == "consensus":
                row.add_class("visible")
            else:
                row.remove_class("visible")
        except Exception:
            pass

    def _update_status(self, text: str) -> None:
        engines, error = self._parse_engines(text)
        status = self.query_one("#ml-editor-status", Static)
        if error:
            status.update(f"Invalid: {error}")
            status.remove_class("status-valid")
            status.add_class("status-invalid")
        else:
            count = len(engines)
            status.update(f"Valid JSON — {count} engine(s)")
            status.remove_class("status-invalid")
            status.add_class("status-valid")

    def _parse_engines(self, text: str):
        """Parse ML engines JSON. Returns (engines_list, error_string)."""
        text = text.strip()
        if not text:
            return [], None
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            return None, f"Line {e.lineno}, col {e.colno}: {e.msg}"

        if not isinstance(data, list):
            return None, "Engines must be a JSON array"

        for i, entry in enumerate(data):
            if not isinstance(entry, dict):
                return (
                    None,
                    f"Engine {i + 1}: must be an object with 'type' and 'model'",
                )
            etype = entry.get("type")
            if not etype:
                return None, f"Engine {i + 1}: missing 'type' field"
            if etype not in VALID_ML_ENGINE_TYPES:
                return None, f"Engine {i + 1}: unknown type '{etype}'"
            if not entry.get("model"):
                return None, f"Engine {i + 1}: missing 'model' field"
            threshold = entry.get("threshold")
            if threshold is not None:
                if not isinstance(threshold, (int, float)):
                    return None, f"Engine {i + 1}: threshold must be a number"
                if not 0.0 <= threshold <= 1.0:
                    return None, f"Engine {i + 1}: threshold must be 0.0-1.0"

        return data, None

    def action_save(self) -> None:
        editor = self.query_one("#ml-engines-editor", TextArea)
        text = editor.text

        engines, error = self._parse_engines(text)
        if error:
            self.app.notify(f"Cannot save: {error}", severity="error")
            return

        try:
            config = self._load_full_config()
            pi = config.get("prompt_injection", {})
            if not isinstance(pi, dict):
                pi = {}

            pi["ml_engines"] = engines

            try:
                threshold_input = self.query_one("#ml-threshold-input", Input)
                threshold = int(threshold_input.value) if threshold_input.value else 2
                pi["consensus_threshold"] = max(1, threshold)
            except Exception:
                pass

            config["prompt_injection"] = pi
            self._write_full_config(config, backup=True)
            self.app.notify(
                f"Saved {len(engines)} ML engine(s)", severity="information"
            )
            self.load_config()
        except Exception as e:
            self.app.notify(f"Save failed: {e}", severity="error")

    def action_reload(self) -> None:
        self.load_config()
        self.app.notify("Reloaded from disk", severity="information")

    def action_refresh(self) -> None:
        self.load_config()
        self.app.notify("ML engines config refreshed", severity="information")

    def _save_strategy(self, strategy: str) -> None:
        if self._save_config_field("ml_strategy", strategy):
            self.app.notify(f"Strategy set to: {strategy}", severity="success")
        else:
            self.app.notify("Error saving strategy", severity="error")

    def _save_fallback(self, fallback: str) -> None:
        if self._save_config_field("fallback_on_error", fallback):
            self.app.notify(f"Fallback set to: {fallback}", severity="success")
        else:
            self.app.notify("Error saving fallback", severity="error")
