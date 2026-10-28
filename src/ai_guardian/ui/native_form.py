"""Complete single-field native forms, isolated from the tray's GUI state."""

import json
import platform
from html import escape
from typing import Any, Iterable

from ai_guardian.ui.modal import UIUnavailable, run_native_command
from ai_guardian.ui.monitor import (
    COCOA_PLACE_WINDOW,
    MonitorContext,
    current_origin,
    resolve_bounds,
    restore_context,
)

# These scripts consume display-only JSON over stdin, never executable input.
_COCOA_FORM = COCOA_PLACE_WINDOW + r"""
(function () {
    var displayed = false;
    try {
        ObjC.import('Cocoa');
        var data = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
        var p = JSON.parse($.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding).js);
        var app = $.NSApplication.sharedApplication;
        app.setActivationPolicy(0);
        var alert = $.NSAlert.alloc.init;
        alert.setMessageText(String(p.title));
        var submit = alert.addButtonWithTitle(String(p.submit_label));
        alert.addButtonWithTitle('Cancel');
        var view = $.NSView.alloc.initWithFrame($.NSMakeRect(0, 0, 640, 360));
        var scroll = $.NSScrollView.alloc.initWithFrame($.NSMakeRect(0, 80, 640, 280));
        scroll.setHasVerticalScroller(true);
        var text = $.NSTextView.alloc.initWithFrame($.NSMakeRect(0, 0, 620, 280));
        text.setString(String(p.message));
        text.setEditable(false);
        text.setSelectable(true);
        text.setVerticallyResizable(true);
        text.setHorizontallyResizable(false);
        text.setMinSize($.NSMakeSize(0, 280));
        text.setMaxSize($.NSMakeSize(1000000, 1000000));
        text.textContainer.setWidthTracksTextView(true);
        scroll.setDocumentView(text);
        view.addSubview(scroll);
        var field = p.field;
        var control = null;
        function ready() {
            return !field || !field.required || (field.type === 'bool'
                ? Number(control.state) === 1 : String(control.stringValue.js).trim().length > 0);
        }
        ObjC.registerSubclass({
            name: 'AIGuardianFormTarget', superclass: 'NSObject',
            methods: {
                'changed:': {types: ['void', ['id']], implementation: function() { submit.setEnabled(ready()); }},
                'controlTextDidChange:': {types: ['void', ['id']], implementation: function() { submit.setEnabled(ready()); }}
            }
        });
        var target = $.AIGuardianFormTarget.alloc.init;
        if (field) {
            if (field.type === 'bool') {
                control = $.NSButton.alloc.initWithFrame($.NSMakeRect(0, 12, 640, 50));
                control.setButtonType(3);
                control.setTitle(String(field.label));
                control.setState(field.default ? 1 : 0);
                control.setTarget(target);
                control.setAction('changed:');
            } else {
                var label = $.NSTextField.alloc.initWithFrame($.NSMakeRect(0, 48, 640, 24));
                label.setStringValue(String(field.label));
                label.setBezeled(false); label.setDrawsBackground(false); label.setEditable(false);
                view.addSubview(label);
                control = $.NSTextField.alloc.initWithFrame($.NSMakeRect(0, 12, 640, 28));
                control.setStringValue(String(field.default || ''));
                control.setDelegate(target);
            }
            view.addSubview(control);
        }
        alert.setAccessoryView(view);
        submit.setEnabled(ready());
        var window = alert.window;
        placeWindowOnTargetScreen(window, p.screen_bounds, p.monitor_id);
        app.activateIgnoringOtherApps(true);
        displayed = true;
        window.makeKeyAndOrderFront(null);
        if (control && field.type !== 'bool') window.makeFirstResponder(control);
        if (Number(alert.runModal) !== 1000 || !ready()) {
            return JSON.stringify({modal_status: 'complete', value: null});
        }
        var result = {};
        if (field) result[field.name] = field.type === 'bool'
            ? Number(control.state) === 1 : String(control.stringValue.js).trim();
        return JSON.stringify({modal_status: 'complete', value: result});
    } catch (error) {
        return JSON.stringify({modal_status: displayed ? 'failed' : 'unavailable'});
    }
})();
"""

_WINDOWS_FORM = r"""
$ErrorActionPreference = 'Stop'
$displayed = $false
try {
    [Console]::InputEncoding = [Text.Encoding]::UTF8
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    $p = [Console]::In.ReadToEnd() | ConvertFrom-Json
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class GuardianDpi {
    [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr value);
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    private struct Device {
        public int size;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string name;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string description;
        public int flags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string identity;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string key;
    }
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    private static extern bool EnumDisplayDevices(string name, int index, ref Device device, int flags);
    public static string Identity(string name) {
        var device = new Device(); device.size = Marshal.SizeOf(typeof(Device));
        return EnumDisplayDevices(name, 0, ref device, 1) && !String.IsNullOrEmpty(device.identity)
            ? device.identity : name;
    }
}
'@
    [GuardianDpi]::SetThreadDpiAwarenessContext([IntPtr](-4)) | Out-Null
    $form = New-Object System.Windows.Forms.Form
    $form.Text = $p.title
    $form.ClientSize = New-Object System.Drawing.Size(760, 520)
    $form.StartPosition = 'CenterScreen'
    $form.MinimizeBox = $false
    $form.MaximizeBox = $false
    $form.FormBorderStyle = 'FixedDialog'
    $review = New-Object System.Windows.Forms.TextBox
    $review.Location = New-Object System.Drawing.Point(16, 16)
    $review.Size = New-Object System.Drawing.Size(728, 350)
    $review.Multiline = $true
    $review.ReadOnly = $true
    $review.ScrollBars = 'Both'
    $review.WordWrap = $true
    $review.Text = $p.message -replace "`n", "`r`n"
    $form.Controls.Add($review)
    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = $p.submit_label
    $ok.Location = New-Object System.Drawing.Point(474, 470)
    $ok.Size = New-Object System.Drawing.Size(270, 32)
    $ok.DialogResult = 'OK'
    $form.Controls.Add($ok)
    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = 'Cancel'
    $cancel.Location = New-Object System.Drawing.Point(16, 470)
    $cancel.Size = New-Object System.Drawing.Size(100, 32)
    $cancel.DialogResult = 'Cancel'
    $form.Controls.Add($cancel)
    $form.AcceptButton = $ok
    $form.CancelButton = $cancel
    $field = $p.field
    if ($null -ne $field) {
        if ($field.type -eq 'bool') {
            $control = New-Object System.Windows.Forms.CheckBox
            $control.Text = $field.label
            $control.Location = New-Object System.Drawing.Point(16, 380)
            $control.Size = New-Object System.Drawing.Size(728, 60)
            $control.Checked = [bool]$field.default
            $update = { $ok.Enabled = !$field.required -or $control.Checked }
            $control.add_CheckedChanged($update)
        } else {
            $label = New-Object System.Windows.Forms.Label
            $label.Text = $field.label
            $label.Location = New-Object System.Drawing.Point(16, 380)
            $label.Size = New-Object System.Drawing.Size(728, 24)
            $form.Controls.Add($label)
            $control = New-Object System.Windows.Forms.TextBox
            $control.Location = New-Object System.Drawing.Point(16, 410)
            $control.Size = New-Object System.Drawing.Size(728, 28)
            $control.Text = [string]$field.default
            $update = { $ok.Enabled = !$field.required -or ![string]::IsNullOrWhiteSpace($control.Text) }
            $control.add_TextChanged($update)
        }
        $form.Controls.Add($control)
        & $update
    }
    if ($null -ne $p.screen_bounds -or $p.monitor_id) {
        # Revalidate here, not only in Python before PowerShell startup.
        $screen = [System.Windows.Forms.Screen]::PrimaryScreen
        foreach ($candidate in [System.Windows.Forms.Screen]::AllScreens) {
            $r = $candidate.WorkingArea
            $b = $p.screen_bounds
            if (($p.monitor_id -and [GuardianDpi]::Identity($candidate.DeviceName) -eq $p.monitor_id) -or
                (!$p.monitor_id -and $null -ne $b -and $r.X -eq $b[0] -and $r.Y -eq $b[1] -and $r.Width -eq $b[2] -and $r.Height -eq $b[3])) {
                $screen = $candidate
                break
            }
        }
        $area = $screen.WorkingArea
        $form.AutoScroll = $true
        $form.AutoScrollMinSize = New-Object System.Drawing.Size(760, 520)
        $form.Size = New-Object System.Drawing.Size([Math]::Min($form.Width, [Math]::Max(1, $area.Width-32)), [Math]::Min($form.Height, [Math]::Max(1, $area.Height-32)))
        $form.StartPosition = 'Manual'
        $form.Location = New-Object System.Drawing.Point([int]($area.X+($area.Width-$form.Width)/2), [int]($area.Y+($area.Height-$form.Height)/2))
    }
    $form.add_Shown({ $form.Activate(); if ($null -ne $control) { $control.Focus() | Out-Null } })
    $displayed = $true
    $answer = $form.ShowDialog()
    if ($answer -ne [System.Windows.Forms.DialogResult]::OK) {
        [Console]::Out.WriteLine('{"modal_status":"complete","value":null}')
    } else {
        $result = @{}
        if ($null -ne $field) {
            $result[$field.name] = if ($field.type -eq 'bool') { $control.Checked } else { $control.Text.Trim() }
        }
        [Console]::Out.WriteLine((@{modal_status='complete'; value=$result} | ConvertTo-Json -Compress))
    }
    $form.Dispose()
} catch {
    $status = if ($displayed) { 'failed' } else { 'unavailable' }
    [Console]::Out.WriteLine((@{modal_status=$status} | ConvertTo-Json -Compress))
}
"""


class NativeForm:
    """A provider-bound renderer; Linux never changes toolkit after display."""

    def __init__(self, *, screen_bounds=None) -> None:
        self.screen_bounds = screen_bounds
        self._linux_provider: str | None = None

    def __call__(
        self,
        title: str,
        message: str,
        fields: Iterable[dict[str, Any]],
        *,
        submit_label: str = "Continue",
    ) -> dict[str, Any] | None:
        field_list = list(fields)
        if len(field_list) > 1 or any(
            field.get("type", "text") not in {"text", "bool"}
            or set(field) - {"name", "label", "type", "default", "required", "help"}
            for field in field_list
        ):
            raise UIUnavailable("Native form does not implement these controls")
        field = dict(field_list[0]) if field_list else None
        if field is not None:
            field.setdefault("type", "text")
            field.setdefault("label", field["name"])
            if field.get("help"):
                message += "\n\n" + str(field["help"])
        context = restore_context(
            self.screen_bounds if self.screen_bounds is not None else current_origin()
        )
        payload = {
            "title": title,
            "message": message,
            "field": field,
            "submit_label": submit_label,
            "screen_bounds": resolve_bounds(self.screen_bounds),
            "monitor_id": (
                context.monitor_id if isinstance(context, MonitorContext) else None
            ),
        }
        system = platform.system()
        if system == "Linux":
            return self._linux_form(payload)
        if system == "Darwin":
            command = ["osascript", "-l", "JavaScript", "-e", _COCOA_FORM]
        elif system == "Windows":
            command = ["powershell", "-NoProfile", "-STA", "-Command", _WINDOWS_FORM]
        else:
            raise UIUnavailable("No native form implementation")
        result = run_native_command(
            command, input_text=json.dumps(payload, ensure_ascii=False)
        )
        if result.returncode != 0:
            raise RuntimeError("Native form ended without a completed result")
        value = json.loads(result.stdout.strip())
        if not isinstance(value, dict):
            raise RuntimeError("Native form returned an invalid result")
        if value.get("modal_status") == "unavailable":
            raise UIUnavailable("Native form unavailable before display")
        if value.get("modal_status") != "complete":
            raise RuntimeError("Native form ended without a completed result")
        result_value = value.get("value")
        return result_value if isinstance(result_value, dict) else None

    def _linux_form(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        from ai_guardian.tray.plugins import _linux_dialog_provider_order

        providers = (
            (self._linux_provider,)
            if self._linux_provider
            else _linux_dialog_provider_order()
        )
        field = payload["field"]
        label = field["label"] if field else ""
        for provider in providers:
            if provider == "zenity":
                command = [
                    "zenity",
                    "--title",
                    payload["title"],
                    "--text",
                    payload["message"],
                    "--no-markup",
                    "--width=760",
                    "--height=480",
                    "--ok-label",
                    payload["submit_label"],
                ]
                if not field:
                    command += ["--info"]
                elif field["type"] == "bool":
                    command += [
                        "--list",
                        "--checklist",
                        "--hide-header",
                        "--column=",
                        "--column=Confirmation",
                        "--print-column=2",
                        "TRUE" if field.get("default") else "FALSE",
                        label,
                    ]
                else:
                    command += [
                        "--entry",
                        "--entry-text",
                        str(field.get("default", "")),
                    ]
                    command[command.index("--text") + 1] += "\n\n" + label
            else:
                command = [
                    "kdialog",
                    "--title",
                    payload["title"],
                    "--ok-label",
                    payload["submit_label"],
                ]
                # Qt auto-detects rich text; keep backend metadata literal.
                plain_message = payload["message"]
                if field and field["type"] == "text":
                    plain_message += "\n\n" + label
                message = (
                    '<qt><p style="white-space: pre-wrap">'
                    + escape(plain_message)
                    + "</p></qt>"
                )
                if not field:
                    command += ["--msgbox", message]
                elif field["type"] == "bool":
                    command += [
                        "--separate-output",
                        "--checklist",
                        message,
                        "confirmed",
                        label,
                        "on" if field.get("default") else "off",
                    ]
                else:
                    command += [
                        "--inputbox",
                        message,
                        str(field.get("default", "")),
                    ]
            try:
                result = run_native_command(command)
            except UIUnavailable:
                if self._linux_provider:
                    raise
                continue
            self._linux_provider = provider
            if result.returncode != 0:
                return None
            if not field:
                return {}
            value: str | bool = result.stdout.strip()
            if field["type"] == "bool":
                value = value == (label if provider == "zenity" else "confirmed")
            if field.get("required") and not value:
                return None
            return {field["name"]: value}
        raise UIUnavailable("No Linux native form provider could start")
