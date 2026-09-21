# Secret and PII Protection in AI Workflows

*How AI Guardian helps keep credentials and personal information out of prompts, files, commits, and tool output.*

AI assistants are often asked to inspect configuration, debug services, review logs, or prepare changes. Those tasks can expose API keys, tokens, passwords, connection strings, or personally identifiable information. The risk is not limited to source code: sensitive data can appear in a prompt, a generated patch, a command result, or a screenshot.

AI Guardian addresses this with scanning at multiple points in the workflow. Secret scanning can inspect content before it is used, while post-tool checks can inspect returned output. Redaction can mask detected values while preserving enough context for a person or agent to understand what happened.

## Built-in and optional scanners

The project includes a built-in pattern engine so basic scanning does not depend on an external binary. Optional engines can add coverage or provide organization-specific workflows. The exact engine mix should be chosen according to the environment, performance needs, licensing requirements, and the kinds of credentials the organization uses.

A useful explanation for readers is that no scanner sees every possible secret format. Built-in patterns provide a baseline, while teams may need custom rules, regular updates, and a proper secret-management system. A blocked finding is a signal to investigate the data path, not proof that every other secret is safe.

## What happens when a secret is found?

Secret findings are handled more strictly than many other detections. The documentation emphasizes that detected secrets are blocked rather than merely logged as a warning. Violation records can contain useful context such as a file location or category, but they should not expose the full secret value.

This is important for operations. An audit trail should help answer questions such as “which tool produced this finding?” or “which file contained it?” without creating a second place where the credential is copied.

## PII and redaction

PII detection extends the same idea beyond credentials. Depending on the configured scanners and patterns, AI Guardian can identify information such as email addresses, phone numbers, payment data, or other sensitive identifiers. Teams should review the expected data types and false-positive behavior before choosing a strict action mode.

Redaction is useful when the surrounding content is needed but the sensitive value is not. For example, an error message may be diagnostically useful even when a token embedded in its URL must be masked. The result should preserve context while minimizing disclosure.

## Protecting the commit path

A pre-commit workflow adds another checkpoint. Scanning staged files helps catch a credential before it enters version control. This complements runtime protection: a developer might accidentally create a test fixture, copy a production response into a log, or paste a token into a configuration example.

Use placeholders in documentation and examples. Never test with a live credential. If a real secret is ever exposed, follow the organization’s incident process and rotate or revoke it through the proper secret-management system.

## A practical review checklist

- Identify which scanners are active.
- Confirm where violation records are stored and who can read them.
- Test with inert, clearly marked values.
- Review false positives without copying sensitive data into tickets or chat.
- Add pre-commit scanning for repositories that handle credentials.
- Treat scanning as one layer alongside secret managers, access controls, and code review.

## Detection is a data-flow question

A useful way to think about scanning is to follow the data rather than focus only on files. Where did the value enter the workflow? Was it read from a repository, pasted into a prompt, returned by a command, included in a screenshot, or generated into a patch? Where could it go next? Could it be written to a commit, sent to a model provider, printed in a log, or included in a tool call?

This perspective explains why pre-tool and post-tool checks complement each other. A file may be clean when first opened but produce sensitive output after a command runs. Conversely, an unsafe value may be present in an input before any tool executes. Multiple checkpoints reduce the chance that one missed event becomes the only line of defense.

Scanning also supports better engineering habits. Teams can replace real examples with placeholders, keep production data out of development repositories, and route credentials through dedicated secret-management systems. AI Guardian provides detection and evidence; the organization still owns the larger data-handling policy.

Read more: [Secret Scanning](https://ai-guardian.readthedocs.io/en/latest/security/SECRET_SCANNING/), [Scanner Installation](https://ai-guardian.readthedocs.io/en/latest/SCANNER_INSTALLATION/), and [Security Features](https://ai-guardian.readthedocs.io/en/latest/security/).
