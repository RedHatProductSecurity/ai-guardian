# Uninstall and orphaned-integration recovery

AI Guardian's hooks, plugins/extensions, and MCP registrations live in host-owned
files, outside its Python installation. Removing a package, virtual environment,
interpreter, or launcher first can leave those registrations behind. A startup
fallback cannot run when its executable or interpreter no longer exists.

**These are operator-terminal lifecycle tools, not agent tools.** They are never
invoked automatically by a hook, daemon, SDK, or MCP server. Agent-originated
execution of the recovery entrypoint and identified uninstall wrappers is denied,
including in trusted development sessions. A genuine security denial is not an
orphan and must not trigger cleanup. No hook response, strict failure setting,
host permission policy, or security configuration is relaxed by recovery.

## Prerequisites and obtaining the tools

Use a reviewed checkout of the desired AI Guardian release, or download
`uninstall.sh` / `uninstall.ps1` and `scripts/ai_guardian_recovery.py` from the
**same revision**, retaining that directory layout. The recovery engine uses only
the Python standard library. It requires an **independent Python 3.11+** that has
not been removed with AI Guardian; this is separate from the application's
Python 3.10 minimum. No AI Guardian import, host CLI, Node/npm, daemon, scanner,
network connection, or WSL is needed with the companion engine present.

The Bash wrapper also supports the existing HTTPS `curl .../uninstall.sh | bash`
distribution path: if its companion is unavailable, it downloads the engine from
the repository's `main` branch using curl. For a version-pinned or offline review,
obtain both files from one release checkout instead. PowerShell requires both
local files and does not download or execute an additional network payload.

Close the affected IDEs/CLIs and, for normal package uninstall, close the tray and
stop the daemon through their ordinary operator controls first. Read the preview
before applying changes. Do not run recovery against production configurations as
a test of host failure behavior.

## Normal uninstall

On POSIX, `bash uninstall.sh --dry-run` previews user integration cleanup and
normal uninstall. `bash uninstall.sh` confirms integration changes, then confirms
process/desktop/package removal. Package detection supports uv tool, the dedicated
`~/.ai-guardian-venv`, pyenv's `ai-guardian` environment, and the selected Python's
pip installation. Integration failures stop the workflow before package/data
removal. Project integrations are not touched unless explicitly selected.

On Windows, use native PowerShell, for example `./uninstall.ps1 -DryRun` followed
by `./uninstall.ps1`. `-Python 'C:\Python312\python.exe'` selects the independent
interpreter. The wrapper removes the matching uv tool or the selected Python's
pip installation after successful integration cleanup. Other interpreter/venv
installations must be removed with their original package manager. It does not
signal processes, delete virtual environments, or remove desktop/startup entries.
Those are deliberate Windows limitations, not a claim of POSIX feature parity.

Both paths preserve AI Guardian settings, logs, caches, and violation history by
default. POSIX `--all` explicitly opts into deleting AI Guardian config/state/cache
and violation history; it cannot be combined with integration-only recovery.
Windows has no data-deletion option. Neither path uninstalls Python, uv, pyenv,
scanners, host CLIs, or unrelated integrations.

## Orphan recovery without the package

Use integration-only mode when the application is already absent or when only
registrations need repair. This does **not** stop processes, remove packages or
desktop entries, or modify AI Guardian settings/history.

```bash
bash uninstall.sh --integrations-only --scope user --dry-run
bash uninstall.sh --integrations-only --scope user
```

```powershell
./uninstall.ps1 -IntegrationsOnly -Scope user -DryRun
./uninstall.ps1 -IntegrationsOnly -Scope user
```

The standalone engine can also be run directly with independent Python:
`python3 -I -S scripts/ai_guardian_recovery.py --scope user --dry-run`.
`-I -S` excludes application/site imports and environment-based Python injection;
it does not disable host or AI Guardian security checks.

### Explicit project selection

Choose `project` to leave user integration files alone, or `both` for user files
and explicitly named project roots. Project-only scope requires integration-only
mode in the wrappers. There is no repository, parent, child, or home-directory
crawl, and the current directory is never an implicit project selection.

```bash
bash uninstall.sh --integrations-only --scope project --project /work/app --dry-run
```

```powershell
./uninstall.ps1 -IntegrationsOnly -Scope project -Project 'C:\work\app' -DryRun
```

Repeat Bash `--project` for more roots; PowerShell accepts a `-Project` string
array when invoked in a PowerShell session. Review each scope separately.
Noninteractive operator automation may use `--yes` / `-Yes`; these flags do not
override ownership checks, parser errors, file safety checks, or agent denial.

## Cleanup inventory and preservation contract

The finite inventory follows `setup/hooks.py`, `setup/mcp.py`, and `ide_paths.py`.
The [relocation table](AGENT_SUPPORT.md#ide-specific-home-and-configuration-paths)
defines home-variable precedence, including Gemini's nested `.gemini` directory,
OpenClaw's state-versus-config distinction, and OpenCode's explicit file override.
Only the effective selected home is visited, not every previous installation.
Run separately for other deliberately selected historical homes.

| Surface | Selected cleanup targets |
|---|---|
| Claude, Cursor, Copilot, Grok, Codex, Windsurf, Gemini, Augment, Antigravity, Crush | Owned commands in their known hook containers; Copilot's top-level arrays and Antigravity's named namespace included |
| JSON/JSONC MCP | Exact `ai-guardian` entries with an owned local launch command; unrelated names, remote/custom servers, settings and containers retained |
| Codex/Grok TOML | Owned `[mcp_servers.ai-guardian]`, quoted spelling and child tables; other table contents retained and complete parsed result verified |
| Codex legacy | Selected home's `codex.json`, plus historical home-level `codex.json`, only when an owned registration exists |
| OpenCode V1/V2 | Selected JSON/JSONC, legacy `mcp.ai-guardian`, V2 `mcp.servers.ai-guardian`, owned absolute/file-URI V1 plugin registrations; current plugin/shared bridge and old discovery-directory bridge |
| Pi | Current managed `ai-guardian/index.ts` and matching `package.json`, and owned legacy flat `ai-guardian.ts`, in user or explicitly selected project scope |
| AiderDesk/OpenClaw | Generated `index.ts`, matching package manifest and shared bridge in the selected extension/plugin home |
| Cline/ZooCode/Kiro project scripts | Only known event filenames and Windows script variants with the exact generated single-command shape; never their shared hook directories |
| Other selected project files | Known Claude/Cursor/Codex/Copilot/Grok/Gemini/Antigravity/Crush files, project OpenCode JSON/JSONC and `.opencode` artifacts; user-home overrides do not redirect these paths |

Ownership is conservative: an exact executable/module launch, the generated
source-version marker, or a matching managed package identity is required. A
name containing `ai-guardian`, a comment, a similarly named binary, or an
unrecognized source file is insufficient. Mixed/custom compound hook commands,
remote servers, ambiguous same-name plugins and unsupported TOML layouts are
retained rather than guessed at. Inline TOML MCP definitions currently require
operator review. A nonzero result names every known retained/failed path without
printing configuration values or raw parser exceptions.

Every edited or removed integration file gets an exact, unique sibling
`*.ai-guardian-backup-<id>.bak`; existing backups are never overwritten.
Backup files use POSIX mode `0600`; Windows files inherit their parent directory's
ACL, so the selected configuration directory must already be access-restricted.
JSONC comments/formatting are retained around surgical member deletions. TOML edits
are validated against the complete original settings minus the owned server.
Writes use a same-directory temporary file and atomic replacement. Link/reparse
paths, hard links, non-regular/oversized files, parse errors, duplicate JSON keys,
unwritable paths, failed backups and intervening content changes fail safely.
These checks reduce accidental damage; they are not an adversarial filesystem
transaction or a substitute for closing concurrent config editors.

Preview creates no backups or config writes. Exit **0** means the selected cleanup
completed (or a successful preview); **1** means cancellation or partial failure;
**2** means invalid arguments/prerequisites. Review originals/backups after partial
failure and rerun only after resolving the reported conditions. Repeated successful
cleanup is a no-op and produces no additional backups. Backups may contain private
host configuration; protect and retain them under your own retention policy.

Dependency caches/lockfiles and unknown files inside managed extension directories
are deliberately retained; only generated entrypoints/manifests/bridges are
removed. Skills, rules, static guidelines, project source, Git hooks and
`.pre-commit-config.yaml` are outside this IDE integration recovery scope. Manage
pre-commit integrations separately using the [pre-commit guide](PRE_COMMIT.md).
No system/enterprise, dashboard/cloud, remote/container, or other user's
configuration is modified. A leftover directory is not evidence that its removed
entrypoint is still registered.

## Missing-runtime lifecycle matrix

Evidence as of **2026-10-24**: source/setup contracts and isolated recovery tests,
**not live host qualification**. `U` means the host's exact UI/exit/continuation
behavior has **not been experimentally verified** for any of these three cases:
missing pinned executable, missing interpreter, missing launcher/module. All three
prevent the unavailable application from returning its normal decision. A surviving
Python launcher can handle application import failure; it cannot handle its own
absence. Do not equate import failure with a real security denial.

`H/U`: installed event invokes the missing runtime; host outcome unverified.
`L/U`: plugin/extension loads but its child launch or bridge may fail; load/runtime
outcome unverified. `M/U`: owned MCP local process cannot initialize; host error/
retry/continuation unverified. `—`: no managed surface for that stage.

| Host | Startup/lifecycle | Prompt | Tool | Plugin/extension | MCP | Known contract, not a host-crash claim |
|---|---|---|---|---|---|---|
| Claude Code (`claude`) | H/U | H/U | H/U | — | M/U | Nested command hooks; missing-process handling is outside the surviving launcher |
| Cursor (`cursor`) | — | H/U | H/U | — | M/U | Setup sets `failClosed: true` on decision hooks; observation hooks have no decision channel |
| Copilot (`copilot`) | — | H/U | H/U | — | M/U if explicitly configured | Top-level managed event arrays |
| Grok Build (`grok`) | H/U | H/U | H/U | — | M/U | Only `PreToolUse` has a blocking decision channel |
| Codex CLI / desktop Codex mode (`codex`) | H/U | H/U | H/U | — | M/U | Managed lifecycle includes compaction/end; regular ChatGPT mode is not covered |
| Windsurf (`windsurf`) | — | H/U | H/U | — | M/U if configured | Nested hook events; no universal fail-open assumption |
| Gemini CLI (`gemini`) | H/U | H/U | H/U | — | M/U if configured | BeforeAgent/BeforeTool/AfterTool and startup registration |
| Antigravity (`antigravity`) | — | H/U (PreInvocation) | H/U | — | M/U | Post-tool observation has limited host data |
| Cline (`cline`) | — | H/U | H/U | — | M/U if configured | Project event scripts |
| ZooCode (`zoocode`) | — | H/U | H/U | — | M/U if configured | Shared Cline project-script surface |
| Kiro (`kiro`) | — | H/U | H/U | — | M/U if configured | Project event scripts; user MCP separate |
| AiderDesk (`aiderdesk`) | L/U | L/U | L/U | L/U | M/U if configured | TypeScript entrypoint delegates to shared child-process bridge |
| OpenClaw (`openclaw`) | L/U | L/U | L/U | L/U | M/U if configured | Plugin discovery and child-process failure are separate boundaries |
| OpenCode V1/V2 (`opencode`) | L/U | L/U | L/U | L/U | M/U if configured | V1 explicit registration and V2 auto-discovery; V2 MCP uses `mcp.servers` |
| Pi (`pi`) | L/U | L/U | L/U | L/U | L/U | Managed extension owns both hooks and MCP tool bridge; no native MCP file |
| Augment (`augment`) | — | — | H/U | — | M/U if configured | Pre/post-tool hook integration |
| Crush (`crush`) | — | — | H/U | — | M/U | Partial managed event coverage, not universal enforcement |
| Junie (`junie`) | — | — | — | — | M/U | MCP-only, static guidelines do not invoke a runtime |

The tests verify package-independent recovery for synthetic missing executable,
interpreter and module registrations; current setup schemas; JSON/JSONC/TOML;
mixed integrations; relocated paths; explicit projects; preview/backups;
cancellation, safe failure and idempotency. Existing startup-failure and strict
denial contracts remain unchanged. CI adds Linux/macOS Bash and native Windows
PowerShell lifecycle coverage; a configured CI gate is not evidence of a completed
run. No installed host or live user installation was removed during development.

For live qualification, use a disposable account per host/version/platform, install
mixed integrations, independently remove each pinned runtime component, exercise
each applicable startup/prompt/tool/plugin/MCP stage, record errors/exit codes and
whether the requested action ran, then preview/apply recovery and restart. Record
the exact evidence before changing a `U` cell. Never generalize a shell launch error
into a claim that an entire host crashes, or automatically erase security controls
after an ordinary denial. In particular, do not change Cursor's strict decision
policy merely to hide a missing-runtime error.

After cleanup, **fully restart** the affected host (including any background
service) to unload cached plugins and MCP connections. Recovery of one local scope
does not remove registrations loaded from another project, parent, system layer,
remote machine, or dashboard. Use the reported paths and host diagnostics to
identify remaining scopes; do not recursively remove shared configuration folders.
