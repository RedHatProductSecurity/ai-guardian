# Daemon-only server installation

`ai-guardian-daemon` is a separate PyPI distribution for a headless server that
needs the AI Guardian daemon lifecycle and REST API, but not the workstation
tray, Web Console, IDE hooks, or scanners. It is published alongside the full
`ai-guardian` distribution starting with version **1.22.0**.

The regular `pip install ai-guardian` / `uv tool install ai-guardian` path is
unchanged and continues to install the full feature set. Choose one distribution
per environment; do not install both into the same virtual environment. `uv tool`
installs each tool into its own isolated environment.

## Install and start

Using `uv`:

```bash
uv tool install 'ai-guardian-daemon>=1.22.0'
ai-guardian-daemon init-config
ai-guardian-daemon start -b
ai-guardian-daemon status
```

Or install with `pip` in a dedicated virtual environment:

```bash
python3 -m venv "$HOME/.venvs/ai-guardian-daemon"
source "$HOME/.venvs/ai-guardian-daemon/bin/activate"
python -m pip install --upgrade 'ai-guardian-daemon>=1.22.0'
ai-guardian-daemon init-config
ai-guardian-daemon start -b
```

`init-config` creates the normal private global configuration if one does not
already exist; it preserves an existing file. On a host, the daemon REST API
binds to loopback by default and creates its authentication token in private state
storage. Container detection can select `0.0.0.0`; set `daemon.rest_host` explicitly
and apply the deployment's network controls when that is not intended. `status`
reports both IPC and REST readiness. To stop or restart it, use
`ai-guardian-daemon stop` or `ai-guardian-daemon restart`.

## Enable HTTPS

For a VM, create a certificate and private key as described in
[the Ubuntu VM guide's TLS identity step](UBUNTU_VM.md#4-create-a-dedicated-lab-tls-identity-on-the-vm).
Edit `~/.config/ai-guardian/ai-guardian.json`, preserving its other fields, and
set the daemon's TLS configuration:

```json
{
  "daemon": {
    "rest_host": "127.0.0.1",
    "rest_tls": {
      "enabled": true,
      "cert_file": "/home/guardian/.config/ai-guardian/tls-vm.example/server-cert.pem",
      "key_file": "/home/guardian/.config/ai-guardian/tls-vm.example/server-key.pem"
    }
  }
}
```

Merge these fields into the existing `daemon` object rather than replacing the
whole configuration. Keep the unencrypted private key owner-only (mode `0600` on
POSIX), keep the REST listener on loopback, and independently verify the
certificate identity from the workstation. Enabling HTTPS does not replace
daemon-token authentication. Restart and verify readiness:

```bash
ai-guardian-daemon restart
ai-guardian-daemon status
```

The REST health endpoint is `/api/health`; see the
[Ubuntu VM guide](UBUNTU_VM.md#7-verify-https-before-pairing) for a certificate-
verified `curl` check and the [configuration reference](CONFIGURATION.md) for TLS
semantics. Invalid TLS configuration prevents REST startup rather than falling
back to HTTP.

## Connect a workstation

Install the full `ai-guardian` distribution on the workstation, configure an SSH
alias that reaches the server as the daemon user, and verify HTTPS first. Then use
the workstation tray's **Add daemon via SSH** flow and review the SSH host key and
TLS identity before trusting the connection. The guest does not need the Web
Console or the full package for SSH-managed pairing. Follow the workstation-side
[pairing entry point](UBUNTU_VM.md#choose-a-pairing-entry-point) and
[identity review](UBUNTU_VM.md#review-explicitly-trust-and-connect) steps; those
sections apply without the VM Console bootstrap. A discovered alias alone does
not enroll or trust a daemon.

## Dependency and feature scope

The daemon-only wheel declares only `cryptography` as a runtime dependency. The
daemon and REST server otherwise use the Python standard library; `cryptography`
is included for native HTTPS certificate validation. The package does not install
NiceGUI, OCR/ONNX Runtime, tray/Pillow, Docker, MCP/gRPC, cloud SDKs, Bandit, or
Tree-sitter grammars.

This distribution supports daemon configuration initialization, start/stop/
restart/status, and the daemon REST management/readiness API. It is **not** a
supported agent-hook, SDK or security-scanning installation: it does not provide
the normal `ai-guardian` CLI or IDE hook setup, tray, Web Console, optional scanner
runtime dependencies or external scanner binaries, image/ML scanning, sandbox
management, or MCP integrations. Use the full `ai-guardian` distribution wherever
local agent interactions must be scanned or those features are needed. The
workstation that manages a remote daemon also uses the full distribution.

## Upgrade

Upgrade the selected installation with `uv tool upgrade ai-guardian-daemon` or
`python -m pip install --upgrade ai-guardian-daemon` inside its dedicated
environment. Existing users of `ai-guardian` should continue upgrading
`ai-guardian`; no package switch or configuration migration is required.
