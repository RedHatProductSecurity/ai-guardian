# Kubernetes Deployment Guide

AI Guardian can run as a shared daemon in a Kubernetes cluster, providing centralized security enforcement for all AI agents running as pods or on developer workstations that connect remotely.

## Architecture

```
┌─────────────────────────────────────┐
│  Kubernetes Cluster                 │
│                                     │
│  ┌──────────────────────────────┐   │
│  │  ai-guardian pod             │   │
│  │  ┌────────────────────────┐  │   │
│  │  │ ai-guardian daemon     │  │   │
│  │  │ REST API: :63152       │  │   │
│  │  │ Hook socket: :63151    │  │   │
│  │  └────────────────────────┘  │   │
│  └──────────────────────────────┘   │
│              │                      │
│    ai-guardian Service (ClusterIP)  │
└──────────────┼──────────────────────┘
               │ NodePort / LoadBalancer / Route
               ▼
        Host tray client polls
        /ask/pending for dialogs
```

The daemon runs as a long-lived pod. IDE hooks (Claude Code, Cursor, etc.) on developer workstations connect to the cluster-exposed REST API. The host tray polls `/ask/pending` and shows ask-mode dialogs on the desktop (#1342).

## Prerequisites

- `kubectl` configured for your cluster
- `kustomize` (or `kubectl` >= 1.14 which includes it)
- For Kind: [Kind](https://kind.sigs.k8s.io) and Podman Desktop or Docker Desktop

## Quick Start — Kind (Local)

### 1. Create Kind Cluster

On **macOS**, Kind uses Podman/Docker networking that requires explicit port mappings:

```bash
kind create cluster --config deploy/kubernetes/overlays/kind/kind-cluster.yaml
```

On **Linux**, NodePort ports are accessible directly at `localhost:nodePort` — the default Kind cluster works without extra config:

```bash
kind create cluster
```

### 2. Deploy

```bash
kubectl apply -k deploy/kubernetes/overlays/kind/
```

This applies the base manifests (Deployment + ClusterIP Service + ConfigMap) with the Kind NodePort overlay.

### 3. Verify

```bash
kubectl get pods -l app=ai-guardian
kubectl logs -l app=ai-guardian -f
```

All daemon pods must also carry an ownership label. Use a unique owner value
for each user or tenant when sharing a namespace:

```yaml
metadata:
  labels:
    app: ai-guardian
    ai-guardian.owner: my-user
```

Configure the tray with the same owner value. Discovery adds this selector to
every Kubernetes API or `kubectl` query, so credentials are only requested from
pods owned by that configured identity.

Wait for the pod readiness probe to pass (checks `GET /api/status` on port 63152).

### 4. Reach the REST API

```bash
# Linux — NodePort accessible directly
curl http://localhost:63152/api/status

# macOS — same (extraPortMappings route through Kind's control-plane)
curl http://localhost:63152/api/status
```

## Production Deployment

### Vanilla Kubernetes (LoadBalancer)

```bash
kubectl apply -k deploy/kubernetes/overlays/production/
```

The Service becomes type `LoadBalancer`. Your cloud provider assigns an external IP:

```bash
kubectl get svc ai-guardian
# NAME          TYPE           CLUSTER-IP     EXTERNAL-IP     PORT(S)
# ai-guardian   LoadBalancer   10.96.0.10     34.102.x.x      63152:xxx/TCP,63151:xxx/TCP
```

Configure the tray to connect at `http://<EXTERNAL-IP>:63152`.

### OpenShift / OCP

```bash
kubectl apply -k deploy/kubernetes/overlays/openshift/
```

This adds an OpenShift Route with TLS edge termination. The Route provides a stable hostname:

```bash
kubectl get route ai-guardian
# NAME          HOST/PORT
# ai-guardian   ai-guardian-<namespace>.apps.<cluster-domain>
```

Configure the tray `tray-targets.json` with the Route URL:

```json
{
  "daemons": [
    {
      "name": "openshift-daemon",
      "url": "https://ai-guardian-<namespace>.apps.<cluster-domain>"
    }
  ]
}
```

## Config Customization

The `ai-guardian-config` ConfigMap provides the daemon's `ai-guardian.json`. Edit before deploying or patch after:

```bash
# Edit the base configmap before apply
vim deploy/kubernetes/base/configmap.yaml
kubectl apply -k deploy/kubernetes/overlays/kind/

# Or patch a running deployment
kubectl create configmap ai-guardian-config \
  --from-file=ai-guardian.json=my-config.json \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/ai-guardian
```

The initContainer copies the ConfigMap content to an `emptyDir` volume at startup, so the daemon can write PID files and session state alongside the config file.

## Validating the Ask Dialog Forwarding Scenario (#1342)

This validates the pull-model: hooks in pods queue ask requests, the host tray polls and shows dialogs on the developer's desktop.

### Step 1 — Deploy and verify

```bash
kubectl apply -k deploy/kubernetes/overlays/kind/
kubectl wait --for=condition=Ready pod -l app=ai-guardian --timeout=60s
curl http://localhost:63152/api/status
```

### Step 2 — Configure the tray

Start the tray on your host machine. The daemon at `localhost:63152` is auto-discovered by the container discovery mechanism. Check that it appears as a remote target:

```bash
ai-guardian daemon status
# Should show: localhost:63152 (container)  running
```

If not auto-discovered, add it to `~/.config/ai-guardian/tray-targets.json`:

```json
{
  "daemons": [
    {
      "name": "kind-daemon",
      "url": "http://localhost:63152"
    }
  ]
}
```

### Step 3 — Register the tray with the daemon

The tray registers itself automatically when it discovers a remote daemon. Verify:

```bash
curl http://localhost:63152/api/tray/status
```

### Step 4 — Trigger an ask dialog from a hook

Configure a hook to use `ask` action, then trigger it from a pod or local Claude Code session connected to the remote daemon. The flow:

1. Hook fires in pod → daemon queues ask request at `/ask/pending`
2. Host tray polls `/ask/pending` → finds the request
3. Tray shows dialog on host desktop
4. User chooses Allow/Block → tray POSTs decision back
5. Pod daemon receives decision → hook returns to Claude

### Manual test (simulate a queued prompt)

```bash
# Queue a test prompt
curl -s -X POST http://localhost:63152/api/ask/pending \
  -H "Content-Type: application/json" \
  -d '{"violation_type":"secret_detected","summary":"Test prompt","fallback_action":"block"}'

# Check the tray picks it up (tray logs or UI)
# Respond
curl -s -X POST http://localhost:63152/api/ask/<prompt_id>/decision \
  -H "Content-Type: application/json" \
  -d '{"decision":"block"}'
```

## Tray Discovery

The tray uses `discover_all()` in `src/ai_guardian/daemon/discovery.py` to find:
- Local daemon (Unix socket)
- Container daemons (Podman/Docker label `ai-guardian.daemon=true`)
- Kubernetes pods via `kubectl` (label `app=ai-guardian`)
- Manual targets from `tray-targets.json`

For the Kind deployment, the NodePort at `localhost:63152` is discovered via the container/kubernetes path automatically when the tray has cluster access.

## Connecting IDE Hooks to the Cluster Daemon

Developer workstations can point their Claude Code (or other IDE) hooks at the cluster daemon instead of running a local daemon.

Add to `~/.claude/settings.json` or project `.claude/settings.json`:

```json
{
  "env": {
    "AI_GUARDIAN_DAEMON_URL": "http://localhost:63152"
  }
}
```

Hooks will send requests to the cluster daemon instead of spawning a local one.

## Cleanup

```bash
# Remove deployment
kubectl delete -k deploy/kubernetes/overlays/kind/

# Remove Kind cluster
kind delete cluster
```
