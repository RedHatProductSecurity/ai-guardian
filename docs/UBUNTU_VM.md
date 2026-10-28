# Headless Ubuntu VM: HTTPS and SSH quickstart (upcoming release)

> **Upcoming-release guide — not supported by PyPI 1.20.0.** Checked on
> **2026-10-28**: [production PyPI](https://pypi.org/pypi/ai-guardian/json) still
> reports **1.20.0**, with no published `1.21.*`. Its wheel has neither native
> daemon TLS nor SSH-managed enrollment. The first supporting **published**
> version is therefore **not yet established**; these features target **1.21**.
> The `>=1.21.0` constraints below are provisional and cannot succeed today.
> Wait for a supporting production release; do not substitute a source checkout,
> development dependencies, GitHub RC artifact or TestPyPI installation.

This guide takes a fresh Ubuntu Server VM to a loopback HTTPS daemon controlled
by the **workstation tray over SSH**, using only the released PyPI package in
virtual environments. The earlier successful `1.21.0-dev` source-build VM
walkthrough is useful evidence, **not** fresh-PyPI qualification. The
[release checklist](#release-qualification) remains open.

| Required feature | First production PyPI release |
|---|---|
| Native daemon HTTPS (#2551) and SSH enrollment (#2552) | Not published; planned for 1.21 |
| Private storage/setup diagnostics (#2584) | Not published; planned for 1.21 |
| Alias discovery and native-first pairing (#2587 / #2589) | Not published; planned for 1.21 |
| Tray discovery settings (#2591) and SSH menu parity (#2592) | Merged development changes, not published; planned for 1.21 |

Recheck each feature against the actual released artifact before replacing this
notice with a confirmed minimum version. A merged PR or a running development
process does not prove PyPI availability.

## Which machine does what?

Run commands yourself in ordinary terminals, not through an AI agent. Stop on a
failed command; do not continue past a failed installation or health check. Unless
marked otherwise, **VM** means an SSH shell as the regular user `guardian`;
**workstation** means your logged-in Linux desktop, with a browser and tray.

| Component | Runs on | Address / storage in this example |
|---|---|---|
| Daemon REST listener | VM | HTTPS at `127.0.0.1:63152`, TLS identity `guardian-vm.test`; check the actual port |
| Bootstrap Web Console | VM | HTTP `127.0.0.1:8080`, forwarded to workstation `127.0.0.1:18080` |
| Bootstrap browser | Workstation | `http://127.0.0.1:18080`; files/settings still belong to the VM |
| Routine tray and Web Console | Workstation | Locally opened/printed Console URL; select `ssh-guardian-vm` |
| SSH alias and saved pairing | Workstation | User SSH config and private AI Guardian state, respectively |
| TLS server private key | VM only | Fresh private directory printed in step 4 |

**Ordering matters: SSH-managed enrollment requires HTTPS first.** Use an
ordinary SSH Console tunnel to configure HTTPS on the VM, verify it, **then**
enroll from the workstation. A Console tunnel alone never enrolls a daemon.

## 1. Prepare the host and guest

- Create a headless **Ubuntu Server LTS** guest under KVM/libvirt, for example
  Ubuntu 24.04 LTS with Python 3.12. AI Guardian requires Python **3.10+**;
  the project's supported test matrix is 3.10–3.14. No guest desktop or browser
  is needed. Follow the [Ubuntu installation guide](https://documentation.ubuntu.com/server/tutorial/basic-installation/)
  and [libvirt guide](https://documentation.ubuntu.com/server/how-to/virtualisation/libvirt/)
  for VM creation, rather than installing a desktop in the guest.
- This example assumes a regular VM user **`guardian`**, an SSH alias
  **`guardian-vm`**, and a guest address such as **`192.168.122.50`**. Substitute
  your own user/address. The alias is not necessarily the libvirt VM name.
- The libvirt **system NAT network** is sufficient for SSH from its workstation
  host to the guest. Other hosts or user-session/SLIRP networking may need a
  separately configured SSH route. Do not expose REST or Console ports publicly.
- **KDE/Plasma is a desktop, not a Linux distribution.** Install hypervisor,
  OpenSSH client, `ssh-copy-id`, desktop tray and dialog prerequisites using
  your workstation distribution's instructions. Do not run the guest's Ubuntu
  package commands blindly on a Fedora, openSUSE or other KDE host. See
  [tray requirements](CONSOLE.md#system-tray) and
  [modal providers](MODAL_PROVIDERS.md).

**VM console**, using sudo only for OS prerequisites:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip openssh-server openssl curl ca-certificates
sudo systemctl enable --now ssh
python3 --version
openssl version
```

Use OpenSSL **3.x** for the certificate recipe below. Ensure the guest clock is
correct and both machines can reach production PyPI. Allow SSH only over the
intended private route; keep REST and Console bound to loopback.

## 2. Verify SSH before involving AI Guardian

First obtain the VM's SSH host-key fingerprint through its **trusted hypervisor
console**, independently of the first SSH connection:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

**Workstation:** reuse an appropriate existing public key, or create a dedicated
identity. For a new identity, choose an **unused** filename; never agree to
overwrite another key. Use a passphrase and your desktop SSH agent:

```bash
ssh-keygen -t ed25519 -f "$HOME/.ssh/id_ed25519_guardian_vm" -C guardian-vm
ssh-add "$HOME/.ssh/id_ed25519_guardian_vm"
```

If that filename already exists, skip generation and use its matching public
key, or choose a different unused filename throughout these examples.
`ssh-copy-id: ERROR: No identities found` means there was no suitable public
identity to copy; generating/reusing a key and passing its **`.pub`** file
explicitly resolves that prerequisite. Never copy the private key to the VM.

Edit the workstation's `~/.ssh/config`, preserving existing entries:

```sshconfig
Host guardian-vm
    HostName 192.168.122.50
    User guardian
    IdentityFile ~/.ssh/id_ed25519_guardian_vm
    IdentitiesOnly yes
    StrictHostKeyChecking yes
```

For the **first** connection, request OpenSSH's interactive first-use review:

```bash
ssh -o StrictHostKeyChecking=ask guardian-vm
```

Compare the offered fingerprint with the independently obtained fingerprint
before accepting it. If it differs, stop and investigate. Authenticate using
your existing authorized method (a guest password may be needed initially),
then `exit` back to the workstation. Do not accept a changed key merely to
silence an error. Now copy only the public key and verify unattended access:

```bash
ssh-copy-id -i "$HOME/.ssh/id_ed25519_guardian_vm.pub" guardian-vm
ssh -o BatchMode=yes guardian-vm true
```

The last command must exit successfully without a password, passphrase or
host-key question. If using an agent, the **workstation tray process** must
inherit that agent's environment and have the identity unlocked. Starting an
agent in an unrelated terminal does not update an already-running tray. Launch
the tray from the appropriate desktop/agent environment; do not enable agent
forwarding or copy private keys to the guest for this workflow. Never publish
keys, daemon tokens or pairing records in diagnostics.

## 3. Install from PyPI and create global configuration

**Release gate:** perform this step only once a supporting production version
exists. Until then, the proposed install correctly finds no matching release;
do not lower the constraint to 1.20.0 to continue this guide.

**VM**, as `guardian`, before initial package invocation/setup/startup:

```bash
umask 077
namei -l "$HOME/.config/ai-guardian" "$HOME/.local/state/ai-guardian"
```

Missing components are normal on a fresh account. Audit **existing** components:
the application directories/files must belong to the intended user, with trusted
ownership along the path and no group/other-writable ancestors. For example,
an owner-only leaf under `.local/state` mode `0775` is still unsafe. Review
unexpected links and any non-default XDG/config/state locations too.

`umask 077` restricts **new** files; it does not repair existing directories.
Stop and have the owner/administrator correct the specifically identified
unsafe path. Do not weaken validation, recursively chmod a home/shared tree,
or make paths world-writable. See
[storage preconditions](MULTI_DAEMON_TRAY.md#posix-storage-preconditions) and
[issue #2584](https://github.com/RedHatProductSecurity/ai-guardian/issues/2584).

After that audit, install as the **same regular user used for SSH**:

```bash
umask 077
python3 -m venv "$HOME/.venvs/ai-guardian"
source "$HOME/.venvs/ai-guardian/bin/activate"
python -m pip install --upgrade pip
python -m pip install --upgrade 'ai-guardian>=1.21.0'
ai-guardian --version
ai-guardian setup --create-config
```

Inspect an existing virtualenv before reusing it; do not delete another
installation. Do not use system-wide `sudo pip`, an editable install, or a
repository clone. **Package installation alone does not create global config.**
Setup creates `~/.config/ai-guardian/ai-guardian.json` for this account. If setup
offers optional IDE integration, it is not required for connectivity; only
select integrations you intend to install.

Activation changes PATH only in this shell. In subsequent SSH sessions, either
activate again or use the installed executable's absolute path:
`/home/guardian/.venvs/ai-guardian/bin/ai-guardian` for this sample user. The
commands below use `"$HOME/.venvs/ai-guardian/bin/ai-guardian"` **inside the VM**.

```bash
"$HOME/.venvs/ai-guardian/bin/ai-guardian" daemon start
"$HOME/.venvs/ai-guardian/bin/ai-guardian" daemon status
```

Check configuration and **REST API** readiness, not just a PID, **IPC: running**
or **Config: loaded**. A working IPC socket can coexist with an unavailable REST
listener, for example when private token storage is unsafe. Before step 6, a
fresh daemon normally serves loopback HTTP; enrollment requires the verified
HTTPS listener established below. Record the actual runtime REST port from
status; **63152 is the default, not a guarantee**, including with port `0`.

### Optional: install an agent on the VM

An agent is useful for later end-to-end hook tests, **not required** for tray
connectivity. To use OpenCode, install **V2** using its
[official installation instructions](https://opencode.ai/v2/docs/) as the VM
user. Then, with that `opencode` executable on the VM's PATH:

```bash
source "$HOME/.venvs/ai-guardian/bin/activate"
ai-guardian setup --ide opencode --install-scanner
```

See [OpenCode integration](OPENCODE.md) for version detection, plugin activation
and qualification limits. Installing this integration is separate from proving
that the workstation can reach the daemon.

## 4. Create a dedicated lab TLS identity on the VM

**VM:** keep this shell open through step 7 so `TLS_DIR` stays defined. Create a
fresh private directory; repeating this command must not overwrite old keys:

```bash
umask 077
TLS_DIR=$(mktemp -d "$HOME/.config/ai-guardian/tls-vm.XXXXXX")
openssl req -x509 -newkey rsa:3072 -noenc -sha256 -days 90 \
  -keyout "$TLS_DIR/server-key.pem" \
  -out "$TLS_DIR/server-cert.pem" \
  -subj "/CN=guardian-vm.test" \
  -addext "subjectAltName=DNS:guardian-vm.test" \
  -addext "basicConstraints=critical,CA:FALSE" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth" \
  -addext "subjectKeyIdentifier=hash" \
  -addext "authorityKeyIdentifier=keyid:always"
printf 'Certificate directory: %s\n' "$TLS_DIR"
openssl x509 -in "$TLS_DIR/server-cert.pem" -noout \
  -fingerprint -sha256 -ext subjectAltName -dates
```

The directory is `0700`, with newly created key/certificate files `0600` under
this umask. The **matching, unencrypted PEM key** allows unattended startup;
its owner-only storage is essential. Keep it on the VM, never in browser fields,
chat or the workstation. Record the absolute directory and public certificate's
**SHA-256 fingerprint and SAN** over this already host-key-verified SSH session
for the later independent pairing comparison.

`guardian-vm.test` is the expected TLS identity, not a public DNS requirement.
This **90-day self-signed lab certificate** is explicitly trusted only for this
dedicated daemon. That is not permission to trust any certificate found by
discovery. Do not install it in a global CA store. For production, organizational
CA issuance and renewal/rotation, use the
[advanced PKI reference](MULTI_DAEMON_TRAY.md#private-vm-provisioning-and-pairing-no-public-inbound-rest)
and [certificate lifecycle guidance](MULTI_DAEMON_TRAY.md#validation-failures-renewal-and-restart).

## 5. Bootstrap with the VM-hosted Web Console

**Do this before SSH-managed enrollment.** First check for existing listeners:
on the **VM**, `ss -ltnp 'sport = :8080'`; on the **workstation**,
`ss -ltnp 'sport = :18080'`. An empty result means no matching listening socket.
If occupied, identify its owner/purpose and choose another unused port; never
kill an unrelated process. Update the corresponding forwarding/Console port
and browser URL together.

In a **second workstation terminal**, run this foreground command:

```bash
ssh -t -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18080:127.0.0.1:8080 guardian-vm \
  'exec "$HOME/.venvs/ai-guardian/bin/ai-guardian" console --web --port 8080 --no-open'
```

The remote shell expands `$HOME` on the **VM**; workstation virtualenv activation
is irrelevant to that remote executable. Keep the default loopback Console bind.
Open **`http://127.0.0.1:18080` in the workstation browser**. NiceGUI's printed
`127.0.0.1:8080` address belongs to the **VM**, not the browser's machine.

Keep this terminal running while using the page. `-t` allocates a remote PTY;
Ctrl+C there interrupts the foreground remote Console. Wait for SSH to exit and
check the owned listener if cleanup is uncertain. Closing a **non-PTY** SSH
command, or losing the network, is not proof that its remote Console stopped.

This is the **Web Console webpage**, not the daemon REST listener. Its bootstrap
URL can remain HTTP on loopback: SSH encrypts the machine-to-machine traffic.
Turning on REST HTTPS in the next step does not change this browser URL.

## 6. Save global HTTPS settings, then restart the VM daemon

In the **VM-hosted Console forwarded at port 18080**, select its **local daemon**
and **Global** configuration scope, then **Global Settings → Daemon REST HTTPS**.
If step 4 printed `/home/guardian/.config/ai-guardian/tls-vm.A1b2C3`, enter:

| Field | Value for this VM lab |
|---|---|
| Enable native HTTPS | On |
| Certificate chain PEM path (on daemon host) | `/home/guardian/.config/ai-guardian/tls-vm.A1b2C3/server-cert.pem` |
| Private-key PEM path (on daemon host) | `/home/guardian/.config/ai-guardian/tls-vm.A1b2C3/server-key.pem` |
| Trusted CA PEM path (empty: system trust) | `/home/guardian/.config/ai-guardian/tls-vm.A1b2C3/server-cert.pem` |
| Expected server SAN identity / SNI | `guardian-vm.test` |
| Optional independently verified SHA-256 leaf pin | Leave empty for initial VM-local trust; workstation enrollment separately records the verified leaf pin |

Replace the example username/directory/suffix with the **exact printed absolute
VM paths**. These inputs do not expand `$TLS_DIR`, `$HOME` or `~`, generate files,
or upload private keys. The trusted CA field explicitly trusts the generated
self-signed public certificate for **VM-local REST clients**; it is not a
server client-auth setting. Do not leave it empty for this self-signed recipe.

Preserve the daemon's **`127.0.0.1` REST bind** and daemon-token authentication.
HTTPS neither changes the bind nor replaces authentication. Click **Save HTTPS
settings**, then in the original **VM SSH shell** run:

```bash
"$HOME/.venvs/ai-guardian/bin/ai-guardian" daemon restart
"$HOME/.venvs/ai-guardian/bin/ai-guardian" daemon status
```

Saving or reloading alone does **not** replace the active listener/certificate.
Refresh the VM Console after restart. If REST is unavailable, resolve its
credential-free startup error before pairing; do not accept IPC liveness as TLS
readiness. Invalid TLS material does not fall back to plaintext.

## 7. Verify HTTPS before pairing

**VM, same shell as certificate generation:** replace `63152` with the actual
runtime REST port from status if different:

```bash
REST_PORT=63152
curl --noproxy '*' --fail --show-error \
  --cacert "$TLS_DIR/server-cert.pem" \
  --resolve "guardian-vm.test:$REST_PORT:127.0.0.1" \
  "https://guardian-vm.test:$REST_PORT/api/health"
```

Expected: JSON containing **`"status": "ok"`**. `--resolve` connects to VM
loopback while verifying the certificate's **`guardian-vm.test` SAN**; neither a
public DNS record nor a public REST port is needed. Certificate verification
remains enabled. In another shell, set `TLS_DIR` to the exact previously printed
absolute directory (or substitute that certificate path directly), not a newly
generated directory. Shell variables do not survive logout/reboot.

Health verifies transport/connectivity, **not authenticated control**. This
additional unauthenticated request should still report **HTTP 401**:

```bash
curl --noproxy '*' --show-error \
  --cacert "$TLS_DIR/server-cert.pem" \
  --resolve "guardian-vm.test:$REST_PORT:127.0.0.1" \
  --output /dev/null --write-out 'HTTP %{http_code}\n' \
  "https://guardian-vm.test:$REST_PORT/api/status"
```

Do not paste a daemon token into commands or chat to test this. The enrollment
flow performs its own authenticated verification after explicit identity review.

## 8. Enroll from the workstation, not the VM Console

### Prepare the workstation installation

The **workstation tray and workstation Console** must use a supporting published
release too, with the **tray version at least as new as the daemon**. For a fresh
Linux workstation install, after the same private-storage audit as step 3:

```bash
umask 077
python3 -m venv "$HOME/.venvs/ai-guardian"
source "$HOME/.venvs/ai-guardian/bin/activate"
python -m pip install --upgrade pip
python -m pip install --upgrade 'ai-guardian>=1.21.0'
ai-guardian --version
ai-guardian setup --create-config
```

The same **unpublished-release gate** applies. If already installed, upgrade the
intended workstation environment rather than creating a second competing one;
preserve existing settings. For Linux tray support, satisfy your distribution's
GTK/AppIndicator and [PyGObject build prerequisites](https://pygobject.gnome.org/getting_started.html),
then install the optional extra **in this workstation virtualenv**:

```bash
python -m pip install --upgrade 'ai-guardian[tray-linux]>=1.21.0'
ai-guardian doctor
```

A distro `python3-gi` installation alone is not necessarily visible inside an
isolated virtualenv. Confirm the prerequisites from the same desktop environment
that will run the tray. The headless **guest does not need this tray extra**.
After upgrading, quit and relaunch already-running workstation tray/Console
processes from the upgraded installation; updating package files does not replace
an existing process. Start the workstation tray in its own desktop terminal:

```bash
"$HOME/.venvs/ai-guardian/bin/ai-guardian" daemon tray start
```

### Choose a pairing entry point

- **Direct tray:** choose **Add daemon via SSH** and enter `guardian-vm`.
  It uses the shared **native-first pairing flow** (Native → Tkinter → NiceGUI
  where eligible), not necessarily the Web Console. No discovery opt-in is needed.
- **Browser alternative:** in a separate **workstation terminal, not through SSH**,
  activate its virtualenv and run `ai-guardian console --web`. Use that command's
  opened/printed **workstation Console URL**, not the VM's port-18080 page.
  The **daemon picker is home page `/`**, not a sidebar item. From any daemon
  dashboard, click **AI Guardian** in the top-left header to return home.
  **SSH daemon connections** appears **above the daemon cards**. Its **Add daemon
  via SSH** accepts the known alias without discovery.

Both pages may have loopback browser URLs; that alone does not identify the
machine hosting them. Pairing in the VM's own forwarded Console stores a pairing
**on the VM**, not in the workstation tray. Use the workstation-hosted entry point.

### Optional: discover your existing SSH alias

On **workstation Console home `/` → SSH daemon connections**:

1. Enable **Discover SSH aliases**.
2. Set **Optional alias prefix (empty lists all concrete aliases)** to
   **`guardian-`** for this walkthrough, or leave it empty for all supported names.
3. Click **Save SSH discovery settings**. These settings are **workstation-global**,
   not settings on the selected VM or its project.

Discovery is **off by default**. The default **`ai-guardian-`** prefix does **not**
match `guardian-vm`; no alias renaming is required. This reads supported concrete
declarations in the workstation user's SSH configuration, **not libvirt/AWS
inventory**. Conditional/unsupported Include layouts have limits; see the
[SSH alias parser reference](MULTI_DAEMON_TRAY.md#discover-ssh-aliases).

Expect **SSH aliases available to pair (N)** in the Console and, after refresh,
the tray when candidates exist. A candidate is **not an enrolled daemon**.
Listing names does not contact hosts, power on a VM, start a daemon or grant trust.
Already-paired and dismissed aliases are excluded. Do **not** remove a working
pairing to force rediscovery: removal also dismisses that alias. For optional
repeat testing, add `guardian-vm-test` as a second name in the same declaration
(`Host guardian-vm guardian-vm-test`), preserving its connection settings, then
verify `ssh -o BatchMode=yes guardian-vm-test true`. Manual **Add daemon via SSH**
remains available for deliberate pairing of a dismissed alias.

**Development UI update:** #2591 added **Discover SSH aliases...** directly in
the tray, next to manual pairing; its enable/Continue and prefix/Save steps edit
the same settings. It is merged, but not in production PyPI as of the date above.
Do not expect that entry in 1.20.0. The Console path above remains available in
the target development workflow; reconfirm both paths against the final release.

### Review, explicitly trust, and connect

1. Choose a candidate's **Review discovered daemon**, or use **Add daemon via SSH**
   with `guardian-vm`. Review skips manual alias entry, **not identity checks**.
2. In **Verify SSH daemon identity**, check destination/user, remote daemon name,
   actual loopback port, SAN identity **`guardian-vm.test`** and certificate
   **SHA-256 fingerprint** against step 4's independently obtained values through
   verified SSH. Colons/case may differ in the fingerprint display, not its bytes.
3. Only if these match, check **I confirm this SSH destination and daemon
   certificate identity**, then **Trust and add daemon**. **Cancel/Close does not
   enroll anything.** SSH host-key verification, TLS CA/SAN/validity/pin checks and
   authenticated daemon status must all succeed before a pairing is saved.
4. After discovery refresh, expect **`ssh-guardian-vm`** (or
   **`ssh-guardian-vm-test`** for that alias) with connected status. The pairing is
   saved privately on the **workstation**, not in global config or an SSH key file.

AI Guardian now owns its **HTTPS REST tunnel**, separately from the manual
18080-to-8080 Console tunnel. Stop the foreground bootstrap command with Ctrl+C
when finished; that tunnel is unnecessary for routine workstation-tray
administration. Saved pairings can reconnect after tray restart/VM recovery once
SSH, the HTTPS daemon and the unchanged saved identity are available. Turning
discovery off hides candidates without deleting saved connections/tunnels.

### Which SSH tray menu should appear?

The earlier source-build walkthrough had only **Status**, **Pause...**, **Web
Console** and **Manage SSH connection...**. **Web Console** there was the same
role as **Console** in local/container menus; fewer shortcuts did not mean failed
pairing. Open it and select the remote target to use supported Console pages.

[#2592](https://github.com/RedHatProductSecurity/ai-guardian/issues/2592) is now
merged in development: SSH targets share applicable **Console**, **Violations**,
**Metrics & Audit**, **Statistics**, **Terminal**, **Maintenance** and **MCP**
entries. Runtime/capability/offline differences still apply; see the
[menu audit](MULTI_DAEMON_TRAY.md#ssh-menuaction-parity-audit). Neither that parity
nor [#2591](https://github.com/RedHatProductSecurity/ai-guardian/issues/2591) is yet
a PyPI feature. Check the final published version's menus rather than promising
the old reduced menu or every development shortcut. Never substitute local
maintenance commands for a remote action.

## 9. Return after shutdown or reboot

Installation, alias discovery and a saved pairing **do not start the VM or its
daemon**. This guide does not install or claim a verified boot-time daemon
service. Hypervisor VM autostart, guest daemon startup and managed tunnel
reconnection are three different lifecycle mechanisms.

1. Power on the VM using the correct hypervisor instance/network. From the
   **workstation**, verify `ssh -o BatchMode=yes guardian-vm true` again.
2. Connect with `ssh guardian-vm`, then run **on the VM as the same SSH user**:

   ```bash
   "$HOME/.venvs/ai-guardian/bin/ai-guardian" daemon status
   ```

3. **If stopped**, start the existing installation and check readiness:

   ```bash
   "$HOME/.venvs/ai-guardian/bin/ai-guardian" daemon start
   "$HOME/.venvs/ai-guardian/bin/ai-guardian" daemon status
   ```

4. Reuse the saved TLS paths/certificate/key and verify step 7 with their actual
   paths and current REST port. Let the workstation tray reconnect/refresh.
   Do not regenerate certificates or enroll again merely because the guest was
   stopped. A changed/expired identity needs separate deliberate verification and
   [renewal handling](MULTI_DAEMON_TRAY.md#validation-failures-renewal-and-restart).

**The remote daemon is stopped. Start it as the SSH user, then reconnect.** means
the remote probe could connect but found no running daemon. A powered-off VM may
instead fail SSH before metadata can be read; not every outage produces that
same error. Automatic tunnel reconnection is not automatic daemon startup.

## 10. Optional background Console forwarding and owned cleanup

Use this only for an **already-running VM Console** on loopback port 8080, for
example one kept open in a separate VM terminal. The foreground bootstrap command
already owns its own forward; do not stack this on its occupied port. Check both
listeners as in step 5 first.

**Workstation:** create a dedicated private control socket for this tunnel only:

```bash
umask 077
CONTROL_DIR=$(mktemp -d "${TMPDIR:-/tmp}/guardian-console.XXXXXX")
CONTROL_SOCKET="$CONTROL_DIR/ssh"
ssh -M -S "$CONTROL_SOCKET" -o ControlPersist=no -o BatchMode=yes \
  -o ExitOnForwardFailure=yes -fNT \
  -L 127.0.0.1:18080:127.0.0.1:8080 guardian-vm
printf 'Console tunnel control socket: %s\n' "$CONTROL_SOCKET"
```

Open `http://127.0.0.1:18080`. `-N` starts **no remote command**: it does not start
the VM Console, daemon or VM, and does not enroll anything. A successful local
forward bind alone does not prove that something listens on remote port 8080.
This is not a service and is not guaranteed to survive network disconnects,
logout or reboot.

In the same **workstation shell**, stop **only this owned tunnel**:

```bash
ssh -S "$CONTROL_SOCKET" -O exit guardian-vm
rmdir "$CONTROL_DIR"
```

In another shell, use the exact printed socket path and its directory instead;
do not guess another client's socket. `rmdir` removes only an empty directory.
This does not stop the VM Console or the tray's separately managed REST tunnel.
Stop a Console you started from its original terminal with Ctrl+C. Never use
blanket SSH/process kills or terminate an unrelated port owner.

## Troubleshooting checklist

| Symptom | Check / next step |
|---|---|
| `ssh-copy-id: ERROR: No identities found` | Reuse/generate an appropriate key without overwriting another identity; explicitly copy its matching `.pub` file (step 2). |
| Non-interactive SSH fails | Verify host key, alias/user/port, public-key authorization and desktop agent availability. Make the BatchMode check pass before pairing. |
| Package installed / daemon running, but global config missing | Run `setup --create-config` from the intended VM virtualenv as the SSH user; package installation is not setup. |
| Unsafe config/state ancestors, missing REST token, or IPC-only startup | Read that user's `daemon status`; audit ownership, links and every existing ancestor, not just the leaf. See #2584/storage preconditions; do not weaken permissions or paste token material. |
| **Remote daemon metadata is unavailable or invalid** | Confirm the installation, global config and private state belong to the SSH user and are visible in non-interactive SSH. Custom XDG/AI Guardian paths must be available there too. |
| **SSH-managed connections require a running HTTPS daemon** | Complete TLS provisioning, save Global settings, explicitly restart and pass the verified health request before attempting enrollment. |
| TLS file/CA/SAN/validity error | Check exact VM paths, matching key/certificate, owner-only key, trusted certificate field, `guardian-vm.test` SAN, clock and expiry. Keep verification enabled; share no private material. |
| Console/forward port occupied | Identify existing listeners on the correct machine, choose unused ports and adjust both ends/URL. A non-PTY SSH interruption may have left your old VM Console running. |
| VM visible in its own Console, absent from workstation tray | Complete **workstation-side** enrollment. The port-18080 browser page administers a VM-hosted client. |
| Cannot find daemon picker/discovery settings | In the **workstation Console**, click the top-left **AI Guardian** link to `/`; the SSH card is above daemon cards, not in the sidebar. Native Add is a different entry point. |
| Valid alias, no candidates | Check opt-in, `guardian-`/empty prefix (not default `ai-guardian-`), supported SSH config layout, paired/dismissed status and the versions of actually running/restarted workstation components. |
| Candidate visible, no connected target | Inventory is not enrollment: review, independently verify and explicitly complete trust. |
| Remote daemon stopped / SSH unavailable after shutdown | Follow step 9: VM power → SSH → same-user daemon status/start → verified REST → reconnect. Do not reset TLS/trust just for an outage. |
| Connected target has fewer entries / says Web Console | Compare its build with the #2592 development changes above. Use supported pages with the remote target selected, not workstation-local maintenance. |

## Release qualification

**Status on 2026-10-28:** production PyPI metadata and the SHA-256-verified
`ai_guardian-1.20.0-py3-none-any.whl` were inspected; that wheel lacks the native
TLS/SSH modules and TLS schema. No qualifying published version exists to record
for the VM or workstation. The earlier reporter walkthrough used **1.21.0-dev**
source builds, not a fresh PyPI install; it did not establish boot-time startup
or complete desktop/platform qualification.

Documentation checks on Linux with Python **3.14.7**, OpenSSL **3.5.8** and curl
**8.18.0** passed shell syntax, local links/navigation, exact UI-label checks and
the certificate/strict-TLS curl recipe against a **disposable synthetic loopback
endpoint**. These checks do not qualify daemon authentication, live SSH/Console
lifecycles, native desktop behavior or a released VM/workstation installation.

Before calling this a release-qualified reproducible PyPI walkthrough:

- [ ] Identify each feature's first **production PyPI** version, update the table
  and minimum constraints, and remove the upcoming notice only when justified.
- [ ] Install the actual released package/dependencies into fresh VM and
  workstation virtualenvs; record Ubuntu/Python/OpenSSL versions, workstation
  OS/desktop and both AI Guardian versions/artifact identities. No source/editable
  or development-dependency substitution.
- [ ] Follow the entire sequence, including global setup/storage, TLS fields,
  restart, verified health and unauthenticated 401, and independently verified
  workstation pairing. Record what was actually observed, not just unit results.
- [ ] Verify native/manual pairing, browser home navigation, optional prefix
  discovery, cancellation, dismissed/paired aliases and the released tray menus.
- [ ] Verify foreground PTY shutdown and dedicated background tunnel cleanup;
  no unrelated listeners/processes should be stopped.
- [ ] Power off/reboot and recover using step 9; verify saved pairing/tunnel
  reconnection with the original valid identity. Qualify any proposed boot-time
  daemon service separately before documenting it as automatic.

Keep this gate open in [#2585](https://github.com/RedHatProductSecurity/ai-guardian/issues/2585)
until those exact released-artifact observations are recorded. See the
[advanced multi-daemon reference](MULTI_DAEMON_TRAY.md) for ongoing administration.
