## What changed

<!-- State the user or operational outcome, not only implementation details. -->

## Evidence

- [ ] Tests added or updated
- [ ] CI is expected to pass
- [ ] Relevant docs/runbooks updated
- [ ] Screenshots, API examples, or metrics attached when behavior changed

## Risk and rollback

- [ ] No migration or data-shape change
- [ ] Migration is forward-compatible and has been tested against a backup
- [ ] Rollback image tag and trigger are documented below
- [ ] Security/privacy/LLM impact was assessed

Rollback plan:

<!-- Exact prior immutable image tag and verification steps. -->

## Reviewer checklist

- [ ] No secrets, credentials, private prompts, or user data were added
- [ ] Public-facing claims remain evidence-backed and attributable
- [ ] Background work is idempotent or has a documented recovery path
