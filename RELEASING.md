# Release Management Process

This document describes the release management process for AI Guardian.

## Automated Release Script (Recommended)

The fastest way to create a release — no AI agent required:

```bash
scripts/release.sh minor              # minor release (X.Y.Z -> X.(Y+1).0)
scripts/release.sh patch              # patch release (X.Y.Z -> X.Y.(Z+1))
scripts/release.sh major              # major release (X.Y.Z -> (X+1).0.0)
scripts/release.sh --dry-run minor    # preview without executing
```

The script automates prerequisite validation, Release Readiness CI, interactive
Cursor verification, release preparation, TestPyPI, production tagging,
publication checks, and merge-back. Run it as an authorized maintainer in your
terminal, outside an active DAF agent session. Land preparation changes through
the normal feature-branch review workflow first; do not launch it from a DAF
issue branch such as `2563`.

Start from a clean `main` synchronized with `origin/main`, with current remote
production tags. The script calculates the target from the latest local
production `v*` tag, not the development package version. For the 1.20.0 release,
preview with `scripts/release.sh --dry-run minor` and confirm `v1.19.0` →
`1.20.0`, branch `release-1.20`, and next development version `1.21.0-dev`.
Only then run `scripts/release.sh minor`. A dry run is a plan, not evidence that
the release gates passed. Complete all six Cursor events when prompted, and
verify TestPyPI and the reviewed release notes before approving production.

**Do not blindly re-run after a partial or published release.** A newly created
production tag changes the next calculated version. Reconcile the intended
version, existing branch/tags, and registry artifacts before resuming; never
replace an already published PyPI version.

**The final completion message is not release evidence.** Some publication,
container, and documentation failures only produce warnings. Match every CI run
to the intended source/tag commit, check its final conclusion, and independently
verify every deliverable in the [release checklist](#release-checklist). Keep
the release issue open until that evidence and the post-release checks exist.

**Requirements**: `gh` CLI (authenticated), `python3`, `git`, `sed`, `curl`, `git-cliff` (`brew install git-cliff`).

### One-time Read the Docs setup

The release script pushes semantic version tags but does not manage Read the Docs project settings. Configure this once in **Read the Docs → Admin → Automation Rules**:

1. Match: **SemVer versions**
2. Version type: **Tag**
3. Action: **Activate version**

The GitHub integration then builds each `vX.Y.Z` tag automatically. Read the Docs maps the greatest stable semantic version to `/en/stable/`, while `/en/latest/` continues to track `main`. The release script waits for and verifies the exact `/en/vX.Y.Z/` URL after pushing the production tag.

## Table of Contents

- [Automated Release Script](#automated-release-script-recommended)
- [Release Authorization Policy](#release-authorization-policy)
- [Version Numbering](#version-numbering)
- [Branch Strategy](#branch-strategy)
- [Release Workflow](#release-workflow)
- [Patch / Hotfix Workflow](#patch--hotfix-workflow)
- [Release Checklist](#release-checklist)
- [Version Infrastructure](#version-infrastructure)
- [Testing Releases with TestPyPI](#testing-releases-with-testpypi)

## Release Authorization Policy

**IMPORTANT:** Only repository maintainers can create release tags that trigger PyPI publication.

### Repository Access Model

This repository uses a **fork-based workflow**:

- **Maintainers** (@itdove): Have Write/Admin access
  - Can push to branches
  - Can create and push tags
  - Can create releases
  - Handle all PyPI publications

- **Contributors**: Must use forks (no direct access)
  - Cannot push tags
  - Cannot push to branches
  - All contributions via pull requests from forks
  - See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow details

### Why Fork-Based Workflow?

**Technical Enforcement**: Since GitHub free accounts don't support tag protection rules, the fork-based workflow provides:

1. ✅ **Prevents unauthorized tag creation** - Only maintainers have push access
2. ✅ **Standard open source practice** - Common workflow for OSS projects
3. ✅ **Code review required** - All changes go through PRs
4. ✅ **Release control** - Maintainers control all PyPI publications

### Authorized Release Managers

Currently authorized to create release tags:

- **@itdove** (Repository Owner)

### For Contributors

**You CANNOT create release tags.** Instead:

1. ✅ **Fork the repository** (see [CONTRIBUTING.md](CONTRIBUTING.md))
2. ✅ **Submit pull requests** with features/fixes
3. ✅ **Update CHANGELOG.md** in your PR under `[Unreleased]` section
4. ✅ **Maintainers handle releases** - they will create tags and publish

**DO NOT attempt to:**
- ❌ Create version tags (v1.2.0, etc.)
- ❌ Push tags to the main repository
- ❌ Modify version numbers in pyproject.toml or __init__.py

### Test Releases (TestPyPI)

**Maintainers only** can create test tags for TestPyPI validation:

```bash
# Use the /release skill
/release test

# Or manually
git tag -a v1.2.0-test1 -m "Test release"
git push origin v1.2.0-test1
```

Contributors can test locally but cannot push test tags to the repository.

### Automation Tools

Use `scripts/release.sh` for fully automated releases (no AI agent required):

```bash
scripts/release.sh minor   # Create minor version release
scripts/release.sh patch   # Create patch version release
scripts/release.sh major   # Create major version release
```

The `/release` skill is also available for AI-assisted releases via Claude Code.

The automated script also runs `scripts/sync_release_versions.py` so the
normal and OpenShell container defaults, pinned container examples, and root
README release image references move to the new stable version together. The
script fails if one of those active references is missing. CI repeats the
guard with:

```bash
python scripts/sync_release_versions.py --check
```

**Note**: Only maintainers should push release tags.

### Tag Monitoring

The `tag-monitor.yml` workflow provides additional security:

- Logs all tag creation events
- Verifies authorization for production tags
- Creates security issues for unauthorized attempts
- Provides audit trail

**Protected via CODEOWNERS**:
- `.github/workflows/publish.yml` - Tag-routed PyPI/TestPyPI publishing
- `.github/workflows/tag-monitor.yml` - Tag creation monitoring
- `RELEASING.md` - This file

Changes to these files require maintainer approval.

## Version Numbering

We follow [Semantic Versioning](https://semver.org/) (MAJOR.MINOR.PATCH):

- **MAJOR**: Breaking changes (incompatible API changes)
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)
- **Development**: X.Y.Z-dev (on main branch)

Examples:
- `1.0.0` - First stable release
- `1.1.0` - Added new features
- `1.1.1` - Bug fixes only
- `1.2.0-dev` - Development version on main branch

## Branch Strategy

### Main Branches

- **main**: Active development branch (latest features, version X.Y.0-dev)
- **release-X.Y**: Release branches (e.g., release-1.0, release-1.1)
- **hotfix-X.Y.Z**: Hotfix branches for critical fixes to released versions

### Tags

- **vX.Y.Z**: Git tags for each release (e.g., v1.0.0, v1.0.1, v1.1.0)

### Branch Lifecycle

```
main (v1.1.0-dev)
  |
  |--- release-1.0 (created from main when ready for v1.0.0)
  |      |
  |      |--- v1.0.0 (tagged after testing)
  |      |
  |      |--- cherry-pick fix from main (preferred for patch releases)
  |      |     |
  |      |     |--- v1.0.1 (tagged on release-1.0)
  |      |
  |      |--- (if release-1.0 deleted) hotfix-1.0.2 (created from v1.0.1 tag)
  |             |
  |             |--- v1.0.2 (tagged after fix)
  |
  |--- release-1.1 (created from main when ready for v1.1.0)
         |
         |--- v1.1.0 (tagged after testing)
```

## Release Workflow

### Prerequisites

1. All features for the release are merged to `main`
2. All tests pass on `main`
3. CHANGELOG.md is up-to-date in the Unreleased section
4. GitHub issues for the release are complete

### Cursor Hook Compatibility Verification

Before creating the release branch, verify that Cursor still supports hooks via `~/.cursor/hooks.json`. The `/release` skill automates this check as a mandatory gate.

If running manually:
1. Run: `python .claude/skills/release/release_helper.py cursor-verify-setup`
2. Perform manual Cursor test (see instructions printed by setup)
3. Run: `python .claude/skills/release/release_helper.py cursor-verify-analyze`
4. Run: `python .claude/skills/release/release_helper.py cursor-verify-cleanup`

If any hook event fails, investigate before proceeding with the release.

### Step-by-Step Release Process

#### 1. Create Release Branch

```bash
# Ensure main is up-to-date
git checkout main
git pull origin main

# Create release branch (e.g., release-1.0)
git checkout -b release-1.0 main

# Push release branch
git push -u origin release-1.0
```

#### 2. Update Version Numbers

Update version in **pyproject.toml**:
```toml
[project]
name = "ai-guardian"
version = "1.0.0"  # Remove -dev suffix
```

Update version in **src/ai_guardian/__init__.py**:
```python
__version__ = "1.0.0"  # Remove -dev suffix
```

Synchronize the Rust package manifest and lockfile:
```bash
python3 scripts/sync_rust_middleware_version.py --version 1.0.0
```

Commit the version bump:
```bash
git add pyproject.toml src/ai_guardian/__init__.py rust/openshell-middleware/Cargo.toml rust/openshell-middleware/Cargo.lock
git commit -m "$(cat <<'EOF'
chore: bump version to 1.0.0 for release

Prepare for v1.0.0 release:
- Update version in pyproject.toml

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"
```

#### 3. Update CHANGELOG.md

Review and consolidate user-impact entries, then move them into a dated version
section. Preserve a fresh `## [Unreleased]` section and update comparison links:

```markdown
## [1.0.0] - 2025-01-15

### Added
- Initial stable release
- [List of features added]

### Changed
- [List of changes]

### Fixed
- [List of bug fixes]

[1.0.0]: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.0.0
```

**Before committing or tagging**, change the release-branch README installer
URLs from `main` to the exact production tag. Synchronize active stable
references with `python3 scripts/sync_release_versions.py --stable-version 1.0.0`.
After all source documentation and references are final, regenerate
`docs/notebooklm-export.md` using the
[release export recipe](AGENTS.md#generating-combined-documentation-for-llm-upload).
Do not rewrite historical changelog entries or historical examples.

Commit the changelog:
```bash
git add CHANGELOG.md README.md container/Dockerfile container/Dockerfile.openshell container/README.md docs/notebooklm-export.md
git commit -m "$(cat <<'EOF'
docs: update CHANGELOG.md for v1.0.0 release

Move unreleased items to v1.0.0 section with release date.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"
```

#### 4. Run Tests and Final Validation

Use CI for the complete Python/OS test matrix, lint, integrations, smoke/scenario
containers, multi-architecture builds, and Rust validation. Locally, run only
directly related unit tests and complete affected UX contract files when fixing
code; documentation-only preparation does not require a full test run.

```bash
python3 .claude/skills/release/release_helper.py get-version
python3 scripts/sync_rust_middleware_version.py --version 1.0.0 --check
python3 scripts/sync_release_versions.py --check
```

#### 5. Push Release Branch

```bash
# Push the release branch with version bump and changelog
git push origin release-1.0
```

Obtain successful standard CI and Release Readiness evidence for the intended
source. Identify the actual workflow run by ref, commit, event, and creation
time, not simply the latest run. `gh run watch RUN_ID --exit-status` must finish
successfully and the run's conclusion must be `success`. Readiness must include
the Python 3.10–3.14 install matrix, upgrade, IDE/hooks, daemon/config/MCP,
smoke/scenario, container-build, and Rust middleware gates.

Complete [TestPyPI verification](#testing-releases-with-testpypi) from the
reviewed release commit before creating the production tag.

#### 6. Create Git Tag

```bash
# Create annotated tag
git tag -a v1.0.0 -m "Release version 1.0.0

See CHANGELOG.md for details.
"

# Push tag to remote - this triggers the GitHub Actions publish workflow
git push origin v1.0.0
```

**Important:** Pushing the tag will automatically trigger two GitHub Actions workflows:
1. **Publish Package** — builds and publishes to PyPI, creates a GitHub Release
2. **Build Container Images** — builds and pushes the normal image to
   `quay.io/redhatproductsecurity/ai-guardian:<version>` and the dedicated
   OpenShell image to `quay.io/redhatproductsecurity/ai-guardian-openshell:<version>`

The Read the Docs GitHub integration also builds the activated version tag. This requires the one-time SemVer tag activation rule described above.

Note: `:latest` tracks the main branch (updated on every merge), not releases,
in both primary Quay repositories. The OpenShell image has its own repository;
it is not represented by an `openshell` tag in the normal image repository.

#### 7. Verify GitHub Actions Workflows

After pushing the tag:

1. Go to GitHub Actions: https://github.com/RedHatProductSecurity/ai-guardian/actions
2. Check the "Publish Package" run for this exact tag/commit — require `success`
3. Check the "Build Container Image" run for this exact tag/commit — require `success`
4. Check PyPI: https://pypi.org/project/ai-guardian/
5. Check GitHub Releases: https://github.com/RedHatProductSecurity/ai-guardian/releases
6. Verify the versioned container image on quay.io:
   ```bash
   podman pull quay.io/redhatproductsecurity/ai-guardian:<version>
   podman run -it quay.io/redhatproductsecurity/ai-guardian:<version> ai-guardian --version
   podman pull quay.io/redhatproductsecurity/ai-guardian-openshell:<version>
   podman run --rm --entrypoint ai-guardian \
       quay.io/redhatproductsecurity/ai-guardian-openshell:<version> --version
   ```
7. Verify the GitHub Release wheel, sdist, four Rust archives, and `checksums.txt`;
   check SHA-256 values and agreement between Python and middleware versions.
8. Record both container manifests/digests and runtime AI Guardian versions.
9. Verify the exact versioned documentation at `https://ai-guardian.readthedocs.io/en/v<version>/`,
   `/en/stable/` at that release, and `/en/latest/` at `main`.

If a workflow fails, stop and inspect the matching run before deciding recovery.
Do not delete/repoint a published production tag or replace an uploaded PyPI
version. A partially published release needs an explicit maintainer recovery
decision and may require a new patch version.

#### 8. Update Install URLs in README.md

The `README.md` contains `curl` install commands that reference a specific git ref for `install.sh` and `install.ps1`. These URLs must point to the correct ref depending on the branch:

- **Release branches** (`release-X.Y`): URLs point to the **release tag** (e.g., `v1.11.1`) so users install the exact released version
- **Main branch**: URLs point to **`main`** since there is no PyPI release for the dev version — developers browsing main get the latest install script

**On the release branch:** verify that step 3 pinned installer URLs **before the
tag was created**. PyPI uses the README snapshot in that tag; changing URLs
after publication cannot repair the uploaded package.

**On main** (during merge-back):
```bash
# Ensure main's README points to main, not a version tag
# This should already be the case if main was set up correctly
grep 'raw.githubusercontent.com' README.md
# Should show: .../main/install.sh and .../main/install.ps1
```

**Why this convention?**
- Release branches serve stable users who want a known-good version
- Main serves developers who want the latest code
- There is no PyPI package for dev versions, so a version tag URL on main would be misleading

#### 9. Merge Back to Main and Bump Dev Version

```bash
# Switch to main
git checkout main

# Cherry-pick CHANGELOG update (NOT full merge — avoids version conflicts)
# For patch releases where main already has all the code changes:
git cherry-pick <changelog-commit-sha>  # Or manually add the version section

# For minor/major releases, merge the release branch:
git merge release-1.0 --no-ff -m "Merge release-1.0 into main"

# Bump both Python version files to "1.1.0-dev"
```

Update both Python version files, synchronize Rust, restore README installer
URLs to `main`, and retain the new stable container references:
```bash
python3 .claude/skills/release/release_helper.py update-version 1.1.0-dev
python3 scripts/sync_rust_middleware_version.py --version 1.1.0-dev
python3 scripts/sync_rust_middleware_version.py --version 1.1.0-dev --check
python3 scripts/sync_release_versions.py --check
```

Commit and push:
```bash
git add pyproject.toml src/ai_guardian/__init__.py rust/openshell-middleware/Cargo.toml rust/openshell-middleware/Cargo.lock README.md
git commit -m "$(cat <<'EOF'
chore: bump version to 1.1.0-dev

Begin development cycle for v1.1.0.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"

# Push to remote
git push origin main
```

## Patch / Hotfix Workflow

### When to Use

Use patch releases for:
- Critical bugs in production releases
- Security vulnerabilities
- Data corruption issues
- Severe performance problems

**Do NOT use patch releases for**:
- Minor bugs (wait for next minor release)
- New features
- Refactoring

### Which Approach to Use

| Situation | Approach |
|---|---|
| Minor release branch (`release-x.y`) still exists | **Preferred:** Apply fix on `release-x.y` directly |
| Minor release branch deleted | Create `hotfix-x.y.z` from last release tag |
| Emergency fix, no time to cherry-pick | Create `hotfix-x.y.z` from last release tag |

### Preferred: Patch on Existing Release Branch

When the `release-x.y` branch still exists, apply the patch fix there directly instead of creating a separate hotfix branch.

#### 1. Switch to the Release Branch

```bash
git checkout release-1.0
git pull origin release-1.0
```

#### 2. Apply the Fix

Cherry-pick the fix from main, or make the fix directly on the release branch:

```bash
# Option A: Cherry-pick from main (preferred when fix already merged to main)
git cherry-pick <commit-sha-of-the-fix>

# Option B: Make the fix directly on the release branch
# Make your fixes, write tests
pytest

git add <files>
git commit -m "$(cat <<'EOF'
fix: critical bug in permission validation

Fixes timeout issue when validating MCP permissions.

Fixes: #123

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"
```

#### 3. Update Version Numbers

Update to patch version in **pyproject.toml**:
```toml
version = "1.0.1"
```

Update to patch version in **src/ai_guardian/__init__.py**:
```python
__version__ = "1.0.1"
```

```bash
git add pyproject.toml src/ai_guardian/__init__.py
git commit -m "chore: bump version to 1.0.1"
```

#### 4. Update CHANGELOG.md

Add a new section for the patch:

```markdown
## [1.0.1] - 2025-01-20

### Fixed
- Critical timeout issue in permission validation (#123)

[1.0.1]: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.0.1
```

```bash
git add CHANGELOG.md
git commit -m "docs: update CHANGELOG for v1.0.1"
```

#### 5. Tag and Release

```bash
# Create tag on the release branch
git tag -a v1.0.1 -m "Patch release 1.0.1

Critical fix for permission validation timeout.
"

# Push release branch and tag
git push origin release-1.0
git push origin v1.0.1
```

The GitHub Actions workflow will automatically publish to PyPI and create a release.

#### 6. Cherry-pick to Main

```bash
# Cherry-pick the fix to main (if not already there)
git checkout main
git cherry-pick <commit-sha-of-the-fix>  # Only the fix commit, not version bumps
git push origin main
```

### Fallback: Hotfix Branch from Tag

When the `release-x.y` branch has been deleted or in emergencies, create a hotfix branch from the last release tag.

#### 1. Create Hotfix Branch

```bash
# Create hotfix branch from the release tag
git checkout -b hotfix-1.0.1 v1.0.0
```

#### 2. Fix the Bug

Make the necessary code changes to fix the critical bug.

```bash
# Make your fixes
# Write tests to verify the fix
pytest

# Commit the fix
git add <files>
git commit -m "$(cat <<'EOF'
fix: critical bug in permission validation

Fixes timeout issue when validating MCP permissions.

Fixes: #123

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"
```

#### 3. Update Version Numbers

Update to patch version in **pyproject.toml**:
```toml
version = "1.0.1"
```

Update to patch version in **src/ai_guardian/__init__.py**:
```python
__version__ = "1.0.1"
```

```bash
git add pyproject.toml src/ai_guardian/__init__.py
git commit -m "chore: bump version to 1.0.1"
```

#### 4. Update CHANGELOG.md

Add a new section for the hotfix:

```markdown
## [1.0.1] - 2025-01-20

### Fixed
- Critical timeout issue in permission validation (#123)

[1.0.1]: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/v1.0.1
```

```bash
git add CHANGELOG.md
git commit -m "docs: update CHANGELOG for v1.0.1 hotfix"
```

#### 5. Tag and Release

```bash
# Create tag
git tag -a v1.0.1 -m "Hotfix release 1.0.1

Critical fix for permission validation timeout.
"

# Push hotfix branch and tag
git push origin hotfix-1.0.1
git push origin v1.0.1
```

The GitHub Actions workflow will automatically publish to PyPI and create a release.

#### 6. Merge Back and Clean Up

```bash
# Cherry-pick the fix to main (NOT merge the version bumps)
git checkout main
git cherry-pick <commit-sha-of-the-fix>  # Only the fix commit, not version bumps
git push origin main

# Delete hotfix branch
git branch -d hotfix-1.0.1
git push origin --delete hotfix-1.0.1
```

## Release Checklist

Use this checklist for each release:

### Pre-Release
- [ ] All planned features merged to `main`
- [ ] Clean, synchronized maintainer checkout; tooling/authentication available
- [ ] Standard test/lint CI passes for the intended source
- [ ] Dependencies/security reviewed; critical/high fixes addressed and deferrals recorded
- [ ] Scope resolved; deferred issues remain open with limitations disclosed
- [ ] CHANGELOG.md reviewed for user impact, breaking upgrades, and current qualification evidence
- [ ] Cursor version and all six setup/manual-test/analyze/cleanup results recorded
- [ ] Dry run selects the intended version, release branch, and next development version

### Release Branch
- [ ] Create release branch (`release-X.Y`)
- [ ] Update both Python version files and synchronize Cargo.toml/Cargo.lock
- [ ] Preserve fresh Unreleased section, dated release notes, and correct comparison links
- [ ] Pin README installer URLs to the production tag before tagging
- [ ] Synchronize stable container references (`python scripts/sync_release_versions.py --stable-version X.Y.Z`)
- [ ] Regenerate docs/notebooklm-export.md after source docs/references are final
- [ ] Push release branch
- [ ] Successful Release Readiness evidence includes every required job for the intended source
- [ ] TestPyPI actual package version, metadata, README, contents, and clean installation verified
- [ ] Clean up temporary test tag; authorized maintainer approves production tag (`vX.Y.Z`)

### GitHub Actions & Release
- [ ] Matching Publish Package and Build Container Image runs both conclude `success`
- [ ] PyPI exact version, clean installation, CLI/doctor, and previous-stable upgrade verified
- [ ] GitHub Release notes, wheel, sdist, four middleware archives, and checksums verified
- [ ] Python/middleware versions agree; non-Python archives are not PyPI distributions
- [ ] Both separate Quay repositories have versioned manifests/digests and runtime-version evidence
- [ ] Exact versioned Read the Docs site works; stable points to it and latest remains main

### Post-Release
- [ ] Merge release branch back to `main`
- [ ] Bump both Python files and Rust to the next development version (`X.Y+1.0-dev`)
- [ ] Restore README installer URLs to main and retain new stable container references
- [ ] Rust/stable-reference checks pass and the new Unreleased section is usable
- [ ] Attach source/tag, CI/manual evidence, registry URLs, checksums/digests, docs, and deferrals to the issue
- [ ] Close the release issue only after all deliverables are independently verified
- [ ] Announce release (if applicable)

### Patch / Hotfix (if needed)
- [ ] Check if `release-x.y` branch exists (preferred) or create `hotfix-x.y.z` from tag (fallback)
- [ ] Apply fix (cherry-pick from main or fix directly)
- [ ] Update version to patch level
- [ ] Update CHANGELOG.md
- [ ] Create and push tag
- [ ] Verify GitHub Actions completes
- [ ] Cherry-pick fix to `main` (if not already there)
- [ ] (Hotfix branch only) Delete hotfix branch after merge

## Version Infrastructure

### Version Storage

Version number is stored in two locations that must be kept in sync:

1. **pyproject.toml** - Package metadata
   ```toml
   [project]
   version = "1.0.0"
   ```

2. **src/ai_guardian/__init__.py** - Runtime version
   ```python
   __version__ = "1.0.0"
   ```

**Important:** Always update both files when bumping versions.

This uses the modern Python packaging standard (PEP 621) with hatchling as the build backend.

### Active Stable Release References

The two package files above are the runtime/package version. `main` continues
to use a `-dev` package version, so stable container fallbacks and pinned
examples are maintained separately in:

- `container/Dockerfile`
- `container/Dockerfile.openshell`
- `container/README.md`
- `README.md`
- `docs/notebooklm-export.md`

Do not update historical examples or changelog entries. For a release, run the
project synchronizer with the new stable version; after merge-back, use its
`--check` mode to confirm the references still match the latest stable
`CHANGELOG.md` heading.

### Version Display

Users can check the version using:
```bash
ai-guardian --version
# Output: ai-guardian 1.0.0
```

### Development Versions

Development versions on `main` branch always have the `-dev` suffix:
- `1.0.0-dev` - Developing towards v1.0.0
- `1.1.0-dev` - Developing towards v1.1.0

This helps distinguish development builds from stable releases.

### Python Support Policy

Release `1.20.0` raises the minimum supported Python version from 3.9 to
3.10. This is a breaking support change under the project's compatibility
policy. The `1.19.x` release line (`1.19.0` last stable) is the last line compatible with Python 3.9.
Users must upgrade to Python 3.10 or newer before installing `1.20.0` or a
later release; users who cannot upgrade should pin `ai-guardian<1.20`.

## GitHub Actions CI/CD

### Workflows

The release-relevant GitHub Actions workflows include:

1. **test.yml** - Runs tests on Python 3.10, 3.11, 3.12, 3.13, 3.14
   - Triggered on: push to main, pull requests
   - Includes coverage reporting

2. **lint.yml** - Runs code quality checks (pylint, black, ruff, mypy)
   - Triggered on: pull requests

3. **publish.yml** - Routes `v*-test*` tags to TestPyPI; production version tags
   publish Python distributions to PyPI and create the GitHub Release with Rust
   middleware assets and checksums. The tag selects the registry; package
   metadata selects the uploaded version. Manual dispatch is not inherently a
   TestPyPI operation. Both registries require their matching trusted publisher.

4. **release-readiness.yml** - Validates installs, upgrade, IDE/hooks, daemon,
   config/MCP, smoke/scenarios, containers, and middleware compatibility.

5. **build-container.yml** - Publishes both separate versioned Quay images;
   `latest` remains the main-branch channel.

### Ubuntu Runner Policy

All GitHub Actions Linux release-readiness, wheel, PyPI, and container
publishing jobs are pinned to `ubuntu-26.04`. This keeps release artifacts and
trusted-publishing jobs independent of the moving `ubuntu-latest` image label.
The `.github/workflows/container-build-validation.yml` workflow exercises
scanners, smoke tests, scenario containers, Docker Buildx, QEMU, and
multi-architecture image builds on the same runner; release readiness invokes
it as an explicit gate. The supported Python 3.10 through 3.14 matrix runs in
the standard test workflow on `ubuntu-26.04`.

The Read the Docs build remains separately configured for `ubuntu-24.04` in
`.readthedocs.yaml`; that setting is not a GitHub Actions runner policy.
The pinned NVIDIA Ubuntu 24.04 base in `container/Dockerfile.openshell` is
likewise a runtime image choice and is unrelated to hosted runner selection.

### Setting Up PyPI Trusted Publishing

To enable automatic PyPI publishing:

1. Go to PyPI project settings: https://pypi.org/manage/project/ai-guardian/settings/
2. Navigate to "Publishing" section
3. Add a new publisher:
   - **PyPI Project Name**: ai-guardian
   - **Owner**: RedHatProductSecurity
   - **Repository**: ai-guardian
   - **Workflow**: publish.yml
   - **Environment**: production

This allows GitHub Actions to publish without storing API tokens.

### Setting Up TestPyPI Trusted Publishing

To enable automatic TestPyPI publishing for testing (recommended):

1. Create TestPyPI account: https://test.pypi.org/account/register/
2. Verify your email address
3. Go to TestPyPI publishing settings: https://test.pypi.org/manage/account/publishing/
4. Click "Add a new pending publisher"
5. Configure publisher:
   - **PyPI Project Name**: ai-guardian
   - **Owner**: RedHatProductSecurity
   - **Repository**: ai-guardian
   - **Workflow**: publish.yml
   - **Environment**: testpypi
6. Create GitHub environment at https://github.com/RedHatProductSecurity/ai-guardian/settings/environments:
   - Name: `testpypi`
   - (Optional) Add protection rules

See [Testing Releases with TestPyPI](#testing-releases-with-testpypi) for detailed usage instructions.

## Testing Releases with TestPyPI

Before publishing to production PyPI, you can test the entire release process using TestPyPI.

### Why TestPyPI?

**Benefits:**
- ✅ Test the entire release process without touching production
- ✅ Verify PyPI Trusted Publishing configuration works
- ✅ Catch packaging/metadata issues early
- ✅ Safe experimentation with workflow changes
- ✅ Standard best practice for Python projects

### Prerequisites

#### 1. TestPyPI Account
Create an account at https://test.pypi.org/account/register/ and verify your email.

#### 2. Configure Trusted Publishing on TestPyPI

1. Go to https://test.pypi.org/manage/account/publishing/
2. Click "Add a new pending publisher"
3. Configure publisher settings:
   - **PyPI Project Name**: `ai-guardian`
   - **Owner**: `RedHatProductSecurity`
   - **Repository name**: `ai-guardian`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `testpypi`
4. Save configuration

#### 3. Create GitHub Environment

1. Go to https://github.com/RedHatProductSecurity/ai-guardian/settings/environments
2. Click "New environment"
3. Name: `testpypi`
4. (Optional) Add protection rules:
   - Required reviewers: yourself
   - Deployment policy must admit the intended `v*-test*` tag refs, not only release branches
5. Save environment

### Testing a Release

#### Step 1: Use the reviewed release commit

The canonical script creates the test tag from the prepared release branch,
after version, README URL, stable-reference, and documentation-export updates.
For example, package metadata stays at `1.2.0` while the test tag is
`v1.2.0-test1`. The tag selects TestPyPI; it does **not** rewrite the distribution
version. Do not assume a `-test1` package version exists.

#### Step 2: Create and push the test tag

```bash
git tag -a v1.2.0-test1 -m "Test release v1.2.0-test1"
git push origin v1.2.0-test1
```

The tag must contain `-test` to select TestPyPI in `publish.yml`. Production
tags must not contain it. The script performs these operations for you.

#### Step 3: Monitor the matching Publish Package run

Select the `Publish Package` run for the exact test tag and source commit.
Require a successful conclusion; `gh run watch RUN_ID --exit-status` reports a
failed run as a command failure. Do not use an unrelated latest run as evidence.
Test tags publish Python distributions only, not production middleware assets
or a GitHub Release.

#### Step 4: Verify the actual uploaded package

For the example above, inspect
`https://test.pypi.org/project/ai-guardian/1.2.0/`, not a guessed test-suffixed
version. Verify metadata, Python minimum, README rendering and installer URLs,
package resources, wheel/sdist contents, and artifact identity against the
matching source and workflow hashes.

An existing TestPyPI version can be skipped rather than uploaded again. A green
workflow alone therefore does not prove the new artifact was tested. If files
already exist or the build changed, stop and reconcile the metadata and uploaded
artifacts; incrementing only the test tag does not change the package version.

#### Step 5: Install the verified TestPyPI wheel in a clean environment

Download the exact wheel from the matching TestPyPI version page and verify its
SHA-256 against that upload's evidence. Create a fresh virtual environment, then
install that local wheel; dependencies can come from ordinary PyPI:

```bash
python -m pip install ./ai_guardian-1.2.0-py3-none-any.whl
python -m pip check
ai-guardian --version
ai-guardian --help
ai-guardian doctor
```

Do not mix TestPyPI and PyPI indexes to select `ai-guardian`: the same version
could be resolved from the wrong registry. Installing the verified local wheel
establishes which artifact is under test. Also validate upgrade from the previous
stable version in an isolated environment.

#### Step 6: Clean up the temporary tag and approve production

After recording verification, remove only the intended temporary test tag:

```bash
git tag -d v1.2.0-test1
git push origin --delete v1.2.0-test1
```

Keep the reviewed release branch. Production must use the same reviewed commit;
any intervening change needs renewed verification. The script cleans up its test
tag and asks for explicit production-tag approval. Do not approve while any gate
or artifact identity is unresolved.

### Tag Naming Convention

- **TestPyPI:** `v1.2.0-test`, `v1.2.0-test1`, `v1.2.0-test2`
  - Pattern: `v*-test*` selects TestPyPI in `publish.yml`
  - Tag numbering does not change package metadata or permit replacing an upload

- **Production PyPI:** `v1.2.0`, `v1.2.1`, `v1.3.0`
  - Pattern: `v*` (without `-test` suffix) triggers production workflow
  - Only create after TestPyPI validation succeeds

### Manual Workflow Trigger

`publish.yml` also accepts manual dispatch, but it is **not** a dedicated
TestPyPI workflow. Registry routing still depends on the selected ref containing
`-test`. A dispatch on `main` or another non-test ref takes the production path;
do not use it as a TestPyPI shortcut. Prefer the reviewed test-tag route above.

### Troubleshooting

**Workflow fails with authentication error:**
- Verify TestPyPI Trusted Publishing is configured correctly
- Check that the GitHub environment `testpypi` exists
- Ensure workflow name matches `publish.yml` and environment matches `testpypi`

**Package upload fails:**
- Verify the actual package metadata version and whether files already exist
- Do not expect a new test tag alone to produce a new package version

**Installation from TestPyPI fails:**
- Install the verified local TestPyPI wheel in a fresh environment
- Resolve its dependencies separately from ordinary PyPI; retain artifact hashes

## Manual PyPI Publishing

If you need to publish manually (without GitHub Actions):

### 1. Install Build Tools

```bash
pip install --upgrade build twine
```

### 2. Build Distribution Packages

```bash
# Clean previous builds
rm -rf dist/ build/ *.egg-info

# Build packages
python -m build
```

### 3. Test on TestPyPI (Optional)

```bash
# Upload to TestPyPI
python -m twine upload --repository testpypi dist/*
```

Verify and install the exact uploaded wheel as described in
[TestPyPI verification](#testing-releases-with-testpypi), rather than mixing
package indexes.

### 4. Publish to Production PyPI

```bash
python -m twine upload dist/*
```

**Note:** You'll need PyPI credentials configured in `~/.pypirc` or via `TWINE_USERNAME` and `TWINE_PASSWORD` environment variables. See [PyPI publishing docs](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/) for details.

## References

- [Semantic Versioning](https://semver.org/)
- [Keep a Changelog](https://keepachangelog.com/)
- [Python Packaging User Guide](https://packaging.python.org/)
- [PEP 621 - Storing project metadata in pyproject.toml](https://peps.python.org/pep-0621/)
- [Hatchling Build Backend](https://hatch.pypa.io/latest/)
- [GitHub Actions - Publishing to PyPI](https://docs.github.com/en/actions/automating-builds-and-tests/building-and-testing-python#publishing-to-package-registries)
- [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
