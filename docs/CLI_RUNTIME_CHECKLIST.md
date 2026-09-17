# CLI/Runtime Integration Checklist

Use this checklist when adding or changing a CLI-capable AI integration in the
normal Docker/Podman container, the NVIDIA OpenShell image, or the
`ai-guardian sandbox` runtime selection. It is the companion to the
[IDE/Agent Integration Checklist](IDE_INTEGRATION_CHECKLIST.md): that checklist
covers host hooks, plugins, MCP, transcripts, and IDE setup; this one covers
distribution, authentication, policies, image contents, and runtime behavior.

Adding an integration to the canonical IDE registry does not automatically add
it to either container runtime. Complete the applicable items below and mark
every non-applicable item with a reason in the issue or pull request.

## Runtime support record

Create or update this record for every CLI/agent. A runtime may be supported,
runtime-installed, experimental, or explicitly unsupported.

| Field | Container | OpenShell |
| --- | --- | --- |
| Support status |  |  |
| CLI key and display name |  |  |
| Invocation (`--cli`, and `--agent` if applicable) |  |  |
| Image source and version |  |  |
| Installation mode (bundled/runtime/inherited) |  |  |
| Authentication and provider profile |  |  |
| Policy and network requirements |  |  |
| Config/home/environment paths |  |  |
| Interactive and automated invocation |  |  |
| Linux/macOS/Windows support |  |  |
| Evidence and known limitations |  |  |

For OpenCode, keep the two concepts separate: `--cli opencode` selects the
executable and `--agent NAME` selects its profile. Do not use an agent profile
name as a provider name. For all other CLIs, document whether an additional
profile or model selector exists.

## 1. Scope, support, and legal classification

- [ ] Choose a stable CLI key and display name. Keep the key consistent across
  the CLI parser, sandbox labels, entrypoint variables, policy filenames,
  provider helpers, tray controls, and documentation.
- [ ] Classify the integration separately for the normal container and
  OpenShell: bundled, inherited from a base image, runtime-installed,
  custom-image-only, experimental, or unsupported.
- [ ] Record supported CLI versions, host operating systems, image
  architectures, upstream account requirements, and known limitations.
- [ ] Review the CLI license, service terms, telemetry, authentication terms,
  and any required Terms-of-Service consent before bundling or redistributing
  it. Record the decision and source links.
- [ ] Decide whether a proprietary CLI requires an interactive or explicit
  runtime consent flow. Do not silently bundle it because it is available in
  the normal container.
- [ ] State whether the integration is expected to run interactively, through
  `exec`, through an automated/print mode, or in all of those modes.

## 2. Shared command and setup contract

- [ ] Add or update the CLI parser and validation in
  [`src/ai_guardian/cli.py`](../src/ai_guardian/cli.py), including help text,
  defaults, invalid combinations, and environment-variable overrides.
- [ ] Add or update runtime selection and command construction in
  [`src/ai_guardian/sandbox.py`](../src/ai_guardian/sandbox.py). Verify that
  the selected CLI, profile, model, provider, policy, image, repository, and
  workdir remain distinct values.
- [ ] Verify the CLI-to-setup mapping in `container/entrypoint.sh`, including
  selected-only, all-CLI, and all-integration setup scopes.
- [ ] Verify the command's home-directory variable, config paths, writable
  directories, temporary files, and cache paths in a clean temporary HOME.
- [ ] Verify startup environment values and ensure credentials are not placed
  in command arguments, image layers, logs, labels, or policy files.
- [ ] Verify that configuration preserves unrelated user settings and is
  idempotent on repeated startup.
- [ ] Verify repository and working-directory behavior for an uploaded or
  mounted repository, including spaces, missing paths, and a home-directory
  default where applicable.
- [ ] Verify interactive startup, explicit command execution, `--print` or
  other automated modes, exit behavior, signals, non-zero exits, and timeout
  handling.
- [ ] If the CLI has a special non-interactive authentication flag or wrapper
  requirement, implement it only at the appropriate command boundary and
  document the difference. Do not install a persistent wrapper without an
  explicit reason and test.

## 3. Normal Docker/Podman container

- [ ] Update the normal image and startup path only when the CLI is intended
  to be available there. Relevant surfaces include `container/Dockerfile`,
  `container/run.sh`, `container/entrypoint.sh`, and the source-wheel/vendor
  installation path.
- [ ] Add the CLI key to these shell arrays (they are not auto-derived from
  the Python registry):
  - `SUPPORTED_AGENTS` in `container/run.sh`
  - `SUPPORTED_AGENT_IDES` in `container/entrypoint.sh`
  - `CLI_AGENT_IDES` in `container/entrypoint.sh` (if the agent is CLI-based)
- [ ] Add the CLI to the normal container's supported setup list, or document
  why it is intentionally GUI/editor-only or unavailable in this runtime.
- [ ] For a bundled CLI, add a reproducible version pin and build-time
  `--version` verification. Avoid mutable `latest` package installation.
- [ ] For a runtime-only CLI, document the installer, consent, authentication,
  custom-image boundary, and the reason it is not included in the published
  image.
- [ ] Verify normal-container behavior with a temporary HOME/config directory,
  a clean repository, an existing user configuration, and a second startup.
- [ ] Build the normal image for each supported architecture and run the CLI's
  version/help check inside it.
- [ ] Update the normal container's policy/configuration documentation if the
  CLI needs environment variables, files, or a different daemon startup mode.

## 4. OpenShell image and sandbox

- [ ] Add the CLI to the OpenShell selector only if it is terminal-capable and
  supported by the OpenShell image. Keep GUI/editor-only integrations out of
  the selector and image.
- [ ] Update the selected-CLI setup list and command mapping in
  `container/entrypoint.sh`. Verify selected-only, `cli`, and `all` setup
  scopes, plus the installed-package compatibility check.
- [ ] For a bundled CLI, add an explicit version `ARG`, reproducible install,
  and build-time `--version` verification to
  `container/Dockerfile.openshell`. Record whether the CLI is inherited from
  the OpenShell base image or deliberately refreshed by AI Guardian.
- [ ] For an inherited or runtime-only CLI, document the base-image contract,
  custom-image boundary, consent flow, and version-monitoring limitation.
- [ ] Add or update `container/policies/agents/<cli>.yaml` when the CLI needs a
  selected-CLI policy. Keep the baseline, selected-CLI policy, provider-owned
  policy, and optional GitHub overlays separate.
- [ ] Verify the minimum filesystem and network permissions. Deny unrelated
  agent endpoints by default and document every required egress exception.
- [ ] Verify repository upload/mount behavior, `/sandbox/repo` workdir,
  OpenShell `exec`, connect, logs, start/restart, and daemon service exposure.
- [ ] Verify tray and NiceGUI discovery, authentication headers, service URL
  lookup, and failure output for a running and a stopped sandbox.
- [ ] Build the OpenShell image locally, record its base/image digest and CLI
  versions, and recreate the sandbox after image changes.
- [ ] Verify the OpenShell image publishing workflow uses the dedicated image
  repository and correct tag behavior. Do not accidentally mirror the image to
  the normal container repository.

## 5. Authentication, providers, and inference

Provider configuration and policy configuration are separate requirements: a
provider supplies credentials, endpoints, or binaries; a policy grants the
filesystem and network access needed to use them. A provider profile does not
automatically make the CLI usable, and a policy does not provide credentials.

- [ ] Identify every supported auth mode: API key, OAuth, local auth file,
  cloud ADC, workload identity, provider refresh, or custom gateway auth.
- [ ] Verify auth discovery on Linux and macOS, including HOME overrides,
  config paths, symlinks, permissions, and absent/partial credential files.
- [ ] Verify the provider profile type, name, credential variable, endpoint,
  model/inference route, refresh behavior, and gateway prerequisites.
- [ ] Verify both implicit provider selection and explicit `--provider NAME`.
  A missing compatible provider must fail with an actionable message.
- [ ] Verify provider-backed credentials are not copied into sandbox arguments,
  uploaded repositories, image layers, logs, or ordinary environment values
  that the CLI can read when a provider abstraction is required.
- [ ] Verify placeholder environment values used by a gateway route are clearly
  non-secret and do not trigger misleading plain-credential warnings.
- [ ] Verify the required gateway settings, such as Providers v2, are checked
  or documented before sandbox creation.
- [ ] For Vertex or another gateway route, verify the base URL, model, region,
  project, provider type, and CLI-specific endpoint format independently.
- [ ] Test the actual CLI request through the provider route; a successful
  provider creation alone is not sufficient evidence.

## 6. Policies and runtime security

- [ ] Compose the shared baseline, selected-CLI policy, provider-owned policy,
  and explicit user overlays in the documented order.
- [ ] Validate the resulting policy with the runtime's schema/tooling and test
  that unrelated endpoints remain denied.
- [ ] Test the minimum required filesystem access, repository access, home
  directory behavior, and nested-sandbox settings.
- [ ] Test the minimum required network access for model requests, auth refresh,
  package/plugin/catalog access, and GitHub operations when those features are
  explicitly enabled.
- [ ] Verify that adding a provider does not silently grant broad network or
  filesystem access, and adding a policy does not silently expose credentials.
- [ ] Document optional overlays separately from the default policy. In
  particular, GitHub read-only/read-write access must be explicit.

## 7. Tests and evidence

- [ ] Add focused unit tests for parser defaults, invalid combinations,
  command construction, environment propagation, provider selection, policy
  composition, and credential redaction.
- [ ] Update `tests/unit/test_container_scripts.py` for image arguments,
  entrypoint setup, selector scope, installation/version checks, and workflow
  coverage.
- [ ] Update the related sandbox and tray tests, including OpenCode profile
  handling when applicable.
- [ ] Run the directly affected unit tests with an isolated HOME/config and
  without relying on the developer's credentials.
- [ ] Build and smoke-test the normal container with a disposable repository
  and the selected CLI.
- [ ] Build and smoke-test a disposable OpenShell sandbox with the selected
  policy and provider. Test both implicit and explicit provider selection.
- [ ] Test at least one authenticated model request, one denied network or
  filesystem operation, one repository operation, and one lifecycle operation.
- [ ] Test Linux and macOS host paths when authentication, gateway behavior,
  or process handling differs. Record unsupported platforms explicitly.
- [ ] Update the relevant CI jobs, including container build, scenario tests,
  CLI version health, and release-readiness checks.
- [ ] Record the tested image digest, CLI versions, provider/model/region,
  gateway version, host OS, and known failures in the issue or pull request.

## 8. Documentation and release gate

- [ ] Update `README.md`, `container/README.md`, `docs/Sandbox.md`, and the
  applicable capability/support tables.
- [ ] State whether the OpenShell integration is experimental and list the
  exact CLI/profile combinations that were tested.
- [ ] Document required environment variables, provider setup, policy setup,
  image rebuild requirements, and the difference between interactive and
  automated launch modes.
- [ ] Update tray/create-modal help or choices when the new CLI is user-visible.
- [ ] Update version-monitoring sources for every explicitly managed bundled
  version. Document any native installer without a stable release endpoint.
- [ ] Add the integration to release-readiness matrices or record a tested
  exclusion. Confirm the checklist itself remains discoverable from the docs
  index.

For an existing CLI, rerun the applicable sections whenever its command,
profile, image/base image, version pin, provider, auth bridge, policy, model
route, or lifecycle behavior changes. Runtime support is not complete until
the normal container and OpenShell status are both documented, even when one
of them is explicitly unsupported.
