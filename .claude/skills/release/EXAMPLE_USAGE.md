# Release Skill Usage Examples

This document provides step-by-step examples of using the release skill.

## Example 1: Regular Minor Release

**Scenario**: You've added new features to main and want to release v1.3.0.

**Prerequisites**:
- On main branch
- All tests passing
- CHANGELOG.md Unreleased section has content

**Steps**:

```bash
# In Claude Code, invoke the skill
/release minor
```

**What happens**:

1. Skill validates prerequisites
2. Creates `release-1.3` branch from main
3. Updates version: `1.2.0-dev` → `1.3.0` in both files
4. Updates CHANGELOG.md:
   - Moves Unreleased content to `## [1.3.0] - 2026-04-08`
   - Updates version links
5. Creates commit with proper message format
6. Provides tag creation command:
   ```bash
   git tag -a v1.3.0 -m "Release version 1.3.0"
   git push origin v1.3.0
   ```
7. Provides post-release checklist

**Expected output**:
```
✓ Prerequisites validated
✓ Version updated: 1.2.0-dev → 1.3.0
✓ CHANGELOG.md updated for v1.3.0
✓ Changes committed to release-1.3 branch

Next steps:
1. Review the changes
2. Create tag: git tag -a v1.3.0 -m "Release version 1.3.0"
3. Push tag: git push origin v1.3.0
4. Monitor GitHub Actions
5. Merge back to main after verification
```

## Example 2: Patch Release

**Scenario**: You need to release v1.2.1 with bug fixes.

```bash
/release patch
```

**Result**: Version updated `1.2.0-dev` → `1.2.1`

## Example 3: Hotfix Release

**Scenario**: Critical bug in production v1.2.0 needs immediate fix.

```bash
/release hotfix v1.2.0
```

**What happens**:

1. Validates v1.2.0 tag exists
2. Creates `hotfix-1.2.1` branch from v1.2.0 tag
3. Waits for you to implement the fix
4. Updates version: `1.2.0` → `1.2.1`
5. Updates CHANGELOG.md with hotfix entry
6. Provides tag and merge-back commands

**Workflow**:
```
1. /release hotfix v1.2.0
2. [Make your bug fix]
3. [Skill updates version and CHANGELOG]
4. Tag: git tag -a v1.2.1 -m "Hotfix 1.2.1"
5. Push: git push origin v1.2.1
6. Merge to release-1.2: git checkout release-1.2 && git merge hotfix-1.2.1
7. Cherry-pick to main: git checkout main && git cherry-pick <fix-commit-sha>
```

## Example 4: TestPyPI Test Release

**Scenario**: You want to test the release process before production.

```bash
/release test
```

**What happens**:

1. Creates `release-1.2-test` branch
2. Updates version: `1.2.0-dev` → `1.2.0-test1`
3. Creates commit
4. Creates test tag: `v1.2.0-test1`
5. Provides TestPyPI verification steps

**After tag push**:
1. GitHub Actions triggers TestPyPI workflow
2. Package published to https://test.pypi.org/project/ai-guardian/
3. Verify installation:
   ```bash
   uv pip install --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ \
     ai-guardian==1.2.0-test1
   # or: pip install --index-url https://test.pypi.org/simple/ \
   #   --extra-index-url https://pypi.org/simple/ ai-guardian==1.2.0-test1
   ```
4. Test functionality
5. Clean up test branch and tag

## Example 5: Manual Helper Usage

**Get current version**:
```bash
python .claude/skills/release/release_helper.py get-version
# Output:
# pyproject.toml: 1.2.0-dev
# __init__.py: 1.2.0-dev
# Match: True
```

**Calculate next version**:
```bash
python .claude/skills/release/release_helper.py calc-version "1.2.0-dev" minor
# Output: 1.3.0
```

**Validate prerequisites**:
```bash
python .claude/skills/release/release_helper.py validate --type regular
# Output: ✓ All prerequisites validated
```

**Update version (careful!)**:
```bash
# Only use this if you know what you're doing
python .claude/skills/release/release_helper.py update-version "1.2.0"
```

## Error Handling Examples

### Error: Dirty working directory

**Error message**:
```
✗ Validation failed:
  - Working directory has uncommitted changes
```

**Solution**: Commit or stash your changes before releasing.

### Error: Version mismatch

**Error message**:
```
✗ Validation failed:
  - Version mismatch: pyproject.toml=1.2.0-dev, __init__.py=1.3.0-dev
```

**Solution**: Fix the version mismatch manually, then retry.

### Error: Empty CHANGELOG

**Error message**:
```
✗ Validation failed:
  - CHANGELOG.md [Unreleased] section is empty
```

**Solution**: Add your changes to CHANGELOG.md under the Unreleased section.

### Error: Tests failing

**Error message**:
```
✗ Tests failed
  - 3 tests failing in test_ai_guardian.py
```

**Solution**: Fix the failing tests before releasing.

## Tips

1. **Always test first**: Use `/release test` to verify the workflow before production
2. **Check CHANGELOG**: Ensure Unreleased section has meaningful content
3. **Review commits**: Check the changes before pushing tags
4. **Monitor CI**: Watch GitHub Actions after pushing tags
5. **Keep versions in sync**: The skill handles this, but verify after manual edits

## Troubleshooting

**Skill not found**:
- Check `/Users/dvernier/.claude/skills/release/SKILL.md` exists
- Restart Claude Code if needed

**Helper script errors**:
- Verify Python 3.10+ installed
- Check you're in the ai-guardian repository directory

**Version calculation wrong**:
- Check current version format matches semantic versioning
- Remove any invalid suffixes manually

## Advanced Usage

### Custom CHANGELOG date

```bash
# In skill prompt, specify custom date
# The helper supports --date flag:
python .claude/skills/release/release_helper.py update-changelog "1.2.0" --date "2026-12-25"
```

### Dry-run validation

```bash
# Check prerequisites without making changes
python .claude/skills/release/release_helper.py validate --type regular
```

### Multiple test releases

```bash
/release test  # Creates v1.2.0-test1
# If needed, increment manually for second test:
# v1.2.0-test2, v1.2.0-test3, etc.
```

## Integration with RELEASING.md

The skill automates steps from RELEASING.md but doesn't replace the documentation.
Use RELEASING.md for:
- Understanding the release philosophy
- Manual recovery procedures
- GitHub Actions configuration
- PyPI Trusted Publishing setup

Use `/release` skill for:
- Day-to-day release operations
- Reducing human error
- Faster releases
- Consistent version management
