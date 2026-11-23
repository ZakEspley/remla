# Full-resolution snapshots (photo1 test rollout)

The selected lab YAML may omit `stillCapture` or set it to `false` to disable
capture. The first candidate supports only an explicit PNG opt-in:

```yaml
stillCapture:
  enabled: true
  streamPath: cam
  sensorMode: {width: 2592, height: 1944}
  format: png
```

The dimensions must match exactly one native sensor mode when exclusive access
is available; startup validates structure without opening the camera. The
image is **processed 8-bit RGB** even when the sensor uses 10-bit raw Bayer.
No JPEG, raw DNG, or 16-bit processed colour option is implemented. The user
chose owner access whenever opted in, without a separate time gate. The
installed photo1 service now enforces a 10-second cooldown and at most 100
charged attempts per rolling hour in `snapshot-budget.json`; a failed capture
still costs an attempt. The ledger was retained across the policy change;
denied requests do not consume an attempt. A hundred real epoch timestamps fit
under the ledger's 4096-byte input limit in local tests.

`Experiment/capture_still` returns a short-lived one-use private bearer token
for an HTTP download at page-relative `ws/snapshot`; see `docs/protocol.md`.
Photo1's isolated test runtime, selected-lab opt-in, broker, and Photoelectric
button are installed together. This is **not** a stable release or a claim that
other labs support the endpoint; do not copy the lab opt-in alone.

The privileged boundary is an **optional** local-source provisioning step:
`bash scripts/install-snapshot.sh --dry-run` previews the files. An operator
must separately review the source and approve running the script as root;
it does **not** run during stable `scripts/install.sh` or `remla upgrade`.
Provisioning installs the root-owned broker, sudoers rule and fixed systemd
capture/recovery units, and enables boot recovery. It does not start ReMLA,
MediaMTX, or a capture. `sudo remla mediamtx stop` routes through that broker
after provisioning; do not use an older runtime's uncoordinated stop CLI while
snapshots are enabled. The broker stores interruption intent under
`/var/lib/remla-snapshot`, stops the worker cgroup before MediaMTX recovery,
and will not clear a failed-recovery marker until the `cam` source reports
online. A marker blocks new captures; inspect and repair the recovery path
before enabling again. A normal intentional stop is preserved.

**Photo1 test status:** as `remla`, Picamera2 and the installed broker produced
native 2592×1944 RGB PNGs with MediaMTX initially inactive and active. When
active, normal success, an unsupported sensor mode, and killing the broker
mid-interruption all restored the real `cam` source; recovery also cleared the
marker and worker output after the kill. A live owner-only JSON command through
nginx downloaded a PNG with a one-use bearer token; a queued client was denied.
Both services were active with zero automatic restarts after the first rollout.
Public two-browser/human UI acceptance, failure of MediaMTX itself, reboot
recovery, and clean-image installation remain unverified. The persistent
runtime-state hash mismatch is diagnostic; do not discard saved state.

**Cooldown report:** the owner reported a successful browser snapshot at 15:54
and a generic-error retry at 15:55 while the *prior* 120-second policy was
installed. The 15:54:12 charge and 15:54:19 HTTP 200 download were followed by
no second charge/download; a cooldown rejection is consistent with those
times, although the exact JSON code was not observed.

**Approved policy rollout:** a separate 0.4.6 test venv now runs at
`/opt/remla/releases/0.4.6-cyclic-camera-snapshot-10s-100h-794ef0bf5f43/venv`
(offline wheel SHA-256 `794ef0bf…`; only `snapshot_budget.py` differs from the
prior installed Python modules). The operator approved a safe restart; a
guarded transient switch stopped/started ReMLA once and replaced only
Photoelectric `app.js` and shared `video.js`. Backup copies of the prior
site and original budget are root-protected at
`/var/www/.remla-photo1-snapshot-100-before-794ef0bf/`; prior links are at
`/opt/remla/backups/remla-snapshot-100-links-794ef0bf.txt`. The root-owned
switch script is retained at `/opt/remla/backups/remla-snapshot-100-switch-794ef0bf.sh`.
Read-only postchecks confirm active ReMLA/MediaMTX without automatic restarts,
unchanged selected YAML/settings and budget, clear recovery marker, idle capture
unit, active recovery timer, ready native `cam`, listening WebSocket and
matching nginx-served JS hashes. The frontend now uses the existing alert
dialog for specific cooldown/hourly-limit/busy/capture/download failures,
without rendering token or raw server text; pending stays on the button.
The installed `alert-dialog.js` hash matches the tested component source.
The separately approved frontend-only overlay switch replaced **only** shared
`static/js/components/video.js`. Its pointer-transparent warning that live
video may pause appears while a capture is pending, then clears. The exact
pre-overlay JS (SHA-256 `fd8d505e…`) is protected at
`/var/www/.remla-photo1-snapshot-overlay-before-5a7793d5/video.js`; restore it
atomically only with a served-hash check if a frontend rollback is required.
The new nginx-served hash is `5a7793d5e917ac839e483414c5337864b749be1d9e6c2ad5b8a626f14dc32d8e`.
Post-switch checks found the same active ReMLA and MediaMTX PIDs, zero automatic
restarts, idle capture unit and clear recovery marker. No browser was refreshed
or connected for this switch; an owner refresh to see the new module needs a
safe window because disconnecting may reset or move devices.
The 303-test backend and 46-test frontend suites pass locally. **No live
capture under the new policy or two-browser acceptance has been run**; do not
infer photo quality or physical safety from service health alone.

After this test rollout, local source hardening removed the logging/printing
of failed WebSocket send frames (which can contain a one-use download token),
and made the optional broker installer hold the broker's private transaction
lock while replacing assets. These fixes are **not in photo1's installed test
runtime**; update it only in a separately approved safe restart window. The
hardware-free backend suite with these fixes passes 303 tests.

**Rollback budget compatibility:** the prior snapshot runtime rejects a ledger
with more than three entries *before* expiring old entries. If the new policy
has charged four or more attempts, never roll back to that old snapshot runtime
with snapshots enabled: it would deny capture indefinitely, even after one
hour. Preserve the ledger unchanged. For the protected no-snapshot
`/opt/remla/previous` runtime, first restore the exact pre-snapshot selected
YAML and the pre-button website; it disables snapshots without touching the
ledger. To return to the old snapshot runtime later, plan a separately
reviewed compatibility fix or an explicit operator-approved, budget-preserving
ledger migration after its attempts have expired. Keep root broker/recovery
units while any transaction is pending.

Rollback requires a supervised window because stopping ReMLA can reset or move
devices. The exact pre-opt-in YAML is protected at
`/opt/remla/backups/photo1-snapshot-before-beb2bf9eb22f.yml`; prior runtime
links are recorded in `/opt/remla/backups/remla-snapshot-links-beb2bf9eb22f.txt`.
The two pre-button website assets are protected at
`/var/www/.remla-photo1-snapshot-before-247a820f/`. Do not switch to an older
runtime while a snapshot transaction is pending: reconcile the root marker
first, and leave the broker/recovery units installed until every interruption
marker has cleared. The selected YAML now has hash
`81fedeb9326df4dd0a27beb86cf6ed6b73135b773147b5ac89a841cd4d53381f`.
