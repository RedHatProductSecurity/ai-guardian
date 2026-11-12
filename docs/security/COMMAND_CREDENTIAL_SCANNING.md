# Command Credential Scanning

AI Guardian includes a separate, default-on command scanner for credential values
placed directly in supported HTTP-client arguments. Its default action is
**block**, before a supported native Bash/Shell command executes. It does not extend or change
the optional password-likelihood heuristic.

## What it detects

The built-in parser recognizes direct invocations of:

- `curl`: user/password and proxy-user options, bearer-token options,
  authorization-related headers, and URL userinfo.
- `wget`: user/password options, authorization-related headers, and URL userinfo.
- PowerShell `Invoke-WebRequest`/`iwr` and `Invoke-RestMethod`/`irm`:
  literal authorization headers, token options, URL userinfo, and supported
  plaintext `ConvertTo-SecureString -AsPlainText` credential expressions.

Findings distinguish inline literals from variable/credential-store references,
interactive authentication without a value, and unsupported or incomplete
analysis. Credential references and no-value/interactive authentication are
advisory: the scanner does not inspect the environment, credential files, or
credential stores. Unsupported wrappers and incomplete parsing are not reported
as confirmed credentials; the configured action is applied conservatively.

## Actions and configuration

```json
"command_credential_scanning": {
  "enabled": true,
  "action": "block"
}
```

`enabled` defaults to `true`. `action` defaults to `block` and accepts:

- `block` — deny inline literals and incomplete analysis before execution.
- `ask` — require a private, operation-scoped **Allow Once** or **Block** decision;
  if approval is unavailable, the command is denied.
- `warn` — show a value-free warning and allow the command.
- `log-only` — retain a value-free finding without a user-facing warning.

References and interactive/no-value authentication remain advisory under each
action because no literal credential value was identified.

The setting is available in the generated config, profiles, JSON schema, Doctor,
global Web Console settings, and the Secret Scanning settings page. This is a
global-only policy: project-local config cannot disable or weaken it. It can be
disabled explicitly in global config with `"enabled": false`.

The MCP `check_command` tool can report a value-free recommendation, but MCP is
advisory: it cannot stop execution. Native pre-tool hooks apply the configured
block/Ask decision before execution.

## Privacy and limitations

The scanner does not expand variables, execute commands, or read credential files.
Finding records contain only fixed command/option labels, a classification, and
bounded argument positions; they never retain the argument value or full command.
Blocking is a pre-tool execution control, **not** a way to retract command text
that the AI model has already seen.

This is a bounded command-argument parser, not a general shell interpreter. It
does not cover every CLI, alias, wrapper, authentication scheme, or shell feature.
An unrelated command is ignored. No file-content scan, SARIF finding factory, or
`.aiguardignore.toml` scanner type applies: the implementation is reachable from
pre-execution command hooks, SDK command checks, and the MCP `check_command`
advisor, not file scanning.
It has no third-party dependency. Existing supported CLI hook smokes exercise one
synthetic blocked command and a clean allow control using only the local mock
provider; no real credential or external endpoint is used.

## Manual verification

1. In an isolated test project with a supported native command hook, request a
   command such as `curl --user demo:synthetic_smoke_value https://example.invalid/`.
2. Confirm the native pre-tool hook denies execution and reports that an inline
   credential was found while withholding the value.
3. Confirm a harmless command is allowed, and a variable reference is advisory.
4. Inspect the value-free violation entry; verify neither the synthetic value nor
   the full command appears in the record.
5. Repeat with `action: "warn"` only in a disposable test configuration and
   confirm the command may proceed with the fixed warning.

No command in this guide should be run with a real credential.
