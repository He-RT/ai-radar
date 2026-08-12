# Backup and restore

Run `bash infra/scripts/test-restore-drill.sh` from a Docker-capable workstation to
rehearse the production destructive PostgreSQL and MinIO data-plane restore in an
isolated Compose project. The drill writes original probes, backs them up, mutates both
stores, applies the shared production data-restore primitive, and verifies the original
values through the least-privileged application account. Its deliberately dummy
application-image digests mean it does not cover application migration, service startup,
or readiness; those remain part of a separately provisioned full recovery exercise.

The workstation also needs `flock`; Ubuntu provides it through `util-linux`. On macOS,
install the same tools with `brew install util-linux`; the drill resolves both Apple
Silicon and Intel Homebrew prefixes automatically.

## Backup contract

backup.sh creates a gzip archive containing:

- a PostgreSQL custom-format pg_dump;
- a mirror of the private MinIO application bucket;
- metadata with UTC timestamp and release version; the active release-state file
  separately holds the validated source SHA and web/API/worker digest set used to
  render Compose (the loader also safely accepts pre-binding four-line state files);
- SHA-256 checksums for all archived files.

It intentionally does not back up the runtime environment file or GitHub credentials. Keep the environment file in a separate approved secret-management backup process. Valkey is treated as recoverable queue/cache state and is not restored.

## Schedule and retention

Install the supplied systemd service and timer through the VPS bootstrap runbook. The default schedule is 02:30 UTC with up to 15 minutes of jitter and a default retention of 14 days.

Run an on-demand backup before every risky migration:

~~~sh
sudo -u radar-deploy bash /opt/amplitude-radar/infra/scripts/backup.sh
~~~

To use an encrypted off-host copy, upload the completed archive to an approved backup destination after backup.sh succeeds. Verify checksum and retention remotely. The baseline archive is locally encrypted only to the extent provided by the host volume; enable provider disk encryption and off-host encrypted copies.

## Monthly recovery exercise

At least monthly, run the data-plane drill with a recent archive in a disposable,
isolated environment using a separate environment file and Compose project. Validate:

- archive checksum verification;
- PostgreSQL data restoration, including event and evidence counts;
- MinIO object retrieval;
- documented recovery time and recovery-point age.

Periodically perform a separately provisioned full recovery exercise to validate current
application migrations, selected vector search results, service readiness, and public
traffic restoration.

Do not run a test restore against the production project name.

## Production restore

A production restore is destructive and needs incident commander approval.

1. Choose and checksum-verify the exact archive.
2. Record the required confirmation phrase: RESTORE followed by the archive filename.
3. Inform stakeholders that public traffic and workers will be stopped.
4. Run:

~~~sh
sudo -u radar-deploy bash /opt/amplitude-radar/infra/scripts/restore.sh \
  --archive /var/backups/amplitude-radar/ARCHIVE \
  --confirm "RESTORE ARCHIVE"
~~~

5. The script validates paths and checksums, stops Caddy/web/api/workers, replaces PostgreSQL, mirrors MinIO with deletion enabled, applies current migrations, restarts services, and waits for health checks.
6. Verify counts, source links, correction records, queued work policy, and public readiness before reopening intake.

Use --dry-run first to validate an archive without stopping services. If restore fails, application containers remain stopped on purpose; preserve logs and escalate rather than exposing a partially restored system.
