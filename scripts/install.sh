#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="ZakEspley/remla"
INSTALL_ROOT="/opt/remla"
SERVICE_USER="remla"
OPERATOR="${SUDO_USER:-${REMLA_OPERATOR:-}}"
VERSION=""
WHEEL=""
REQUIREMENTS=""
DRY_RUN=0
SKIP_INIT=0
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ASSET_DIRECTORY="$SCRIPT_DIR/../packaging"

usage() {
    cat <<'EOF'
Usage: sudo ./install.sh [--version VERSION] [--wheel PATH] [--requirements PATH] [--skip-init] [--dry-run]

Install ReMLA on Raspberry Pi OS. Without --wheel, the installer downloads the
requested GitHub release (or the latest stable release) and verifies SHA256SUMS.
EOF
}

fail() {
    printf 'remla installer: %s\n' "$*" >&2
    exit 1
}

normalize_nginx_web_root_permissions() {
    if [[ -d /var/www/remla ]]; then
        chown -R root:root /var/www/remla
        find /var/www/remla -type d -exec chmod 0755 {} +
        find /var/www/remla -type f -exec chmod 0644 {} +
    fi
}

while (($#)); do
    case "$1" in
        --version)
            VERSION="${2:-}"
            shift 2
            ;;
        --wheel)
            WHEEL="${2:-}"
            shift 2
            ;;
        --requirements)
            REQUIREMENTS="${2:-}"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --skip-init)
            SKIP_INIT=1
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            fail "unknown option: $1"
            ;;
    esac
done

if [[ -z "$OPERATOR" ]]; then
    fail "run through sudo from the Raspberry Pi operator account"
fi

if (( ! DRY_RUN )) && (( EUID != 0 )); then
    fail "run this installer with sudo"
fi

if [[ -n "$WHEEL" ]]; then
    [[ -f "$WHEEL" ]] || fail "wheel not found: $WHEEL"
    if [[ -z "$VERSION" ]]; then
        wheel_name="$(basename "$WHEEL")"
        [[ "$wheel_name" =~ ^remla-([0-9][A-Za-z0-9.]*[^-])- ]] || fail "could not determine version from $wheel_name"
        VERSION="${BASH_REMATCH[1]}"
    fi
else
    if [[ -z "$VERSION" ]]; then
        VERSION="$(python3 - "$REPOSITORY" <<'PY'
import json
import sys
from urllib.request import urlopen

with urlopen(f"https://api.github.com/repos/{sys.argv[1]}/releases/latest", timeout=30) as response:
    tag = json.load(response)["tag_name"]
print(tag.removeprefix("v"))
PY
)"
    fi
    release_url="https://github.com/${REPOSITORY}/releases/download/v${VERSION}"
    work_directory="$(mktemp -d)"
    trap 'rm -rf "$work_directory"' EXIT
    WHEEL="$work_directory/remla-${VERSION}-py3-none-any.whl"
    REQUIREMENTS="$work_directory/requirements.txt"
    checksums="$work_directory/SHA256SUMS"
    curl --fail --location --silent --show-error "$release_url/SHA256SUMS" --output "$checksums"
    curl --fail --location --silent --show-error "$release_url/$(basename "$WHEEL")" --output "$WHEEL"
    curl --fail --location --silent --show-error "$release_url/requirements.txt" --output "$REQUIREMENTS"
    curl --fail --location --silent --show-error "$release_url/remla.service" --output "$work_directory/remla.service"
    curl --fail --location --silent --show-error "$release_url/49-remla.rules" --output "$work_directory/49-remla.rules"
    (
        cd "$work_directory"
        grep "  $(basename "$WHEEL")$" SHA256SUMS | sha256sum --check --status --
        grep "  requirements.txt$" SHA256SUMS | sha256sum --check --status --
        grep "  remla.service$" SHA256SUMS | sha256sum --check --status --
        grep "  49-remla.rules$" SHA256SUMS | sha256sum --check --status --
    ) || fail "release checksum verification failed"
    ASSET_DIRECTORY="$work_directory"
fi

if (( DRY_RUN )); then
    printf 'Would install ReMLA %s for operator %s.\n' "$VERSION" "$OPERATOR"
    printf 'Release runtime: %s/releases/%s\n' "$INSTALL_ROOT" "$VERSION"
    printf 'Global command: /usr/local/bin/remla\n'
    printf 'System service: remla.service\n'
    exit 0
fi

architecture="$(dpkg --print-architecture)"
case "$architecture" in
    arm64|armhf) ;;
    *) fail "ReMLA installer supports Raspberry Pi OS arm64 or armhf, not $architecture" ;;
esac

id "$OPERATOR" >/dev/null 2>&1 || fail "operator account does not exist: $OPERATOR"

apt-get update
apt-get install --yes --no-install-recommends \
    ca-certificates curl i2c-tools nginx pigpio python3-pigpio python3-pip python3-venv

if ! getent passwd "$SERVICE_USER" >/dev/null; then
    useradd --system --home /var/lib/remla --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi
getent group remlausers >/dev/null || groupadd --system remlausers
getent group gpio >/dev/null || groupadd --system gpio
getent group i2c >/dev/null || groupadd --system i2c
usermod --append --groups remlausers,gpio,i2c "$SERVICE_USER"
usermod --append --groups remlausers "$OPERATOR"

install -d -o "$SERVICE_USER" -g remlausers -m 2775 "$INSTALL_ROOT"
install -d -o "$SERVICE_USER" -g remlausers -m 2775 "$INSTALL_ROOT/releases"
release_directory="$INSTALL_ROOT/releases/$VERSION"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$release_directory"
wheel_asset="$release_directory/$(basename "$WHEEL")"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0644 "$WHEEL" "$wheel_asset"
runuser -u "$SERVICE_USER" -- python3 -m venv "$release_directory/venv"
if [[ -n "$REQUIREMENTS" ]]; then
    requirements_asset="$release_directory/requirements.txt"
    install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0644 "$REQUIREMENTS" "$requirements_asset"
    runuser -u "$SERVICE_USER" -- "$release_directory/venv/bin/pip" install --require-hashes --no-deps -r "$requirements_asset"
    runuser -u "$SERVICE_USER" -- "$release_directory/venv/bin/pip" install --no-deps --force-reinstall "$wheel_asset"
else
    runuser -u "$SERVICE_USER" -- "$release_directory/venv/bin/pip" install --force-reinstall "$wheel_asset"
fi

install -d -o "$SERVICE_USER" -g remlausers -m 2770 /var/lib/remla/labs
install -d -o "$SERVICE_USER" -g remlausers -m 2770 /etc/remla
ln -sfn "$release_directory/venv" "$INSTALL_ROOT/current"
cat > /usr/local/bin/remla <<'EOF'
#!/bin/sh
export REMLA_CONFIG_HOME=/etc
export REMLA_LABS_DIRECTORY=/var/lib/remla/labs
export REMLA_IPC_SOCKET=/run/remla/remla_cmd.sock
export REMLA_OPERATOR_GROUP=remlausers
exec /opt/remla/current/bin/remla "$@"
EOF
chmod 0755 /usr/local/bin/remla

service_source="$ASSET_DIRECTORY/remla.service"
policy_source="$ASSET_DIRECTORY/49-remla.rules"
[[ -f "$service_source" ]] || fail "missing service asset: $service_source"
[[ -f "$policy_source" ]] || fail "missing policy asset: $policy_source"
install -m 0644 "$service_source" /etc/systemd/system/remla.service
install -m 0644 "$policy_source" /etc/polkit-1/rules.d/49-remla.rules

systemctl daemon-reload
systemctl enable pigpiod.service
systemctl restart pigpiod.service

if (( SKIP_INIT )); then
    normalize_nginx_web_root_permissions
    printf 'ReMLA %s is installed. Run the installer again without --skip-init to configure this laboratory.\n' "$VERSION"
    exit 0
fi

/usr/local/bin/remla init
chown -R "$SERVICE_USER":remlausers /etc/remla /var/lib/remla/labs
find /etc/remla /var/lib/remla/labs -type d -exec chmod 2770 {} +
find /etc/remla /var/lib/remla/labs -type f -exec chmod 0660 {} +
normalize_nginx_web_root_permissions

printf 'ReMLA %s is installed and configured. Use `remla status` to check the service.\n' "$VERSION"
