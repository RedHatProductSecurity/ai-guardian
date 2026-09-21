# Prompt Injection, Context Poisoning, and Unicode Attacks

*Three ways untrusted content can influence an AI workflow—and how to explain the defenses without publishing attack recipes.*

AI assistants do not only process code. They read issue descriptions, documentation, logs, webpages, generated files, and tool output. Any of that content may contain instructions that look authoritative to the model but should not control the workflow.

AI Guardian treats this as a layered content-security problem. Prompt-injection detection looks for attempts to manipulate the assistant’s instructions or behavior. Context-poisoning detection focuses on instructions that try to persist across turns or become part of the assistant’s working context. Unicode detection looks for invisible or deceptive characters that can hide meaning from a human reviewer.

## Prompt injection

Prompt injection is not simply a rude sentence in a file. The risk is that untrusted content attempts to redefine the assistant’s priorities, request sensitive information, or direct it toward an unsafe operation. Detection can use heuristics, language-aware analysis, and configurable sensitivity.

The right article framing is defensive: show how a suspicious document is identified, how the action mode affects the result, and how a developer investigates the finding. Avoid publishing real attack strings or step-by-step instructions for defeating a detector. Safe demonstrations can use inert, test-prefixed values that are clearly not intended to control a real agent.

## Context poisoning

Context poisoning is related but emphasizes persistence. A document, memory entry, or tool result may try to insert instructions that remain active after the original content is no longer obvious. Detection helps surface that behavior before it becomes part of a longer workflow.

Because legitimate documentation sometimes discusses persistence, context-related detection can produce false positives. That is why the project exposes sensitivity and action choices. Teams should evaluate findings against real project content and use the documented review process when an alert is legitimate.

## Unicode attacks

Unicode can create a gap between what a file appears to say and what software interprets. Zero-width characters, bidirectional overrides, tag characters, and look-alike characters can make review harder. AI Guardian can detect several of these categories and report the location and type of suspicious character.

The safe lesson is not to teach readers how to hide instructions. It is to make hidden text visible, keep source review human-readable, and treat unexpected characters in code, configuration, or instructions as something to investigate.

## Action modes and layered defense

These detections can use `block`, `warn`, or `log-only` modes depending on the feature and the chosen profile. A development team may begin with warnings to understand the signal, while a high-security environment may block more categories immediately. The policy should reflect the risk and the team’s ability to respond.

No detector is perfect. Heuristics can miss novel content, and strict sensitivity can create noise. Layering matters: even if a malicious instruction is not detected, directory rules, tool permissions, SSRF protection, secret scanning, and output redaction may still limit the impact.

## A responsible demonstration

Use a harmless sample document containing an explicit marker such as `TEST-INJECTION-SAMPLE`. Show the scan result, the violation category, and the review path. Do not include real credentials, functional payloads, or instructions for bypassing protections.

## Why these threats belong together

These features address different stages of the same trust problem. Prompt-injection detection considers the meaning of instructions. Context-poisoning detection considers how instructions may persist. Unicode detection considers whether the text a human reviews is the same text that software or a model receives.

Together, they encourage a more careful question: “Who authored this content, and what authority should it have?” A project README may be useful reference material, but it should not automatically become a system instruction. A tool result may contain valuable data, but it should not silently redefine the task. A visually normal line of text may deserve inspection if it contains unexpected characters.

This framing keeps the controls understandable. The goal is not to distrust every file or make AI-assisted development impossible. The goal is to preserve the distinction between information the assistant may analyze and instructions it is authorized to follow.

Read more: [Prompt Injection](https://ai-guardian.readthedocs.io/en/latest/security/PROMPT_INJECTION/), [Unicode Attacks](https://ai-guardian.readthedocs.io/en/latest/security/UNICODE_ATTACKS/), and [Security Design](https://ai-guardian.readthedocs.io/en/latest/SECURITY_DESIGN/).
