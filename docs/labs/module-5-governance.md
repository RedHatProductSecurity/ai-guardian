# Module 5 — Governance

## Lesson 11 — Enterprise Deployment and Practical Limitations

### Why governance matters

AI Guardian changes the way an organization approves, monitors, and reviews AI-assisted development. A successful rollout therefore needs more than installation. It needs policy ownership, an exception process, integration verification, and a realistic understanding of what detection can and cannot guarantee.

### A phased rollout

Begin with visibility. Inventory the agents, repositories, runtimes, and extensions in scope. Review the Console, violation records, and integration matrix. Learn which findings are common before making broad enforcement decisions.

Next, select a security profile that fits the environment. A lower-friction profile may help a team learn the signal; a stricter profile may be appropriate for sensitive or regulated work. The profile is a starting point, not a substitute for policy ownership.

Assign responsibility for global policy, project policy, remote policy, scanner health, and incident review. Developers need a clear route for legitimate questions. Security teams need enough evidence to understand whether a finding is a real risk, a workflow problem, or a false positive.

### Centralized policy

Some requirements should remain consistent across repositories. Remote policy sources and immutable settings can help enforce those requirements. Use them selectively and document why a setting is protected. Project teams can then retain flexibility where it does not weaken the organization’s security posture.

This training does not ask learners to edit protected security configuration. Instead, learners identify the policy owner, gather evidence, and use the approved change or exception process.

### Know the limits

Prompt-injection detection can miss novel or obfuscated content. Secret scanning depends on pattern coverage and may miss organization-specific formats. Different agents expose different hook events, so protection depth varies. Some failure paths prioritize availability and allow work to continue when a scan cannot complete.

These limitations are not reasons to abandon the tool. They are reasons to use defense in depth: code review, CI scanning, network restrictions, least privilege, secret managers, sandboxing, and incident response.

### Capstone activity

Create a deployment plan for a fictional engineering team. Include:

- Agents and runtimes in scope.
- Directories and data requiring protection.
- An initial profile and rollout stage.
- Owners for global and project policy.
- Signals to review in logs, metrics, and traces.
- The process for investigating a blocked operation.
- The controls that remain outside AI Guardian’s scope.

### Final assessment

Explain why an organization should measure AI Guardian’s findings and integration coverage before treating the deployment as complete. A strong answer should mention visibility, policy ownership, agent-specific capabilities, operational evidence, and defense in depth.

## Hands-on capstone: design a responsible rollout

**Time:** 45–60 minutes  
**Scenario:** A fictional engineering organization has 40 developers, three AI coding agents, several repositories, and a small set of projects that process customer data. The organization wants consistent protection without preventing ordinary development work.

Prepare a rollout document with these sections:

### 1. Scope and inventory

List the agents, repositories, runtime environments, and extensions that must be reviewed. Identify which workflows are interactive IDE sessions, SDK-based applications, commit-time checks, or sandboxes.

### 2. Data and path boundaries

Describe which repositories and directories are in scope, which locations contain sensitive data, and which data must never be copied into the lab or documentation. Keep the description abstract; do not use real paths or credentials.

### 3. Rollout stages

Define an initial visibility stage, an evaluation stage, and an enforcement stage. For each stage, describe what evidence will be collected and who reviews it. Do not propose bypassing or weakening protected controls.

### 4. Ownership and escalation

Assign fictional owners for platform operations, security policy, project configuration, agent integrations, and incident response. Describe how a developer reports a legitimate block or integration gap.

### 5. Success measures

Choose measurable signals such as healthy hook coverage, visible violation records, scanner availability, latency, repeated findings, and time to resolve a legitimate workflow issue. Explain what change would trigger a review.

### 6. Limitations and defense in depth

Name at least four limitations of AI Guardian and pair each with a complementary control such as code review, CI scanning, network policy, secret management, least privilege, sandboxing, or incident response.

### Capstone rubric

- **Policy clarity:** Roles, scope, and escalation paths are explicit.
- **Technical accuracy:** The plan distinguishes hooks, SDK checks, sandboxes, scanners, and observability.
- **Safety:** The plan uses disposable data and does not request changes that weaken protections.
- **Operational realism:** The plan includes health checks, evidence review, upgrades, and retention.
- **Defense in depth:** The plan does not treat AI Guardian as the only security control.

### Further reading

[Security Design](https://ai-guardian.readthedocs.io/en/latest/SECURITY_DESIGN/) · [Configuration](https://ai-guardian.readthedocs.io/en/latest/CONFIGURATION/) · [Documentation index](https://ai-guardian.readthedocs.io/en/latest/documentation/)
