#!/usr/bin/env bash
# Opt-in, local-source provisioning. Do not run as part of a stable release install.
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
ASSETS="$ROOT/packaging"
STATE=/var/lib/remla-snapshot
HELPER=/usr/local/libexec/remla-snapshot-helper

[[ $# == 0 || ( $# == 1 && $1 == --dry-run ) ]] || { echo 'Usage: sudo scripts/install-snapshot.sh [--dry-run]' >&2; exit 2; }
for asset in remla-snapshot-helper remla-snapshot-capture.service remla-snapshot-recovery.service \
             remla-snapshot-recovery.timer remla-snapshot-sudoers remla-snapshot-tmpfiles.conf; do
    [[ -f "$ASSETS/$asset" ]] || { echo "Missing snapshot asset: $asset" >&2; exit 1; }
done
if [[ ${1:-} == --dry-run ]]; then
    echo 'Would provision root-owned snapshot broker, capture/recovery units, private directories, and narrow sudoers policy.'
    echo 'Would enable recovery on boot; would not start/stop ReMLA, MediaMTX, or capture.'
    exit 0
fi
[[ $EUID == 0 ]] || { echo 'Run through sudo' >&2; exit 1; }
umask 077
if [[ -e "$STATE" || -L "$STATE" ]]; then
    [[ -d "$STATE" && ! -L "$STATE" && $(stat -c '%u:%a' "$STATE") == 0:700 ]] \
        || { echo 'Unsafe snapshot state directory' >&2; exit 1; }
else
    install -d -o root -g root -m 0700 "$STATE"
fi
# The broker takes this same lock before writing a marker. Hold it through
# installation so a capture cannot start between the marker check and replacement.
[[ ! -L "$STATE/lock" ]] || { echo 'Unsafe snapshot lock' >&2; exit 1; }
exec {broker_lock}<> "$STATE/lock"
[[ -f "$STATE/lock" && $(stat -c '%u:%a:%h' "$STATE/lock") == 0:600:1 ]] \
    || { echo 'Unsafe snapshot lock' >&2; exit 1; }
flock -n "$broker_lock" || { echo 'Snapshot transaction busy; retry later' >&2; exit 1; }
[[ ! -e "$STATE/transaction.json" ]] || { echo 'Snapshot recovery pending; do not replace the broker' >&2; exit 1; }
id remla >/dev/null
[[ -x /opt/remla/current/bin/python ]] || { echo 'Camera-capable ReMLA runtime missing' >&2; exit 1; }
# A rollback to an older mediamtx stop CLI would bypass the broker's desired-state lock.
runuser -u remla -- /opt/remla/current/bin/python -I -c \
    'import remla.main as m; assert "snapshotBrokerStatePath" in m.mediamtx_stop.__code__.co_names; import remla.snapshot_worker' \
    || { echo 'Current runtime cannot coordinate operator stop or capture' >&2; exit 1; }
/usr/sbin/visudo -cf "$ASSETS/remla-snapshot-sudoers" >/dev/null
install -d -o root -g root -m 0755 /usr/local/libexec
install -o root -g root -m 0755 "$ASSETS/remla-snapshot-helper" "$HELPER"
for unit in remla-snapshot-capture.service remla-snapshot-recovery.service remla-snapshot-recovery.timer; do
    install -o root -g root -m 0644 "$ASSETS/$unit" "/etc/systemd/system/$unit"
done
install -o root -g root -m 0440 "$ASSETS/remla-snapshot-sudoers" /etc/sudoers.d/remla-snapshot
install -o root -g root -m 0644 "$ASSETS/remla-snapshot-tmpfiles.conf" /etc/tmpfiles.d/remla-snapshot.conf
/usr/bin/systemd-tmpfiles --create /etc/tmpfiles.d/remla-snapshot.conf
/usr/bin/systemd-analyze verify /etc/systemd/system/remla-snapshot-{capture,recovery}.service /etc/systemd/system/remla-snapshot-recovery.timer
/usr/bin/systemctl daemon-reload
/usr/bin/systemctl enable remla-snapshot-recovery.service remla-snapshot-recovery.timer
printf 'coordinated\n' > "$STATE/operator-stop-v1"
chmod 0600 "$STATE/operator-stop-v1"
echo 'Snapshot broker provisioned. Capture remains disabled until the selected lab YAML opts in.'
