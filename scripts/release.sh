#!/usr/bin/env bash
# Fully automated release script for AI Guardian.
# No AI agent required — just gh CLI, python3, git, and sed.
#
# Usage:
#   scripts/release.sh minor              # minor release (1.16.0 -> 1.17.0)
#   scripts/release.sh patch              # patch release (1.17.0 -> 1.17.1)
#   scripts/release.sh major              # major release (1.0.0 -> 2.0.0)
#   scripts/release.sh --dry-run minor    # show commands without executing
#   scripts/release.sh --skip-cursor patch
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HELPER="python3 ${REPO_ROOT}/.claude/skills/release/release_helper.py --repo ${REPO_ROOT}"

# --- CLI parsing -----------------------------------------------------------

DRY_RUN=false
SKIP_CURSOR=false
RELEASE_TYPE=""

usage() {
    cat <<'EOF'
Usage: scripts/release.sh [OPTIONS] <minor|patch|major>

Options:
  --dry-run        Show all commands without executing
  --skip-cursor    Skip Cursor hook verification
  -h, --help       Show this help message

Release types:
  minor   Bump minor version   (1.16.0 -> 1.17.0)
  patch   Bump patch version   (1.17.0 -> 1.17.1)
  major   Bump major version   (1.0.0 -> 2.0.0)
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)  DRY_RUN=true; shift ;;
        --skip-cursor) SKIP_CURSOR=true; shift ;;
        -h|--help)  usage ;;
        minor|patch|major) RELEASE_TYPE="$1"; shift ;;
        *) echo "Unknown argument: $1" >&2; usage ;;
    esac
done

[[ -z "$RELEASE_TYPE" ]] && { echo "Error: release type required" >&2; usage; }

# --- Helpers ----------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC} $*"; }
die()     { echo -e "${RED}✗${NC} $*" >&2; exit 1; }
section() { echo -e "\n${CYAN}═══ $* ═══${NC}\n"; }

confirm() {
    local prompt="$1"
    if $DRY_RUN; then
        echo "[dry-run] Would prompt: $prompt"
        return 0
    fi
    read -r -p "$prompt [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || die "Aborted by user"
}

run() {
    if $DRY_RUN; then
        echo "[dry-run] $*"
    else
        "$@"
    fi
}

# macOS vs GNU sed in-place flag
if sed --version >/dev/null 2>&1; then
    SED_INPLACE=(sed -i)
else
    SED_INPLACE=(sed -i '')
fi

cd "$REPO_ROOT"

# --- Phase 1: Validate prerequisites ---------------------------------------

section "Phase 1: Validate Prerequisites"

command -v gh >/dev/null 2>&1        || die "gh CLI not found (brew install gh)"
command -v python3 >/dev/null 2>&1   || die "python3 not found"
command -v git >/dev/null 2>&1       || die "git not found"
command -v sed >/dev/null 2>&1       || die "sed not found"
command -v git-cliff >/dev/null 2>&1 || die "git-cliff not found (brew install git-cliff)"

if ! $DRY_RUN; then
    gh auth status >/dev/null 2>&1 || die "gh not authenticated (run: gh auth login)"
fi

if [[ -n "$(git status --porcelain)" ]]; then
    die "Working tree is not clean. Commit or stash changes first."
fi

CURRENT_BRANCH="$(git branch --show-current)"
RESUMING=false
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    if [[ "$CURRENT_BRANCH" == release-* ]]; then
        RESUMING=true
        warn "Resuming on existing branch: $CURRENT_BRANCH"
    else
        die "Must be on main or a release-* branch (currently on: $CURRENT_BRANCH)"
    fi
fi

if ! $DRY_RUN && ! $RESUMING; then
    git fetch origin
    LOCAL="$(git rev-parse HEAD)"
    REMOTE="$(git rev-parse origin/main)"
    if [[ "$LOCAL" != "$REMOTE" ]]; then
        die "Local main is not up to date with origin/main. Run: git pull origin main"
    fi
fi

CURRENT_VERSION=$($HELPER get-version 2>/dev/null | grep "Current version:" | awk '{print $3}')
[[ -z "$CURRENT_VERSION" ]] && die "Could not determine current version"
info "Current version: $CURRENT_VERSION"

# Auto-populate CHANGELOG Unreleased section from git log if empty
if ! $DRY_RUN; then
    UNRELEASED_CONTENT=$(awk '/^## \[Unreleased\]/{found=1; next} /^## \[/{exit} found{print}' CHANGELOG.md | grep -v '^$' || true)
    if [[ -z "$UNRELEASED_CONTENT" ]]; then
        if command -v git-cliff >/dev/null 2>&1; then
            info "Generating CHANGELOG entries with git-cliff..."
            CLIFF_OUTPUT=$(git-cliff --unreleased --strip header 2>/dev/null || true)
            if [[ -n "$CLIFF_OUTPUT" ]]; then
                # Insert generated content after the ## [Unreleased] line
                awk -v content="$CLIFF_OUTPUT" '
                    /^## \[Unreleased\]/ { print; print ""; print content; next }
                    { print }
                ' CHANGELOG.md > CHANGELOG.md.tmp && mv CHANGELOG.md.tmp CHANGELOG.md
                info "CHANGELOG.md Unreleased section populated from git history"
            else
                die "git-cliff produced no output — add entries to CHANGELOG.md manually"
            fi
        else
            die "CHANGELOG [Unreleased] section is empty and git-cliff not installed.\nInstall: brew install git-cliff (or cargo install git-cliff)"
        fi
    fi
fi

if ! $DRY_RUN; then
    $HELPER validate --type regular || die "Prerequisite validation failed"
fi
info "Prerequisites validated"

# --- Calculate versions -----------------------------------------------------

# Use last v* tag as base (not code version) — correct for patch after minor bump
LAST_TAG=$(git tag --list 'v[0-9]*' --sort=-v:refname | grep -v '\-' | head -1)
[[ -z "$LAST_TAG" ]] && die "No release tags found (expected v*.*.* pattern)"
LAST_RELEASED="${LAST_TAG#v}"
info "Last release: $LAST_RELEASED (tag: $LAST_TAG)"

NEW_VERSION=$($HELPER calc-version "$LAST_RELEASED" "$RELEASE_TYPE")
[[ -z "$NEW_VERSION" ]] && die "Could not calculate next version"
info "New version: $NEW_VERSION"

# Extract major.minor for branch name
MAJOR=$(echo "$NEW_VERSION" | cut -d. -f1)
MINOR=$(echo "$NEW_VERSION" | cut -d. -f2)
RELEASE_BRANCH="release-${MAJOR}.${MINOR}"
TAG_NAME="v${NEW_VERSION}"

# Next dev version (for post-release merge back)
NEXT_MINOR=$((MINOR + 1))
NEXT_DEV_VERSION="${MAJOR}.${NEXT_MINOR}.0-dev"

echo "  Last release:     $LAST_RELEASED"
echo "  Release branch:   $RELEASE_BRANCH"
echo "  Tag:              $TAG_NAME"
echo "  Next dev version: $NEXT_DEV_VERSION"

# --- Phase 2: Release readiness CI -----------------------------------------

section "Phase 2: Release Readiness CI"

if $DRY_RUN; then
    echo "[dry-run] gh workflow run release-readiness.yml --ref main"
    echo "[dry-run] gh run watch <run_id>"
else
    info "Triggering release readiness workflow..."
    gh workflow run release-readiness.yml --ref main
    sleep 5
    RUN_ID=$(gh run list --workflow=release-readiness.yml --limit 1 --json databaseId --jq '.[0].databaseId')

    if [[ -z "$RUN_ID" ]]; then
        die "Could not find release readiness workflow run"
    fi

    info "Waiting for release readiness (run $RUN_ID)..."
    if ! gh run watch "$RUN_ID"; then
        echo ""
        warn "Release readiness FAILED. Showing failed logs:"
        gh run view "$RUN_ID" --log-failed | tail -50
        die "Release readiness check failed. Fix issues and retry."
    fi
    info "Release readiness passed"
fi

# --- Phase 3: Cursor hook verification -------------------------------------

section "Phase 3: Cursor Hook Verification"

if $SKIP_CURSOR; then
    warn "Cursor verification skipped (--skip-cursor)"
elif $DRY_RUN; then
    echo "[dry-run] Would prompt for Cursor hook verification"
else
    read -r -p "Run Cursor hook verification? [y/N] " cursor_answer
    if [[ "$cursor_answer" =~ ^[Yy]$ ]]; then
        $HELPER cursor-verify-setup || die "Cursor verify setup failed"

        echo ""
        echo "Perform the manual Cursor test now (see instructions above)."
        read -r -p "Press Enter when done with manual Cursor test..."
        echo ""

        if ! $HELPER cursor-verify-analyze; then
            $HELPER cursor-verify-cleanup
            die "Cursor hook verification FAILED"
        fi
        $HELPER cursor-verify-cleanup
        info "Cursor hook verification passed"
    else
        warn "Cursor verification skipped by user"
    fi
fi

# --- Phase 4: Create release -----------------------------------------------

section "Phase 4: Create Release Branch"

# Branch: create or switch to existing
if $RESUMING; then
    info "Already on $RELEASE_BRANCH"
elif git rev-parse --verify "$RELEASE_BRANCH" >/dev/null 2>&1; then
    run git checkout "$RELEASE_BRANCH"
    warn "Switched to existing branch: $RELEASE_BRANCH"
else
    run git checkout -b "$RELEASE_BRANCH"
    info "Created branch: $RELEASE_BRANCH"
fi

# Version: update (idempotent — writes same value if already correct)
run $HELPER update-version "$NEW_VERSION"
info "Version: $NEW_VERSION"

# CHANGELOG: skip if already updated for this version
if ! $DRY_RUN && grep -q "^## \[${NEW_VERSION}\]" CHANGELOG.md 2>/dev/null; then
    warn "CHANGELOG.md already has [${NEW_VERSION}] section — skipping"
else
    run $HELPER update-changelog "$NEW_VERSION"
    info "CHANGELOG.md updated"
fi

# README URLs: update only if still pointing to /main/
if [[ -f README.md ]]; then
    if $DRY_RUN; then
        echo "[dry-run] sed: replace /main/ with /${TAG_NAME}/ in README.md raw.githubusercontent URLs"
    elif grep -q "/ai-guardian/main/" README.md; then
        "${SED_INPLACE[@]}" "s|/ai-guardian/main/|/ai-guardian/${TAG_NAME}/|g" README.md
        info "README.md install URLs updated to ${TAG_NAME}"
    else
        warn "README.md URLs already updated — skipping"
    fi
fi

# Generate docs/notebooklm-export.md
section "Generating docs/notebooklm-export.md"

if $DRY_RUN; then
    echo "[dry-run] Would generate docs/notebooklm-export.md"
else
    {
        echo "# AI Guardian — Combined Documentation"
        echo ""
        echo "Auto-generated combined export of all project documentation."
        echo ""
        for f in README.md container/README.md $(find docs -name '*.md' -not -name 'notebooklm-export.md' | sort); do
            if [[ -f "$f" ]]; then
                echo ""
                echo "# === $f ==="
                echo ""
                cat "$f"
            fi
        done
        echo ""
        echo "# === ai-guardian-example.json ==="
        echo ""
        echo '```json'
        cat ai-guardian-example.json
        echo '```'
        for schema in src/ai_guardian/schemas/*.schema.json; do
            if [[ -f "$schema" ]]; then
                echo ""
                echo "# === $(basename "$schema") ==="
                echo ""
                echo '```json'
                cat "$schema"
                echo '```'
            fi
        done
        echo ""
        echo "# === CHANGELOG.md (recent) ==="
        echo ""
        awk '/^## \[[0-9]/{n++} n>2{exit} {print}' CHANGELOG.md
        echo ""
        echo "*(Earlier versions omitted — see CHANGELOG.md for full history)*"
    } > docs/notebooklm-export.md
    info "Generated docs/notebooklm-export.md"
fi

# Commit release changes (skip if nothing changed)
run git add pyproject.toml src/ai_guardian/__init__.py CHANGELOG.md README.md docs/notebooklm-export.md
if $DRY_RUN || ! git diff --cached --quiet 2>/dev/null; then
    run git commit -m "chore: release v${NEW_VERSION}

Prepare v${NEW_VERSION} release:
- Bump version to ${NEW_VERSION}
- Update CHANGELOG.md
- Update README.md install URLs to ${TAG_NAME}
- Regenerate docs/notebooklm-export.md"
else
    warn "No changes to commit — release commit already exists"
fi

run git push -u origin "$RELEASE_BRANCH"
info "Release branch pushed"

# --- Phase 5: TestPyPI verification ----------------------------------------

section "Phase 5: TestPyPI Verification"

TEST_TAG="${TAG_NAME}-test1"

if $DRY_RUN; then
    echo "[dry-run] git tag -a $TEST_TAG"
    echo "[dry-run] git push origin $TEST_TAG"
    echo "[dry-run] gh run watch (TestPyPI publish)"
    echo "[dry-run] git tag -d $TEST_TAG && git push origin --delete $TEST_TAG"
else
    # Clean up stale test tag from a previous run
    if git rev-parse "$TEST_TAG" >/dev/null 2>&1; then
        warn "Removing stale test tag $TEST_TAG from previous run"
        git tag -d "$TEST_TAG" 2>/dev/null || true
        git push origin --delete "$TEST_TAG" 2>/dev/null || true
    fi

    info "Creating test tag for TestPyPI verification..."
    git tag -a "$TEST_TAG" -m "Test release ${TEST_TAG}"
    git push origin "$TEST_TAG"

    sleep 5
    TEST_RUN_ID=$(gh run list --workflow=publish.yml --limit 1 --json databaseId --jq '.[0].databaseId')
    if [[ -n "$TEST_RUN_ID" ]]; then
        info "Waiting for TestPyPI publish (run $TEST_RUN_ID)..."
        gh run watch "$TEST_RUN_ID" || warn "TestPyPI publish may have failed"
    fi

    echo ""
    echo "Verify TestPyPI:"
    echo "  https://test.pypi.org/project/ai-guardian/"
    echo ""
    read -r -p "TestPyPI looks good? Continue to production tag? [y/N] " testpypi_answer

    info "Cleaning up test tag..."
    git tag -d "$TEST_TAG"
    git push origin --delete "$TEST_TAG"

    if [[ ! "$testpypi_answer" =~ ^[Yy]$ ]]; then
        die "Aborted after TestPyPI verification. Release branch is still at origin/$RELEASE_BRANCH."
    fi
    info "TestPyPI verification passed"
fi

# --- Phase 6: Production tag ------------------------------------------------

section "Phase 6: Production Tag"

if git rev-parse "$TAG_NAME" >/dev/null 2>&1; then
    warn "Tag ${TAG_NAME} already exists — skipping tag creation"
    if ! git ls-remote --tags origin "$TAG_NAME" | grep -q "$TAG_NAME"; then
        confirm "Tag exists locally but not on remote. Push ${TAG_NAME}?"
        run git push origin "$TAG_NAME"
        info "Tag ${TAG_NAME} pushed"
    else
        info "Tag ${TAG_NAME} already pushed to origin"
    fi
else
    confirm "About to tag ${TAG_NAME} and push (triggers PyPI publish + container build). Continue?"

    run git tag -a "$TAG_NAME" -m "Release ${NEW_VERSION}

See CHANGELOG.md for details."

    run git push origin "$TAG_NAME"
    info "Tag ${TAG_NAME} pushed"
fi

# --- Phase 7: Wait and verify ----------------------------------------------

section "Phase 7: Wait and Verify"

if $DRY_RUN; then
    echo "[dry-run] gh run watch (publish workflow)"
    echo "[dry-run] gh run watch (build-container workflow)"
    echo "[dry-run] pip install --dry-run ai-guardian==${NEW_VERSION}"
    echo "[dry-run] docker manifest inspect quay.io/redhatproductsecurity/ai-guardian:${NEW_VERSION}"
else
    info "Waiting for publish workflow..."
    sleep 10
    PUB_RUN_ID=$(gh run list --workflow=publish.yml --limit 1 --json databaseId --jq '.[0].databaseId')
    if [[ -n "$PUB_RUN_ID" ]]; then
        gh run watch "$PUB_RUN_ID" || warn "Publish workflow may have failed — check GitHub Actions"
    fi

    info "Waiting for container build workflow..."
    sleep 5
    CTR_RUN_ID=$(gh run list --workflow=build-container.yml --limit 1 --json databaseId --jq '.[0].databaseId')
    if [[ -n "$CTR_RUN_ID" ]]; then
        gh run watch "$CTR_RUN_ID" || warn "Container build may have failed — check GitHub Actions"
    fi

    info "Verifying PyPI publication..."
    if pip install --dry-run "ai-guardian==${NEW_VERSION}" 2>/dev/null; then
        info "PyPI: ai-guardian==${NEW_VERSION} available"
    else
        warn "PyPI verification failed — package may not be available yet (retry in a few minutes)"
    fi

    info "Verifying container image..."
    if docker manifest inspect "quay.io/redhatproductsecurity/ai-guardian:${NEW_VERSION}" >/dev/null 2>&1; then
        info "Container: quay.io/redhatproductsecurity/ai-guardian:${NEW_VERSION} available"
    else
        warn "Container verification failed — image may not be available yet"
    fi
fi

# --- Phase 8: Post-release merge back --------------------------------------

section "Phase 8: Post-Release Merge Back"

run git checkout main
run git pull origin main

# Merge: skip if release branch is already merged
if $DRY_RUN || ! git merge-base --is-ancestor "$RELEASE_BRANCH" main 2>/dev/null; then
    run git merge "$RELEASE_BRANCH" --no-ff -m "Merge ${RELEASE_BRANCH} into main"
else
    warn "Branch $RELEASE_BRANCH already merged into main — skipping merge"
fi

# Dev version bump (idempotent)
run $HELPER update-version "$NEXT_DEV_VERSION"
info "Version: $NEXT_DEV_VERSION"

# Restore README URLs to /main/
if [[ -f README.md ]]; then
    if $DRY_RUN; then
        echo "[dry-run] sed: replace /${TAG_NAME}/ with /main/ in README.md"
    elif grep -q "/ai-guardian/${TAG_NAME}/" README.md; then
        "${SED_INPLACE[@]}" "s|/ai-guardian/${TAG_NAME}/|/ai-guardian/main/|g" README.md
        info "README.md install URLs restored to main"
    else
        warn "README.md URLs already point to main — skipping"
    fi
fi

# Commit post-release changes (skip if nothing changed)
run git add pyproject.toml src/ai_guardian/__init__.py README.md
if $DRY_RUN || ! git diff --cached --quiet 2>/dev/null; then
    run git commit -m "chore: begin ${NEXT_DEV_VERSION} development cycle

Post-release: bump version to ${NEXT_DEV_VERSION} and restore README URLs to main."
else
    warn "No changes to commit — post-release commit already exists"
fi

run git push origin main
info "Main branch updated"

# --- Done -------------------------------------------------------------------

section "Release Complete"

echo "  Version: ${NEW_VERSION}"
echo "  Tag: ${TAG_NAME}"
echo "  PyPI: https://pypi.org/project/ai-guardian/${NEW_VERSION}/"
echo "  GitHub: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/${TAG_NAME}"
echo "  Container: quay.io/redhatproductsecurity/ai-guardian:${NEW_VERSION}"
echo ""
info "Done!"
