# Module 3 — Daily Use

## Lesson 6 — Responding to Blocked Operations

### Core idea

A blocked operation is a security signal, not an invitation to retry until it succeeds. The first task is classification: determine whether the finding concerns a tool permission, directory, secret, prompt, network destination, configuration file, or extension.

### Investigation workflow

1. Read the user-facing reason and record the category.
2. Open the Console or violation log entry.
3. Identify the tool, path, source, and time involved.
4. Decide whether the requested operation is actually necessary.
5. If it is legitimate, use the organization’s approved review process.
6. Re-test only after the responsible policy owner has made or approved a decision.

This workflow prevents two common mistakes: treating every block as a false positive and treating every block as proof of malicious intent. A test fixture may resemble a secret; a real credential may be exposed accidentally. Evidence and context determine the next step.

### Practice exercise

Use a harmless practice repository and review a sample violation in the Console or documentation examples. Write a short incident note containing the category, affected resource, likely cause, impact assessment, and recommended next action. Do not include sensitive values in the note.

### Knowledge check

What is the correct first response to a block? Identify and investigate the category before changing the task or requesting a policy decision.

## Lesson 7 — AI Guardian Across Coding Agents

### Core idea

Different AI coding agents expose different hook events and response formats. AI Guardian uses adapters to normalize those inputs so that the core scanning pipeline can apply common checks.

An adapter may normalize the event type, tool name, tool input, path, working directory, session identifier, prompt, tool response, and transcript information. It also determines how an allow or block decision is returned to the host.

### Capability comparison

Do not evaluate an integration only by whether its name appears in a supported list. Check the capability matrix for:

- Prompt submission checks.
- Pre-tool and post-tool checks.
- Session and transcript coverage.
- MCP registration or advisory support.
- Plugin or extension boundaries.
- Known limitations and confidence level.

An MCP-only integration may not provide the same enforcement timing as a full hook integration. A commit-time scanner protects a different boundary from an interactive pre-tool hook.

### Guided activity

Choose two agents from the current support matrix. Create a comparison table with their setup command, managed events, MCP status, transcript support, and known limitations. Then write one sentence explaining which agent provides the stronger match for a fictional team requirement and why.

### Assessment

Given a missing event or unexpected result, learners should first check the host agent’s capability matrix and adapter behavior before assuming the scanner itself failed.

## Hands-on labs

### Lab 3A — Investigate a violation record

**Time:** 25 minutes  
**Goal:** Practice an evidence-first response to a blocked operation.

1. Open a documented sample violation or a harmless finding from the practice environment.
2. Record the timestamp, violation category, tool or event, path if present, and action taken.
3. Decide whether the finding indicates a genuine risk, a harmless test artifact, or insufficient information.
4. Write the next responsible action: change the task, consult the policy owner, or document the finding for review.
5. Confirm that your note contains no secret values or unnecessary sensitive output.

**Expected result:** The learner can explain the finding without retrying the blocked operation blindly.

### Lab 3B — Compare two agent integrations

**Time:** 30 minutes  
**Goal:** Use the capability matrix to choose an integration deliberately.

1. Select two supported agents from the current documentation.
2. Record their setup commands, managed hook events, MCP status, transcript support, and known limitations.
3. Choose a fictional project requirement such as interactive coding, commit-time scanning, or custom-agent integration.
4. Recommend one agent for that requirement and cite the capability that drove the decision.
5. Identify one security boundary that remains outside both integrations.

**Deliverable:** A comparison table plus a short recommendation.

### Reflection

Answer these questions in writing:

- What information makes a violation actionable?
- Why can two supported agents provide different protection depth?
- When should a developer involve a policy owner rather than continue troubleshooting locally?

### Assessment rubric

- **Complete:** Evidence is recorded accurately, sensitive data is not copied, and the proposed next step is responsible.
- **Needs revision:** The learner retries the operation without classification, assumes every block is a false positive, or treats a supported integration as full coverage without checking its matrix.

### Further reading

[Console Guide](https://ai-guardian.readthedocs.io/en/latest/CONSOLE/) · [Violation Logging](https://ai-guardian.readthedocs.io/en/latest/VIOLATION_LOGGING/) · [Agent Support](https://ai-guardian.readthedocs.io/en/latest/AGENT_SUPPORT/)
