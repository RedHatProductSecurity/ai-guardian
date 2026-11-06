# Codex Linux sandbox runtime troubleshooting

AI Guardian's Codex smoke requires Codex's normal `workspace-write` sandbox. A
Bubblewrap startup failure is a failed smoke case—not evidence that the tool ran,
and not a reason to switch Codex to unrestricted execution.

## Runner message

When the smoke's privacy-safe aggregate diagnostics classify a function result as
`permission_denied_bwrap`, the runner prints an explanation and points here. It
does not print the raw Codex error. The case remains failed, and execution,
PostToolUse, output-containment, and clean-exit assertions are not waived.

## Known local Podman failure

On Fedora 44 with rootless Podman and Codex CLI 0.167.0, a retained smoke container
reproduced:

```text
bwrap: Can't mount devpts on /newroot/dev/pts: Permission denied
```

In that same container, nested user/mount/pid/network/ipc/uts namespace creation
and a tmpfs mount succeeded, while a devpts mount failed. Podman reported SELinux
and seccomp enabled, AppArmor disabled, and the default seccomp profile. This
narrows the symptom to Bubblewrap's devpts mount; it does **not** establish which
kernel or container security layer denied it. Do not infer a specific SELinux or
seccomp rule from this message alone.

## GitHub Actions is a different runtime

The Release Readiness container job currently runs on `ubuntu-26.04` with Docker
and uses the regular `ai-guardian sandbox create` path. Local Linux Podman runs use
a smoke-specific startup gate and egress firewall. Either environment may pass or
fail independently; a successful GitHub Actions run does not qualify every local
Docker/Podman/SELinux/AppArmor setup. Check the workflow result for each configured
CLI smoke before claiming readiness. Claude Code remains conditional on the
repository's explicit terms-of-service consent variable.

The Codex CLI smoke step currently has a temporary `continue-on-error` allowance
so this unresolved runtime issue does not block the release process. A failure is
reported in the workflow warning and job summary, but remains an unqualified Codex
result—not a passing smoke. Other CLI and OpenShell failures remain blocking. Remove
the exception only after Codex executes the native tool and passes the existing
execution, output-containment, and clean-exit checks.

## Safe response

- Keep Codex in `workspace-write` and keep the outer egress firewall and all smoke
  evidence checks enabled.
- Diagnose the specific runtime denial using read-only host/runtime evidence, or
  run the smoke on a runtime that supports the required Bubblewrap mounts.
- Do not use `danger-full-access`, setuid Bubblewrap, an unconfined AppArmor
  profile, or weakened seccomp/SELinux/container policy as a workaround without
  explicit review and authorization.
- Do not treat tool offers, hook events, or violation records alone as proof of
  command execution or output containment.

OpenAI Codex issue [#35547](https://github.com/openai/codex/issues/35547) tracks
the related need for actionable diagnostics when Linux sandbox backends are
unavailable. Its reported AppArmor/old-kernel failure differs from the Fedora
`devpts` reproduction above.
