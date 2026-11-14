#!/usr/bin/env bash
# Fully automated release script for AI Guardian.
# No AI agent required — just gh CLI, python3, git, sed, curl, and git-cliff.
#
# Usage:
#   scripts/release.sh minor                  # preview + required CI (default)
#   scripts/release.sh --execute minor        # create a minor release
#   scripts/release.sh --execute --skip-cursor patch
#   scripts/release.sh --execute --resume patch # resume required CI for this attempt
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HELPER="python3 ${REPO_ROOT}/.claude/skills/release/release_helper.py --repo ${REPO_ROOT}"
CONTAINER_VERIFIER="${REPO_ROOT}/scripts/verify_container_images.py"
RELEASE_CI_GATE="${REPO_ROOT}/scripts/release_ci_gate.py"

# --- CLI parsing -----------------------------------------------------------

DRY_RUN=true
RELEASE_MODE=""
SKIP_CURSOR=false
RESUME_CI=false
RELEASE_TYPE=""

usage() {
    cat <<'EOF'
Usage: scripts/release.sh [OPTIONS] <minor|patch|major>

Options:
  --dry-run        Preview release changes; required CI still runs (default)
  --execute        Execute the release; required for any release mutations
  --resume         Resume the saved, incomplete required-CI attempt only
  --skip-cursor    Skip Cursor hook verification
  -h, --help       Show this help message

Release types:
  minor   Bump minor version   (X.Y.Z -> X.(Y+1).0)
  patch   Bump patch version   (X.Y.Z -> X.Y.(Z+1))
  major   Bump major version   (X.Y.Z -> (X+1).0.0)
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            if [[ "$RELEASE_MODE" == "execute" ]]; then
                echo "Error: --dry-run and --execute cannot be combined" >&2
                exit 2
            fi
            RELEASE_MODE="preview"
            DRY_RUN=true
            shift
            ;;
        --execute)
            if [[ "$RELEASE_MODE" == "preview" ]]; then
                echo "Error: --dry-run and --execute cannot be combined" >&2
                exit 2
            fi
            RELEASE_MODE="execute"
            DRY_RUN=false
            shift
            ;;
        --skip-cursor) SKIP_CURSOR=true; shift ;;
        --resume) RESUME_CI=true; shift ;;
        -h|--help)  usage ;;
        minor|patch|major) RELEASE_TYPE="$1"; shift ;;
        *) echo "Unknown argument: $1" >&2; usage ;;
    esac
done

[[ -z "$RELEASE_TYPE" ]] && { echo "Error: release type required" >&2; usage; }

if $DRY_RUN; then
    echo "Release mode: preview only (GitHub CI will run; pass --execute to make release changes)"
else
    echo "Release mode: execute"
fi

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
command -v curl >/dev/null 2>&1      || die "curl not found"
command -v git-cliff >/dev/null 2>&1 || die "git-cliff not found (brew install git-cliff)"

gh auth status >/dev/null 2>&1 || die "gh not authenticated (run: gh auth login)"

if [[ -n "$(git status --porcelain)" ]]; then
    die "Working tree is not clean. Commit or stash changes first."
fi

CURRENT_BRANCH="$(git branch --show-current)"
ON_RELEASE_BRANCH=false
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    if [[ "$CURRENT_BRANCH" == release-* ]]; then
        ON_RELEASE_BRANCH=true
        warn "Resuming on existing branch: $CURRENT_BRANCH"
    else
        die "Must be on main or a release-* branch (currently on: $CURRENT_BRANCH)"
    fi
fi

if ! $DRY_RUN && ! $ON_RELEASE_BRANCH; then
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

info "Basic environment checks passed"

# --- Calculate versions -----------------------------------------------------

# Use last v* tag as base (not code version) — correct for patch after minor bump
LAST_TAG=$(git tag --list 'v[0-9]*' --sort=-v:refname | grep -v '\-' | head -1)
[[ -z "$LAST_TAG" ]] && die "No release tags found (expected v*.*.* pattern)"
LAST_RELEASED="${LAST_TAG#v}"
info "Last release: $LAST_RELEASED (tag: $LAST_TAG)"

NEW_VERSION=$($HELPER calc-version "$LAST_RELEASED" "$RELEASE_TYPE")
[[ -z "$NEW_VERSION" ]] && die "Could not calculate next version"
info "New version: $NEW_VERSION"

CONTAINER_IMAGES=$($HELPER container-images "$NEW_VERSION")
NORMAL_CONTAINER_IMAGE=$(printf '%s\n' "$CONTAINER_IMAGES" | sed -n 's/^normal: //p')
OPENSHELL_CONTAINER_IMAGE=$(printf '%s\n' "$CONTAINER_IMAGES" | sed -n 's/^openshell: //p')
[[ -z "$NORMAL_CONTAINER_IMAGE" || -z "$OPENSHELL_CONTAINER_IMAGE" ]] && \
    die "Could not determine release container image references"

# Extract major.minor for branch name
MAJOR=$(echo "$NEW_VERSION" | cut -d. -f1)
MINOR=$(echo "$NEW_VERSION" | cut -d. -f2)
RELEASE_BRANCH="release-${MAJOR}.${MINOR}"
TAG_NAME="v${NEW_VERSION}"

# Patch releases belong to the existing stable line, never to main's newer
# development tree. Require the exact matching release branch and a clean
# synchronization with its remote before dispatching CI or preparing files.
if [[ "$CURRENT_BRANCH" == release-* && "$CURRENT_BRANCH" != "$RELEASE_BRANCH" ]]; then
    die "Current branch $CURRENT_BRANCH does not match the release target $RELEASE_BRANCH. Switch to the matching release branch and retry."
fi

if [[ "$RELEASE_TYPE" == "patch" ]]; then
    if [[ "$CURRENT_BRANCH" != "$RELEASE_BRANCH" ]]; then
        die "Patch releases must run from the matching stable branch $RELEASE_BRANCH, not $CURRENT_BRANCH. Switch to $RELEASE_BRANCH and retry."
    fi

    git fetch origin || die "Could not fetch origin to verify $RELEASE_BRANCH"
    LOCAL_RELEASE_SHA=$(git rev-parse HEAD) || die "Could not determine local $RELEASE_BRANCH commit"
    REMOTE_RELEASE_SHA=$(git rev-parse --verify "origin/$RELEASE_BRANCH" 2>/dev/null) || \
        die "Remote branch origin/$RELEASE_BRANCH was not found. Restore the stable release branch before retrying."
    if [[ "$LOCAL_RELEASE_SHA" != "$REMOTE_RELEASE_SHA" ]]; then
        die "Local $RELEASE_BRANCH is not synchronized with origin/$RELEASE_BRANCH. Preserve or reconcile local commits, then retry from the remote stable tip."
    fi
    info "Patch release source verified: $RELEASE_BRANCH ($LOCAL_RELEASE_SHA)"
fi

# Next dev version (for post-release merge back)
NEXT_MINOR=$((MINOR + 1))
NEXT_DEV_VERSION="${MAJOR}.${NEXT_MINOR}.0-dev"

echo "  Last release:     $LAST_RELEASED"
echo "  Release branch:   $RELEASE_BRANCH"
echo "  Tag:              $TAG_NAME"
echo "  Next dev version: $NEXT_DEV_VERSION"

# --- Phase 2: Required CI validation ----------------------------------------

section "Phase 2: Required CI Validation"

SOURCE_REF="$CURRENT_BRANCH"
SOURCE_SHA=$(git rev-parse HEAD) || die "Could not determine the source commit for CI"
[[ -z "$SOURCE_SHA" ]] && die "Could not determine the source commit for CI"
info "Required CI source: ${SOURCE_REF} (${SOURCE_SHA})"
if $DRY_RUN; then
    warn "Preview mode still dispatches GitHub Actions workflows; no release changes are made."
fi

CI_STATE_FILE=$(git -C "$REPO_ROOT" rev-parse --git-path ai-guardian-release-attempt.json) || \
    die "Could not locate repository state for the required-CI attempt"
if [[ "$CI_STATE_FILE" != /* ]]; then
    CI_STATE_FILE="${REPO_ROOT}/${CI_STATE_FILE}"
fi
CI_MODE="preview"
$DRY_RUN || CI_MODE="execute"
CI_RESUME_ARGS=()
$RESUME_CI && CI_RESUME_ARGS+=(--resume)
if ! python3 "$RELEASE_CI_GATE" \
    --state-file "$CI_STATE_FILE" \
    --release-type "$RELEASE_TYPE" \
    --release-version "$NEW_VERSION" \
    --release-mode "$CI_MODE" \
    --source-ref "$SOURCE_REF" \
    --source-sha "$SOURCE_SHA" \
    "${CI_RESUME_ARGS[@]}"; then
    die "Required CI validation failed or was incomplete."
fi

if ! $DRY_RUN; then
    python3 "$RELEASE_CI_GATE" \
        --state-file "$CI_STATE_FILE" \
        --release-type "$RELEASE_TYPE" \
        --release-version "$NEW_VERSION" \
        --release-mode "$CI_MODE" \
        --source-ref "$SOURCE_REF" \
        --source-sha "$SOURCE_SHA" \
        --mark-release-started || \
        die "Could not mark this release attempt as started; no release files were prepared."
fi

# Defer release-file preparation until every required workflow has passed.
if ! $DRY_RUN && ! $ON_RELEASE_BRANCH; then
    UNRELEASED_CONTENT=$(awk '/^## \[Unreleased\]/{found=1; next} /^## \[/{exit} found{print}' CHANGELOG.md | grep -v '^$' || true)
    if [[ -z "$UNRELEASED_CONTENT" ]]; then
        if command -v git-cliff >/dev/null 2>&1; then
            info "Generating CHANGELOG entries with git-cliff..."
            CLIFF_OUTPUT=$(git-cliff --unreleased --strip header 2>/dev/null || true)
            if [[ -n "$CLIFF_OUTPUT" ]]; then
                # Insert generated content after the ## [Unreleased] line
                CLIFF_TMP=$(mktemp)
                echo "$CLIFF_OUTPUT" > "$CLIFF_TMP"
                awk '
                    /^## \[Unreleased\]/ { print; print ""; while ((getline line < "'"$CLIFF_TMP"'") > 0) print line; next }
                    { print }
                ' CHANGELOG.md > CHANGELOG.md.tmp && mv CHANGELOG.md.tmp CHANGELOG.md
                rm -f "$CLIFF_TMP"
                info "CHANGELOG.md Unreleased section populated from git history"
            else
                die "git-cliff produced no output — add entries to CHANGELOG.md manually"
            fi
        else
            die "CHANGELOG [Unreleased] section is empty and git-cliff not installed.\nInstall: brew install git-cliff (or cargo install git-cliff)"
        fi
    fi

    $HELPER validate --type regular || die "Prerequisite validation failed"
    info "Release prerequisites validated"
else
    info "Release inputs collected"
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
if $ON_RELEASE_BRANCH; then
    info "Already on $RELEASE_BRANCH"
elif git rev-parse --verify "$RELEASE_BRANCH" >/dev/null 2>&1; then
    run git checkout "$RELEASE_BRANCH"
    run git merge main --no-edit
    warn "Switched to existing branch: $RELEASE_BRANCH (merged main)"
else
    run git checkout -b "$RELEASE_BRANCH"
    info "Created branch: $RELEASE_BRANCH"
fi

# Version: update (idempotent — writes same value if already correct)
run $HELPER update-version "$NEW_VERSION"
info "Version: $NEW_VERSION"

# Keep the external Rust middleware package version in the release tag. The
# middleware reports CARGO_PKG_VERSION during OpenShell capability negotiation.
run python3 "${REPO_ROOT}/scripts/sync_rust_middleware_version.py" \
    --repo "${REPO_ROOT}" \
    --version "${NEW_VERSION}"
info "Rust middleware version synchronized to ${NEW_VERSION}"

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

# Stable container references: update the project-specific release locations
# after the package version and CHANGELOG have been updated. The synchronizer
# fails if an expected active reference disappears, so adding a new release
# location cannot silently create a stale version.
section "Synchronizing release version references"
run python3 "${REPO_ROOT}/scripts/sync_release_versions.py" \
    --repo "${REPO_ROOT}" \
    --stable-version "${NEW_VERSION}"
info "Stable release references synchronized to ${NEW_VERSION}"

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
run git add pyproject.toml src/ai_guardian/__init__.py \
    rust/openshell-middleware/Cargo.toml rust/openshell-middleware/Cargo.lock \
    CHANGELOG.md README.md \
    container/Dockerfile container/Dockerfile.openshell container/README.md \
    docs/notebooklm-export.md
if $DRY_RUN || ! git diff --cached --quiet 2>/dev/null; then
    run git commit -m "chore: release v${NEW_VERSION}

Prepare v${NEW_VERSION} release:
- Bump version to ${NEW_VERSION}
- Update CHANGELOG.md
- Update README.md install URLs to ${TAG_NAME}
- Synchronize stable versions in container defaults and examples
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

DOCS_URL="https://ai-guardian.readthedocs.io/en/${TAG_NAME}/"
DOCS_VERSION_URL_PREFIX="$DOCS_URL"
DOCS_AVAILABLE=false
DOCS_VERIFICATION_STATUS="not checked (dry-run)"

if $DRY_RUN; then
    echo "[dry-run] gh run watch (publish workflow)"
    echo "[dry-run] gh run watch (build-container workflow)"
    echo "[dry-run] pip install --dry-run ai-guardian==${NEW_VERSION}"
    echo "[dry-run] python3 ${CONTAINER_VERIFIER} ${NORMAL_CONTAINER_IMAGE} ${OPENSHELL_CONTAINER_IMAGE}"
    echo "[dry-run] Verify ${DOCS_URL}"
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

    info "Verifying container images with bounded retries..."
    if ! python3 "$CONTAINER_VERIFIER" \
        "$NORMAL_CONTAINER_IMAGE" "$OPENSHELL_CONTAINER_IMAGE"; then
        warn "One or more versioned container images remain unavailable; inspect the Build Container Image workflow before continuing"
    fi

    info "Waiting for versioned documentation..."
    DOCS_HTTP_STATUS="000"
    DOCS_EFFECTIVE_URL=""
    for _attempt in {1..18}; do
        DOCS_RESPONSE=$(curl --silent --location --max-time 10 \
            --output /dev/null --write-out '%{http_code} %{url_effective}' \
            "$DOCS_URL" 2>/dev/null || true)
        DOCS_HTTP_STATUS="${DOCS_RESPONSE%% *}"
        DOCS_EFFECTIVE_URL=""
        if [[ "$DOCS_RESPONSE" == *" "* ]]; then
            DOCS_EFFECTIVE_URL="${DOCS_RESPONSE#* }"
        fi
        [[ -n "$DOCS_HTTP_STATUS" ]] || DOCS_HTTP_STATUS="000"

        if [[ "$DOCS_HTTP_STATUS" =~ ^2[0-9]{2}$ ]] && \
            [[ "$DOCS_EFFECTIVE_URL" == "${DOCS_VERSION_URL_PREFIX}"* ]]; then
            DOCS_AVAILABLE=true
            break
        fi
        sleep 10
    done
    if $DOCS_AVAILABLE; then
        DOCS_VERIFICATION_STATUS="verified (HTTP ${DOCS_HTTP_STATUS}; release version served)"
        info "Read the Docs: ${DOCS_URL} available (HTTP ${DOCS_HTTP_STATUS})"
    else
        if [[ "$DOCS_HTTP_STATUS" == "404" ]] || \
            { [[ "$DOCS_HTTP_STATUS" =~ ^2[0-9]{2}$ ]] && \
                [[ "$DOCS_EFFECTIVE_URL" != "${DOCS_VERSION_URL_PREFIX}"* ]]; }; then
            DOCS_VERIFICATION_STATUS="failed (inactive or wrong version served; HTTP ${DOCS_HTTP_STATUS})"
            warn "Read the Docs did not serve ${TAG_NAME} as an active release version (HTTP ${DOCS_HTTP_STATUS}): ${DOCS_URL}"
            if [[ -n "$DOCS_EFFECTIVE_URL" ]] && \
                [[ "$DOCS_EFFECTIVE_URL" != "${DOCS_VERSION_URL_PREFIX}"* ]]; then
                warn "The request ended at ${DOCS_EFFECTIVE_URL}; a redirect to another version does not verify ${TAG_NAME}."
            fi
            warn "Check Read the Docs → Versions and the ${TAG_NAME} build. Ensure Admin → Automation Rules matches SemVer versions / Tag / Activate version; activate ${TAG_NAME} if needed, then verify the release URL. Do not rerun scripts/release.sh."
        else
            DOCS_VERIFICATION_STATUS="failed (unavailable; HTTP ${DOCS_HTTP_STATUS})"
            warn "Read the Docs did not make ${TAG_NAME} available after retries (HTTP ${DOCS_HTTP_STATUS}): ${DOCS_URL}"
            warn "Inspect the ${TAG_NAME} build in Read the Docs → Versions and confirm Admin → Automation Rules is SemVer versions / Tag / Activate version. Do not rerun scripts/release.sh."
        fi
    fi
fi

# --- Phase 7b: Announce only verified production publication -----------------

section "Phase 7b: Release Announcement"

ANNOUNCEMENT_URL=""
ANNOUNCEMENT_STATUS="not confirmed (retry announcement only; release unchanged)"
if $DRY_RUN; then
    # The helper previews offline and bypasses version/config auto-detection.
    $HELPER announce-release "$NEW_VERSION" --dry-run
    ANNOUNCEMENT_STATUS="not posted (dry-run)"
else
    # Warning-only workflow/pip checks above are NOT proof of publication. The
    # helper independently verifies the exact public Release and production PyPI
    # wheel/sdist before its paginated lookup and at most one create request.
    if ANNOUNCEMENT_URL=$($HELPER announce-release "$NEW_VERSION") && \
        [[ "$ANNOUNCEMENT_URL" =~ ^https://github\.com/RedHatProductSecurity/ai-guardian/discussions/[1-9][0-9]*$ ]]; then
        ANNOUNCEMENT_STATUS="$ANNOUNCEMENT_URL"
        info "Release announcement: ${ANNOUNCEMENT_URL}"
    else
        ANNOUNCEMENT_URL=""
        warn "Release announcement not confirmed; the existing release is unchanged."
        warn "Check Announcements, then retry only: $HELPER announce-release ${NEW_VERSION}"
    fi
fi

# --- Phase 7c: Optional NotebookLM release-export replacement -----------------

section "Phase 7c: Optional NotebookLM Refresh"

NOTEBOOKLM_STATUS="failed/unconfirmed (retry refresh only; release unchanged)"
NOTEBOOKLM_ARGS=()
$DRY_RUN && NOTEBOOKLM_ARGS+=(--dry-run)
if NOTEBOOKLM_RESULT=$($HELPER refresh-notebooklm "$NEW_VERSION" "${NOTEBOOKLM_ARGS[@]}"); then
    case "$NOTEBOOKLM_RESULT" in
        updated\ \(*|skipped\ \(*) NOTEBOOKLM_STATUS="$NOTEBOOKLM_RESULT" ;;
        *) warn "NotebookLM refresh returned an unrecognized status; not confirmed." ;;
    esac
else
    warn "Optional NotebookLM refresh failed/unconfirmed; release completion and merge-back continue."
    warn "Inspect the notebook and saved refresh state, then retry only: $HELPER refresh-notebooklm ${NEW_VERSION}"
fi
case "$NOTEBOOKLM_STATUS" in
    updated\ \(*|skipped\ \(*) info "NotebookLM: ${NOTEBOOKLM_STATUS}" ;;
    *) warn "NotebookLM: ${NOTEBOOKLM_STATUS}" ;;
esac

# --- Phase 8: Post-release merge back --------------------------------------

section "Phase 8: Post-Release Merge Back"

run git checkout main
run git pull origin main

# Merge: skip if release branch is already merged
if $DRY_RUN || ! git merge-base --is-ancestor "$RELEASE_BRANCH" main 2>/dev/null; then
    if $DRY_RUN; then
        run git -c merge.conflictStyle=merge merge --no-commit --no-ff "$RELEASE_BRANCH"
        run git commit -m "Merge ${RELEASE_BRANCH} into main"
    else
        MERGE_STATUS=0
        if git -c merge.conflictStyle=merge merge --no-commit --no-ff "$RELEASE_BRANCH"; then
            MERGE_STATUS=0
        else
            MERGE_STATUS=$?
        fi

        MERGE_CONFLICTS=$(git diff --name-only --diff-filter=U)
        if [[ -n "$MERGE_CONFLICTS" ]]; then
            warn "Resolving validated release metadata conflicts"
            python3 "${REPO_ROOT}/scripts/resolve_release_merge.py" \
                --repo "${REPO_ROOT}" \
                --release-version "${NEW_VERSION}" \
                --next-dev-version "${NEXT_DEV_VERSION}"
        elif [[ "$MERGE_STATUS" -ne 0 ]]; then
            die "Merge from $RELEASE_BRANCH failed without resolvable file conflicts"
        fi

        MERGE_CONFLICTS=$(git diff --name-only --diff-filter=U)
        if [[ -n "$MERGE_CONFLICTS" ]]; then
            printf '%s\n' "$MERGE_CONFLICTS" >&2
            die "Post-release merge still has unresolved conflicts"
        fi

        run git commit -m "Merge ${RELEASE_BRANCH} into main"
    fi
else
    warn "Branch $RELEASE_BRANCH already merged into main — skipping merge"
fi

# Dev version bump (idempotent)
run $HELPER update-version "$NEXT_DEV_VERSION"
info "Version: $NEXT_DEV_VERSION"

run python3 "${REPO_ROOT}/scripts/sync_rust_middleware_version.py" \
    --repo "${REPO_ROOT}" \
    --version "${NEXT_DEV_VERSION}"
info "Rust middleware version synchronized to ${NEXT_DEV_VERSION}"

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

# Verify that the release branch's stable references survived the merge-back.
run python3 "${REPO_ROOT}/scripts/sync_release_versions.py" \
    --repo "${REPO_ROOT}" \
    --check
info "Stable release references verified after merge-back"

# Commit post-release changes (skip if nothing changed)
run git add pyproject.toml src/ai_guardian/__init__.py \
    rust/openshell-middleware/Cargo.toml rust/openshell-middleware/Cargo.lock \
    README.md
if $DRY_RUN || ! git diff --cached --quiet 2>/dev/null; then
    run git commit -m "chore: begin ${NEXT_DEV_VERSION} development cycle

Post-release: bump version to ${NEXT_DEV_VERSION} and restore README URLs to main."
else
    warn "No changes to commit — post-release commit already exists"
fi

run git push origin main
info "Main branch updated"

if ! $DRY_RUN; then
    python3 "$RELEASE_CI_GATE" \
        --state-file "$CI_STATE_FILE" \
        --release-type "$RELEASE_TYPE" \
        --release-version "$NEW_VERSION" \
        --release-mode "$CI_MODE" \
        --source-ref "$SOURCE_REF" \
        --source-sha "$SOURCE_SHA" \
        --mark-release-completed || \
        die "Release actions completed, but the saved CI attempt could not be marked complete. Do not replay this release."
fi

# --- Done -------------------------------------------------------------------

section "Release Summary"

echo "  Version: ${NEW_VERSION}"
echo "  Tag: ${TAG_NAME}"
echo "  PyPI: https://pypi.org/project/ai-guardian/${NEW_VERSION}/"
echo "  GitHub: https://github.com/RedHatProductSecurity/ai-guardian/releases/tag/${TAG_NAME}"
echo "  Announcement: ${ANNOUNCEMENT_STATUS}"
echo "  NotebookLM: ${NOTEBOOKLM_STATUS}"
echo "  Container: ${NORMAL_CONTAINER_IMAGE}"
echo "  OpenShell: ${OPENSHELL_CONTAINER_IMAGE}"
echo "  Docs: https://ai-guardian.readthedocs.io/en/${TAG_NAME}/"
echo "  Docs (stable): https://ai-guardian.readthedocs.io/en/stable/"
echo "  Docs (latest): https://ai-guardian.readthedocs.io/en/latest/"
echo "  Docs verification: ${DOCS_VERIFICATION_STATUS}"
echo ""
if $DRY_RUN; then
    info "Dry run complete; no announcement posted."
elif [[ -n "$ANNOUNCEMENT_URL" && "$DOCS_AVAILABLE" == true ]]; then
    info "Done!"
else
    if [[ -z "$ANNOUNCEMENT_URL" ]]; then
        warn "Release process finished with an unconfirmed announcement; retry the announcement only, not publication."
    fi
    if [[ "$DOCS_AVAILABLE" != true ]]; then
        warn "Release publication and main-branch merge-back completed, but Read the Docs verification needs attention. Follow the guidance above; do not rerun the full release."
    fi
    exit 1
fi
