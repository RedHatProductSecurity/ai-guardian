# Module 4 — Advanced Deployment

## Lesson 8 — The AI Guardian SDK

### Core idea

IDE hooks do not cover every program that processes untrusted content. A custom Python agent, batch job, or direct model integration can use the SDK to place checks at application boundaries.

### Guided example

The SDK supports monitored sessions with explicit checks:

```python
from ai_guardian.sdk import monitor

with monitor() as session:
    session.check_content(user_input)
    session.check_file("/path/to/input.json")
    session.check_command("example-command --dry-run")
```

In a training environment, use a harmless input file and a safe dry-run command. Observe the returned result and document how a blocked finding should be reported to the caller. Do not catch and discard security exceptions merely to keep a workflow moving.

The SDK may run checks in-process or delegate to a daemon-backed mode. Choose based on process boundaries, deployment, latency, and operational visibility.

### Knowledge check

Why is the SDK described as additive? It extends protection to programs where hooks do not apply; it does not weaken or replace hook enforcement in an IDE session.

## Lesson 9 — AI Guardian Sandboxes

### Core idea

Sandboxes place an AI workload inside a managed runtime with its own filesystem, network, credentials, and lifecycle. Docker and Podman provide familiar container workflows. OpenShell adds a gateway-managed model for per-sandbox policy and credential separation.

### Guided activity

Plan a sandbox for a fictional repository. Document:

- The minimum repository directory that must be available.
- Which credentials should remain outside the agent sandbox.
- Whether Docker, Podman, or OpenShell is the better fit.
- Which agent and image will be used.
- How the sandbox will be stopped and removed after the exercise.

Use the documented sandbox command for the installed version. Do not mount broad host directories or real credential stores for a training exercise.

### Knowledge check

Why does a container not automatically protect every file? Anything mounted into the container may be available to the agent unless another control prevents access.

## Lesson 10 — Operating and Observing AI Guardian at Scale

### Core idea

Protection needs operational visibility. The daemon supports long-lived processing; the tray can show status and lifecycle controls; violation logs record blocked operations; latency metrics show performance; and OpenTelemetry traces help diagnose workflows.

### Guided activity

Create an operations checklist with these questions:

1. Is the daemon healthy?
2. Which agent and policy are active?
3. Where are violation records stored?
4. Who can access logs and traces?
5. How long should operational data be retained?
6. What signal would show that an upgrade changed behavior?

Review paths, URLs, commands, and trace metadata as potentially sensitive operational data.

### Further reading

[SDK Guide](https://ai-guardian.readthedocs.io/en/latest/SDK/) · [Sandbox CLI](https://ai-guardian.readthedocs.io/en/latest/Sandbox/) · [Observability](https://ai-guardian.readthedocs.io/en/latest/OBSERVABILITY/)

## Hands-on labs

### Lab 4A — Add checks to a small Python workflow

**Time:** 30 minutes  
**Goal:** Identify security boundaries in a program that processes untrusted content.

1. Create a disposable Python script that accepts a text file as input.
2. Identify where the file enters the program, where it is sent to a model client, and where any tool command would be created.
3. Add a monitored session using the documented SDK interface.
4. Check the input content and the input file before any model or tool action.
5. Use a harmless dry-run command for the command check.
6. Record how the program should report a blocked result to its caller.

**Expected result:** The learner can draw the program’s trust boundaries and explain why each check occurs where it does.

Do not add real provider credentials or connect the exercise to production services.

### Lab 4B — Compare sandbox runtimes

**Time:** 30 minutes  
**Goal:** Select a runtime based on isolation and operations rather than familiarity alone.

Create a comparison table with Docker, Podman, and OpenShell as columns. Compare:

- How the runtime is installed and operated.
- Where provider credentials are held.
- How repositories enter the sandbox.
- How network and filesystem policy is applied.
- How the daemon or Console is reached.
- How the sandbox is stopped and removed.

Use the official documentation for the installed version. If a runtime is unavailable, complete the comparison from the documentation and clearly mark the result as theoretical.

### Lab 4C — Design an observability runbook

**Time:** 25 minutes  
**Goal:** Connect operational signals to decisions.

Write a runbook with one response for each event:

1. The daemon is not visible.
2. Violation volume suddenly increases.
3. Hook latency rises after an upgrade.
4. A trace contains more project metadata than expected.
5. A sandbox stops unexpectedly.

For each response, name the first evidence source, the responsible owner, and the safe next action. Include a note about log and trace access controls.

### Assessment

Submit the Python boundary diagram, runtime comparison, and observability runbook. A complete submission explains both capability and limitation: what the control does, what it does not do, and how a human verifies the result.
