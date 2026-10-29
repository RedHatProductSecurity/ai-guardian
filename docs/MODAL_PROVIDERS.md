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
| Password-likelihood Ask: existing `prompt --mode ask`, private decision-only variant | T → G; same Ask providers, values withheld, Allow Once / Block only | T → G | T → G |
| Tray-forwarded remote ask on macOS 14+ | G in subprocess; existing tray focus-safety Tk suppression remains | As above | As above |
| Plugin parameter forms: `TrayPromptApp.run` | T → G | T → G | T → G |
| Simple form flows / tray Add daemon via SSH and discovered-alias review: `run_form_flow` | N JXA/Cocoa input/checkbox/full review → isolated T → G | N desktop-ordered zenity/kdialog input/checklist → isolated T → G | N PowerShell WinForms input/checkbox/scrollable review → isolated T → G |
| Tray Discover SSH aliases... settings: `run_form_flow` | N JXA/Cocoa two-step checkbox/prefix → isolated T → G | N desktop-ordered zenity/kdialog two-step checklist/prefix → isolated T → G | N PowerShell WinForms two-step checkbox/prefix → isolated T → G |
| Multi-target plugin selection: `TrayTargetSelectorApp.run` | G only | G only | G only |
| Working-directory picker: `working_dir.choose_directory` | N AppleScript choose folder → isolated T | N desktop-ordered zenity/kdialog → isolated T | N PowerShell WinForms FolderBrowserDialog → isolated T |
| SSH VM working directory: `run_form_flow` | N JXA/Cocoa optional absolute-path input → isolated T → G | N desktop-ordered zenity/kdialog input → isolated T → G | N PowerShell WinForms input → isolated T → G |
| Tray Pause... daemon/project/session hierarchy: `open_pause_controls` | isolated T → G | isolated T → G | isolated T → G |
| Browser form's auxiliary file/directory Browse | N AppleScript choose file/folder → isolated T | N desktop-ordered zenity/kdialog → isolated T | N PowerShell WinForms OpenFileDialog/FolderBrowserDialog → isolated T |
| Sandbox create/configuration/policy editor: `show_sandbox_form` | isolated T → G | isolated T → G | isolated T → G |
| Sandbox deletion (must type exact name): `show_sandbox_confirmation` | N AppleScript text-entry confirmation → isolated T → G | N zenity entry/kdialog inputbox → isolated T → G | N PowerShell VisualBasic InputBox → isolated T → G |
| Sandbox upload summary/errors and complete policy replacement review | isolated T → G; compact native confirmation is ineligible | Same | Same |
| Sandbox live progress: `show_sandbox_progress` | isolated T; otherwise captured-output object | Same | Same |
| Sandbox captured logs: `show_sandbox_log` | isolated T → G, complete scrollable/copyable text | Same | Same |
| Support destination/bundle/View/ZIP/result/upload/publication review | Trusted isolated Tk desktop script only | Same | Same |
| Web Console's already-open page/dialog controls | G, stays in the current browser session | Same | Same |

### Explicit exceptions

- **Tray pause controls:** a complete hierarchy needs inline per-row duration/Resume
  dropdowns, full identities, inherited-state explanations and
  in-place refresh. Native simple forms do not implement this contract and are
  ineligible; the shared dispatcher selects isolated Tk → isolated NiceGUI.
  One child/window remains open across actions. Only display snapshots and narrow
  row/action/duration events cross its stdin/stdout channel; credentials and
  transport objects stay in the tray worker. Row tokens expire on refresh.
  Dropdowns start at inert placeholders. Selecting a duration pauses that row
  immediately; a paused row instead offers Resume. There is no separate Pause
  button or shared duration selector. The Tk window requests 1200 × 820 within
  usable bounds, with width-fitting content and responsive label wrapping so the
  action column remains visible on narrow screens. Close/Escape before any action changes nothing; closing never rolls back actions
  already explicitly taken. Resume clears only the selected row's own pause.
  Unknown/offline/unsupported rows remain visible with unavailable controls.
  The same captured monitor context follows startup fallback and every refresh.
  The initial Tk geometry is applied explicitly before monitor placement, so
  single-monitor/no-context flows do not fall back to the canvas's small natural
  size. Compact instructions keep controls first; full help/lifetime text remains
  available in a collapsed in-window section without switching providers.
- **Password-likelihood Ask:** reuses the existing local/remote transport and
  modal dispatcher, with one operation-scoped Allow Once / Block decision. Both
  providers withhold candidate text and omit source/persistent-exception controls;
  there is no source-file recovery. Cancellation, timeout and unavailable approval
  deny. Automatic display-less detection still permits registered remote tray
  forwarding; explicit headless does not. A queued remote timeout is terminal.
  Manually verify synthetic contextual/ambiguous/incomplete input, both decisions,
  Close/Escape/timeout, provider startup-only fallback and exclusive preferences,
  local and SSH tray forwarding/disconnect, and unchanged stronger credential
  enforcement. These UI/transport checks do not establish the model boundary;
  follow [password-likelihood qualification](security/PASSWORD_LIKELIHOOD.md).

- **Placement:** with captured monitor context, native implementations without a
  positioned window/owner are ineligible on **all** platforms. Messages,
  confirmations and host-path pickers therefore start with isolated Tk; Linux's
  zenity/kdialog forms/actions likewise defer to Tk. Cocoa forms/setup/actions and
  WinForms simple forms retain native eligibility when the complete layout fits.
  Restricted/unknown origins and small work areas use the complete scrollable Tk
  implementation. Browser forms retain the context and show explicit manual-move
  guidance rather than claiming URL launch places a window. Explicit preferences
  remain exclusive. See [Physical-monitor placement](#physical-monitor-placement).
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

## Physical-monitor placement

Tray callbacks capture display-only context **before** starting a worker, child
process, source collection or command. It contains immutable usable bounds,
platform display identity when available, coordinate/DPI information and whether
automatic placement can be enforced. The same context follows confirmations,
reopened forms, pickers, progress/log/error/result windows and support View/upload/
publication reviews. It is not saved in bundles/configuration and grants no consent.

`ui/monitor.py` is the shared placement implementation. Immediately before showing
a window it re-enumerates monitors by identity, not by the later pointer/focus or
old geometry. Rearranged/resized monitors use their current work area. If the
origin disappears, use the primary monitor's current work area. If inventory is
unavailable, discard the stale offset and let the window manager place a smaller,
resizable recovery window; its title explains **Display unavailable; move window
to a visible screen**. Single-monitor and non-tray flows keep normal WM defaults.
Identity means the platform's display identifier, not a promise of hardware serial
tracking where the desktop exposes only connector/logical identity.

| Platform / host | Capture and coordinates | Qualification / explicit fallback |
|---|---|---|
| macOS | Existing AppKit mouse-menu event, menu window/status-item context for keyboard activation; `screens[0]` baseline converts Cocoa points to Tk top-left coordinates. Cocoa display number survives geometry changes. | Tk stays isolated; inventory uses a non-UI Cocoa child, never AppKit-before-Tk. An unknown keyboard origin is not replaced with an unrelated pointer. |
| Windows | Shell notification-icon rectangle, not another application's focus or the keyboard user's pointer. Monitor work areas exclude taskbars; device interface identity is preferred over display numbering. | Capture and Tk/WinForms use per-monitor-aware physical pixels. Coordinates are not multiplied by DPI; current DPI controls decoration allowance. |
| Linux X11 | Mapped GTK tray-menu window, or an actual pointer menu event; GTK device scale converts to XRandR root pixels. XRandR monitor identity and EWMH work area are queried through optional system X11/XRandR libraries. | No Tk or subprocess is started on the tray loop. Missing libraries/desktop geometry produce explicit recovery, not stale offsets. Native commands lacking reliable monitor ownership are ineligible. |
| Remote AppIndicator/DBusMenu hosts | The panel may render the menu in another process without supplying its physical coordinates, including keyboard activation. | Do **not** guess from pointer/focus. Use a visible desktop-managed Tk window titled **Move this window to the tray screen**; move it with the title bar or the desktop's Move-to-screen command before continuing. |
| Wayland / XWayland | The compositor can deny absolute positioning or expose only XWayland monitor data. | Position requests are best effort, **not a guarantee**. The same explicit title/manual-move fallback applies. Native Wayland without X11 inventory uses the smaller WM-positioned recovery window. |
| NiceGUI in a normal browser | Every standalone modal retains originating context, including target selection and plugin parameter forms. | A browser may reuse any window. A visible banner says **The browser cannot place this dialog… Move this window… before continuing.** Move the browser with the title bar/desktop controls. No unsupported `moveTo`, silent discarded argument, automatic permission grant, or claim of enforced placement. Already-open Web Console pages remain browser-owned. |

Placement-capable Tk windows clamp to usable work areas with current-DPI frame
allowance and capped minimum/maximum sizes; scrollable content and bottom actions
remain available. Parameter forms and tray support reviews use a shared
two-axis viewport with reserved actions; support's full, wrapped, initially
unchecked consent stays outside that scrolling review. Native Cocoa providers
share an in-child identity check for every window, including Later, and reject
an undersized complete layout before first display rather than dropping controls.
WinForms also rechecks screen identity/work area after child startup.
Negative coordinates are absolute (`+-N` in Tk geometry), not
offsets from another screen's edge. Owned file panels receive a positioned parent;
support preview windows use the action origin even if the parent was moved later.
Folder opening/external application links remain explicitly user-launched desktop
applications, not AI Guardian-owned modal windows.

Scheduled setup/upgrade prompts and hook-originated asks have **no tray origin**:
their existing provider/security fallback and WM/browser placement remain the
default. No pointer position is fabricated to label them as tray actions. Support
continues to require its isolated native user-only approvals; moving a window,
Next, or provider failure never authorizes collection/upload/publication.

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
5. On **physical** monitors, invoke every applicable matrix row from a non-primary
   tray/menu, with both mouse and keyboard. Include About/results, setup plus Later,
    SSH settings/pairing, pause controls, parameters plus Browse, target selection and each sandbox
   form/confirmation/upload/policy/progress/log/error/reopen. Repeat while delayed:
   move pointer **and** application focus to a different screen before display.
   Exercise a pre-display provider failure and subsequent windows without changing
   the origin. Verify the complete outer window and controls fit the usable area.
   Repeat with monitors left/right/above/below primary, negative coordinates,
   mixed resolutions, 100%/150%/200% scaling and taskbars/docks on different edges.
   Rearrange/resize, then disconnect the originating screen during a delayed flow;
   verify visible primary fallback, and single-monitor behavior. Check focus after
   tray close/repeated opens and absence of permanent topmost. For remote panels,
   Wayland or browsers, verify the **explicit manual-move guidance** and actually
   move the window before continuing; record this as fallback, not enforcement.
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
   For each support stage, including per-file View, check the same physical-monitor
   origin through source delays and provider startup errors. No placement test may
   auto-check consent, upload a Gist, publish a Discussion or duplicate a send.
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

For **Pause...**, verify a single root action with one/multiple daemons; daemon →
project → session rows each have their own duration/Resume dropdown. Exercise every
duration, timed expiry, an inherited pause and resuming only one layer. Confirm
in-place refresh, inert initial dropdown values, unavailable/older-daemon rows,
duplicate session titles with full keys, stale clicks and SSH reconnect/removal.
Opening, Refresh, Close and Escape without an action must not change pause state.
Check that a single-monitor/no-placement-context launch actually applies the
requested initial geometry within WM limits. Confirm row controls are visible
before expanding help, and Show help/Help changes no pause state.
Repeat startup-only fallback, post-display failure, exclusive preferences,
headless and physical-monitor checks; never change a live security configuration
just to simulate failure.
