# When AI Guardian Blocks an Operation

*A calm, repeatable workflow for understanding findings, reviewing context, and fixing legitimate problems.*

A block is not the end of a task. It is a security signal that says an operation crossed a policy boundary or matched a detection rule. The fastest way to recover productively is to understand the category, inspect the surrounding context, and decide whether the task or the policy needs attention.

## Start with the category

AI Guardian can report blocked tool permissions, directory access, secrets, prompt injection, SSRF, Unicode issues, configuration threats, and other findings. The category usually tells you where to begin:

- A tool-permission finding points to the requested capability and policy.
- A directory finding points to the path and operation.
- A secret finding points to the content location and scanner result.
- A prompt or context finding points to untrusted instructions.
- A network finding points to the request destination and reason category.

Do not begin by repeatedly retrying the same operation. First determine what the system saw.

## Use the Console and violation history

The web and terminal consoles provide a human-facing way to inspect configuration, recent violations, scanner status, and daemon health. Violation logging provides a JSONL audit trail that can be filtered by type, timestamp, tool, or location.

The record should contain enough information to investigate without copying sensitive content into a new ticket or chat message. Treat logs as security-sensitive: file paths, URLs, and command context may reveal project structure even when secret values are redacted.

## Separate false positives from legitimate blocks

Some content resembles a secret, an instruction, or a dangerous command even when it is part of a test, fixture, documentation example, or generated output. A false positive is not a reason to remove a broad control. Instead:

1. Confirm that the content is genuinely harmless.
2. Identify the narrowest scope of the exception.
3. Use the documented annotation, ignore, or allowlist mechanism.
4. Record why the exception is safe.
5. Re-run the relevant check and review the result.

For shared repositories, project-level rules should be reviewed like code. For enterprise-managed policies, contact the policy owner instead of altering protected settings locally.

## Learn from repeated findings

Repeated blocks can reveal a workflow problem. Perhaps a build process is copying sensitive output into a log, a test fixture contains realistic credential-shaped strings, or an agent is being asked to access a directory it never needed.

The right fix may be to change the workflow, move a secret into a secret manager, reduce the scope of a task, or improve documentation. Security tooling is most useful when it makes these design problems visible.

## Keep the human in the loop

AI Guardian can classify and enforce policy, but people still decide whether a business process is legitimate. A blocked operation should result in a clear decision: change the task, request an approved policy change, or stop the operation.

That habit turns a block from friction into feedback. Over time, the organization gains both safer defaults and a better understanding of how AI tools are actually used.

## A block is part of the product experience

Security tools are often judged only by whether they stop a dangerous action. In an AI workflow, the quality of the explanation matters almost as much. A useful finding tells a person what category was involved, what resource was affected, and where to look next. That information lets the developer change the task intelligently instead of guessing.

This is also why violation history is valuable beyond incident response. A repeated category may indicate that a team needs better documentation, a narrower workflow, a safer test fixture, or a new integration review. Aggregated findings can show where the assistant is regularly asked to cross a boundary that the project should redesign.

The most mature teams treat findings as feedback about both security and developer experience. They preserve important controls while improving the workflows around them.

Read more: [Console Guide](https://ai-guardian.readthedocs.io/en/latest/CONSOLE/), [Violation Logging](https://ai-guardian.readthedocs.io/en/latest/VIOLATION_LOGGING/), and [Configuration Cookbook](https://ai-guardian.readthedocs.io/en/latest/COOKBOOK/).
