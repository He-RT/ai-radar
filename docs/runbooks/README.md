# Operations runbooks

These runbooks assume the single-VPS Compose baseline in infra. Use UTC for server logs and incident timestamps; communicate user-facing times in Asia/Shanghai when appropriate.

## Emergency order

1. Protect people, credentials, and data before availability.
2. Record the current release version, the web/API/worker digest set, incident start time, and evidence links.
3. Contain the failing path with the smallest reversible change.
4. Preserve facts and audit trails. Do not silently rewrite published content or delete logs needed for investigation.
5. Recover, verify through an independent path, and document follow-up work.

## Runbook index

- [VPS bootstrap and restricted SSH](vps-bootstrap.md)
- [Release](release.md)
- [Rollback](rollback.md)
- [Backup and restore](backup-restore.md)
- [Observability](observability.md)
- [Content incident](content-incident.md)
- [LLM failure](llm-failure.md)
- [Queue backlog](queue-backlog.md)
- [Secret leak](secret-leak.md)

## On-call evidence standard

For every material incident, retain:

- UTC timestamps and the exact image digests.
- Affected event IDs, job IDs, source URLs, and user impact count when known.
- Before/after screenshots or API responses with personal data redacted.
- Commands run and their exit status.
- The owner of the next update and the decision deadline.

Never paste secrets, raw user content, private prompts, or unredacted logs into a public GitHub issue.
