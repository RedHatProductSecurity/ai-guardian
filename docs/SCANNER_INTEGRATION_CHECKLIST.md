# Scanner Integration Checklist

Use this checklist when adding or changing an external secret scanner engine or
a built-in security detection scanner. Complete the section that matches the
change, and record any non-applicable items in the issue or pull request. For
image and runtime changes, also follow the
[CLI/Runtime Integration Checklist](CLI_RUNTIME_CHECKLIST.md).

## Adding an External Secret Scanner Engine

Use this checklist when adding a third-party secret scanner that AI Guardian
installs or invokes as an external tool. The built-in detection scanner
checklist below applies when adding a new detector to the hook pipeline.

- [ ] **License and data flow** — Verify the upstream license for the selected
  release and review any distribution or service terms. Preserve required
  copyright and license notices when redistributing scanner binaries in
  installers or images. Document the license in
  `docs/SCANNER_INSTALLATION.md`; document copyleft terms and required notices
  in `docs/MULTI_ENGINE_SUPPORT.md`, following its
  [license considerations](MULTI_ENGINE_SUPPORT.md#license-considerations).
  Document whether scans send content or metadata to a remote service, and any
  required consent or credentials.
- [ ] **Pinned version and update checks** — Add the exact version to
  `[tool.ai-guardian.scanners]` in `pyproject.toml`; update
  `scripts/check_scanner_versions.py` and the integration workflow so the
  version and its release assets are verified.
- [ ] **Installer and CLI** — Add platform and architecture asset resolution,
  checksum or signature verification, scanner registration, CLI naming or
  aliases, and version reporting. Add related unit tests for supported assets,
  verification failures, installation, and CLI exposure.
- [ ] **Container images** — Install the pinned scanner during each supported
  image build, including OpenShell, so runtime policies do not need download
  access for scanner installation. Update container build checks where
  applicable.
- [ ] **Documentation and release notes** — Update the supported-scanner and
  installation documentation, explain any limitations or service
  requirements, and add a `CHANGELOG.md` entry.

## Adding a New Security Scanner

A scanner is a new detection engine that integrates into the hook pipeline and
`ai-guardian scan`. Use `supply_chain` (Issue #1055) and `code_scanning` (Issue
#828) as reference implementations. Every item below is required — missing any
one causes a broken or incomplete feature.

### 1. Dependency
- [ ] `pyproject.toml` — add fixed or optional dependency

### 2. Scanner module
- [ ] `src/ai_guardian/<scanner>.py` — scanner class with `scan(content, file_path)` → returns findings

### 3. Violation type
- [ ] `src/ai_guardian/constants.py` — add `ViolationType.<SCANNER> = "<scanner>"` to enum
- [ ] `src/ai_guardian/hook_processing.py` — add entry to `_ASK_VIOLATION_LABELS`

### 4. Config loading
- [ ] `src/ai_guardian/config/loaders.py` — add `_<SCANNER>_DEFAULTS` dict + `_load_<scanner>_config()` function

### 5. Hook integration
- [ ] `src/ai_guardian/hook_processing.py`:
  - Import `_load_<scanner>_config` at top of file
  - Add `_log_<scanner>_violation()` (follow `_log_supply_chain_violation` pattern)
  - Add `run_<scanner>_scan()` returning `ScanResult` with `result.extra["action"]` set
  - Wire into the correct hook path (PreToolUse Write/Edit, PostToolUse Bash, UserPromptSubmit, etc.)
  - Use `_handle_ask_mode_auto()` → `_log_ask_decision()` for ask-mode dispatch

### 6. Batch scan (`ai-guardian scan`)
- [ ] `src/ai_guardian/scanner.py` — add import, `_check_<scanner>()` method, call it in `_scan_file()` (and `_scan_image_file()` if applicable)
- [ ] `src/ai_guardian/sarif_formatter.py` — add `create_<scanner>_finding()` factory; import it in `scanner.py` inside the `HAS_SARIF` try block

### 7. MCP server
- [ ] `src/ai_guardian/mcp_server.py` — add suggestion string to `_SAFE_SUGGESTIONS` dict; `scan_directory` picks up new findings automatically via `FileScanner`

### 8. Config defaults & schema
- [ ] `src/ai_guardian/setup/config.py` — add `"_comment_<scanner>"` (top-level) **and** `"_comment_action"`, `"_comment_enabled"` etc. (nested inside the scanner dict) to `_get_default_config_template()`. These are auto-extracted into `CONFIG_FIELD_HELP` by `_build_field_help()` — every `_comment_*` key you add here becomes a tooltip automatically.
- [ ] `src/ai_guardian/help_content.py` — for any field not covered by a `_comment_*` key in `setup/config.py`, add a manual entry to `_FIELD_HELP_SUPPLEMENT` following the `"<scanner>.<field>"` key convention.
- [ ] `src/ai_guardian/schemas/ai-guardian-config.schema.json`:
  - Add `"<scanner>"` object with full property definitions
  - Add `"<scanner>"` to the `violation_type` enum array (two places: `enum` + `default`)
- [ ] `ai-guardian-example.json` — add fully-commented example block for the new section
- [ ] All four profile templates: `src/ai_guardian/templates/profiles/{minimal,standard,strict,moderator}.json`

### 9. TUI console
- [ ] `src/ai_guardian/tui/<scanner>.py` — new `*Content(Container)` panel (config status, violations, inline help). Add `_apply_tooltips()` method that calls `CONFIG_FIELD_HELP.get("<scanner>.<field>")` and sets `.tooltip` on key widgets (enable toggle, action select, etc.). Call `_apply_tooltips()` from `on_mount()` after `load_config()`.
- [ ] `src/ai_guardian/tui/app.py`:
  - Add `("Label", "panel-<scanner>")` to the relevant `NAV_GROUPS` section
  - Add `with Container(id="panel-<scanner>"): yield <Scanner>Content()` in the compose tree
  - Add `"panel-<scanner>": ("...")` entry to `PANEL_DESCRIPTIONS`
- [ ] `src/ai_guardian/tui/global_settings.py`:
  - Add `("<scanner>", "gs_<scanner>", "emoji Label")` to `FEATURE_TOGGLES`
  - Add `"<scanner>": {"schema_path": ..., "options": [...], "default": ...}` to `FEATURE_ACTIONS`
- [ ] `src/ai_guardian/tui/violations.py`:
  - Add `"<scanner>"` to `KNOWN_VIOLATION_TYPES`
  - Handle `vtype == "<scanner>"` in `_extract_matched_from_violation()`
  - Add `TabPane("Label", id="filter-<scanner>")` + `VerticalScroll(id="violations-list-<scanner>")` in compose
  - Add load call in `load_all_filters()`
- [ ] `tests/unit/test_tui.py` — update nav leaf count assertion

### 10. Web console
- [ ] `src/ai_guardian/web/pages/<scanner>.py` — new `create_<scanner>_page(service, daemon_name)` with enable toggle, action selector, config options. Import `field_help_icon` from `ai_guardian.web.components.help_panel` and add `field_help_icon("<scanner>")` next to section headers and `field_help_icon("<scanner>.<field>")` next to individual field labels (action, ignore_files, ignore_tools, etc.).
- [ ] `src/ai_guardian/web/app.py` — add `@ui.page("/{daemon_name}/<slug>")` route
- [ ] `src/ai_guardian/web/components/header.py` — add `("Label", "/<slug>")` to the relevant nav group
- [ ] `src/ai_guardian/web/pages/global_settings.py`:
  - Add `("<scanner>", "Label", "description")` to the relevant `DASHBOARD_SECTIONS` group
  - Add `"<scanner>": {...}` to `ACTION_MODES`
  - Add `"<scanner>": "<default>"` to `ACTION_DEFAULTS`
- [ ] `src/ai_guardian/web/pages/dashboard.py`:
  - Add `("<scanner>", "Label", "description")` to `DASHBOARD_SECTIONS`
  - Add `"<scanner>": "<slug>"` to `FEATURE_PAGE_SLUGS`
  - Add `"<scanner>": "<default_action>"` to `_DEFAULT_ACTIONS`
  - Handle the scanner in `_get_scanner_label()` if it produces violations
- [ ] `src/ai_guardian/web/pages/violations.py`:
  - Add `"<scanner>"` to `KNOWN_VIOLATION_TYPES`
  - Add `("Label", "<scanner>", "description")` to `FILTER_TABS`
  - Add `"<scanner>": [("Field", "key"), ...]` to `DETAIL_FIELDS`
  - Handle `vtype == "<scanner>"` in `_extract_matched_from_violation()`

### 11. Tests
- [ ] `tests/unit/test_<scanner>.py` — unit tests: clean input, known-bad input, config options (threshold, allowlist), suppression annotations, robustness (empty input, parse errors)

### 12. Help tooltips
- [ ] `src/ai_guardian/setup/config.py` — add `_comment_*` keys inside the scanner dict in `_get_default_config_template()` for each configurable field so they surface automatically as tooltips in both consoles
- [ ] `src/ai_guardian/help_content.py` → `_FIELD_HELP_SUPPLEMENT` — add any field that `setup/config.py` doesn't cover with a `_comment_*` key (use `"<scanner>.<field>"` keys)
- [ ] `src/ai_guardian/tui/<scanner>.py` — `_apply_tooltips()` sets `.tooltip` on key widgets from `CONFIG_FIELD_HELP`
- [ ] `src/ai_guardian/web/pages/<scanner>.py` — `field_help_icon("<scanner>.<field>")` called next to every section and field label
- [ ] `src/ai_guardian/web/pages/global_settings.py` — existing loop calls `field_help_icon(section)` and `field_help_icon(f"{section}.action")` automatically for any new scanner added to `FEATURE_GROUPS`
- [ ] `src/ai_guardian/tui/global_settings.py` — existing `_apply_tooltips()` loop covers any new scanner added to `FEATURES`

### 13. Don't forget
- [ ] `.aiguardignore.toml` scanner type — add to `SCANNER_TYPES` in `aiguardignore.py` if file-content based
- [ ] `docs/AGENT_SUPPORT.md` — add row to Violation Type Coverage Matrix
- [ ] `CHANGELOG.md` — add entry under `[Unreleased]`
- [ ] `src/ai_guardian/doctor.py` — add `check_<scanner>()` method to verify the scanner's underlying dependency is importable (use `importlib.util.find_spec()`); add it to the `checks` list in `run_all()`; add display name to `_CHECK_DISPLAY_NAMES`; update the check count assertion in `tests/unit/test_doctor.py::TestDoctorRunAll::test_run_all_returns_report`
