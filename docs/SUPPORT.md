# Support bundles and public GitHub Discussions

The default support destination is **GitHub Discussions** in
[`RedHatProductSecurity/ai-guardian`](https://github.com/RedHatProductSecurity/ai-guardian/discussions).
When GitHub is selected, the first native screen has a **Destination** dropdown:
**Create ZIP only** (default, no upload) or **Gist + Discussion** (requires GitHub
credentials). Choose a destination and click **Next** to open its review page;
changing the dropdown alone does not continue or send anything. For **Gist +
Discussion**, selected diagnostic files go into one **unlisted Gist owned by your
GitHub account**; the public Discussion
contains your sanitized message and a separate **Diagnostics** link, not inline
file contents. Explicitly configured S3,
GCS, email and local destinations remain in effect, including from the tray.

This is not the GitHub Issues workflow. **Bug Reports** (`bug-reports`) is
preselected; **Q&A** (`q-a`) is the only other supported category. Q&A must
support accepted answers; Bug Reports does not need to. Repository/category IDs
are discovered from GitHub and category-to-repository membership is checked before publication. Missing
categories, disabled Discussions, or mismatches fail without a fallback.

> **Public visibility:** anyone can read the submitted title, description, and
> diagnostics. Sanitization is not a guarantee of confidentiality. Remove anything
> you do not want published, including private hostnames, paths, and context.
> An unlisted ("secret") Gist is **not private**. Anyone with its link can read it,
> and publishing the link in a public Discussion exposes it to readers.

You own the diagnostic Gist and can manage or delete it on GitHub. Deletion does
not retract downloaded copies, forks, quotations or caches. AI Guardian never
deletes your Gist automatically, including when Discussion publication is cancelled.

## Posting permissions and privacy

For a public repository, **organization membership is not normally required**.
[GitHub allows any authenticated user who can view the repository to start a discussion](https://docs.github.com/en/discussions/quickstart#creating-a-new-discussion).
Organization-level discussions use the same access rules as their source
repository. Repository/account interaction restrictions can still apply, and
[announcement-format categories restrict who can start a discussion](https://docs.github.com/en/discussions/managing-discussions-for-your-community/managing-categories-for-discussions).
The support categories should use open discussion or Q&A formats, not announcements.
The submitting GitHub API credential must also have the appropriate permissions;
being able to browse a public repository does not grant every token API access.

**A public repository has no private discussion category or per-report private
visibility.** Discussions inherit the repository's visibility. Anyone can read,
copy, or potentially index the published report, even without signing in.
Removing a post later cannot guarantee that all copies disappear. Redaction of
secrets/PII is not a confidentiality guarantee: directory names, hostnames,
permission rules, commands and infrastructure details may also be private.

Diagnostic files are sorted alphabetically, with **doctor.json always first**.
On new lists, only **doctor.json is checked by default** when available; all other
files start unchecked. You can uncheck Doctor too. Previously saved explicit
choices, including deselections, are retained when reopening the same bundle.
The Discussion **title starts blank** unless you supplied a proposal; both its
title and message are required. ZIP/legacy review also requires a message.
**Create ZIP / Send** stays disabled until the required fields contain non-whitespace
text and at least one file is selected. Inclusion and final-publication review remain essential.
For confidential diagnostics, export locally and arrange a separate private
ticket, upload portal or support mailbox with the maintainers. No private intake
address is assumed or automatically substituted. A private GitHub repository
requires explicitly granted access and may expose other reports to those invited;
it is not equivalent to a private per-customer support ticket.

## If your agent CLI or MCP is unavailable

Run AI Guardian directly from your own terminal:

```bash
ai-guardian support send --prepare
```

This standalone command does **not** need an agent, MCP connection, or running
AI Guardian daemon, and does not try to start the daemon. It prepares the local
bundle, displays its review path, and offers local ZIP export or the
category/context, Gist-upload approval and final public-consent dialogs. Neither route depends on the
agent/IDE integration you are troubleshooting. For a separate file-review step,
use `support prepare` followed later by `support send`, as below.

## From the system tray

Choose **Contact supports**, directly above **About** in the top-level tray menu.
It honors the configured support destination and opens a native modal, not a
shell or terminal. Empty/missing destinations use **GitHub Discussions**; that
route uses a **Destination** dropdown and **Next** button rather than separate
destination buttons. **Create ZIP only** is selected initially. Selecting
**Gist + Discussion** disables Next with an explanation if GitHub CLI has no
configured credential for `github.com`; switching back to ZIP re-enables Next.
The chooser checks only local credential availability; GitHub verifies the
credential/account after you choose the public route. No login or permission
upgrade is started automatically. ZIP export remains available without credentials.
No saved setting or previously prepared bundle destination is changed.

- **View** opens each complete prepared diagnostic as read-only plain text, using
  **Next page / Previous page** for large files without omitting the ending.
  **Wrap lines** switches between word wrapping and a horizontal scrollbar.
  Wrapping starts off, stays consistent across pages, and never edits the file.
- An **include checkbox** beside each file lets you exclude it without editing
  or deleting the original configuration. New lists check only **doctor.json**,
  shown first; remaining files are alphabetical. Only checked files are exported.
  Keep at least one selected and complete required fields to enable **Create ZIP / Send**.
- **Select all / Deselect all** controls and a live selected-file count simplify
  choosing diagnostics. File names, redaction/truncation notes, and View buttons
  are aligned in a scrollable table.
- For GitHub, select **Bug Reports** or **Q&A** and enter a **required title** (no
  generated default) and message.
  `support-context.json` supplies this editable proposal; it is not uploaded as
  a separate diagnostic containing superseded wording.
- Use the required **Your message** to describe the problem, expected behavior, and reproduction
  steps. Your edited text is sanitized again before the final preview.
- The **final destination** shows the public repository and selected category.
- **Send** opens the exact Gist-upload review. Its initially unchecked consent box
  and **Create Gist** button authorize only that upload. The next preview shows
  the exact Discussion, including the actual Gist link, for separate public consent.
- **Cancel** before upload sends nothing. After upload, Cancel prevents the
  Discussion but leaves your Gist online; the result shows its management link.
- For **Create ZIP only**, **Create ZIP** saves the selected files and sanitized
  message locally. It does not authenticate to GitHub, upload, open an email client,
  or create a Discussion.

The completion dialog stays open until you close it and shows the result,
including **Open Discussion** and **Open Gist** buttons after public submission.
If publication is cancelled or fails after upload, **Open Gist** is still available.
For a created ZIP, **Open destination folder** opens its containing directory in
the native file browser, without opening/extracting the archive or sending it.
Support dialogs are explicitly restored, raised and focused when opened, with
only a temporary foreground hint rather than permanent always-on-top behavior.
There is no second send step for completed public submission. The ZIP result
instead states that nothing was sent and prints the archive path. Explicit local,
bucket, and email destinations retain their existing delivery flow.

The entry remains available with no running daemon or MCP connection, in both
single- and multi-daemon layouts. It prepares **local tray-host diagnostics**;
it does not collect diagnostics from connected container/Kubernetes daemons.
Use the support command in the relevant remote environment for those diagnostics.

Opening the menu item is not publication approval. GitHub still requires the
native exact-content review and final public consent, never a hidden `--yes` or
terminal prompt. With no usable
desktop/Tk, a notification gives the standalone command and nothing is sent;
the tray does not silently fall back to opening a shell. See the
desktop/authentication prerequisites below.

## Prepare → user review → choose delivery

```bash
ai-guardian support prepare --title "Unexpected behavior" --category bug-reports
ai-guardian support send
```

1. **Prepare locally.** No Discussion is created or diagnostic information sent
   to GitHub during preparation. The protected directory includes sanitized
   diagnostics and `support-context.json` (title, description, approved category).
   `--description`, `--no-log`, `--no-violations`, and `--output DIRECTORY` are
   available. When using `--output`, review that directory: sending uses those
   same files, including edits and removals, not a hidden original copy.
2. **Review the local files yourself.** The agent receives only the path, file
   list, redaction counts, and destination summary. It must not read the protected
   contents. **Delete any files you do not want to send from the printed temporary
   directory before continuing**, or edit those prepared copies. Do not delete
   the original CLI settings. Removed files are never
   re-collected from the original sources.
3. **Choose delivery on your desktop.** For GitHub, select **Create ZIP
   only** or **Gist + Discussion** from the first screen's **Destination** dropdown,
   then click **Next**. Next opens the selected review page; it is not permission
   to upload or publish. ZIP export needs no GitHub account or token;
   review the selected files/message and click **Create ZIP**. For publication,
   sending resolves the
   authenticated GitHub account and fixed repository/category. A native dialog
   lets you view and check/uncheck diagnostic files, choose Bug Reports or Q&A,
   and edit troubleshooting context. Send opens the next dialog showing the
   **exact sanitized Gist description, filenames and contents**, authenticated owner,
   unlisted visibility, and redaction counts. Nothing has been uploaded yet.
   Edits replace the proposal in `support-context.json`; that local metadata is
   not also published as a diagnostic file containing discarded wording.
4. **Approve the Gist upload explicitly.** Check the initially unchecked upload
   consent box, then click **Create Gist**. Only those reviewed files are uploaded,
   to your account. An unlisted Gist is readable by anyone with its URL. If you
   cancel now, no upload or Discussion occurs.
5. **Approve the exact Discussion explicitly.** After the upload, the next native
   dialog shows your sanitized message unchanged and the actual Gist URL in a
   separate **Diagnostics** section. Diagnostic file contents are not embedded.
   **Publish publicly** is disabled until you check the
   initially unchecked public-consent box. The consent control stays visible below
   the preview with a hint explaining how to enable the button. Then click
   **Publish publicly**, or Cancel. Approval is private to the backend,
   lasts at most five minutes and never outlives the bundle, is single-use, and
   binds the account, repository, resolved category, title/body, and exact file
   contents. File or selection changes invalidate approval and require review
   again. Gist-upload consent is independently time-limited and single-use too.
   There is no client approval parameter; `--yes`, terminal input, and an agent's assertion
   cannot grant either approval. Cancelling after upload never deletes the Gist;
   the result gives its link for management/deletion.
6. **Continue in the Discussion.** Success returns `discussion_url` and `gist_url` in human CLI,
   `--json`, and MCP results, and in the tray completion dialog. Existing
   `status`, `destination`, and `message` fields retain their meanings.
   Keep the bundle reference for troubleshooting.

### Included CLI configurations

Preparation includes existing supported CLI settings, hooks, and MCP registration
files, alongside AI Guardian's own configuration. It follows the same relocated
CLI-home/config paths as setup and includes known overlays in the active project.
Each file is an individually removable `cli-<integration>-<scope>-<kind>.json`
diagnostic copy in the review directory; JSON/JSONC, TOML, and YAML inputs are
normalized to JSON. No CLI executable, agent, or MCP service needs to work.

Copies redact credential fields/containers, environment and header values,
detected secrets/PII, and home/project prefixes. **Original configuration files
are never changed.** Credential stores, auth files, histories, conversations,
and arbitrary plugin/skill directories are not collected. Claude's mixed global
state file contributes only its MCP registration mapping.

Reads are limited to 256,000 bytes per CLI configuration and 1,000,000 bytes in
total. Linked, unreadable, malformed, oversized, or unsafely sanitizable files
produce a small omission-status diagnostic, never an unsanitized raw fallback.
Check the file list and redaction counts, and uncheck or delete unwanted copies
before confirming export/publication. Sanitization cannot promise confidentiality.

## Create ZIP only — nothing uploaded

With GitHub as the configured/default destination, choose **Create ZIP only**.
Review the files using View (large files have complete next/previous pages),
keep at least one diagnostic selected and fill in the required **Your message**.
Only **doctor.json** starts checked, with the other files in alphabetical order.
**Create ZIP** remains disabled until both requirements are met. The read-only destination
shows the planned local archive path; **Create ZIP** confirms local creation only.

The archive contains the selected sanitized prepared files, including nested
configuration copies, plus the required sanitized message. **Only the log
may have a marked tail excerpt.** Violation records are filtered to the last
12 hours and kept complete, without a newest-100 limit or size crop. Configuration
files and other collected structured diagnostics are complete.

Results identify `delivery_status: zip_only`, print `zip_path`, and explicitly
state **No files were uploaded or sent to support. No Discussion was created.**
The tray result's **Open destination folder** button opens Finder, Windows File
Explorer, or the default Linux file browser on the ZIP's directory, only when
clicked. The result stays open. If the browser cannot be launched, the ZIP stays
intact and the dialog points you to the displayed path for manual opening.
There is no GitHub authentication, Gist upload or automatic email hand-off. The
ZIP is stored in a restricted-access directory under AI Guardian's state directory
(`support-exports/…`) and survives cleanup/expiry of the temporary review bundle.
It is **not encrypted**; review it and arrange an appropriate support channel
before forwarding it by email or any other means. No private recipient is assumed.

Creating a ZIP does not rewrite `support.export_destination`. The original
reviewed bundle and selected-file choices remain available to a later
`ai-guardian support send` within their original lifetime. That command offers
ZIP or Gist + Discussion again and still requires fresh public consent for publication.
It never uploads the ZIP merely because you created it.

## Local directory export is not a support submission

With a saved local destination, the terminal asks:

```text
Export bundle locally to <local-directory>? [y/N]
```

**Yes only saves the reviewed files locally** under `<local-directory>/<bundle-id>/`.
The tray honors that saved local destination too; it shows the selected-file
review and actual local path instead of forcing a GitHub report.
The completion message says **Exported locally**, prints that retained location,
and explicitly states that no files were sent to support and no Discussion was
created. It is not an upload, email, ticket, or GitHub publication.

The retained reviewed copy remains available to `ai-guardian support send` from
another terminal within the original bundle lifetime. Repeating that command
does not fail merely because local export finished; it reuses the same copy and
never restores files you deleted or excluded. A narrower selection cannot overwrite
an existing retained export in place; use a new export directory or prepare a new
bundle rather than assuming old exported files have been removed.
Older exports whose reference still points to
a removed temporary directory are recovered from that exact local destination
when present and unexpired. Local exports themselves are not deleted on expiry;
an expired retained directory can be explicitly selected with `--bundle`.

To actually submit a public support Discussion, first select **GitHub Discussions
(public)** in Web Console → MCP Settings → Support Bundle Export. Then prepare a
new bundle, or explicitly reuse the reviewed local copy:

```bash
ai-guardian support send --bundle <local-directory>/<bundle-id>
```

Explicitly selecting an existing directory uses the currently configured
destination and requires a fresh native public review. No local export is ever
silently rerouted to GitHub.

The same backend serves `prepare_support_bundle(title?, description?, category?)`
and `send_support_bundle(bundle_id)`. The agent should request sending only after
you review the files; the native final confirmation is additionally enforced.

## Authentication and desktop prerequisites

The **Gist + Discussion** workflow is available only with configured GitHub
credentials; **Create ZIP only** needs none. Missing CLI, missing credentials or a
local credential lookup timeout disables only the public choice. Credential
availability does not prove that a token is still valid or has sufficient permissions;
GitHub verifies identity and enforces access before performing each operation.
Install [GitHub CLI](https://cli.github.com/) (MIT) and authenticate **your own**
account for `github.com`, for example with `gh auth login --hostname github.com`.
AI Guardian retrieves that account's credential into process memory and queries
GitHub for its identity; it never accepts a supplied reporter name, uses a shared
support bot, or stores the credential in bundle metadata, logs, or Discussion
or Gist content. Authentication is pinned throughout both reviews and submission.
AI Guardian never runs login, refresh, or scope-escalation commands for you.

GitHub's [Discussions API guide](https://docs.github.com/en/graphql/guides/using-the-graphql-api-for-discussions)
documents `public_repo` for public-repository OAuth/classic-token access. The
[Gists API](https://docs.github.com/en/rest/gists/gists#create-a-gist) additionally
requires Gist access (`gist` for OAuth/classic tokens). A credential must support
**both** Gist creation and Discussions writing in the canonical repository,
subject to organization authorization. Known missing OAuth Gist scopes are
rejected before upload; GitHub remains authoritative for other credential types
and access restrictions. No
Issue/Release write permission or external bucket is needed. GitHub account
authentication identifies the submitting account; it does **not** prove that
diagnostics are genuine or that maintainers endorse the report.

Public approval requires an available native Tk desktop dialog. AI Guardian
launches its installed review script with isolated Python, not project-local
module lookup or a caller-supplied executable. It does not start an
unauthenticated browser/HTTP approval endpoint or fall back to
agent-controlled terminal confirmation. Without a usable desktop/Tk installation
(including headless/container/remote-only sessions), sending fails closed and
keeps the local bundle. Review on a desktop or complete the submission manually
in your browser. No automatic publication is performed to compensate.

## Text diagnostics, size limits, and manual attachments

### Recent logs and readable excerpts

`ai-guardian.log` includes only timestamped records from the **last 12 hours**,
with multiline tracebacks belonging to those records. Older, future-dated, and
unattributed preamble text is not collected. Reads are bounded even for very large
logs; only the newest complete records in the bounded tail can be retained.

`violations.jsonl` includes **all sanitized violation records from the last
12 hours**, newest first. Older, future-dated and invalid/undated records are
excluded. Included records stay complete: there is no arbitrary count cap,
byte-size truncation or partial JSON excerpt. Source audit logs are unchanged.

**Only the log is truncated.** Collected sanitized configuration files, violation
records, metrics and other structured diagnostics remain complete, including
their final fields. They are never cut to satisfy a preview or publication budget.
Unsafe/unparseable CLI settings still produce explicit omission status, not raw
or partial configuration data.

The prepared log copy is bounded to **1,000,000 bytes**, retaining its newest text.
For GitHub, the log alone uses the space remaining in a **40,000-byte diagnostic
target** after complete non-log files, with a minimum 1,024-byte newest-log budget.
This keeps default diagnostic uploads compact; it does not guarantee
that very large complete configurations fit the total Gist input limit. A **Truncated**
notice and file-list note identify a shortened log. UTF-8 characters are not split.
Original source logs/configurations are never modified.

### What View and Send include

**View reads the complete prepared copy. Send uses that same copy without an
additional size crop.** A prepared log excerpt is identical in both paths.
Sending repeats security redaction and authentication-credential scrubbing; the
separate Gist upload preview is authoritative for its exact filenames/content.
The subsequent public preview is authoritative for the Discussion title/body/link.

The built-in viewer reads up to **1,000,000 bytes per page**, preserving UTF-8
boundaries. **Next page / Previous page** and byte-range indicators let you inspect
the whole file, including the final configuration fields; there is no whole-file
display cap. Paging does not alter the prepared file or ZIP. Binary, linked or
otherwise unsupported files still fail safely rather than rendering unsafe content.
Importing an older bundle does not silently filter or shorten it; prepare a new
bundle for fresh 12-hour log/violation records.

### Public delivery limits

The supported automated delivery uploads **UTF-8 text files to your unlisted Gist**.
Sanitization covers the title, description, filenames and file text. Gist names
are flattened, numbered to avoid collisions, and restricted to plain-text
extensions; other extensions receive `.txt` so they do not render as active Markdown/HTML.
The exact filenames and complete sanitized content are shown before upload.
Gist input is bounded to **1,000,000 bytes total** and **100 diagnostic files**.
The Discussion body has a separate **60,000 UTF-8 bytes** limit including your
message, reference, link and formatting; diagnostics do not consume that body limit.
Binary, excessive imported/edited,
unregistered, or linked files are not silently skipped. If a message or edited
bundle still exceeds the limit, publication fails without creating a Discussion.

`createDiscussion` accepts a title/body and repository/category IDs, **not a ZIP
upload**. If complete Gist delivery is not supported, the result is an error
(`manual_required`, `delivery_status: not_published`): **no Discussion was
created**. Uncheck unwanted/oversized files and retry with a new review, or run
`support send` again and choose **Create ZIP only** for a separately arranged
private support channel. Complete configurations
are not silently cut to make sending succeed. Attaching files in GitHub's browser
UI would still make them public in this repository. A local filesystem path is not
an attachment. No Issues/Release upload API or non-GitHub service is used.
No draft/partial delivery is reported as a completed diagnostic submission.
The file chooser opens before Gist diagnostic-size/content validation, so you
can uncheck binary or oversized diagnostics before the final preview. Previews
are bounded plain text; they never execute file contents or follow linked files.

## Retry and lifetime

Authentication, permissions, API rate limits, unavailable categories, and network
errors produce credential-free messages without changing the destination. The
reviewed bundle remains available within its normal lifetime (30 minutes by
default). Known rejected requests can be retried only with a new review/approval.
GitHub bundles retain private Gist/upload and Discussion/publication receipts
for that lifetime; re-sending a successful bundle returns the same Discussion URL
and explicitly says no new diagnostics were sent.

After a Gist upload, cancellation or a known Discussion failure returns
`delivery_status: gist_only` and `gist_url`, without claiming a completed support
submission. The result and tray dialog show the URL so you can manage/delete the
existing Gist. Retrying the same selected files/account verifies and reuses that
Gist, then requires fresh consent to the exact Discussion. Changed files/accounts,
changed remote contents, or a deleted Gist never trigger a silent replacement
upload or fallback to inline diagnostics. Prepare a new bundle for a different
upload, and manage the old Gist yourself.

A timeout, partial response, server failure, interrupted process, or unverified
creation response can mean GitHub already created the Gist or Discussion. A persisted
pre-mutation journal blocks automatic retries, including after process restart.
**Check your own Gists and the repository Discussions manually** before taking any
further action. A known Gist URL is reported even if later publication fails;
an unknown upload outcome does not invent a URL or upload another copy.
Do not assume `clientMutationId` provides idempotency. Receipt-write failures
also remain fail-closed against duplicate publication.
Gists are not deleted when the local bundle expires. Delete the Gist yourself
if you no longer want to retain the uploaded diagnostic files.

## Configuration and upgrades

```json
"support": {"export_destination": "github-discussions", "github_category": "bug-reports", "bundle_ttl_minutes": 30}
```

Generated configurations/profiles and empty/missing destinations select GitHub
Discussions, including when the support section is absent from a saved config.
Explicit legacy destinations remain in effect for tray, CLI and MCP. A previously prepared
bundle retains its original destination; no existing bundle is silently rerouted.

To change an explicit legacy destination, select **GitHub Discussions
(public)** in Web Console → MCP Settings → Support Bundle Export, or select
`github-discussions` in the global support configuration. Preparation
is still local; selecting the default never constitutes publication approval.
The settings offer only Bug Reports and Q&A, not every discovered repository
category. The backend enforces the same restriction for CLI and MCP requests.

Explicit local paths, `s3://…`, `gs://…`, and `mailto:…`/email destinations retain
their configuration/authentication semantics. Legacy automated export can still
use `support send --prepare --yes`; this does not authorize GitHub publication.
Without SMTP, email export prepares a ZIP for manual attachment and opens the
mail client. The result says **Manual email delivery required**, not that an email
was sent; attach the reviewed ZIP and complete sending yourself.
