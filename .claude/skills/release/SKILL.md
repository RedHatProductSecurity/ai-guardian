---
name: release
description: Automate project release workflow with version management, CHANGELOG updates, and git operations
user-invocable: true
---

# Release Skill

Automates the release management workflow for any project, following semantic versioning and Keep a Changelog conventions. Works with Python, Node.js, and other project types through automatic version file detection.

## Usage

```bash
/release minor              # Create minor version release (1.1.0 -> 1.2.0)
/release patch              # Create patch version release (1.1.0 -> 1.1.1)
/release major              # Create major version release (1.0.0 -> 2.0.0)
/release hotfix v1.1.0      # Create hotfix from v1.1.0 tag
/release test               # Create TestPyPI test release
```

## Authorization Notice

**IMPORTANT**: This repository uses a fork-based workflow.

- **Maintainers** (@itdove): Can use this skill to create and push releases
- **Contributors**: Should NOT create or push production tags
  - Fork the repository instead (see CONTRIBUTING.md)
  - Submit pull requests with changes
  - Update CHANGELOG.md in your PR
  - Maintainers will handle releases

**If you are a contributor (not @itdove):**
- ✅ You can use `/release test` for local testing
- ✅ You can use the skill to understand the process
- ❌ DO NOT push production tags (v1.2.0, etc.)
- ✅ Let maintainers create releases from your PRs

## Skill Invocation

When invoked with arguments (e.g., `/release minor`), this skill guides you through:

1. **Safety Checks**: Verify prerequisites before starting
2. **Release Readiness CI**: Trigger automated readiness workflow and wait for results
3. **Version Management**: Update package metadata and project-specific release references
4. **CHANGELOG Management**: Update CHANGELOG.md with proper format
5. **Git Operations**: Create branches, commits, and tags
6. **Post-Release Guidance**: Provide checklist for manual steps (maintainers only)

## Release Types

### Regular Release (`/release major|minor|patch`)

**Purpose**: Create a new production release from main branch

**Prerequisites**:
- All tests pass on main
- CHANGELOG.md has Unreleased section with changes
- Main branch is up-to-date

**Steps**:
1. Verify prerequisites (clean working directory, tests pass, CHANGELOG updated)
2. Run release readiness CI (mandatory — see Release Readiness CI section below)
3. Documentation review (mandatory — see checklist below)
4. Dependency security review (mandatory — merge open Dependabot CVE fixes)
5. Cursor hook compatibility verification (mandatory — see section below)
6. Create release branch (e.g., `release-1.2`)
7. Determine new version based on release type
8. Update version in all configured package files (remove `-dev` suffix)
9. Update CHANGELOG.md (move Unreleased to version section with date)
10. Update install URLs in `README.md` to point to the release tag (e.g., `v1.2.0`) — **MUST happen before tagging**
11. Synchronize project-specific stable references before tagging
12. Commit changes with proper commit message format
13. TestPyPI verification (recommended — see TestPyPI Verification section below)
14. Create tag and push
15. Verify PyPI publication and both versioned container images
16. Provide post-release checklist

### Hotfix Release (`/release hotfix <tag>`)

**Purpose**: Create a critical bug fix for an existing release

**Preferred approach**: If the minor release branch (`release-x.y`) still exists, apply the patch fix there directly instead of creating a separate hotfix branch. Only create a `hotfix-x.y.z` branch when the release branch has been deleted or in emergencies.

**Prerequisites**:
- Valid release tag exists (e.g., v1.0.0)
- Bug fix is truly critical

**Steps**:
1. Verify tag exists
2. Check if `release-x.y` branch exists
   - **If yes (preferred)**: Switch to `release-x.y`, cherry-pick or apply fix there
   - **If no (fallback)**: Create `hotfix-x.y.z` branch from the specified tag
3. Guide through bug fix implementation
4. Calculate hotfix version (increment patch)
5. Update version in both files
6. Update CHANGELOG.md with patch/hotfix entry
7. Provide instructions for tagging
8. Provide cherry-pick-to-main and cleanup guidance

### Test Release (`/release test`)

**Purpose**: Test release process with TestPyPI before production

**Prerequisites**:
- TestPyPI account configured
- GitHub Actions workflow set up

**Steps**:
1. Create test release branch
2. Calculate test version (add `-test` suffix)
3. Update version in both files
4. Create test tag (v*-test* pattern)
5. Provide TestPyPI verification steps
6. Provide cleanup instructions

## Version Management

### Auto-Detection

On first use, the skill automatically detects version files in your project by scanning for common patterns:

**Python projects**:
- `pyproject.toml`: `version = "X.Y.Z"`
- `setup.py`: `version="X.Y.Z"`
- `__init__.py`: `__version__ = "X.Y.Z"`

**Node.js projects**:
- `package.json`: `"version": "X.Y.Z"`

**Generic projects**:
- `VERSION` file: `X.Y.Z`
- `version.txt`: `X.Y.Z`

The detected configuration is saved to `.release-config.json` and can be edited manually if needed.

**CRITICAL**: All detected version files MUST be kept in sync. The skill automatically updates all configured files together.

### AI Guardian release references

AI Guardian keeps a stable container fallback on `main` even though the
package version on `main` is a `-dev` version. The package-aware helper cannot
infer that separate stable value, so the canonical release script also runs:

```bash
python scripts/sync_release_versions.py --stable-version X.Y.Z
```

This updates the active stable references in the normal and OpenShell
Dockerfiles, the root and container READMEs, and the generated documentation
export. It fails when an expected reference is missing. CI runs the matching
check automatically:

```bash
python scripts/sync_release_versions.py --check
```

Historical changelog entries and historical examples are intentionally not
rewritten. The release-readiness workflow derives its previous stable package
from `CHANGELOG.md`, so it does not require a manually maintained version pin.

**Version Format**:
- Production: `"1.0.0"` (semantic versioning)
- Development: `"1.1.0-dev"` (on main branch)
- Test: `"1.2.0-test1"` (for TestPyPI testing)

**Version Transitions**:
- Regular release: `1.1.0-dev` → `1.2.0` (remove -dev)
- Hotfix: `1.1.0` → `1.1.1` (increment patch)
- Test: `1.2.0-dev` → `1.2.0-test1` (replace -dev with -test1)
- Post-release: `1.2.0` → `1.3.0-dev` (increment minor, add -dev)

## CHANGELOG.md Format

**Location**: Project root directory (auto-detected as `CHANGELOG.md`)

**Format**: Keep a Changelog format (https://keepachangelog.com/)

**Structure**:
```markdown
## [Unreleased]

### Added
- New features

### Changed
- Changes to existing functionality

### Fixed
- Bug fixes

## [1.2.0] - 2026-04-08

### Added
- Feature X
- Feature Y

[Unreleased]: https://github.com/owner/repo/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/owner/repo/releases/tag/v1.2.0
```

**When updating for release**:
1. Move all `[Unreleased]` content to new version section
2. Add release date in YYYY-MM-DD format
3. Update comparison links at bottom
4. Create new empty `[Unreleased]` section

## Commit Message Format

Follow project conventions:

```
<type>: <subject>

<body>

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

**Types**:
- `chore:` - Version bumps, release preparation
- `docs:` - CHANGELOG updates
- `fix:` - Hotfix bug fixes
- `feat:` - New features (rare in release commits)

**Always use HEREDOC** for commit messages to ensure proper formatting:
```bash
git commit -m "$(cat <<'EOF'
chore: bump version to 2.2.0 for release

Prepare for v2.2.0 release:
- Update version in pyproject.toml
- Update version in devflow/__init__.py

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"
```

## Safety Checks

**Before starting any release**:
1. ✅ Verify git status is clean (no uncommitted changes)
2. ✅ Verify on correct branch (main for regular, tag for hotfix)
3. ✅ Verify tests pass: `pytest`
4. ✅ Verify CHANGELOG.md has Unreleased section (regular releases only)
5. ✅ Verify versions match between files

**Error Handling**:
- Dirty working directory → Abort, ask user to commit/stash changes
- Tests failing → Abort, ask user to fix tests first
- Wrong branch → Abort, guide to correct branch
- Missing CHANGELOG updates → Abort, ask user to update CHANGELOG

## Release Readiness CI (mandatory)

Before creating the release branch, trigger the automated release readiness workflow to validate install, upgrade, IDE setup, daemon, detection, config, and MCP server functionality.

**Workflow**: `.github/workflows/release-readiness.yml`

**Steps**:

1. **Trigger the workflow** on the current branch:
   ```bash
   gh workflow run release-readiness.yml --ref $(git branch --show-current)
   ```

2. **Wait for completion** (polls every 30 seconds):
   ```bash
   # Get the run ID
   sleep 5
   RUN_ID=$(gh run list --workflow=release-readiness.yml --limit 1 --json databaseId --jq '.[0].databaseId')

   # Wait for it to finish
   gh run watch "$RUN_ID"
   ```

3. **Check results**:
   - If **all jobs pass**: proceed with the release
   - If **any job fails**: abort the release and investigate
     ```bash
     gh run view "$RUN_ID" --log-failed
     ```

**Jobs validated**:
- `fresh-install` — Clean install across Python 3.9–3.14
- `upgrade-from-previous` — Upgrade from last stable release
- `multi-agent-setup` — All IDE adapters (claude, cursor, copilot, etc.)
- `daemon-lifecycle` — Daemon start/status/reload/pause/resume/stop
- `detection-end-to-end` — Secret, PII, and prompt injection detection
- `config-validation` — Config profiles, migration, doctor checks
- `mcp-server` — MCP server initialize and tool call response
- `smoke-tests` — End-to-end violation detection for all types (secret, PII, prompt injection, SSRF, directory blocking, config exfil, jailbreak, context poisoning)

**Skipping**: The readiness check may be skipped for hotfix releases (`/release hotfix`) when the fix is urgent, but this should be documented in the release notes.

**Note**: The release readiness workflow includes smoke tests (`smoke-tests.yml`) as a reusable workflow — no need to run smoke tests separately.

## Documentation Review (mandatory)

Before creating the release branch, compare docs against changes since the previous release tag:

1. **Review all docs/ files for accuracy**:
   ```bash
   find docs/ -name '*.md' -type f | sort
   ```
   Read each file and verify its content matches current functionality.

2. **Check for new features not yet documented**:
   ```bash
   git log --oneline <previous-tag>..HEAD --grep='feat'
   ```

3. **Verify README.md**:
   - Kept concise (~300 lines max) — detailed documentation belongs in `docs/` files, not README
   - Each feature gets one line plus a link to its `docs/` page
   - Security Disclaimer present and complete
   - Quick Start commands work
   - Feature list matches current capabilities
   - All links resolve (especially for PyPI)

4. **Verify CONTRIBUTING.md is current**

5. **Verify ai-guardian-example.json matches schema and setup.py defaults**

6. **Verify docs/COOKBOOK.md**:
   - If new config options were added in this release, add Q&A entries to the cookbook
   - If existing config behavior changed, update relevant cookbook entries

7. **Verify CHANGELOG.md**:
   - No back-and-forth entries
   - No bugs that only existed between releases
   - Organized by user impact (Added/Changed/Fixed/Security)

## Dependency Security Review (mandatory)

Before creating the release branch, check for open Dependabot security alerts and PRs:

1. **Check for open Dependabot security PRs**:
   ```bash
   gh pr list --label dependabot --state open
   ```

2. **Check for security advisories**:
   ```bash
   gh api repos/{owner}/{repo}/dependabot/alerts --jq '[.[] | select(.state=="open")] | length'
   ```

3. **Merge critical security fixes**:
   - Review and merge any open Dependabot PRs that address CVEs
   - Prioritize PRs with `security` label
   - At minimum, merge all **critical** and **high** severity updates before release

4. **Document any deferred updates**:
   - If a Dependabot PR is deferred (e.g., requires breaking changes), note it in the release notes
   - Create a follow-up issue for deferred security updates

**Skipping**: May be skipped for urgent hotfix releases, but this should be documented in the release notes.

## Cursor Hook Compatibility Verification (mandatory)

Cursor IDE uses its own hooks in `~/.cursor/hooks.json`. Since Cursor could change hook support in any update, each release must verify all 6 hook events still fire correctly. This is a semi-automated 3-step flow.

**Workflow**: `.claude/skills/release/release_helper.py` (cursor-verify-* subcommands)

### Step 1 — Setup (automated)

```bash
python .claude/skills/release/release_helper.py cursor-verify-setup
```

This command:
- Creates a debug hook script at `/tmp/cursor-hook-debug.sh`
- Backs up `~/.cursor/hooks.json`
- Adds debug hook entries alongside existing hooks for all 6 events (beforeSubmitPrompt, beforeReadFile, beforeShellExecution, afterShellExecution, preToolUse, postToolUse)
- Cleans any old debug log files
- Prints instructions for the manual test

### Step 2 — Manual Cursor test (release manager)

Follow the printed instructions:
1. Upgrade Cursor to the latest version (menu > Check for Updates, or download from cursor.sh)
2. Restart Cursor completely (quit and relaunch)
3. Open any project in Cursor
4. Type a prompt that triggers a file read (e.g., "Read the contents of README.md")
5. Type a prompt that triggers a shell command (e.g., "Run ls in the terminal")
6. Type a prompt that triggers a tool use (e.g., "Add a comment to README.md")
7. Wait for the response to complete
8. Close the Cursor chat session (or close Cursor entirely)
9. Return to this release session

### Step 3 — Analysis (automated)

```bash
python .claude/skills/release/release_helper.py cursor-verify-analyze
```

This command reads `/tmp/cursor-hook-debug-*.json` files and reports:
- PASS/FAIL per hook event with fire count
- Cursor version detected from the `cursor_version` field

### Cleanup (always run)

```bash
python .claude/skills/release/release_helper.py cursor-verify-cleanup
```

Removes debug hooks from hooks.json, deletes debug script and log files, removes backup.

### Decision

- **All 6 events PASS**: Proceed with release. Add to CHANGELOG: "Verified Cursor hook compatibility with Cursor vX.Y.Z"
- **Any event FAIL**: Block the release. Investigate whether Cursor dropped hook support. Only proceed with explicit override and documented justification.

**Skipping**: May be skipped for hotfix releases (`/release hotfix`) when the fix is urgent, but this should be documented in the release notes.

## TestPyPI Verification (recommended)

Before creating the production tag, verify the package builds and renders correctly on TestPyPI. This catches README rendering issues, missing files, and metadata problems before they reach the real PyPI (where you can't re-upload the same version).

**Workflow**: `.github/workflows/publish-test.yml`

**Steps**:

1. **Create a test tag** from the release branch (after all commits including URL updates):
   ```bash
   git tag -a vX.Y.Z-test1 -m "Test release vX.Y.Z-test1"
   git push origin vX.Y.Z-test1
   ```

2. **Wait for TestPyPI publish** workflow to complete:
   ```bash
   sleep 5
   RUN_ID=$(gh run list --workflow=publish-test.yml --limit 1 --json databaseId --jq '.[0].databaseId')
   gh run watch "$RUN_ID"
   ```

3. **Verify on TestPyPI**:
   - Check the project page: `https://test.pypi.org/project/ai-guardian/X.Y.Z-test1/`
   - Verify README renders correctly (install URLs, badges, formatting)
   - Verify metadata (version, description, classifiers)
   - Optionally test install: `pip install -i https://test.pypi.org/simple/ ai-guardian==X.Y.Z.test1`

4. **If issues found**: fix on release branch, delete the test tag, create a new test tag (`-test2`), and re-verify.

5. **If clean**: proceed with production tag creation.

6. **Clean up test tags** after production release:
   ```bash
   git tag -d vX.Y.Z-test1
   git push origin --delete vX.Y.Z-test1
   ```

**Skipping**: May be skipped for hotfix releases when the fix is urgent. Document the skip in the release notes.

**Why this matters**: PyPI does not allow re-uploading the same version. A README rendering bug or missing metadata on PyPI is permanent for that version — you'd need a patch release (X.Y.Z+1) to fix it.

## Container Image Release Verification

This repository publishes two different container products. The normal image
and the OpenShell sandbox image use separate primary Quay repositories:

- `quay.io/redhatproductsecurity/ai-guardian:<version>` — normal Docker/Podman
  support image
- `quay.io/redhatproductsecurity/ai-guardian-openshell:<version>` — OpenShell
  sandbox image

The build workflow also updates `:latest` in each repository after a successful
merge to `main`. The OpenShell image is never published as an `openshell` tag
in the normal repository and is not copied to the legacy `itdove` repository.
Use the release helper to print the canonical versioned references:

```bash
python .claude/skills/release/release_helper.py container-images X.Y.Z
```

After the production tag's `Build Container Image` workflow completes, verify
both manifests and at least one runtime version from each image:

```bash
podman manifest inspect quay.io/redhatproductsecurity/ai-guardian:X.Y.Z
podman manifest inspect quay.io/redhatproductsecurity/ai-guardian-openshell:X.Y.Z
podman run --rm quay.io/redhatproductsecurity/ai-guardian:X.Y.Z ai-guardian --version
podman run --rm --entrypoint /usr/local/bin/claude \
    quay.io/redhatproductsecurity/ai-guardian-openshell:X.Y.Z --version
```

If the OpenShell repository has not been created or the workflow cannot push
to it, stop the release and have a maintainer provision
`quay.io/redhatproductsecurity/ai-guardian-openshell` before retrying.

## Git Operations

**Branch Naming**:
- Regular release: `release-X.Y` (e.g., `release-2.2`)
- Patch fix: Prefer existing `release-X.Y` branch; use `hotfix-X.Y.Z` (e.g., `hotfix-2.1.1`) only when release branch is deleted
- Test release: `release-X.Y-test` (e.g., `release-2.2-test`)

**Tag Naming**:
- Production: `vX.Y.Z` (e.g., `v2.2.0`)
- Test: `vX.Y.Z-testN` (e.g., `v2.2.0-test1`)

**Important**:
- DO NOT push tags automatically - provide command for user to review and push
- DO NOT run destructive operations without confirmation
- DO provide clear instructions for manual steps

## Post-Release Checklist

**⚠️ MAINTAINERS ONLY** - Check project's RELEASING.md or CONTRIBUTING.md for authorized release managers.

**Before pushing tag:**
- [ ] Confirm you are authorized to create releases
- [ ] Review all changes on the release branch
- [ ] Verify tests pass locally
- [ ] Verify version is correct in all configured files

**After creating release tag:**
1. [ ] Push tag: `git push origin vX.Y.Z`
2. [ ] Monitor CI/CD pipeline (GitHub Actions, GitLab CI, etc.)
3. [ ] Verify package publication (PyPI, npm, etc.)
4. [ ] Verify both versioned container images, including the dedicated OpenShell repository
5. [ ] Verify release notes created
6. [ ] Test installation from package registry
7. [ ] Merge release branch back to main
8. [ ] Bump version to next dev cycle (X.Y+1.0-dev)
9. [ ] Ensure main branch `README.md` install URLs point to `main` (not a version tag — there is no PyPI release for dev versions)
10. [ ] Push main branch
11. [ ] (Hotfix only) Cherry-pick fix to main
12. [ ] Generate combined docs export — run the shell one-liner from AGENTS.md "Generating Combined Documentation for LLM Upload" section to create `docs/notebooklm-export.md`
13. [ ] Update NotebookLM sources — if the `notebooklm-mcp` MCP server is available, upload the generated `docs/notebooklm-export.md` and update other sources in the AI Guardian notebook using `source_add`
14. [ ] Generate demo guide — create `X.Y-demo-guide.md` in the external docs directory (see AGENTS.md) documenting new features with step-by-step demonstrations for stakeholder walkthroughs

**If you are NOT authorized:**
- ❌ DO NOT push the tag
- ✅ Create PR with the release branch
- ✅ Notify maintainers that release is ready
- ✅ Provide the tag command in PR description

## Workflow Examples

### Regular Minor Release

```bash
/release minor

# Skill will:
# 1. Auto-detect version files (first run only)
# 2. Verify prerequisites
# 3. Run documentation review checklist
# 4. Create release-1.2 branch
# 5. Update version 1.1.0-dev → 1.2.0 in all detected files
# 6. Update CHANGELOG.md for v1.2.0
# 7. Commit changes
# 8. Provide tag creation command: git tag -a v1.2.0 -m "..."
# 9. Provide post-release instructions
```

### Hotfix Release

```bash
/release hotfix v1.1.0

# Skill will:
# 1. Verify v1.1.0 tag exists
# 2. Check if release-1.1 branch exists
#    - If yes: switch to release-1.1 (preferred)
#    - If no: create hotfix-1.1.1 branch from v1.1.0
# 3. Wait for user to implement fix (or cherry-pick from main)
# 4. Update version to 1.1.1 in all configured files
# 5. Update CHANGELOG.md for v1.1.1
# 6. Commit changes
# 7. Provide tag creation and cherry-pick-to-main commands
```

### Test Release

```bash
/release test

# Skill will:
# 1. Create release-1.2-test branch
# 2. Update version 1.2.0-dev → 1.2.0-test1 in all configured files
# 3. Commit changes
# 4. Create test tag v1.2.0-test1
# 5. Provide test verification steps
# 6. Provide cleanup commands
```

## Implementation Guidelines

**When user invokes this skill**:

1. **Auto-detect version files** (first run only): Scan for common version file patterns
2. **Parse arguments**: Determine release type (major/minor/patch/hotfix/test)
3. **Run safety checks**: Verify prerequisites before proceeding
4. **Release readiness CI**: Trigger `release-readiness.yml` workflow and wait for all jobs to pass (regular releases only, may skip for urgent hotfixes)
5. **Documentation review**: Run the mandatory documentation review checklist (regular releases only)
6. **Dependency security review**: Check for open Dependabot CVE alerts and merge critical/high severity fixes (regular releases only)
7. **Cursor hook verification**: Run the semi-automated Cursor hook compatibility check (regular releases only, may skip for urgent hotfixes)
8. **Calculate new version**: Based on current version and release type
9. **Update version files**: Edit all detected package version files atomically
10. **Update CHANGELOG**: Move Unreleased to version section with date
11. **Update install URLs**: Replace `main` with release tag in README.md install commands (**before tagging** — PyPI uses the tag snapshot as package README)
12. **Synchronize release references**: Run `python scripts/sync_release_versions.py --stable-version X.Y.Z`
13. **Create commits**: Use proper commit message format
14. **TestPyPI verification**: Create test tag, verify README renders correctly on TestPyPI (recommended, may skip for hotfixes)
15. **Create production tag**: After TestPyPI verification passes
16. **Validate**: Run `python scripts/sync_release_versions.py --check` and ensure package versions match

**Error Recovery**:
- If any step fails, provide clear error message and recovery steps
- Never leave repository in inconsistent state
- If versions are out of sync, stop and report the issue
- If no version files detected, provide instructions for manual configuration

## Testing Strategy

**Before using this skill for production releases**:

1. **Test version detection**:
   ```bash
   python .claude/skills/release/release_helper.py get-version
   # Verify all version files detected correctly
   ```

2. **Test with test release first**:
   ```bash
   /release test
   # Verify workflow works end-to-end
   ```

3. **Verify version updates**:
   - Check all detected files updated correctly
   - Run `python scripts/sync_release_versions.py --check`
   - Verify versions match across all files
   - Verify -dev suffix handling

4. **Verify CHANGELOG updates**:
   - Unreleased section moved correctly
   - Date added in correct format
   - Comparison links generated

5. **Verify safety checks**:
   - Test with uncommitted changes (should abort)
   - Test on wrong branch (should abort)
   - Test with missing CHANGELOG updates (should abort)

## References

- **RELEASING.md** - Project-specific release procedures (if available)
- **CONTRIBUTING.md** - Project contribution guidelines (if available)
- **.release-config.json** - Auto-generated version file configuration
- **CHANGELOG.md** - Project changelog (Keep a Changelog format)
- **release_helper.py** - Python automation script
- **.github/workflows/** - CI/CD workflows (if applicable)

## Benefits

- ✅ **Project-agnostic**: Works with Python, Node.js, and generic projects
- ✅ **Auto-detection**: Automatically finds and configures version files
- ✅ Reduces human error in release process
- ✅ Ensures consistency with documented procedures
- ✅ Saves time by automating repetitive tasks
- ✅ Provides guardrails and safety checks
- ✅ Maintains high quality release standards
- ✅ Keeps version files in sync automatically
- ✅ Enforces fork-based workflow authorization (when configured)

## Configuration

The skill creates `.release-config.json` on first use. You can manually edit this file to:

- Add custom version file patterns
- Specify different CHANGELOG location
- Adjust version file descriptions

Example configuration:
```json
{
  "version_files": [
    {
      "path": "pyproject.toml",
      "pattern": "version = \"{version}\"",
      "description": "Python project metadata"
    },
    {
      "path": "src/myproject/__init__.py",
      "pattern": "__version__ = \"{version}\"",
      "description": "Python package version"
    }
  ],
  "changelog": "CHANGELOG.md"
}
```

## Future Enhancements

- Automatic CHANGELOG.md generation from git commits
- Integration with GitHub API for automated PR creation
- Automated package registry verification
- Support for monorepo version management
