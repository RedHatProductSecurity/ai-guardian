# AI Guardian Daemon

The `ai-guardian-daemon` distribution provides a minimal headless daemon and
REST API for server deployments. It is separate from the full `ai-guardian`
package and does not install IDE hooks, the tray, Web Console, scanners, or
sandbox integrations.

```bash
uv tool install ai-guardian-daemon
ai-guardian-daemon init-config
ai-guardian-daemon start -b
ai-guardian-daemon status
```

See the [daemon-only installation guide](https://ai-guardian.readthedocs.io/en/stable/DAEMON_ONLY_INSTALL/)
for TLS setup, supported features, and dependency trade-offs.
