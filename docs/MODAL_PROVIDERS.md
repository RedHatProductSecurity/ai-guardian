# Modal providers and runtime fallback

AI Guardian uses **Native → Tkinter → NiceGUI**, in that order, among
implementations that preserve the **entire** interaction. This is a capability
policy, not a promise that every family has three implementations. NiceGUI and
Python 3.10+ remain required. There is no interactive terminal/Textual fallback.

## Preferences and lifecycle

`console.preferred_ui` and its environment override select:

| Preference | Behavior |
|---|---|
| `auto` | Try eligible providers in the matrix below. |
| `tkinter` | Tk only; no native or browser replacement if unavailable. |
| `nicegui` | NiceGUI only; no Tk or native replacement if unavailable. |
| `headless` | No dialogs or browser launches. |

An unavailable requested implementation produces the family's safe no-UI result.
Existing persisted `textual` values still resolve to NiceGUI, not a terminal UI.

**Only a proven pre-display startup failure advances the cascade.** Missing
executables and Tk initialization failures qualify. Isolated rich-dialog children
track the root's Map event and explicitly report failures before mapping. The
message child retains its separate mapped-readiness protocol from #2569.
The Cocoa bridge reports initialization failure explicitly before showing its
first window; a failure in its later snooze step is terminal. Browser flows latch
possible visibility before requesting the tab. Auxiliary file panels latch it
before entering the panel, since their withdrawn Tk parent does not map.
`None`, `False`, Cancel, Escape, title-bar Close, an answered prompt, a timeout,
or an error of unknown visibility never authorize another provider. A failure
starting a later snooze step cannot restart the initial prompt in another toolkit.
The same rule holds across host input, identity review and results in a form flow.
Modal children have no user-reading deadline.

Native command-line tools do not provide a reliable mapped-window signal. Only
missing executables and recognized display-initialization diagnostics permit
trying another implementation; other errors stop conservatively. A stderr warning
alone is not startup proof. Linux native dismissal is final. Diagnostics report
provider/stage/error class, not raw child stderr, dialog content or result data.

## Platform and capability matrix

N = native implementation, T = Tkinter, G = NiceGUI/browser. An arrow is a
**pre-display** fallback, not a second prompt after cancellation. Implementations
listed as absent are intentionally ineligible, not silently emulated with fewer
controls.

| Modal family / entry point | macOS | Linux | Windows |
|---|---|---|---|
| Plain messages, health/results, plugin modal output: `plugins.show_dialog` | N AppleScript → T → G | N desktop-ordered zenity/kdialog → T → G | N PowerShell WinForms MessageBox → T → G |
| Linked About/message | T → G; N lacks explicit link controls | T → G; same exception | T → G; same exception |
| Proactive action/upgrade/snooze: `ProactivePromptDialog.show` | N JXA/Cocoa NSAlert/accessory controls → T → G | N zenity question/extra buttons or kdialog menu → T → G | T → G; no complete native action/snooze implementation |
| Structured setup/profile/per-IDE choices and later/snooze | N JXA/Cocoa checkbox pairs/profile popup → T → G | T → G; native tools do not implement the complete setup form | T → G; same capability restriction |
| Ask/security decision: CLI `prompt --mode ask` | T → G; native simple prompts lack full decision/edit controls | T → G | T → G |
| Tray-forwarded remote ask on macOS 14+ | G in subprocess; existing tray focus-safety Tk suppression remains | As above | As above |
| Plugin parameter forms: `TrayPromptApp.run` | T → G | T → G | T → G |
| Simple form flows / tray Add daemon via SSH and discovered-alias review: `run_form_flow` | N JXA/Cocoa input/checkbox/full review → isolated T → G | N desktop-ordered zenity/kdialog input/checklist → isolated T → G | N PowerShell WinForms input/checkbox/scrollable review → isolated T → G |
| Tray Discover SSH aliases... settings: `run_form_flow` | N JXA/Cocoa two-step checkbox/prefix → isolated T → G | N desktop-ordered zenity/kdialog two-step checklist/prefix → isolated T → G | N PowerShell WinForms two-step checkbox/prefix → isolated T → G |
| Multi-target plugin selection: `TrayTargetSelectorApp.run` | G only | G only | G only |
| Working-directory picker: `working_dir.choose_directory` | N AppleScript choose folder → isolated T | N desktop-ordered zenity/kdialog → isolated T | N PowerShell WinForms FolderBrowserDialog → isolated T |
| SSH VM working directory: `run_form_flow` | N JXA/Cocoa optional absolute-path input → isolated T → G | N desktop-ordered zenity/kdialog input → isolated T → G | N PowerShell WinForms input → isolated T → G |
| Browser form's auxiliary file/directory Browse | N AppleScript choose file/folder → isolated T | N desktop-ordered zenity/kdialog → isolated T | N PowerShell WinForms OpenFileDialog/FolderBrowserDialog → isolated T |
| Sandbox create/configuration/policy editor: `show_sandbox_form` | isolated T → G | isolated T → G | isolated T → G |
| Sandbox deletion (must type exact name): `show_sandbox_confirmation` | N AppleScript text-entry confirmation → isolated T → G | N zenity entry/kdialog inputbox → isolated T → G | N PowerShell VisualBasic InputBox → isolated T → G |
| Sandbox upload summary/errors and complete policy replacement review | isolated T → G; compact native confirmation is ineligible | Same | Same |
| Sandbox live progress: `show_sandbox_progress` | isolated T; otherwise captured-output object | Same | Same |
| Sandbox captured logs: `show_sandbox_log` | isolated T → G, complete scrollable/copyable text | Same | Same |
| Support destination/bundle/View/ZIP/result/upload/publication review | Trusted isolated Tk desktop script only | Same | Same |
| Web Console's already-open page/dialog controls | G, stays in the current browser session | Same | Same |

### Explicit exceptions

- **Placement:** with captured macOS screen bounds, plain AppleScript messages,
  confirmations and directory pickers skip native and use the screen-aware Tk
  implementation first. Cocoa setup/action prompts can place their native window
  on that display. Tk retains the captured geometry through subprocess payloads.
  Browser-window placement is desktop-managed, not guaranteed on that monitor.
  A screen-aware directory picker without Tk returns no selection rather than
  opening an unplaced native panel. Bounds do not force Tk over an explicit
  browser preference for forms/messages.
- **Multi-target selection:** the existing NiceGUI-only implementation preserves
  multi-selection, Select all, validation and disconnect cancellation. No native
  or Tk implementation currently implements that complete contract. `tkinter`
  and `headless` therefore return no selection; they do not silently open a browser.
- **Host paths:** a browser upload/directory input cannot return an absolute host
  path for a runtime command. Standalone pickers have no NiceGUI tier. Browse in a
  browser parameter form is deliberately an auxiliary OS/Tk picker even with
  `nicegui` selected; it never replaces the parent form or retries cancellation.
  Browse inside a Tk form remains an owned Tk file panel.
- **Progress:** no native or NiceGUI live-stream implementation preserves the
  current output/status/Connect handshake. Those tiers are ineligible. The
  captured-output object keeps the operation running without a live window;
  failure details use the separate full log-review interaction, never a truncated
  message. `nicegui`/`headless` use this object without starting Tk. A result/log
  review after an operation is distinct from retrying its progress window.
- **Support consent:** support's native, user-only review is a security boundary,
  not an ordinary configurable modal. It remains isolated stdlib Tk with its own
  exact-content upload/publication approvals. `headless` or unavailable Tk refuses
  delivery and retains the bundle; no browser, terminal, agent approval, upload,
  automatic credential upgrade or alternate consent tier is introduced. Selecting
  Next is still not consent. Per-daemon preparation runs on the source, but every
  review/consent window remains on the tray user's desktop. All review stages show
  the captured source; remote metadata cannot select delivery or grant approval.
  The local tray-host action stays independent. See [Support bundles](SUPPORT.md).
- **SSH pairing:** the tray's Add action uses the reusable form-flow adapter, not
  the Web Console. All steps retain one provider, including failures and results.
  The native Linux tool is likewise pinned after its first dialog. Only the
  display-safe identity summary reaches renderers; credentials and certificate
  objects remain in the tray-owned manager's closure. Trust starts unchecked and
  is required before enrollment. Native Linux checklist buttons can remain
  enabled while unchecked; submitting that state ends without saving or opening
  another provider. **Manage SSH connection...** still opens the
  existing local Web Console's saved-connection management page; its already-open
  browser controls do not enter a new standalone-modal cascade.
  **Review discovered daemon** enters this same flow directly at the complete
  identity review, skipping host input only. Discovery never opens a modal itself.
  The first native startup failure can still fall back, but cancellation/unchecked
  consent and any later displayed-step failure remain terminal. Verify the direct
  route on each supported desktop as well as manual Add; see the full SSH UX
   contract for opt-in, cancellation, dismissal/restart and identity-change checks.
- **SSH discovery settings:** **Discover SSH aliases...** is always available in
  the workstation tray, including discovery-off/zero-candidate/no-pairing states.
  Reuse `run_form_flow` for the complete two-step interaction: current enable
  checkbox and **Continue**, then current optional literal prefix and **Save**.
  All providers retain both controls, explanations, validation feedback and
  cancellation. Continue is non-mutating; Cancel/Close before Save changes nothing.
  Errors/retries/results stay in the selected provider, including after saving.
  Only display-safe settings reach renderers; configuration I/O runs in the tray
  worker, using the same workstation-global writer as the Web Console. Saving
  requests discovery refresh, not pairing, probing, certificate trust or removal.
  Existing candidate Review/Dismiss actions and saved connections stay unchanged.
- **SSH working directory:** use an optional text field for an absolute VM path,
  not a workstation directory picker. Native → isolated Tk → NiceGUI dispatch,
  complete explanation, validation retry and Cancel/Close follow `run_form_flow`.
  Empty selects remote home. Only Save persists the per-target command directory;
  it does not change daemon configuration scope. Capture placement before the
  worker; no SSH/filesystem probing occurs in the form or menu callback.
- **Process ownership:** Tk messages, sandbox dialogs, plugin CLI forms and tray
  proactive dialogs run outside the tray GUI loop. Proactive NiceGUI fallback also
  runs in its own child and opens the actual loopback port only after server startup.
  Sandbox browser forms, confirmations and logs likewise use a fresh child/server
  per interaction; complete review payloads cross stdin, not command-line limits.
  Plugin runners select transport with the shared selector; the child parameter
  CLI executes the shared runtime policy. The active Web Console keeps its existing
  browser-server lifetime, without entering the tray's Tk process state.

No-UI outcomes remain non-destructive: forms/target/path selection return no value,
confirmations return false, proactive prompts dismiss (or use the shortest snooze
in two-step flows), and ask uses its existing configured security fallback. No
provider failure independently grants permission or performs a destructive action.

## Implementation and automated contracts

`ui/display.py:ui_provider_order` defines capability/preference/placement order.
`ui/modal.py:run_modal` executes it and distinguishes startup unavailability from
completion. Messages, proactive prompts, ask CLI, parameter forms, directory/path
pickers, target selection, reusable simple-form/SSH flows and sandbox
forms/reviews/logs use that policy. Progress
uses the same selector with its documented captured-output exception. Native-only
action/confirmation helpers are implementations called *after* policy selection,
not independent cascades. Support and embedded Web Console dialogs intentionally
remain outside it for the reasons above.

Related unit tests cover policy, actual entry-point calls, child framing, real
mocked Tk initialization failure, complete field/error/log propagation, explicit
preferences and cancellation. About, IDE setup, modal and support UX contracts
cover the user-visible behavior. These checks do **not** establish actual visual
ordering, compositor focus, browser rendering or consent behavior on a desktop.

## Adding a modal

**Do not write another provider-order or fallback loop.** All standalone modal
entry points use `ui/modal.py:run_modal`; it consults the one policy in
`ui/display.py:ui_provider_order`. Individual implementations render content and
return a result. They do not choose the next toolkit.

For a simple form or multi-step form interaction, use `ui/forms.py:run_form_flow`:

```python
from ai_guardian.ui.forms import run_form_flow

def interaction(form):
    values = form("Add connection", "Enter the known destination.", [
        {"name": "host", "label": "Known host", "required": True},
    ])
    if values is None:
        return None
    # Subsequent form(...) calls keep this provider; no cross-toolkit restart.
    return values

result = run_form_flow(interaction, screen_bounds=captured_bounds)
```

The adapter binds native, isolated Tk and isolated NiceGUI renderers to the shared
dispatcher. Its native form supports one text field, one checkbox, or a message;
larger forms need their complete provider implementations and the appropriate
capability classification. Do not label an incomplete native form as supported.
Keep work before the first form non-mutating: a pre-display retry can rerun the
interaction callback. Mutate backend state only after explicit user confirmation.

For other modal families, supply supported renderer callbacks to `run_modal` and
use the family's capability type and safe no-UI result. Add a capability only
when its complete implementation exists; do not change the central order.
Raise `UIUnavailable` only when no interaction has appeared. Track Map/launch
visibility and preserve it across later steps; cancellation is an ordinary final
result, never unavailability. Reuse the child framing helpers rather than guessing
visibility from stderr or nonzero exits.

Capture placement before leaving the tray callback. Keep toolkit state isolated,
serialize only display-safe values, and retain the separate support-consent and
active Web Console exceptions. Add unit tests plus the complete affected UX
contract for precedence, startup-only retry, cancellation/post-display failure,
explicit preferences/headless and full controls. Update this matrix and record
real desktop qualification separately from mocked validation. The contributor
checklist also lives in `AGENTS.md`.

## Manual desktop verification (not yet qualified by this change)

Run on macOS, native Windows, GNOME/zenity and KDE/kdialog, with X11 and Wayland
where available. Use benign test messages, disposable sandboxes and no live support
upload. Record OS/desktop, display server, preference, toolkit process, captured
monitor, result and sanitized screenshots/timing for each matrix row.

1. In automatic mode exercise plain and linked messages, actions, setup/profile
   controls, both snooze steps, parameter/target forms, host-path Browse, ask, and
   sandbox create/upload/delete/policy/progress/log flows. Test SSH input/identity
   review against an explicitly authorized disposable host; Cancel must not save,
   and a later-step failure must not switch toolkits. Confirm the first
   **eligible** toolkit, all controls and complete long text, not merely its theme.
2. Repeat with each explicit preference and headless. Confirm exclusive behavior
   and the documented target/path/progress/support exceptions; no terminal opens.
3. In a disposable test environment, test absent native executables and failed Tk
   initialization. Confirm the next eligible provider appears exactly once. Do
   not change security policy or uninstall the operator's working toolkits.
4. Cancel, Escape, title-bar Close and time out applicable decision prompts. Leave
   informational/review windows open beyond 30 seconds. No cancellation or
   interrupted wait should produce another toolkit. Inject a post-map child
   failure in a developer test harness and confirm no replacement window appears.
5. From a secondary monitor, exercise placement-aware rows, including Cocoa setup,
   Tk forms/messages/directory panels and destructive confirmation. Check focus
   after the tray closes, repeated opens, and that no permanent topmost hint remains.
   Record browser placement limitations separately.
6. Verify typed-name deletion rejects incorrect/empty text. Review the last lines
   of large policies, upload errors and logs, then cancel: no mutation occurs.
   Check log scrolling/copy and progress/Connect behavior separately.
7. Support: use local ZIP review only; check per-file View, full paging, required
    fields, saved selection, native consent controls and safe no-desktop refusal.
    Exercise the distinct local tray-host and per-daemon actions in flat/nested
    layouts (including SSH). During preparation, refresh/reorder/remove a target:
    the Source must not change. Check source provenance/omissions, source-only
    diagnostics and credential-free offline/older-daemon feedback. No remote
    desktop opens, and failures never collect desktop files as a substitute.
   Mock/cancel public upload and publication reviews; do not publish diagnostics as
    part of UI verification. Live publication requires separate operator consent.
8. SSH discovery settings: with discovery off, zero matches and no enrolled
   daemons, find **Discover SSH aliases...** next to **Add daemon via SSH**.
   Check both current values, cancel/close either step, and confirm no persistence.
   Save a custom `guardian-` prefix, then an empty prefix; reject wildcard/invalid
   input with feedback without switching toolkit. Confirm candidates refresh
   without restarting, reopen/restart to check persistence, and compare with the
   local Web Console (untouched controls update; unsaved edits remain). Disable
   discovery: candidates disappear but the settings entry and existing paired
   workers/tunnels remain. No Save may contact a host or grant trust. Repeat the
    preference/startup/cancel/later-step-failure checks above for this flow.
9. SSH Working Dir: confirm it asks for a VM path instead of browsing workstation
   folders. Save an absolute path and verify only that VM's commands use it; empty
   selects remote home. Retry relative/invalid input, Cancel/Close, remove the
   connection with the form open and test each provider/headless preference. No
   mutation before Save and no toolkit switch after display or validation.

Do not check off desktop qualification using selector mocks or merely installed
native executables. Keep any untested platform/scenario explicitly pending.
