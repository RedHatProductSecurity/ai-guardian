# Network, Exfiltration, and Supply-Chain Protection

*How AI Guardian looks beyond prompts and files to the network requests, configuration files, hooks, and extensions around an AI agent.*

An AI assistant can be manipulated without directly reading a secret. It might be encouraged to send data to an unexpected endpoint, inspect a credential-bearing configuration file, or load a plugin that changes the behavior of the development environment. These risks connect application security, network security, and software supply-chain security.

## SSRF protection

Server-Side Request Forgery, or SSRF, occurs when a tool or service is induced to make a request to a location it should not reach. In an AI workflow, the request may come from a generated command, a tool call, or a URL found in untrusted content.

AI Guardian can check for private network destinations, cloud metadata endpoints, and dangerous URL schemes. The goal is to prevent an assistant from turning a seemingly ordinary fetch or request into a path toward internal services or credentials.

The article should explain the decision at a high level: what category was detected, why the request matters, and how a legitimate development need should be reviewed through policy. It should not provide a catalogue of ways to probe protected networks.

## Credential-exfiltration and configuration threats

Configuration files frequently contain connection details, tokens, or provider settings. AI Guardian can scan for patterns that suggest a command or configuration is attempting to move credentials elsewhere. This is different from ordinary secret scanning: the concern is not only that a secret exists, but that the workflow is trying to extract it.

A safe walkthrough can use a synthetic configuration file with placeholder values and an inert command marker. The reader can observe the finding category and the audit record without handling real credentials or real external destinations.

## Supply-chain scanning

AI coding environments increasingly depend on hooks, MCP server definitions, plugins, extensions, and agent configuration files. Those files can introduce executable commands, change environment variables, or add network behavior.

Supply-chain scanning helps identify suspicious patterns in these integration points. It gives teams a chance to review the source and provenance of an extension before allowing it into a development workflow. This is especially important when the extension is shared across many repositories or developers.

## Defense in depth

These checks work best together:

- Network protection limits where a tool can connect.
- Directory rules limit what it can read.
- Secret scanning identifies sensitive values.
- Tool permissions control which capabilities are available.
- Supply-chain scanning examines the code and configuration that extend the agent.
- Violation logging records what was blocked and why.

No single layer can understand every application-specific risk. A blocked request still needs human review, and an allowed request still deserves normal change control when it affects production systems or sensitive data.

## A practical review workflow

When a request is blocked, first identify whether the category is network access, credential exfiltration, configuration threat, or supply-chain behavior. Next, verify the source of the request and whether the project genuinely needs it. Then use the organization’s approved process to request a policy review or document the legitimate use case.

The useful outcome is a better-understood workflow, not a weaker security boundary.

## Where teams use these controls

These protections are especially valuable at integration boundaries. A development team may trust its repository but not every MCP server registered on a workstation. It may trust a build command but not an arbitrary URL embedded in an issue. It may approve a plugin in one context but require additional review before that plugin is used against customer data.

The controls help turn those distinctions into observable decisions. Network checks focus attention on destinations. Configuration and exfiltration checks focus attention on data movement. Supply-chain checks focus attention on the code and metadata that extend the agent’s capabilities.

The result is a more complete threat model for AI-assisted development. Instead of asking only whether the model produced safe text, the organization can ask whether the surrounding tools, files, endpoints, and extensions are trustworthy for the task.

Read more: [SSRF Protection](https://ai-guardian.readthedocs.io/en/latest/security/SSRF_PROTECTION/), [Credential Exfiltration](https://ai-guardian.readthedocs.io/en/latest/security/CREDENTIAL_EXFILTRATION/), and [Configuration](https://ai-guardian.readthedocs.io/en/latest/CONFIGURATION/).
