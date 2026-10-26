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
| Multi-target plugin selection: `TrayTargetSelectorApp.run` | G only | G only | G only |
| Working-directory picker: `working_dir.choose_directory` | N AppleScript choose folder → isolated T | N desktop-ordered zenity/kdialog → isolated T | N PowerShell WinForms FolderBrowserDialog → isolated T |
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
  Next is still not consent. See [Support bundles](SUPPORT.md).
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
pickers, target selection and sandbox forms/reviews/logs use that policy. Progress
uses the same selector with its documented captured-output exception. Native-only
action/confirmation helpers are implementations called *after* policy selection,
not independent cascades. Support and embedded Web Console dialogs intentionally
remain outside it for the reasons above.

Related unit tests cover policy, actual entry-point calls, child framing, real
mocked Tk initialization failure, complete field/error/log propagation, explicit
preferences and cancellation. About, IDE setup, modal and support UX contracts
cover the user-visible behavior. These checks do **not** establish actual visual
ordering, compositor focus, browser rendering or consent behavior on a desktop.

## Manual desktop verification (not yet qualified by this change)

Run on macOS, native Windows, GNOME/zenity and KDE/kdialog, with X11 and Wayland
where available. Use benign test messages, disposable sandboxes and no live support
upload. Record OS/desktop, display server, preference, toolkit process, captured
monitor, result and sanitized screenshots/timing for each matrix row.

1. In automatic mode exercise plain and linked messages, actions, setup/profile
   controls, both snooze steps, parameter/target forms, host-path Browse, ask, and
   sandbox create/upload/delete/policy/progress/log flows. Confirm the first
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
   Mock/cancel public upload and publication reviews; do not publish diagnostics as
   part of UI verification. Live publication requires separate operator consent.

Do not check off desktop qualification using selector mocks or merely installed
native executables. Keep any untested platform/scenario explicitly pending.
