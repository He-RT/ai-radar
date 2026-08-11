# Secret leak

Treat a suspected leak as real until rotation and audit prove otherwise. This includes a committed key, CI log exposure, browser capture, public issue attachment, copied environment file, compromised VPS, or an exposed deployment key.

## First 15 minutes

1. Stop further exposure: redact/delete public material where possible, cancel affected workflows, restrict repository access if needed, and disable compromised integrations.
2. Revoke or rotate the exposed credential at its issuer. Do not wait for investigation.
3. Identify blast radius: credential type, first exposure time, repositories/logs/artifacts, calls made, data accessible, and dependent credentials.
4. Preserve private forensic evidence and command history. Do not paste the secret into tickets or chat.

## Rotation order

Rotate from the outside in:

1. GitHub deploy key and production-environment secrets.
2. LLM/provider keys and any data-source credentials.
3. Caddy/DNS or cloud credentials if exposed.
4. PostgreSQL password, Valkey password, MinIO root password, application secret key, and Grafana password.
5. Session/signing keys, webhooks, and user-facing tokens affected by the application secret rotation.

After changing /etc/amplitude-radar/app.env, deploy an approved release version and
its three published image digests through the deployment workflow. Validate that old
credentials fail and new credentials work. A key in Git history remains compromised
even after deletion; use repository secret scanning and follow the hosting provider's
history-remediation process.

## Special cases

- If the SSH deploy private key leaks, remove its public key from authorized_keys, create a new keypair, update the GitHub environment, and verify the old key is denied.
- If a database, MinIO, or application secret leaks, evaluate whether data access occurred and whether user sessions or signed URLs need invalidation.
- If a secret appeared in a Docker image or build layer, treat every published copy and cache as exposed; rebuild without the secret and use a new tag.

## Closeout

Document exposure window, impacted systems/data, rotation timestamps, validation results, and preventive control. Add a regression guard such as secret scanning, least-privilege credential scope, runtime secret injection, or sanitized logging.
