# Operating and Observing AI Guardian at Scale

*How the daemon, tray, logs, metrics, and traces turn security controls into an operable service.*

Security protection is only useful when people can tell whether it is active, understand what it is doing, and investigate problems without guessing. AI Guardian includes several layers of operational visibility: a background daemon, a tray interface, violation logs, latency metrics, and OpenTelemetry traces.

## The daemon and tray

The daemon provides a long-lived process for hook handling and can reduce repeated startup work. The tray provides a user-facing view over daemons running locally or in supported container environments. Depending on the platform and deployment, it can expose status, statistics, console access, pause/resume controls, and start/stop actions.

This separation is useful. The daemon can run headlessly in a development or CI environment, while the tray is an optional desktop control surface. Teams should decide who is allowed to pause or change a daemon and how that action is recorded.

## Violation logs

AI Guardian records blocked operations in JSONL format. Each line can be processed as an individual event, which makes the log suitable for local inspection, retention policies, and forwarding to a security platform.

The log can help answer operational questions:

- Which security categories are producing findings?
- Which projects or tools are involved?
- Are blocks increasing after a configuration change?
- Are users repeatedly encountering the same false positive?

Logs may contain paths, URLs, and command context. Even when secret values are redacted, the log should be protected with appropriate filesystem permissions and retention.

## Latency metrics

Security checks introduce work into an interactive workflow. Hook-latency tracking can help teams identify slow scanners, expensive patterns, or daemon problems. Metrics are most useful when they are compared against the user experience: a small increase may be acceptable for a high-risk operation, while a delay on every simple file read may need investigation.

Measure before optimizing. Removing a useful check to improve a number is not a successful security improvement.

## OpenTelemetry traces

AI Guardian can export traces for SDK agent runs and interactive sessions to OTLP-compatible systems such as Grafana Tempo, Jaeger, Datadog, Splunk, or Honeycomb. Traces can show the relationship among turns, model calls, tool use, security checks, and timing.

Tracing should be designed with privacy in mind. Decide which metadata is appropriate to export, where trace data is stored, how long it is retained, and who can inspect it. Observability should help security and reliability teams without becoming an uncontrolled copy of sensitive project content.

## A practical operating rhythm

Start each environment with a health check. Review violations and latency periodically. Watch for changes after upgrading an agent, scanner, or policy. Export traces when diagnosing an integration or performance issue, then apply the organization’s retention and access rules.

The result is a feedback loop: protection produces evidence, evidence informs policy and workflow design, and the improved workflow reduces repeated findings.

## From events to decisions

Operational data becomes useful when it is connected to a decision. A rise in secret findings may indicate a new integration is returning sensitive output. Increased latency may point to a scanner or daemon change. A missing trace may reveal that a workflow is running outside the expected hook or SDK boundary.

Teams should define these interpretations in advance. Decide which findings require immediate review, which metrics represent a user-impacting regression, and which trace fields are safe to share with a wider operations group. This turns observability from a dashboard exercise into a practical operating model.

The objective is not to collect everything forever. It is to collect enough trustworthy evidence to maintain protection, investigate changes, and improve the developer experience without creating a new uncontrolled data store.

Read more: [Multi-Daemon Tray](https://ai-guardian.readthedocs.io/en/latest/MULTI_DAEMON_TRAY/), [Violation Logging](https://ai-guardian.readthedocs.io/en/latest/VIOLATION_LOGGING/), and [Observability](https://ai-guardian.readthedocs.io/en/latest/OBSERVABILITY/).
