# Module 1 — Foundations

> **Lab safety:** Use a disposable practice repository and test account. Never place real credentials, customer data, private keys, or production configuration in the lab. Do not edit protected AI Guardian configuration files; use documented setup flows and approved policy processes.

## Lesson 1 — Introduction, Installation, and Verification

### What you will learn

By the end of this lesson, you will be able to explain the security boundary created by an AI coding assistant, describe AI Guardian’s enforcement pipeline, and verify that a supported agent is protected.

### Why this matters

An AI coding assistant is more than a text generator. It may read files, run shell commands, call external tools, access a network, and write changes into a repository. That makes the assistant part of the development environment’s trust boundary.

The assistant can also encounter content that was not written by the project team: issue text, downloaded documentation, logs, generated files, or third-party instructions. Some of that content may contain secrets or instructions that should not control the assistant.

AI Guardian adds checks around this workflow. It is one layer of defense in depth, alongside code review, least privilege, secret management, network controls, and CI security scanning.

### The protection pipeline

Think of a protected interaction as a sequence:

1. A user submits a prompt or the assistant receives content.
2. AI Guardian can inspect the prompt or content for suspicious instructions.
3. The assistant proposes a tool call.
4. Pre-tool checks evaluate permissions, paths, commands, and sensitive content.
5. If allowed, the host executes the tool.
6. Post-tool checks inspect the result before it continues through the workflow.
7. Findings may be blocked, warned about, or logged according to policy.

The MCP security advisor is proactive and advisory: an agent can ask whether an action looks safe before acting. Hooks are the enforcement layer that evaluates the operation during execution. These roles are complementary, but they are not equivalent.

### Tray prerequisites by operating system

The daemon is headless and does not require a desktop. The tray is a separate graphical process, so it needs a logged-in desktop session and a few optional OS integrations for native dialogs and tray icons.

#### Linux

For the tray’s Linux integration, install the PyGObject system package:

```bash
# Fedora / RHEL
sudo dnf install python3-gobject

# Ubuntu / Debian
sudo apt install python3-gi
```

On GNOME, the tray icon also requires the AppIndicator extension:

```bash
# Fedora / RHEL
sudo dnf install gnome-shell-extension-appindicator.noarch

# Ubuntu / Debian
sudo apt install gnome-shell-extension-appindicator
```

Enable the extension and start a new desktop session if your distribution requires it:

```bash
gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com
```

KDE and other desktop environments may use different tray integration. Run `ai-guardian doctor` from the same desktop session that will launch the tray.

#### Tkinter dialogs

Tkinter provides native popup dialogs for interactive decisions. It is optional because AI Guardian can fall back to a browser-based NiceGUI form or a terminal prompt.

```bash
# Fedora / RHEL
sudo dnf install python3-tkinter

# Ubuntu / Debian
sudo apt install python3-tk
```

On macOS, Tkinter is normally included with the system Python. If Python was installed with Homebrew or pyenv, install Tcl/Tk and rebuild the Python environment according to the platform documentation:

```bash
brew install tcl-tk
```

On Windows, Tkinter is included by default with the official Python installer. With `uv`, Tkinter may not be available in the bundled Python; AI Guardian automatically uses its browser or terminal fallback instead. The security checks still operate.

#### macOS and Windows

No separate tray package is normally required beyond the AI Guardian installation and a graphical user session. On newer macOS versions, the tray may open a browser-based dialog rather than a native Tkinter window. On Windows, use a Python installation that includes its standard GUI components.

#### Optional Linux helpers

The tray can open the Console in a terminal window. A supported terminal such as `gnome-terminal`, `kgx`, `konsole`, `xfce4-terminal`, or `xterm` may be needed for that menu action. Window-raising helpers such as `kdotool` on KDE Wayland or `xdotool` on X11 improve browser-window behavior but are optional; the Console can still open without them.

#### Verify the prerequisites

Run:

```bash
ai-guardian doctor
```

Look for the system-tray, dialog-provider, and terminal-emulator checks. A headless server or container may correctly report that the tray is unavailable; that does not mean the daemon or security scanners are unhealthy. In that environment, use the daemon and web or terminal Console instead.

### Guided setup

Use the stable installation documented for your environment. A typical installation is:

```bash
uv tool install ai-guardian
# or
pip install ai-guardian
```

Then run setup for the supported agent you use. For example:

```bash
ai-guardian setup --ide claude --create-config --install-scanner
```

Use the appropriate documented agent name for your environment. Do not copy a command for one host into another host’s configuration.

If a background service is appropriate, start the daemon and optionally the tray:

```bash
ai-guardian daemon start -b
ai-guardian tray start -b
```

Open the Console to inspect status:

```bash
ai-guardian console --web
# or
ai-guardian console
```

The purpose of this first inspection is not to change policy. It is to confirm which integration is active, whether the daemon is healthy, and where violations will appear.

### Hands-on exercise: establish a baseline

Create a small, non-sensitive practice repository containing a README and one harmless source file. Do not place credentials, private keys, customer data, or realistic secret-shaped values in it.

Complete these steps:

1. Run the documented setup command for your agent.
2. Start the daemon if your environment uses it.
3. Open the Console.
4. Record the detected agent, scanner status, active profile, and log location.
5. Run a normal, harmless request such as asking the assistant to explain the practice file.
6. Confirm that the workflow completes and that no unexpected security finding appears.

### Expected result

You should be able to answer four questions:

- Which agent is being protected?
- Which security profile is active?
- Where would you investigate a violation?
- Which part of the pipeline runs before and after a tool call?

### Practical lab: install and verify a protected workflow

**Time:** 20–30 minutes  
**Materials:** Python environment, a supported AI coding agent, and a disposable repository.

#### Part 1 — Prepare the workspace

Create a practice directory with a README and a small source file. Keep the contents ordinary and non-sensitive. Record the agent and operating system you are using so the result is reproducible.

#### Part 2 — Install and set up

Use the stable installation method documented for your platform. Run the documented setup command for your agent. If an administrator manages the policy, stop at the setup or verification step and ask the policy owner before making changes.

#### Part 3 — Inspect the running state

Open the Console or use the documented status and doctor commands. Record:

- The detected agent integration.
- Whether hooks are installed and healthy.
- Whether the daemon is running.
- Which scanner engines are available.
- Which profile or action modes are reported.
- Where violation records are stored.

#### Part 4 — Run a harmless interaction

Ask the assistant to summarize the README or explain the small source file. Observe the interaction without adding any sensitive content. Note whether the request passes through the expected integration and where you would look if it were blocked.

#### Part 5 — Create and save a verification report

Create a new file named `ai-guardian-verification.md` inside the disposable practice repository. Do not save it inside an AI Guardian configuration directory and do not put credentials or private paths in it.

Copy this template into the file and replace the bracketed values with what you observed:

```markdown
# AI Guardian Verification Report

## Environment

- Date:
- Operating system:
- Python version:
- AI Guardian version:
- Protected agent:
- Installation method:

## Observed protection

- Hooks or integration status:
- Daemon status:
- Tray status: [running / not used / unavailable]
- Scanner status:
- Console status:
- Violation location:
- Harmless interaction completed: [yes / no]

## Open questions

- [Write “None” if everything is clear.] 
- [Record anything that needs an administrator, instructor, or policy owner to explain.]
```

Fill in the report using the output from `ai-guardian doctor`, the Console when available, and the harmless interaction from Part 4. If you are on a headless server, use `ai-guardian doctor` as the primary verification tool and use the daemon and other documented CLI checks instead of the tray or desktop Console. In the report, write **not applicable — headless environment** for the tray rather than treating its absence as a security failure.

Save the file, review it for secrets or unnecessary private paths, and submit or keep it with your training materials. The instructor should be able to read the report and understand whether the installation is ready for the next lesson without opening or changing any security configuration file.

### Instructor review criteria

A learner completes the lab successfully when the saved `ai-guardian-verification.md` report identifies the protected agent, confirms the security service or hooks are visible, names the evidence location for violations, uses `ai-guardian doctor` for headless verification when needed, distinguishes an unavailable tray from an unhealthy security service, and contains no sensitive data.

### Knowledge check

1. Why are hooks different from an optional MCP advisor?
2. Why should AI Guardian be combined with other security controls?
3. What should you verify before trusting a first installation?

**Answers:** Hooks enforce during the execution lifecycle, while the advisor is proactive but optional. AI Guardian cannot guarantee detection of every threat, so defense in depth remains necessary. Verify the agent integration, daemon or hook health, scanner status, active policy, and violation visibility.

### Further reading

[AI Guardian home](https://ai-guardian.readthedocs.io/en/latest/) · [Security Design](https://ai-guardian.readthedocs.io/en/latest/SECURITY_DESIGN/) · [Console Guide](https://ai-guardian.readthedocs.io/en/latest/CONSOLE/) · [Multi-Daemon Tray](https://ai-guardian.readthedocs.io/en/latest/MULTI_DAEMON_TRAY/) · [Troubleshooting](https://ai-guardian.readthedocs.io/en/latest/TROUBLESHOOTING/)
