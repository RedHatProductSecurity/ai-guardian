# IDE/Agent Integration Checklist

Use this checklist when adding a new AI coding agent or changing an existing
IDE/agent integration. It is the implementation and verification companion to
the [Agent Support](AGENT_SUPPORT.md) capability reference.

The checklist applies to hook adapters, plugin or extension integrations,
MCP-only integrations, transcript readers, and the dummy-agent test harness.
Mark an item complete only when it is applicable and verified; record the
reason for items that do not apply in the issue or pull request.

## Support model

Classify the integration before making changes. An agent can have more than
one integration mode.

| Mode | Typical surfaces | Result to document |
|------|------------------|--------------------|
| Hook adapter | `hook_adapters/`, `setup/hooks.py` | Which lifecycle events are normalized and enforced |
| Plugin or extension | Agent plugin/extension source and registration | Installation, update, and removal behavior |
| MCP-only | `setup/mcp.py`, MCP server | Advisory capabilities and the absence of hook enforcement |
| Transcript reader | `scanners/transcript/` | Format, path discovery, and incremental scanning support |
| Pre-commit guard | `setup/hooks.py`, `examples/aider/` | Commit-time coverage and its relationship to real-time agent protection |
| Test harness | `dummy_agent.py`, scenario files | Scenarios that provide repeatable hook regression coverage |

For products with multiple host modes, document the boundary for each mode.
For OpenAI Codex, lifecycle hooks cover Codex CLI and Codex mode in the
ChatGPT desktop app. Regular ChatGPT mode is not currently protected by those
Codex hooks. Shared MCP configuration must be documented independently; MCP
availability does not imply hook enforcement.

## 1. Scope and capability record

- [ ] Choose a stable CLI key and display name. Keep aliases consistent with
  the agent's documented name.
- [ ] Record the supported agent versions, operating systems, and installation
  scope. AI Guardian installs hooks and MCP at the local user/desktop level by
  default. Project-level files are read-only discovery/health inputs unless an
  explicit, user-selected project setup flow is part of the supported design.
- [ ] If the agent has local and remote/cloud execution modes, document each
  configuration layer separately. Never imply that a local user config protects
  a remote run; provide an explicit project/team/enterprise target when the
  upstream contract requires one.
- [ ] Review the agent's hook, plugin, extension, MCP, and transcript
  contracts as applicable. Record upstream links and the applicable license
  decision before distributing integration code.
- [ ] Inventory the agent's lifecycle events and map them to the canonical
  events used by AI Guardian: `SessionStart`, `UserPromptSubmit`,
  `PreToolUse`, `PostToolUse`, `PostCompact`, and `SessionEnd`.
- [ ] Record event-specific matchers, timeouts, input channels, output
  channels, exit-code behavior, and whether the agent accepts modified output.
- [ ] Record the response contract for allow, block, warning, and redaction
  paths, including which messages reach the user and the agent.
- [ ] Identify configuration files, environment-variable overrides, project
  files, and whether the integration must preserve unrelated user settings.
- [ ] Identify transcript format and path behavior, including whether the
  agent supplies a path in hook data or requires default-path discovery.
- [ ] Record known limitations, unsupported events, platform differences, and
  a confidence level. Do not label an integration complete without evidence.

## 2. Runtime and setup implementation

### Hook adapter and registry

- [ ] Add or update the adapter in
  `src/ai_guardian/hook_adapters/<agent>.py`.
- [ ] Implement detection, input normalization, and response formatting for
  every supported event. Use the shared `NormalizedHookInput` contract.
- [ ] Add tool-name mappings when the agent uses names that differ from the
  canonical names consumed by the scanning pipeline.
- [ ] Add default transcript-path discovery when the agent does not provide a
  path in hook data.
- [ ] Register the adapter in
  `src/ai_guardian/hook_adapters/__init__.py`: imports, detection order,
  environment aliases, and public exports as applicable.
- [ ] Check detection precedence against every existing adapter so a new
  format cannot be claimed by the wrong adapter or by the fallback adapter.
- [ ] Update the legacy `IDEType` mapping when the adapter is used by a
  compatibility path.

### Setup, reconciliation, and optional surfaces

- [ ] Add or update the entry in `IDESetup.IDE_CONFIGS` in
  `src/ai_guardian/setup/hooks.py`, including display name, config path,
  environment override, hook schema, and script/plugin/extension flags.
- [ ] Define the required managed-hook manifest once in
  `MANAGED_HOOK_EVENTS_BY_IDE` and verify that setup, verification,
  reconciliation, doctor, tray health, and integration tests all consume it.
  Keep upstream events that an adapter can recognize but AI Guardian does not
  install separate from this manifest; they must not be reported as missing.
- [ ] Confirm `--ide <key>`, auto-detection, dry-run, forced update, and hook
  verification behavior for the integration.
- [ ] Preserve unrelated configuration and existing user-owned hooks during
  installation and reconciliation.
- [ ] Add the MCP client registration in `src/ai_guardian/setup/mcp.py` when
  the agent supports the MCP advisor.
- [ ] For every local/remote or desktop/cloud variant, verify the MCP
  registration source independently from hooks. Test that user-level files do
  not get reported as protecting a remote run, and that project files are only
  used when the upstream agent explicitly supports them; otherwise document
  the required dashboard/team/API registration.
- [ ] Add guidelines or rules setup in `src/ai_guardian/setup/rules.py` when
  the agent has a supported context-file mechanism.
- [ ] Add plugin or extension installation, update, and removal handling when
  the integration is not command-hook based.
- [ ] Add or update pre-commit setup, templates, and documentation when the
  integration relies on commit-time scanning rather than agent hooks.
- [ ] Add transcript registration in
  `src/ai_guardian/scanners/transcript/__init__.py` and the appropriate
  transcript module when transcript scanning is supported.
- [ ] Update auto-detection in `src/ai_guardian/daemon/auto_setup.py` and the
  installer scripts when fresh installation should discover the agent.
- [ ] Update console, tray, or status surfaces only when the integration adds
  a user-visible status or setup flow.
- [ ] Trace every setup and health entry point, not only the setup function:
  tray **Check hooks/MCP installation...**, tray **Manual setup (specific
  IDE** (including any explicit remote/project variant), `ai-guardian doctor`,
  `ai-guardian ide-setup`, and any REST/daemon setup-state view. They must use
  the same verification result, preserve the user installation scope by
  default, inspect effective user/project scope without silently modifying
  project files, and report incomplete hook or MCP state consistently.
- [ ] For proactive tray setup prompts, verify that Tkinter/Linux and the
  macOS native fallback expose the same per-integration install/never choices,
  a `Submit` action (without a redundant global Never button), visible snooze
  selection, and dismissal semantics. Verify that the native macOS path
  foregrounds one dialog and has no legacy multi-dialog fallback cascade.
  Ensure a startup check and a manual check cannot show competing snapshots or
  duplicate prompts; verify that an expired snooze and a newly detected
  integration both re-enter the automatic prompt flow.

## 3. Tests and validation

Run directly related unit tests locally. The full suite, integration tests,
and dummy-agent scenarios are exercised by CI according to `AGENTS.md`.

| Behavior | Minimum evidence | Common test locations |
|----------|------------------|-----------------------|
| Detection and normalization | Agent-shaped input selects the intended adapter and produces canonical fields | `tests/unit/test_hook_adapters.py`, `tests/unit/test_<agent>_support.py` |
| Response formatting | Allow, block, warning, and output-transform cases match the agent contract | Adapter tests and `tests/unit/test_hook_adapters.py` |
| Setup and config merge | Fresh setup, existing config, repeated setup, and drift reconciliation behave correctly | `tests/unit/test_setup.py` |
| Auto-detection and prompts | Installed-agent discovery and setup choices are stable | `tests/unit/test_auto_setup.py`, `tests/unit/test_proactive_prompt.py`, `tests/unit/test_cli_ide_setup.py` |
| Transcript scanning | Format parsing, path discovery, incremental positions, and duplicate handling work | `tests/unit/test_<agent>_transcript.py` |
| Hook pipeline | The normalized events reach the shared scanning pipeline | `tests/unit/test_hook_processing.py` and the relevant UX contract test |
| MCP integration | MCP registration and applicable advisor behavior work | `tests/unit/test_mcp_server.py`, `tests/integration/test_integration_mcp.py` |
| Installer behavior | Help, detection, and setup flags include the integration when applicable | `tests/test_install_script.py` |
| User experience | User-facing and agent-facing messages, setup choices, and status reporting are documented and tested | `tests/ux/` |
| Cross-platform behavior | Paths, permissions, process I/O, and executable selection work on supported platforms | Platform parametrization and CI matrix |

Complete the applicable checks:

- [ ] Add focused adapter tests for detection, normalization, event mapping,
  tool mapping, and response formatting.
- [ ] Add setup tests for config creation, merge behavior, verification, and
  reconciliation. Include both a fresh file and a pre-existing config.
- [ ] Add transcript tests for every supported format and path-discovery
  branch. If transcript scanning is not supported, document why.
- [ ] Add hook-pipeline or UX contract coverage for each newly user-visible
  behavior, including the expected permission and message flow.
- [ ] Add installer and auto-detection coverage when the integration is
  discoverable during installation.
- [ ] Use safe, synthetic fixtures only; never include real credentials or
  customer data in tests, docs, screenshots, or issue comments.
- [ ] Update `.github/workflows/release-readiness.yml` when the supported-agent
  setup list or its verification requirements change.
- [ ] Run the related unit tests, then run formatting and lint checks required
  by `AGENTS.md` for code changes.

### Isolated IDE hook matrix

`tests/integration/test_ide_hooks_e2e.py` installs each supported external IDE
integration into a temporary home and project, verifies the generated hook
manifest and MCP registration, and invokes representative allow, directory
block, and post-output redaction paths where the host exposes command hooks.
For Cursor, the local matrix verifies user-level MCP registration separately
from the cloud-project hook flow; project setup must not create a local MCP
file because Cloud Agent MCP is externally registered.
The `ide-hook-e2e` release-readiness matrix runs one IDE per job so failures
identify the IDE and event.

Plugin and extension integrations are verified through their generated
TypeScript bridge and registration because their host runtimes and SDKs are
not dependencies of this repository. Junie is MCP-only, so its test verifies
registration and records that no enforcement hook can be invoked. Windows
setup is structurally checked; the runtime command matrix runs on Ubuntu
because executing generated `.bat` hooks requires a Windows command host.

## 4. Documentation and release bookkeeping

- [ ] Update every applicable reference table in `docs/AGENT_SUPPORT.md`:
  Supported Agents, Hook Capability Matrix, Violation Type Coverage Matrix,
  Agent Confidence Levels, Hook Event Name Mapping, Response Format
  Differences, and Config File Locations.
- [ ] Update the architecture, setup, transcript, and known-limitations
  sections in `docs/AGENT_SUPPORT.md`.
- [ ] Add or update a focused deep-dive guide when setup or troubleshooting
  cannot be explained clearly in the shared support reference.
- [ ] Update `docs/README.md` and `mkdocs.yml` when creating a new document or
  adding a new integration guide.
- [ ] Keep `README.md` concise: link to the shared support reference and this
  checklist instead of duplicating capability tables.
- [ ] Update `AGENTS.md`, `docs/DEVELOPER_GUIDE.md`, or contributor guidance
  when the integration workflow changes.
- [ ] Add a `[Unreleased]` entry to `CHANGELOG.md` for notable integration or
  documentation changes.
- [ ] Link relevant upstream specifications and issue references, and make
  sure confidence and limitation claims match the available test evidence.
- [ ] Build the documentation locally when documentation or navigation files
  change; do not commit the generated `site/` directory.

## 5. Manual acceptance

Use an isolated test configuration and a disposable project where possible.

- [ ] Run setup in dry-run mode and verify that the proposed changes match the
  documented config path and event inventory.
- [ ] Run setup against a fresh configuration, then repeat it to confirm
  idempotence and verify the installed hook status.
- [ ] Exercise a benign prompt and tool call through the real agent or its
  documented simulator. Confirm the expected user and agent message channels.
- [ ] Exercise each applicable warning, block, and output-transform path with
  approved synthetic fixtures. Confirm that the observed result matches the
  documented protection level.
- [ ] Change or remove an AI Guardian-owned hook in the disposable config and
  verify that reconciliation restores the expected manifest without removing
  unrelated settings.
- [ ] Restart the agent and daemon, if used, and verify that sessions,
  transcript positions, and setup status remain consistent.
- [ ] If the agent supports transcripts, confirm that a new conversation is
  discoverable and that incremental scanning does not duplicate findings.
- [ ] Verify upgrade behavior from the previous supported configuration shape
  and record any upstream limitation that prevents full validation.
- [ ] Attach test commands, CI links, or manual evidence to the issue or pull
  request.

## Existing integration changes

For a change to an existing agent, start with the smallest applicable set and
expand it when a shared component is touched:

- [ ] Classify the change as adapter, setup, transcript, MCP, installer,
  console/tray, documentation, or upstream-contract change.
- [ ] Re-check the capability and limitation record against the current agent
  documentation.
- [ ] Run the focused tests for the changed surface and all tests that cover
  shared adapter or hook-processing code.
- [ ] Re-check every row in the support matrix affected by the change, rather
  than updating only the Supported Agents table.
- [ ] Re-check independent health renderers and launchers (doctor and tray
  menu actions) when setup paths, config scopes, or MCP registration change.
  Verify that setup remains user/desktop-scoped by default even when a
  project-level configuration is present, and test every explicit project
  setup action (CLI flag, directory picker, and resulting config paths).
- [ ] Re-run the manual acceptance items for installation, verification, and
  the affected user-visible behavior.
- [ ] Update the confidence level and release-readiness coverage when the
  evidence or support level changes.

## Definition of done

An integration is ready when all applicable checklist items are complete,
focused tests pass, documentation and code agree on capabilities and limits,
release-readiness coverage is synchronized, and the issue or pull request
contains enough evidence for another contributor to reproduce the result.
