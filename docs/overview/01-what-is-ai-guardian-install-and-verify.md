# What Is AI Guardian? Install and Verify Your First Protected Workflow

*A practical introduction to AI Guardian, followed by the fastest path from understanding the problem to running your first protected AI coding session.*

AI coding assistants can read files, run commands, call external services, and modify a project in seconds. That productivity is valuable, but it also creates a new security boundary: the assistant may encounter secrets, untrusted instructions, sensitive directories, or tools that the project owner did not intend to use.

AI Guardian is designed to sit at that boundary. It adds security checks around AI-assisted development, including prompt-injection detection, secret scanning, directory protection, tool permissions, SSRF protection, and audit logging. It is a defense-in-depth layer, not a replacement for code review, network controls, secret management, or secure development practices.

## The basic model

AI Guardian evaluates activity at several points in an AI workflow:

- A user prompt or incoming content can be checked for suspicious instructions.
- A tool request can be checked against permissions and directory rules.
- File contents and commands can be scanned for secrets or dangerous behavior.
- Tool output can be inspected before it is returned to the agent or user.

The optional MCP security advisor allows an agent to ask whether an action appears safe before attempting it. Hooks remain the enforcement layer: they evaluate the operation during execution and can block it according to policy. This distinction matters because an advisory check depends on the agent choosing to ask, while a hook check is part of the execution path.

## Install the stable package

The documentation recommends installing the stable package with `uv` or `pip`:

```bash
uv tool install ai-guardian
# or
pip install ai-guardian
```

Avoid treating unreleased development code as a production installation. If you are evaluating the project from source, use a pinned release for the actual environment you want to protect.

## Set up an agent

Run setup for the AI coding tool you use. For example:

```bash
ai-guardian setup --ide claude --create-config --install-scanner
```

The setup command can create a configuration, install or manage a scanner engine, install the appropriate hooks, and register the MCP security advisor where that integration supports it. Replace `claude` with the supported agent name that matches your environment.

For a first run, the standard security profile is a sensible baseline. If you are learning how findings behave, the moderator profile can make decisions visible and interactive. The right choice depends on whether you are experimenting, developing, or operating under stronger enterprise controls.

## Start the background services

The daemon is useful when you want faster hook processing and a central process for status and logs:

```bash
ai-guardian daemon start -b
ai-guardian tray start -b
```

The tray is optional. The console can be opened in a browser or terminal:

```bash
ai-guardian console --web
# or
ai-guardian console
```

Use the console to confirm that the configuration is loaded, the expected integrations are present, and recent violations can be viewed. A useful first verification is to inspect the status before beginning work, run a harmless project scan, and confirm that the resulting activity is visible in the console or logs.

## What success looks like

At the end of this first session, you should know:

1. Which agent integration AI Guardian is protecting.
2. Which security profile and action modes are active.
3. Whether the daemon, hooks, and scanner are healthy.
4. Where to look when an operation is blocked.

That is enough to begin the rest of the walkthrough. The next article explains how configuration, permissions, and directory rules turn this general protection into a policy that fits a real project.

## The value of a visible boundary

The most important change is often conceptual. Without a security layer, an AI request can look like a single action: read this file, run this command, or install this tool. With AI Guardian, the action becomes observable and classifiable. The organization can ask which capability was requested, which path was involved, which scanner evaluated it, and what policy decision followed.

That visibility helps teams have better conversations about AI development. A blocked request is no longer mysterious, and an allowed request has a documented place in the workflow. Over time, the team can identify which protections are most valuable, which integrations need attention, and where human approval remains important.

AI Guardian also makes the boundary portable. The same concepts—tool permission, directory protection, content scanning, violation logging, and policy ownership—can apply across several supported agents, even though the host tools expose different lifecycle events.

Read more: [AI Guardian home](https://ai-guardian.readthedocs.io/en/latest/), [Configuration](https://ai-guardian.readthedocs.io/en/latest/CONFIGURATION/), and [Console guide](https://ai-guardian.readthedocs.io/en/latest/CONSOLE/).
