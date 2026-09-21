# Configuration, Permissions, and Directory Protection

*How AI Guardian decides which tools may run and which parts of the filesystem an AI assistant may access.*

AI Guardian becomes most useful when its general security features are connected to an explicit policy. That policy answers two practical questions: what may the assistant do, and where may it do it?

## Configuration has layers

AI Guardian can combine settings from several locations. A user configuration provides the general baseline. A project-level configuration can add repository-specific settings. Enterprise deployments can provide remote policy sources, including settings that are intentionally immutable.

This layered model supports both individual developers and teams. A developer may need project-specific scanning rules, while an organization may need certain controls to remain consistent everywhere. The important principle is that not every configuration source has the same authority.

Before changing anything, use the documented configuration locations and precedence rules to understand which file is active. A setting that appears to have no effect may be coming from a higher-priority source or may be protected as immutable. When policy is centrally managed, the correct next step is to discuss the policy with the responsible security team rather than trying to work around it.

## Tool permissions

AI Guardian distinguishes among built-in tools, Skills, and MCP servers. Built-in tools can be allowed while their inputs and outputs are scanned. Skills and third-party MCP servers are treated more cautiously because they can introduce new instructions, code, commands, or external services.

Permission rules can allow or deny tools by matcher and pattern. The documentation describes a last-match-wins model: broad rules should be placed first, followed by narrower exceptions. This makes the rule list readable when it is designed from general policy to specific project needs.

For example, a team might begin with a broad deny for unapproved third-party capabilities and then explicitly allow a small set of reviewed tools. The article should focus on the reasoning behind that policy, not on making the broadest possible allowlist.

## Directory rules

Tool permissions are only half of the boundary. Directory rules control which files and folders an assistant can access. They can protect credentials, private keys, environment files, system directories, version-control internals, and customer data.

AI Guardian also supports `.ai-read-deny` markers. A marker placed in a directory communicates that the directory should not be read by the AI assistant. This is useful when protection should travel with a folder, independent of the global configuration.

A practical project policy often starts with a narrow workspace allowlist and explicit protection for sensitive locations. Use paths that are clear to the people who will maintain them. Avoid rules that depend on undocumented assumptions about the current working directory.

## A safe policy review workflow

When designing a policy:

1. List the directories the assistant genuinely needs.
2. Identify credentials, customer data, build secrets, and system files that must remain outside the workspace.
3. List the external tools and services the project requires.
4. Separate reviewed tools from tools that need further evaluation.
5. Test the policy with harmless files and commands.
6. Review the resulting violations and adjust through the approved configuration process.

The goal is a policy that is understandable, reviewable, and shared by the team. Security controls are easier to operate when people know why a path or tool is protected.

## Why policy design matters

The technical rule is only one part of the result. A policy also communicates intent to the people who maintain a repository. “This workspace is allowed” is easier to understand than a long collection of unexplained exceptions. “This credential directory is protected” gives a developer a clear reason to move the task into a safer workflow instead of trying to make the assistant reach it.

Policy design also affects incident response. When a request is denied, investigators need to know whether the decision came from a global rule, a project boundary, a remote policy, or a directory marker. Clear ownership and readable patterns reduce the time between a finding and a responsible decision.

The best policy is usually not the most complicated one. It is the smallest, clearest boundary that lets the assistant complete legitimate work while keeping sensitive tools and data outside the normal workflow.

Read more: [Tool Policy](https://ai-guardian.readthedocs.io/en/latest/TOOL_POLICY/), [Directory Rules](https://ai-guardian.readthedocs.io/en/latest/security/DIRECTORY_RULES/), and [Configuration](https://ai-guardian.readthedocs.io/en/latest/CONFIGURATION/).
