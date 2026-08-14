"""Scan Configure page — scan project and auto-generate suppression config."""

import json
import threading
from pathlib import Path

from nicegui import run, ui

from ai_guardian.constants import RULE_ID_LABELS, RULE_ID_TO_SLUG
from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.pages.directory_scan import _open_browse_dialog

_SESSION_KEY = "scan_configure_result"


def _serialize_result(result):
    """Convert ScanPipelineResult with dataclass objects to JSON-safe dict."""
    analysis = result.analysis
    return {
        "findings_count": result.findings_count,
        "merged_config": result.merged_config,
        "project_dir": result.project_dir,
        "language_names": result.language_names,
        "analysis": {
            "suppressed_count": analysis.suppressed_count,
            "high_frequency_clusters": [
                {
                    "rule_id": c.rule_id,
                    "sub_type": c.sub_type,
                    "file_count": c.file_count,
                    "total_count": c.total_count,
                    "sample_files": c.sample_files[:5],
                }
                for c in analysis.high_frequency_clusters
            ],
            "directories_to_ignore": [
                {
                    "directory": d.directory,
                    "total_findings": d.total_findings,
                    "high_frequency_findings": d.high_frequency_findings,
                }
                for d in analysis.directories_to_ignore
            ],
            "recommended_config": analysis.recommended_config,
            "recommended_ignore_paths": analysis.recommended_ignore_paths,
        },
    }


def _deserialize_result(data):
    """Reconstruct a ScanPipelineResult from stored session data."""
    from ai_guardian.scan_analyzer import (
        FindingCluster,
        DirectoryAnalysis,
        ScanAnalysisResult,
        ScanPipelineResult,
    )

    a = data["analysis"]

    analysis = ScanAnalysisResult(
        suppressed_count=a.get("suppressed_count", 0),
        high_frequency_clusters=[
            FindingCluster(**c) for c in a.get("high_frequency_clusters", [])
        ],
        directories_to_ignore=[
            DirectoryAnalysis(**d) for d in a.get("directories_to_ignore", [])
        ],
        recommended_config=a.get("recommended_config", {}),
        recommended_ignore_paths=a.get("recommended_ignore_paths", {}),
    )

    return ScanPipelineResult(
        findings_count=data["findings_count"],
        merged_config=data["merged_config"],
        project_dir=data["project_dir"],
        language_names=data.get("language_names", []),
        analysis=analysis,
    )


def _run_scan(project_dir, threshold, cancel_event, progress_state, skip_hidden=True):
    """Run project scan and analysis in a background thread."""
    from ai_guardian.scan_analyzer import run_scan_pipeline

    def on_phase(msg):
        progress_state["phase"] = msg

    def on_file_progress(file_path, index, total):
        progress_state["file"] = file_path
        progress_state["index"] = index
        progress_state["total"] = total

    return run_scan_pipeline(
        project_dir,
        threshold,
        cancel_event,
        on_phase=on_phase,
        on_file_progress=on_file_progress,
        skip_hidden=skip_hidden,
    )


def _render_results(container, result, daemon_name):
    """Render scan analysis results with preview and apply/discard buttons."""
    container.clear()
    analysis = result.analysis
    merged_config = result.merged_config

    lang_names = result.language_names

    with container:
        with ui.card().classes("w-full"):
            ui.label("Scan Results").classes("text-lg font-bold")
            with ui.row().classes("items-center gap-4 flex-wrap"):
                ui.badge(
                    f"{result.findings_count} findings",
                    color="blue",
                ).classes("text-sm")
                ui.badge(
                    f"{analysis.suppressed_count} auto-suppressed",
                    color="green",
                ).classes("text-sm")
                remaining = result.findings_count - analysis.suppressed_count
                if remaining > 0:
                    ui.badge(
                        f"{remaining} remaining",
                        color="amber",
                    ).classes("text-sm")
                else:
                    ui.badge("0 remaining", color="green").classes("text-sm")

            if lang_names:
                ui.label(f"Detected languages: {', '.join(lang_names)}").classes(
                    "text-xs text-grey-6 mt-1"
                )

        if analysis.high_frequency_clusters:
            with ui.card().classes("w-full"):
                ui.label("High-Frequency Clusters (Auto-Suppressed)").classes(
                    "text-base font-bold"
                )
                ui.label(
                    "These patterns appear in many files and are likely false positives."
                ).classes("text-xs text-grey-6")

                for c in analysis.high_frequency_clusters:
                    label = RULE_ID_LABELS.get(c.rule_id, c.rule_id)
                    slug = RULE_ID_TO_SLUG.get(c.rule_id)
                    samples = ", ".join(c.sample_files[:3])

                    with ui.row().classes(
                        "items-center gap-3 w-full py-1 " "border-b border-grey-8"
                    ):
                        if slug:
                            href = f"/{daemon_name}{slug}"
                            ui.link(label, href).tooltip(
                                f"{c.rule_id} — click to view detection config"
                            ).classes("text-sm font-bold")
                        else:
                            ui.label(label).tooltip(c.rule_id).classes(
                                "text-sm font-bold"
                            )
                        ui.badge(c.sub_type, color="grey").classes("text-xs")
                        ui.label(f"{c.file_count} files").classes("text-xs text-grey-4")
                        ui.label(f"{c.total_count} occurrences").classes(
                            "text-xs text-grey-4"
                        )
                        if samples:
                            ui.label(samples).classes("text-xs text-grey-6").style(
                                "font-family: monospace; "
                                "overflow: hidden; "
                                "text-overflow: ellipsis; "
                                "white-space: nowrap; "
                                "max-width: 300px"
                            ).tooltip(samples)

        dirs_to_ignore = [
            d for d in analysis.directories_to_ignore if d.all_high_frequency
        ]
        if dirs_to_ignore:
            with ui.card().classes("w-full"):
                ui.label("Directories to Ignore").classes("text-base font-bold")
                ui.label(
                    "All findings in these directories are high-frequency "
                    "patterns — they will be added to .aiguardignore.toml."
                ).classes("text-xs text-grey-6")

                for d in dirs_to_ignore:
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("folder", color="amber").classes("text-lg")
                        ui.label(f"{d.directory}/").classes("font-mono text-sm")
                        ui.label(f"({d.total_findings} findings)").classes(
                            "text-xs text-grey-6"
                        )

        with ui.card().classes("w-full"):
            ui.label("Config Preview").classes("text-base font-bold")

            if merged_config:
                ui.label("ai-guardian.json changes:").classes("text-sm font-bold mt-2")
                ui.code(
                    json.dumps(merged_config, indent=2),
                    language="json",
                ).classes("w-full")
            else:
                ui.label("No config changes needed.").classes("text-xs text-grey-6")

            if analysis.recommended_ignore_paths:
                ui.label(".aiguardignore.toml entries:").classes(
                    "text-sm font-bold mt-2"
                )
                toml_lines = []
                for scanner_type, paths in sorted(
                    analysis.recommended_ignore_paths.items()
                ):
                    toml_lines.append(f"[{scanner_type}]")
                    toml_lines.append(
                        "paths = [" + ", ".join(f'"{p}"' for p in paths) + "]"
                    )
                    toml_lines.append("")
                ui.code(
                    "\n".join(toml_lines),
                    language="toml",
                ).classes("w-full")


def create_scan_configure_page(service, daemon_name: str):
    """Create the Scan Configure page."""
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}/scan-configure")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        ui.label("Scan Configure").classes("text-2xl font-bold")
        ui.label(
            "Scan a project directory to detect false positives and "
            "auto-generate suppression config (.ai-guardian/ai-guardian.json "
            "and .aiguardignore.toml). All scanners run regardless of "
            "enabled/disabled settings to discover all potential false "
            "positives upfront."
        ).classes("text-xs text-grey-6")

        with ui.card().classes("w-full"):
            ui.label("Scan Settings").classes("text-lg font-bold")
            with ui.row().classes("items-center gap-2 w-full"):
                path_input = (
                    ui.input(
                        label="Project Directory",
                        value=str(Path.home()),
                    )
                    .props("dense outlined")
                    .classes("flex-grow")
                    .style("font-family: monospace")
                )
                ui.button(
                    icon="folder_open",
                    on_click=lambda: _open_browse_dialog(path_input),
                ).props("dense flat")

            with ui.row().classes("items-center gap-4"):
                threshold_input = (
                    ui.number(
                        label="FP Threshold (min files)",
                        value=10,
                        min=2,
                        step=1,
                    )
                    .props("dense outlined")
                    .classes("w-48")
                )
                ui.label(
                    "Patterns appearing in this many files are treated "
                    "as false positives."
                ).classes("text-xs text-grey-6")

            with ui.row().classes("items-center gap-4"):
                skip_hidden_check = ui.checkbox(
                    "Skip hidden directories (starting with .)",
                    value=True,
                )

        results_container = ui.column().classes("w-full gap-4")
        scan_result = [None]
        cancel_event = threading.Event()

        def _show_result_with_actions(result):
            """Render result + action buttons (used for both fresh and restored)."""
            scan_result[0] = result
            _render_results(results_container, result, daemon_name)

            with results_container:
                with ui.column().classes("w-full gap-2 mt-4"):
                    with ui.row().classes("items-center gap-3"):
                        ui.label("Save to:").classes("text-sm text-grey-4")
                        scope_toggle = (
                            ui.toggle(
                                {"project": "Project", "global": "Global"},
                                value="project",
                            )
                            .props(
                                "dense size=sm color=blue-grey-6 "
                                "text-color=white toggle-color=blue-6"
                            )
                            .classes("text-xs")
                        )

                    scanned_dir = scan_result[0].project_dir if scan_result[0] else ""

                    project_row = ui.row().classes("items-center gap-2 w-full")
                    with project_row:
                        ui.label("Project dir:").classes("text-xs text-grey-4")
                        save_dir_input = (
                            ui.input(value=scanned_dir)
                            .props("dense outlined")
                            .classes("flex-grow")
                            .style("font-family: monospace; font-size: 0.8rem")
                        )
                        ui.button(
                            icon="folder_open",
                            on_click=lambda: _open_browse_dialog(save_dir_input),
                        ).props("dense flat size=sm")

                    def _update_target():
                        scope = scope_toggle.value
                        if scope == "global":
                            from ai_guardian.config.utils import get_config_dir

                            target_label.text = str(
                                get_config_dir() / "ai-guardian.json"
                            )
                            project_row.set_visibility(False)
                        else:
                            d = save_dir_input.value.strip() or scanned_dir
                            target_label.text = str(
                                Path(d) / ".ai-guardian" / "ai-guardian.json"
                            )
                            project_row.set_visibility(True)

                    target_label = (
                        ui.label("")
                        .classes("text-xs text-grey-6")
                        .style("font-family: monospace")
                    )
                    _update_target()

                    scope_toggle.on_value_change(lambda _: _update_target())
                    save_dir_input.on_value_change(lambda _: _update_target())

                    with ui.row().classes("items-center gap-2"):
                        merge_btn = ui.button("Merge", icon="merge_type").props(
                            "color=positive"
                        )
                        overwrite_btn = ui.button("Overwrite", icon="sync").props(
                            "color=warning"
                        )
                        discard_btn = ui.button("Discard", icon="cancel").props(
                            "flat color=negative"
                        )

                    async def do_apply(overwrite=False):
                        scope = scope_toggle.value
                        target_dir = save_dir_input.value.strip() or scanned_dir
                        try:
                            await run.io_bound(
                                _apply_config,
                                target_dir,
                                scan_result[0].merged_config,
                                scan_result[0].analysis.recommended_ignore_paths,
                                scope,
                                overwrite,
                            )
                            _clear_session()
                            mode = "overwritten" if overwrite else "merged"
                            ui.notify(f"Config {mode} ({scope})", type="positive")
                        except Exception as exc:
                            ui.notify(f"Error applying config: {exc}", type="negative")

                    def do_discard():
                        results_container.clear()
                        scan_result[0] = None
                        _clear_session()
                        ui.notify("Changes discarded", type="info")

                    merge_btn.on_click(lambda: do_apply(overwrite=False))
                    overwrite_btn.on_click(lambda: do_apply(overwrite=True))
                    discard_btn.on_click(do_discard)

        def _store_session(result):
            try:
                from nicegui import app

                app.storage.user[_SESSION_KEY] = _serialize_result(result)
            except Exception:
                pass

        def _clear_session():
            try:
                from nicegui import app

                app.storage.user.pop(_SESSION_KEY, None)
            except Exception:
                pass

        def _restore_session():
            try:
                from nicegui import app

                stored = app.storage.user.get(_SESSION_KEY)
                if stored:
                    result = _deserialize_result(stored)
                    _show_result_with_actions(result)
            except Exception:
                pass

        _restore_session()

        with ui.row().classes("items-center gap-2"):
            scan_btn = ui.button("Run Scan", icon="search").props("dense")
            stop_btn = ui.button("Stop", icon="stop").props("dense color=negative")
            stop_btn.set_visibility(False)

        progress_state = {"phase": "", "file": "", "index": 0, "total": 0}

        async def do_scan():
            project_dir = path_input.value.strip()
            if not project_dir:
                ui.notify("Enter a project directory", type="negative")
                return
            if not Path(project_dir).is_dir():
                ui.notify("Directory does not exist", type="negative")
                return

            threshold = int(threshold_input.value or 10)
            if threshold < 2:
                threshold = 2

            cancel_event.clear()
            progress_state.update(phase="Starting...", file="", index=0, total=0)
            scan_btn.disable()
            stop_btn.set_visibility(True)
            results_container.clear()
            with results_container:
                with ui.column().classes("w-full gap-2 py-4"):
                    progress_label = ui.label("Starting...").classes("text-grey-4")
                    progress_bar = ui.linear_progress(
                        value=0, show_value=False
                    ).classes("w-full")
                    progress_file = (
                        ui.label("")
                        .classes("text-xs text-grey-6")
                        .style(
                            "font-family: monospace; "
                            "max-width: 600px; "
                            "overflow: hidden; "
                            "text-overflow: ellipsis; "
                            "white-space: nowrap"
                        )
                    )

            def update_progress():
                phase = progress_state["phase"]
                total = progress_state["total"]
                index = progress_state["index"]
                if total > 0:
                    progress_label.text = f"{phase} {index}/{total} files"
                    progress_bar.value = index / total
                    short = progress_state["file"]
                    if len(short) > 80:
                        short = "..." + short[-77:]
                    progress_file.text = short
                else:
                    progress_label.text = phase
                    progress_bar.value = 0

            progress_timer = ui.timer(0.2, update_progress)

            try:
                result = await run.io_bound(
                    _run_scan,
                    project_dir,
                    threshold,
                    cancel_event,
                    progress_state,
                    skip_hidden_check.value,
                )
                progress_timer.deactivate()

                if result is None:
                    results_container.clear()
                    with results_container:
                        ui.label("Scan cancelled.").classes("text-amber")
                    return

                _store_session(result)
                _show_result_with_actions(result)

            except Exception as exc:
                progress_timer.deactivate()
                results_container.clear()
                with results_container:
                    ui.label(f"Scan error: {exc}").classes("text-red")
            finally:
                scan_btn.enable()
                stop_btn.set_visibility(False)

        def do_stop():
            cancel_event.set()

        scan_btn.on_click(do_scan)
        stop_btn.on_click(do_stop)


def _apply_config(
    project_dir, merged_config, ignore_paths, scope="project", overwrite=False
):
    """Write config and aiguardignore files at the chosen scope."""
    import shutil

    from ai_guardian.scan_analyzer import merge_and_write_config

    if merged_config:
        if scope == "global":
            from ai_guardian.config.utils import get_config_dir

            config_path = get_config_dir() / "ai-guardian.json"
        else:
            config_path = Path(project_dir) / ".ai-guardian" / "ai-guardian.json"

        if overwrite:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            if config_path.exists():
                shutil.copy2(config_path, config_path.with_suffix(".json.backup"))
            import json

            config_path.write_text(
                json.dumps(merged_config, indent=2) + "\n", encoding="utf-8"
            )
        else:
            merge_and_write_config(config_path, merged_config)

    if ignore_paths:
        from ai_guardian.project_init import ProjectInitializer

        initializer = ProjectInitializer(Path(project_dir))
        initializer.write_aiguardignore(ignore_paths)
