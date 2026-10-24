# Potential Integrations

The proposals below are not available integrations or commitments to develop them.
For implemented IDE/agent integrations, see [Agent Support](AGENT_SUPPORT.md).

## Potential Integration: ServiceNow Bring Your Own Guardrail (BYOG)

**Status: Potential integration — not implemented, not tested, unsupported, and
unvalidated.**

ServiceNow's Now Assist Guardian / AI Guardian supports Bring Your Own Guardrail
(BYOG), allowing organizations to integrate external security services to evaluate
AI prompts and responses.

AI Guardian (this project) could potentially serve as a custom guardrail provider
for ServiceNow by leveraging its existing REST API and security scanning engines.
These building blocks do not provide a ServiceNow-compatible BYOG integration
today.

Such an integration would require additional development to:

- Adapt ServiceNow's request and response formats to AI Guardian's scanning inputs
  and results.
- Configure secure communication, including authentication and transport
  protection.
- Validate guardrail enforcement for prompts and responses in a suitable
  ServiceNow development/test environment.

**This integration is not currently supported or validated.** Access to a suitable
ServiceNow development environment would be required for testing. No integration
development is planned until there is interest and access to such an environment;
this proposal does not commit the project to implementation or a delivery date.

Organizations or contributors interested in implementing this integration are
encouraged to contribute to the discussion in
[enhancement #2572](https://github.com/RedHatProductSecurity/ai-guardian/issues/2572)
for contributor interest and future validation, or open a related GitHub issue.

**References:**

- [ServiceNow BYOG documentation](https://www.servicenow.com/docs/r/zurich/intelligent-experiences/enable-ai-experiences/configuring-byog.html)
- [AI Guardian GitHub repository](https://github.com/RedHatProductSecurity/ai-guardian)
