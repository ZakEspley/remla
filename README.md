# ReMLA

ReMLA controls physics laboratory equipment from a Raspberry Pi. Production
installations support Raspberry Pi OS `arm64` and `armhf` only.

## Install a published release

After a stable release is published on GitHub, provision a new Pi with one
command from the intended operator account:

```bash
curl -fsSL https://github.com/ZakEspley/remla/releases/latest/download/install.sh | sudo bash
```

For a reproducible install, replace `latest` with a tagged release and pass its
version:

```bash
curl -fsSL https://github.com/ZakEspley/remla/releases/download/v0.4.2/install.sh | sudo bash -s -- --version 0.4.2
```

The installer configures privileged system resources: apt dependencies, ReMLA
in `/opt/remla`, a global `/usr/local/bin/remla` wrapper, MediaMTX, nginx,
pigpiod, the `remla` systemd service, and restricted operator access. It
verifies the downloaded wheel and locked requirements against the release
`SHA256SUMS` file, then runs the interactive lab and camera setup. The
convenience command intentionally trusts GitHub Releases for the bootstrap
script; its checksums detect transfer or asset corruption but do not
independently authenticate a compromised GitHub release. Review a tagged
installer before use if your deployment requires that assurance:

```bash
curl -fL -O https://github.com/ZakEspley/remla/releases/download/v0.4.2/install.sh
less install.sh
sudo bash install.sh --version 0.4.2
```

Sign out and back in (or reboot) after installation so the operator receives
the `remlausers` group membership. Thereafter, use ordinary commands:

```bash
remla link
remla status
remla start
remla stop
remla recover
remla upgrade
remla rollback
```

`remla link` creates the optional `~/remla` workspace symlink to the canonical
`/var/lib/remla/labs` lab root. It never overwrites an existing directory or a
link to another location; clone, branch, and update lab repositories with Git
inside that workspace.

`remla upgrade` downloads a stable GitHub release, verifies its published
checksums, installs it alongside the current version, atomically switches the
runtime, and restarts only `remla.service`. `remla rollback` switches back to
the previous locally installed release. Operating-system updates remain the Pi
administrator's responsibility.
If lab YAML uses fields unsupported by the previous runtime, restore a compatible
lab file before starting it. For photo1's isolated cyclic trial, do **not** run
bare `remla rollback` while the wheel `cyclic` fields are installed; the exact
original YAML backup and runtime links are recorded in `roadmap.md`. A restart
may reset/move devices, so coordinate a clear maintenance window.

## Select and deploy a lab website

Lab selection updates only group-writable ReMLA configuration and does not
need root access:

```bash
remla setup int
```

After changing website or network settings, deploy the selected lab's website
and nginx configuration with the separate privileged command:

```bash
sudo remla setup deploy-website
```

## Reconfigure camera hardware

To change the camera sensor, mux type, camera count, or mux ports without
reinstalling ReMLA, run during a maintenance window:

```bash
sudo remla camera setup
```

The command stops `remla.service`, backs up and updates
`/boot/firmware/config.txt`, and requires a reboot. It does not change the
selected lab YAML: update that YAML's `numCameras`, `cameraNamesDict`, and
`initialCamera` fields to match the physical configuration before starting
ReMLA after reboot.

## Local Pi validation

Build a development wheel with UV, then run the same installer against that
wheel on a dedicated test Pi:

```bash
uv sync
uv build
sudo ./scripts/install.sh --wheel dist/remla-0.4.2-py3-none-any.whl
```

Use `--dry-run` to inspect the local-wheel installation plan without changing
the host. `--skip-init` intentionally leaves the Pi unconfigured and is only
for provisioning automation that will run the interactive setup separately.

## Development

UV manages the locked Python 3.11 development environment and builds standard
PEP 517 wheels:

```bash
uv sync
uv run python -m unittest tests.test_runtime_imports tests.test_experiment_lifecycle tests.test_boot_status tests.test_camera_cycle tests.test_runtime_state tests.test_runtime_operations tests.test_command_scheduler tests.test_mediamtx tests.test_mediamtx_camera tests.test_device_config tests.test_controller_safety tests.test_installation tests.test_release tests.test_workspace tests.test_setup_commands tests.test_web_deployment
uv build
```

Hardware-free tests do not validate GPIO, camera, systemd, nginx, MediaMTX, or
physical safe-stop behavior. Perform the hardware checks in `roadmap.md` on a
dedicated Pi before publishing a stable release.

### Local OpenCode sandbox for both projects

From this checkout, use the workstation's ReMLA-specific `srt` profile to allow
OpenCode to edit both this repository and `~/Projects/remoteLabs`:

```bash
srt --settings "$HOME/.config/srt/remla.json" -- opencode --standalone --auto
```

The profile is stored **outside** both writable repositories so an agent cannot
change its own sandbox policy. It also retains the usual OpenCode data/cache
write paths, provider-network allowlist, and Linux seccomp helper. Plain
`srt -- opencode ...` loads `~/.srt-settings.json` instead and does **not** grant
ReMLA sessions write access to `remoteLabs`. This is a workstation-local
workflow, not a deployable Raspberry Pi setting. Other OpenCode permission
rules may still require approval unless `--auto` is used.

The ReMLA-specific profile also allows `photo1.inst.physics.ucsb.edu:22`
(TCP port 22, intended for SSH), not other hosts or ports. Plain `ssh` does not
use `srt`'s proxy, and DNS inside this sandbox is unavailable. To route a
**direct SSH** session through the same proxy used for Git-over-SSH, use the
user-owned, read-only-to-sandbox helper (replace `USER` with the Pi account):

```bash
srt --settings "$HOME/.config/srt/remla.json" -- \
  python "$HOME/.local/lib/srt/direct-ssh.py" USER@photo1.inst.physics.ucsb.edu
```

The helper accepts only the photo1 destination and srt's expected proxy
command; it uses `-F /dev/null` to skip a Nix-store system SSH include whose
root ownership is remapped to `nobody` inside the sandbox. The host's actual
system SSH config is root-owned and read-only, not world-writable. The helper
requires strict host-key verification against the existing `~/.ssh/known_hosts`
entry.
The profile allows reading **only** that public host-key file under `~/.ssh`:
private keys, user SSH config, and the SSH agent remain unavailable. Host-key
verification and the proxy settings were checked locally, but the Pi was not
contacted. Authentication may require a separate, reviewed method. Do not
disable host-key checks or grant access to keys/agent sockets just to make it
connect. Because `-F /dev/null` also skips normal SSH settings, supply an
explicit `USER@` destination and do not assume SSH aliases or identity settings.

## MediaMTX

`sudo remla mediamtx update` remains a direct administrative maintenance command
for existing installations. ReMLA verifies the release checksum, installs the
matching MediaMTX configuration, and retains the previous configuration at
`/usr/local/etc/mediamtx.yml.previous`.

The `cam` path uses MediaMTX's native Raspberry Pi camera source and
always-available H.264 mode. `ArduCamMultiCamera.imageMod` applies dynamic image
controls through the local MediaMTX API without restarting the source.
