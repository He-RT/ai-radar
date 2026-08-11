# VPS bootstrap and restricted SSH

## Scope and prerequisites

Use one supported Ubuntu VPS with 4 vCPU, 16 GB RAM, a static public IP, and a DNS name such as radar.example.com. Install Docker Engine and the Docker Compose plugin from the official Docker documentation before continuing. Keep an existing console or independent administrator SSH session open during any SSH configuration change.

The only public firewall rules should be TCP 80, TCP 443, UDP 443, and the administration SSH port. PostgreSQL, Valkey, MinIO, Mailpit, Prometheus, Grafana, and Loki must not have public firewall rules.

## Prepare the host

1. Create the repository checkout at /opt/amplitude-radar from a reviewed, signature-
   verified commit that is an ancestor of protected `origin/main`.
2. Create an ed25519 deployment keypair on a controlled administrator machine. Store the private key only as the GitHub production-environment secret DEPLOY_SSH_PRIVATE_KEY.
3. Obtain the VPS host key fingerprint through a trusted channel. Store the complete known_hosts line as DEPLOY_SSH_KNOWN_HOSTS; do not generate it inside a CI workflow.
4. Place the public half temporarily on the VPS with mode 0600, then run:

~~~sh
sudo bash /opt/amplitude-radar/infra/scripts/bootstrap-vps.sh \
  --repo-root /opt/amplitude-radar \
  --authorized-key-file /secure/path/github-actions-deploy.pub
~~~

The script creates radar-deploy, locks password login, creates state and backup directories, installs an authorized key with a forced command, and makes the checkout root-owned. Docker group membership is effectively privileged on a Docker host; the forced command and the protected GitHub environment are compensating controls.

5. Install the SSH restriction drop-in, validate it, and reload SSH.

~~~sh
sudo install -m 0644 \
  /opt/amplitude-radar/infra/ssh/sshd_config.d/60-amplitude-radar.conf.example \
  /etc/ssh/sshd_config.d/60-amplitude-radar.conf
sudo sshd -t
sudo systemctl reload ssh
~~~

6. Generate the runtime environment. This writes secrets only to a mode-0600 file outside the repository.

~~~sh
sudo -u radar-deploy bash /opt/amplitude-radar/infra/scripts/generate-env.sh \
  --domain radar.example.com \
  --email ops@example.com \
  --ghcr-owner example-org
sudo -u radar-deploy editor /etc/amplitude-radar/app.env
~~~

Replace both RADAR_LLM_API_KEY and RADAR_LLM_MODEL placeholders before the first
production deployment. Production configuration fails closed while either placeholder
remains. The production deployment workflow supplies application image digest pins;
copy those three digests only from the published release-job summary or its manifests.

## GitHub production environment

Create a GitHub environment named production and require review by at least two maintainers. Add only these environment secrets:

- DEPLOY_SSH_PRIVATE_KEY
- DEPLOY_SSH_KNOWN_HOSTS
- DEPLOY_SSH_HOST
- DEPLOY_SSH_PORT

Do not add production application secrets to GitHub. The deployment workflow only
sends a validated release version, exact 40-hex source SHA, and three full image
digests to the forced SSH command. It never checks out or executes pull-request code, and it has no
pull_request_target trigger.

The root-owned checkout is deliberately not updated by `radar-deploy`. Before each new
source deployment, an administrator must follow the controlled checkout update in the
[release runbook](release.md#controlled-vps-checkout-update): fetch through the approved
remote, verify the commit or signed tag, require the exact source SHA to be an ancestor
of protected `origin/main`, detach at that SHA, restore root ownership and non-writable
group/other modes, and only then rerun the protected deployment.

## Backups and observability

Install and enable the backup timer:

~~~sh
sudo install -m 0644 /opt/amplitude-radar/infra/systemd/amplitude-radar-backup.service /etc/systemd/system/
sudo install -m 0644 /opt/amplitude-radar/infra/systemd/amplitude-radar-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now amplitude-radar-backup.timer
systemctl list-timers amplitude-radar-backup.timer
~~~

Grafana and Prometheus are loopback-only. Access them with an administrator SSH tunnel, never by adding public port rules.

## Acceptance checks

- Run deploy.sh with `--dry-run` and a complete version/source-SHA/digest set as
  radar-deploy.
- Verify the action key cannot start a shell: an SSH command other than the fixed
  `deploy --version VERSION --source-sha SOURCE_SHA --web-image-digest DIGEST --api-image-digest DIGEST --worker-image-digest DIGEST` form must be denied.
- Verify the public hostname reaches Caddy over HTTPS and no data-service port is visible from another host.
- Verify a backup archive is created and can be validated with restore.sh --dry-run.
- Record the host key fingerprint, firewall rules, image digests, and first backup location in the operations record.
