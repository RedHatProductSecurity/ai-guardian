# Contributing to AI Guardian

Thank you for your interest in contributing! This repo uses `collaborators_only` interaction limits to prevent spam, which means only collaborators can open issues directly. There are still several ways to contribute.

## How to Contribute

### 1. Open a Discussion

[GitHub Discussions](https://github.com/RedHatProductSecurity/ai-guardian/discussions) are open to everyone and don't require collaborator access. Use them for:

- **Bug reports** -- [Bug Reports](https://github.com/RedHatProductSecurity/ai-guardian/discussions/categories/bug-reports) category
- **Feature requests** -- [Ideas](https://github.com/RedHatProductSecurity/ai-guardian/discussions/categories/ideas) category
- **Questions** -- [Q&A](https://github.com/RedHatProductSecurity/ai-guardian/discussions/categories/q-a) category

Maintainers review discussions regularly and will convert them to issues when appropriate.

### 2. Open a Pull Request

Code contributions via fork + PR are always welcome and are not affected by interaction limits. PRs from forks work regardless of collaborator status.

```bash
gh repo fork RedHatProductSecurity/ai-guardian --clone
cd ai-guardian
git checkout -b feature/your-change
# make changes, commit, push
gh pr create --web
```

### 3. Becoming a Collaborator

Active contributors may be invited as collaborators, which grants direct issue access. This happens after sustained quality contributions.

## Branch Naming

- `feature/description` -- New features
- `fix/description` -- Bug fixes
- `docs/description` -- Documentation
- `refactor/description` -- Refactoring
- `test/description` -- Tests

## Commit Messages

```
<type>: <subject>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

## Pull Request Checklist

- [ ] Tests pass: `pytest`
- [ ] CHANGELOG.md updated under `[Unreleased]`
- [ ] One feature/fix per PR
- [ ] No unrelated changes

## Developer Setup

```bash
git clone https://github.com/RedHatProductSecurity/ai-guardian.git
cd ai-guardian
uv venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -e .[dev]
```

See [Developer Install](README.md#developer-install) in the README for testing and linter commands.

For detailed architecture and development workflows, see **[docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)**.

## Release Process

Contributors cannot create releases. Submit PRs with features/fixes; maintainers handle releases. See [RELEASING.md](RELEASING.md).

## Code of Conduct

Be respectful, accept constructive criticism, and focus on what's best for the project.

## Security Issues

Report security vulnerabilities privately to the maintainers -- do not open a public issue.
