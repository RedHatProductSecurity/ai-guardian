# HTTP Request Credential Scanning

AI Guardian can inspect Python source before supported file-write tools apply it
and block hard-coded credentials passed to common HTTP request APIs. This is a
small, source-only static analysis: it parses code but never imports, executes,
or sends the analyzed source to another service.

## Coverage

The default-on scanner recognizes request calls and client/request construction
from `requests`, `httpx`, `aiohttp`, and `urllib.request` (including `urlopen`).
It checks:

- Inline authentication values, including basic-auth username/password pairs.
- Literal values in recognized `Authorization`, `Proxy-Authorization`, `Cookie`,
  API-key, and authentication headers.
- Literal credentials in direct session `auth`/`headers` assignments,
  `headers.update(...)`, and recognized header-key subscript assignments.
- Credentials embedded as user information in HTTP(S) request URLs.
- Credential-named query parameters in literal HTTP(S) request URLs.
- Literal values under explicitly credential-named fields (such as `password`,
  `access_token`, `api_key`, and `client_secret`) in request `data`, `json`, and
  `params` mappings.
- Simple string literals and bounded same-scope assignments/aliases. Common
  module aliases and `from ... import ...` request functions are supported.

The analysis is intentionally bounded. It does not follow helper/interprocedural
flows, arbitrary expression evaluation, runtime values, unsupported HTTP clients,
or JavaScript/TypeScript. Values obtained from environment variables, config,
interactive prompts, or secret managers are treated as references, not literals.
Placeholder examples such as `YOUR_TOKEN`, `$TOKEN`, `${TOKEN}`, `{{TOKEN}}`,
and `<password>` are not reported.
This scanner is separate from code-security analysis and generic secret-pattern
scanning.

## Enforcement and privacy

The scanner runs on Python source supplied to supported `Write` and `Edit`
PreToolUse hooks. It can deny the proposed write, request operation-scoped
Allow Once/Block approval, or warn/log according to policy. It does not prevent
the model from seeing source before the pre-tool hook, and it does not cover
manual edits or write surfaces that do not provide source to the hook.

Finding metadata contains only a fixed client/sink classification and source
line number. Credential values and source snippets are excluded from violation
records, Ask prompts, warning messages, and scanner logs. The saved file path can
be shown as ordinary location metadata. Incomplete parsing is reported only when
the bounded source contains indicators of a supported HTTP client and credential
sink; default block policy treats that analysis as unqualified, not as a confirmed
credential.

## Configuration

This setting is global-only and enabled by default:

```json
"http_request_credential_scanning": {
  "enabled": true,
  "action": "block"
}
```

Actions are `block`, `ask`, `warn`, and `log-only`. `ask` uses the existing
private, operation-scoped approval flow and denies when approval is unavailable.
`warn` and `log-only` do not prevent the write. Disable the scanner only through
global policy; project configuration cannot weaken it. The Console setting is on
the **Secrets** page and in **Global Settings**.

## Limitations

- Static parsing cannot prove that a literal is active, valid, or secret; test
  fixtures and examples can be reported unless they use obvious placeholders.
- Only recognized request APIs and credential sinks are covered. Renamed APIs,
  wrappers, dynamic headers, aliasing across scope boundaries, and indirect flows
  may be missed.
- `Edit` hooks generally provide a replacement fragment rather than the complete
  resulting file. Imports and dataflow outside that fragment are unavailable.
- A pre-tool block is not a guarantee against disclosure: source may already have
  been included in the model context before the proposed write is checked.

Use a secret manager or runtime configuration rather than embedding credentials
in application source.
