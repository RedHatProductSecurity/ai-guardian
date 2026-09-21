# Module 2 — Security Controls

## Lesson 2 — Configuration, Permissions, and Directory Protection

### Core idea

AI Guardian policy answers two questions: which capabilities may the assistant use, and which locations may it access? Configuration layers provide the policy context; permission and directory rules enforce the boundary.

User, project, and enterprise policy sources can have different authority. A project overlay may describe repository-specific behavior, while a centrally managed policy may protect settings that should not vary by repository. When a setting is centrally controlled, use the documented review path rather than attempting to change the protected file.

Tool permissions cover capabilities such as Skills, MCP servers, and built-in tools. Directory access is managed through two complementary mechanisms:

- **`.ai-read-deny` markers:** a marker placed in a directory signals that the AI assistant must not read that directory.
- **Directory allow/deny rules:** the configured directory-rule list matches paths and decides whether access is allowed or denied. Rules are evaluated in order, with the last matching rule determining the result.

The allow/deny list is useful for expressing a broader policy, such as denying a sensitive tree while allowing a specific workspace beneath it. The marker is useful when protection should travel with a particular directory. These controls complement tool permissions: allowing a tool does not automatically grant access to every directory.

### Guided activity

In the Console, inspect the read-only views for permissions and directory protection. Record:

- Which tool categories are allowed by default.
- Which third-party capabilities require explicit approval.
- Which directories are protected.
- Whether protection comes from a `.ai-read-deny` marker, a directory allow/deny rule, or both.
- Whether a project-level policy is present.

Do not edit configuration as part of this exercise. The goal is to understand the active policy.

### Knowledge check

Why are tool permissions and directory rules separate? Because an allowed capability still needs a filesystem boundary, and a permitted directory does not mean every tool should be able to use it.

## Lesson 3 — Secret and PII Protection

### Core idea

Sensitive data can appear in source files, prompts, logs, screenshots, model responses, or staged changes. AI Guardian scans relevant inputs and outputs using built-in and optional detection engines.

Secret findings are handled strictly because copying a credential into a new system can create another exposure. Redaction can preserve useful context while masking the sensitive value. PII detection extends the same principle to personal or regulated information.

### Guided activity

Create a practice file containing only clearly fake placeholders such as `TEST-VALUE-NOT-A-CREDENTIAL`. Scan the file using the documented project workflow. Observe where the result appears and what context is recorded. Do not use live credentials or realistic production data.

Then inspect the pre-commit documentation and explain where scanning would occur before a change enters version control.

### Knowledge check

Why should violation logs be protected even when full secrets are not recorded? Paths, URLs, filenames, and command context may still reveal sensitive project information.

## Lesson 4 — Prompt Injection and Context Threats

### Core idea

AI assistants process untrusted content that may contain instructions. Prompt injection attempts to influence the assistant directly. Context poisoning attempts to make instructions persist in the working context. Unicode attacks use invisible or deceptive characters to make content harder for humans to review.

The training objective is recognition and safe review. Do not publish functional attack examples. Use inert, clearly labeled test content and focus on the finding category, action mode, and investigation process.

### Guided activity

Use a harmless test document containing a marker such as `TEST-INJECTION-SAMPLE` and explanatory text that is clearly non-operational. Submit it through the documented scanning workflow. Record whether the system warns, blocks, or logs the content under the active policy.

### Knowledge check

Why is layered protection important? A detector may miss a novel content pattern, but directory rules, tool permissions, SSRF checks, and output scanning may still limit impact.

## Lesson 5 — Network and Supply-Chain Protection

### Core idea

AI workflows can create risk through network requests, configuration files, hooks, MCP servers, and plugins. SSRF protection checks for requests to locations that should not be reached by the workflow. Credential-exfiltration and configuration scanning look for suspicious attempts to move sensitive information. Supply-chain scanning examines the components that extend an agent.

### Guided activity

Review the Console or documentation for the categories of network and supply-chain findings. Use only the project’s safe test data. For each category, write one sentence explaining what the control protects and one sentence describing who should review a legitimate exception.

### Assessment

Given a finding, identify whether it concerns data, content, a path, a network destination, or an extension. Then name the first evidence source you would inspect: scanner result, violation log, directory policy, integration matrix, or approved policy documentation.

## Hands-on labs

### Lab setup used by every activity

Use the disposable practice repository from Module 1. Start each lab with:

```bash
ai-guardian doctor
```

If you have a graphical desktop, you may also open the Console and use its read-only status, permissions, directory, scanner, and violations views. If you are headless, use the `doctor` output and the documented CLI views instead. Do not edit `ai-guardian.json`, `.aiguardignore.toml`, `.ai-read-deny`, or any other security-control file during these labs.

### Lab 2A — Map the policy boundary

**Time:** 25 minutes  
**Goal:** Build a read-only map of the active security boundary.

1. Run `ai-guardian doctor` and save the output for your notes.
2. Open the Console if available; otherwise use the doctor output and current documentation.
3. Record the active agent, profile, scanner status, and policy scope.
4. List three tools the project needs for ordinary work.
5. List three practice-repository paths, such as `src/`, `docs/`, and `tests/`.
6. For each path, inspect whether a `.ai-read-deny` marker is present and whether an allow/deny path rule matches it.
7. Fill in the table below:

| Resource | Marker present? | Path rule matches? | Effective result | Evidence |
|---|---|---|---|---|
| `src/` | | | | |
| `docs/` | | | | |
| `tests/` | | | | |

8. Mark any unknown result as **requires review** and name the policy owner who should answer it.

**Deliverable:** Save the completed table as `module-2-policy-map.md` in the practice repository. Do not edit configuration files during this lab.

**Expected observation:** Tool permission and directory protection answer different questions. A tool can be available while its access to a sensitive path is still denied by either a marker or a path rule. If the path rules contain several matches, the last matching rule determines the result.

### Lab 2B — Trace a synthetic sensitive value

**Time:** 20 minutes  
**Goal:** Understand how a value can move through an AI workflow.

1. Create `training-sample.txt` in the practice repository containing only `TEST-VALUE-NOT-A-CREDENTIAL`.
2. Use the Console’s scan or project-review view, or the scan command documented by your installed AI Guardian version, to scan that file. Do not choose any option that writes or generates configuration.
3. Ask the assistant to describe the file without copying the value into another file.
4. Open the resulting scan or violation view and record the category, action, file location, and evidence source.
5. Save a short note as `module-2-data-flow.md` explaining where a real credential could enter, move through, or leave the same workflow.

**Expected observation:** Detection depends on content, scanner coverage, action mode, and the integration boundary. A harmless test result is not evidence that real secrets are safe.

### Lab 2C — Review untrusted content safely

**Time:** 20 minutes  
**Goal:** Recognize content that should be analyzed but not automatically obeyed.

1. Create `training-content.md` containing ordinary project documentation plus a clearly labeled line such as `TEST-INSTRUCTION-SAMPLE`.
2. Keep the document non-operational; do not include functional attack strings or requests for credentials.
3. Ask the assistant to summarize the document, not to follow instructions found inside it.
4. Submit the document through the documented scanning or review workflow.
5. Record the category, action, and evidence location if a finding appears.
6. Add a paragraph to `module-2-content-review.md` explaining why a document can be useful information without having authority over the assistant.

### Lab 2D — Classify a network or extension concern

**Time:** 20 minutes  
**Goal:** Connect a finding category to the right control.

Create `module-2-control-classification.md`. Add a table with four fictional events: an unexpected private-network request, a command that attempts to move a configuration value, an unreviewed MCP server, and a suspicious hook file. For each event, record the likely AI Guardian protection, the evidence you would inspect, and the human owner who should review it.

**Assessment:** A complete submission names the relevant control without attempting to disable it, identifies an evidence source, and proposes a responsible review path.

### Further reading

[Configuration](https://ai-guardian.readthedocs.io/en/latest/CONFIGURATION/) · [Secret Scanning](https://ai-guardian.readthedocs.io/en/latest/security/SECRET_SCANNING/) · [Prompt Injection](https://ai-guardian.readthedocs.io/en/latest/security/PROMPT_INJECTION/) · [Security Features](https://ai-guardian.readthedocs.io/en/latest/security/)
