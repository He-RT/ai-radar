# Content incident

Use this runbook for a false or materially misleading claim, incorrect confidence or blast-radius score, missing attribution, duplicate event, copyright complaint, privacy exposure, or unsafe action recommendation.

## Contain within 15 minutes

1. Assign an incident owner and record UTC start time.
2. Stop automated publishing for the affected source, event, storyline, or action recipe. Keep discovery evidence intact.
3. If there is risk of personal harm, financial/legal reliance, or privacy exposure, remove public access immediately and escalate to the incident commander.
4. Preserve the prior public snapshot, source items, model output, editor decision, and audit trail. Do not silently edit history.
5. Determine whether the error is isolated, propagated to briefs, personalized explanations, alerts, search, or exported API data.

## Correct

- Re-check the original source and at least one independent source when available.
- State precisely what was wrong, what changed, why it changed, and which users/pages/snapshots were affected.
- Correct the atomic claim and event record, then issue a visible correction tied to the old version.
- Recompute only derived scores and recommendations that depend on the changed claim.
- If a source right or privacy issue is confirmed, remove or redact only the required material while retaining a non-sensitive audit record.

## Recover

Resume the paused pipeline only after a second editor verifies the correction and a test item passes the same guardrails. Review queue retries so the incident is not republished from a stale job. If an LLM-generated summary contributed, follow [LLM failure](llm-failure.md) as well.

## Closeout

Publish a brief correction for any externally visible material error. Track time-to-containment, total exposure, source of failure, and the durable control added: source rule, schema validation, editor review, duplicate detection, rights check, or model prompt/evaluation.
