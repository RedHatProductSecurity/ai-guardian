# Early Bird PyPI Builds

Stable releases remain the supported default:

```bash
python -m pip install --upgrade ai-guardian
```

The opt-in Early Bird channel publishes at most one eligible development build
per UTC day from protected `main`:

```bash
python -m pip install --upgrade --pre ai-guardian
```

Pip resolves the highest compatible version. `--pre` enables prerelease
selection and can also admit prerelease dependencies, so it is not a promise
that the resolver selects a particular nightly build. Use a separate virtual
environment: Early Bird packages are development builds and are not
production-supported stable releases.

Pin an exact build when reproducing a bug:

```bash
python -m pip install 'ai-guardian==1.24.0.dev7'
```

Each package records its full source commit SHA in package metadata and the
publication record. Include that SHA and the exact package version in bug
reports. Development, release-candidate, and final versions follow PEP 440:
for the same planned base, `.devN < rcN < final`.

To return to stable, install a compatible final release explicitly and omit
`--pre`:

```bash
python -m pip install --upgrade 'ai-guardian==1.24.0'
```

Early Bird publishing has a protected maintainer pause control and does not
change tag-based stable publishing. Maintainers must validate PyPI notification
behavior before production enablement; development uploads may generate email
and the project does not promise a fixed notification count. Old development
builds are retained by default rather than automatically yanked or deleted.

The Python package does not install or guarantee compatibility with the
separately released native Bifrost plugin or OpenShell middleware. Select and
qualify those native artifacts independently.
