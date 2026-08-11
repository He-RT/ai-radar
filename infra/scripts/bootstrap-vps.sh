#!/usr/bin/env bash
# One-time Ubuntu VPS preparation. Review and run only on the intended VPS as root.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

usage() {
  printf '%s\n' "Usage: sudo bash infra/scripts/bootstrap-vps.sh --repo-root /opt/amplitude-radar --authorized-key-file /secure/path/github-actions.pub [--deploy-user radar-deploy]"
}

repo_root=""
authorized_key_file=""
deploy_user="radar-deploy"

while (($#)); do
  case "$1" in
    --repo-root)
      (($# >= 2)) || { usage >&2; exit 64; }
      repo_root="$2"
      shift 2
      ;;
    --authorized-key-file)
      (($# >= 2)) || { usage >&2; exit 64; }
      authorized_key_file="$2"
      shift 2
      ;;
    --deploy-user)
      (($# >= 2)) || { usage >&2; exit 64; }
      deploy_user="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      printf 'ERROR: unknown argument: %s\n' "$1" >&2
      exit 64
      ;;
  esac
done

(( EUID == 0 )) || {
  printf '%s\n' "ERROR: bootstrap must run as root" >&2
  exit 1
}
[[ -d "$repo_root/.git" && -f "$repo_root/infra/scripts/ssh-deploy-gate.sh" ]] || {
  printf '%s\n' "ERROR: --repo-root must be a checked-out repository containing infra/scripts/ssh-deploy-gate.sh" >&2
  exit 1
}
[[ -f "$authorized_key_file" && -r "$authorized_key_file" ]] || {
  printf '%s\n' "ERROR: --authorized-key-file must be a readable public-key file" >&2
  exit 1
}
[[ "$deploy_user" =~ ^[a-z_][a-z0-9_-]*$ ]] || {
  printf '%s\n' "ERROR: --deploy-user is invalid" >&2
  exit 64
}
command -v docker >/dev/null 2>&1 || {
  printf '%s\n' "ERROR: install Docker Engine and the Docker Compose plugin before bootstrap" >&2
  exit 1
}
docker compose version >/dev/null 2>&1 || {
  printf '%s\n' "ERROR: Docker Compose plugin is unavailable" >&2
  exit 1
}

if ! id "$deploy_user" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$deploy_user"
fi
usermod --append --groups docker "$deploy_user"
passwd --lock "$deploy_user" >/dev/null 2>&1 || true

install -d -o "$deploy_user" -g "$deploy_user" -m 0700 /etc/amplitude-radar
install -d -o "$deploy_user" -g "$deploy_user" -m 0700 /var/lib/amplitude-radar
install -d -o "$deploy_user" -g "$deploy_user" -m 0700 /var/backups/amplitude-radar
install -d -o "$deploy_user" -g "$deploy_user" -m 0700 "/home/$deploy_user/.ssh"

key_line="$(sed -n '1p' "$authorized_key_file")"
[[ "$key_line" =~ ^(ssh-ed25519|sk-ssh-ed25519@openssh.com)[[:space:]][A-Za-z0-9+/=]+([[:space:]].*)?$ ]] || {
  printf '%s\n' "ERROR: deployment key must be an ed25519 OpenSSH public key" >&2
  exit 1
}
printf '%s %s\n' \
  'restrict,command="/opt/amplitude-radar/infra/scripts/ssh-deploy-gate.sh",no-agent-forwarding,no-port-forwarding,no-pty,no-user-rc,no-X11-forwarding' \
  "$key_line" >"/home/$deploy_user/.ssh/authorized_keys"
chown "$deploy_user:$deploy_user" "/home/$deploy_user/.ssh/authorized_keys"
chmod 0600 "/home/$deploy_user/.ssh/authorized_keys"

chown -R root:root "$repo_root"
chmod -R go-w "$repo_root"

printf '%s\n' \
  "Bootstrap complete." \
  "Next: install infra/ssh/sshd_config.d/60-amplitude-radar.conf.example as an sshd drop-in, validate with sshd -t, then reload SSH." \
  "Next: generate /etc/amplitude-radar/app.env with generate-env.sh as $deploy_user." \
  "Note: membership in the docker group is privileged; the forced command and protected GitHub environment are mandatory controls."
