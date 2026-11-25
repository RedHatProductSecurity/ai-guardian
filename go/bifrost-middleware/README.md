# AI Guardian Middleware for Bifrost

This directory contains the optional native Go plugin for Bifrost. It protects
gateway-visible LLM traffic through the AI Guardian daemon; it does not replace
the existing agent integrations or require the AI Guardian Broker.

## Compatibility boundary

The initial target is Bifrost OSS `v2.6.0` at revision
`172617bb045c6f43d697843c115e64f0155ed143`, with Go `1.27.4`. The plugin must
be built against the same Bifrost source and toolchain as the host. A plugin
compiled with a different Go version, host architecture, or build settings is
not a supported artifact.

See `compatibility.json` for the machine-readable artifact contract.

Release filenames include the Bifrost and Go versions, for example:
`ai-guardian-bifrost-v2.6.0-go1.27.4-linux-amd64.so`. Select the asset whose
Bifrost version, Go toolchain, operating system, and architecture match the
installed host.

## Installation

The plugin does not contain the AI Guardian scanners. An AI Guardian daemon
must be installed and running wherever the plugin can reach it.

Start and verify a local daemon before starting Bifrost:

```bash
ai-guardian setup --create-config --install-scanner
ai-guardian daemon start -b
ai-guardian daemon status
```

By default, the plugin connects to the permission-protected Unix socket at the
AI Guardian state directory (normally
`~/.local/state/ai-guardian/daemon.sock`). The Bifrost process must run as an
identity permitted to access that socket. Override the socket explicitly with
`AI_GUARDIAN_DAEMON_SOCKET` in the Bifrost service environment.

For a remote daemon, set an operator-controlled HTTPS endpoint and protected
credential in the Bifrost service environment:

```bash
AI_GUARDIAN_DAEMON_URL=https://guardian.example.internal:63152
AI_GUARDIAN_DAEMON_TOKEN_FILE=/etc/ai-guardian/bifrost-token
```

Remote mode requires TLS verification and authentication. The plugin never
accepts a daemon URL, token, or project mapping from an inference request.
`AI_GUARDIAN_DAEMON_URL` takes precedence over the local socket when set.

Failure handling defaults to enforcement mode. Daemon timeouts, unavailable
connections, and malformed verdicts block traffic. An operator may explicitly
set `AI_GUARDIAN_BIFROST_FAILURE_MODE=fail_open` for monitoring-only operation;
this mode must not be used when the gateway is expected to enforce policy.
Explicit daemon security denials remain blocking in both modes.

After the daemon is ready:

1. Identify the Bifrost host version, Go toolchain, operating system, and
   architecture. Select the matching `.so` and checksum files from the GitHub
   Release. Do not select an artifact by architecture alone.
2. Download the plugin and verify its checksum before loading it:

   ```bash
   sha256sum -c ai-guardian-bifrost-v2.6.0-go1.27.4-linux-amd64.so.sha256
   ```

3. Copy the verified `.so` to an operator-owned plugin directory readable by
   the Bifrost process. Keep the file outside writable project or user-content
   directories.
4. Register the absolute path in the Bifrost plugin configuration:

   ```json
   {
     "plugins": [
       {
         "path": "/opt/bifrost/plugins/ai-guardian-bifrost-v2.6.0-go1.27.4-linux-amd64.so",
         "name": "ai-guardian-bifrost",
         "display_name": "AI Guardian Middleware",
         "enabled": true,
         "type": "llm"
       }
     ]
   }
   ```

5. Configure the AI Guardian daemon endpoint and authentication using the
   deployment's protected environment or secret store. Do not put daemon
   tokens in the plugin path, source tree, or logs.
6. Restart or reload Bifrost using its documented plugin lifecycle command.
   Confirm that the plugin is loaded before sending production traffic.

The exact Bifrost configuration-file location and reload command are
deployment-specific. A plugin load failure must not be interpreted as gateway
traffic protection; verify the loaded plugin status and run the middleware
integration checks before relying on it.

## Repository layout

```text
go/bifrost-middleware/
├── compatibility.json
├── go.mod
├── internal/                 # daemon client, policy mapping, hook logic
└── tests/                    # contract and harness tests
```

The implementation must keep Bifrost-specific hook adapters separate from the
daemon client. The daemon remains the authority for scanners, policy, redaction,
and verdicts.

## Artifact policy

Linux AMD64 and ARM64 are the first release targets. macOS artifacts are later
targets. Windows is not a native shared-object target; a future Windows
integration requires a different Bifrost extension mechanism and must not be
represented as a `.so` artifact.

Do not publish a plugin artifact until the matching Bifrost host build,
toolchain, revision, and SHA-256 metadata are available. A distributed Bifrost
binary or container image is a separate release decision and is not bundled by
this module.
