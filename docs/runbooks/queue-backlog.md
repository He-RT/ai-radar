# Queue backlog

## Trigger

Investigate when critical-job oldest age exceeds 10 minutes, any queue exceeds normal capacity for 15 minutes, failure rate exceeds 2 percent, or a worker restarts repeatedly. Page when critical-job oldest age exceeds 30 minutes.

## Triage

1. Record queue depth, oldest age, throughput, retry count, dead-letter count, worker image digest, and recent deployment time.
2. Identify whether producers, consumers, Valkey, PostgreSQL, MinIO, or the LLM provider are limiting throughput.
3. Check idempotency keys before replaying work. Never bulk-retry a queue without knowing whether completed jobs can run twice.
4. Pause non-essential producers first. Preserve high-priority correction, security, and manual-review work.
5. Inspect a small sample of failures with secrets and private content redacted.

## Recover safely

On the 4 vCPU / 16 GB baseline, start with one ingest and one enrichment worker. Scale only one worker type by one replica after confirming CPU, memory, database connection, provider rate limit, and queue throughput headroom. Stop scaling if host free memory falls below 1 GiB, database latency rises materially, or failure rate increases.

Use a dead-letter queue for jobs that exceed a bounded retry count. Fix the root cause, replay a small ordered canary, verify idempotent outcomes, then increase throughput gradually. Do not delete queued jobs merely to make graphs look healthy.

## Verify and prevent recurrence

Confirm oldest age is declining, error rate is normal, duplicate-event rate has not increased, and high-priority work completed. Record whether the cause was deployment, provider, source burst, schema migration, or bad payload. Add capacity limits, backpressure, timeout, rate-limit, or retry-policy tests as appropriate.
