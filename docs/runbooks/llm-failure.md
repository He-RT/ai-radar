# LLM failure

LLM work is assistive. It must not become the sole source of facts, overwrite evidence, or block essential read paths.

## Detect and classify

Classify the failure before acting:

- provider outage, timeout, rate limit, quota, or regional routing issue;
- malformed/tool-call output or schema validation failure;
- hallucinated or unsupported claim;
- prompt injection or unsafe source content;
- unexpected cost, token growth, or repeated retries;
- privacy, data-residency, or key authorization problem.

Capture request/job IDs and provider response class, but not full sensitive prompts or keys.

## Immediate containment

1. Open the circuit breaker for the failing model/provider path.
2. Stop automatic publish, autonomous actions, and unbounded retries for affected job types.
3. Preserve source evidence and mark summaries as pending rather than treating an LLM failure as a negative fact.
4. Serve cached verified content and clear degraded-mode messaging where applicable.
5. Set a bounded retry delay with jitter; do not retry synchronously in web requests.

## Recovery choices

- For an outage, wait for the provider status to recover, then process a small canary batch.
- For schema/output failures, reject invalid output, improve validation, and re-run only idempotent jobs.
- For unsupported claims, quarantine the output, correct affected records, and strengthen claim-to-evidence checks.
- For prompt injection, block the source/item, review sanitization, and rotate credentials if any secret may have been exposed.
- For cost anomalies, set a per-job token/cost cap and require approval before changing model or context limits.

A fallback model requires the same privacy, quality, evaluation, and approval checks as the primary model. Do not silently change models for high-impact content.

## Exit criteria

Restore normal processing only after a canary batch meets factuality, schema, latency, and cost thresholds; queue age is falling; and no duplicate or stale publications appear. Document the provider/model version and any changed policy.
