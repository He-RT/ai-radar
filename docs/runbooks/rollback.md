# Rollback

## Decide whether rollback is safe

An image rollback is safe only when the new database migration is compatible with the prior image. For destructive or irreversible migrations, stop the harmful feature and prepare a forward fix or a tested database restore; do not blindly deploy an older image.

Record:

- current and target release versions and web/API/worker digest sets;
- migration versions;
- user/data impact;
- backup timestamp;
- reason and decision owner.

## Application rollback

1. Pause publishing and non-essential intake if incorrect content or duplicate jobs are being generated.
2. In the protected Deploy production workflow, enter the last known-good release
   version, exact source SHA, and exact web, API, and worker digests from its release
   manifest or prior `/var/lib/amplitude-radar/release.env` record. For a legacy state
   record without `SOURCE_SHA`, recover the SHA from the approved release manifest.
   If checkout HEAD differs, perform the release runbook's controlled, signature- and
   protected-main-verified checkout update before retrying the rollback deployment.
3. Watch the forced-command output until web, api, and Caddy health checks pass.
4. Verify public reads, API readiness, worker stability, queue age, and one safe end-to-end job.
5. Keep the failed image and logs available for investigation; do not prune it during the incident.

The deploy script always reruns the migration command. Therefore migrations must be idempotent and forward-compatible. If the old image cannot operate against the migrated schema, immediately stop the rollback, return to the current healthy image, and follow the forward-fix path.

## Data rollback

Use [backup and restore](backup-restore.md) only for confirmed data corruption, unauthorized modification, or an explicitly approved recovery point objective breach. A database restore replaces live data and can delete MinIO objects absent from the chosen archive.

## Closeout

- Keep enhanced monitoring for at least one normal ingestion cycle.
- Add a regression test, migration guard, or release check that would have caught the issue.
- Publish a correction when any public content or score was affected.
- Update the rollback digest set and release notes with the final state.
