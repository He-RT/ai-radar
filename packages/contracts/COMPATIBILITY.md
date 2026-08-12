# Cross-layer compatibility notes

Observed against `apps/api` and `apps/web` on 2026-08-12. The table records the current transport boundary; it is not an alternate ruleset.

| Area | API | Web | Contract consequence |
|---|---|---|---|
| Event identity and versions | Public response carries UUID `id`, `versions[]`, and `public_version`; briefings embed a schema-v1 envelope that redundantly pins `event_id` and `public_version` | The server adapter preserves `id` as `apiId`; briefing pages render the embedded event rather than joining current facts | `event_ids` remains an ordered compatibility index, while later event changes cannot alter historical briefing content. |
| Confidence | Event `confidence_grade` and per-claim numeric confidence are public facts | The adapter localizes the API grade/status without recalculating either | Presentation cannot silently promote confidence. |
| Evidence | Claims reference `evidence[]` by UUID | The event ledger resolves each claim to the API evidence URL and locator | Broken claim-to-evidence references fail the runtime validator before render. |
| Knowledge cutoff | Radar exposes `knowledge_cutoff`; briefing exposes `cutoff_at`, separately from `generated_at` | Radar and briefing pages render the returned cutoff | The web no longer owns a hard-coded publication clock. |
| Personalization | `PublicFactEnvelope` and `PersonalizedRadarView` define the immutable fact/lens boundary | `/for-you` selects from the shared server dataset and adds presentation ordering only | A dedicated personalized API operation is still a later slice; contract tests already forbid fact mutation. |
| Source of truth | API exposes evidence-backed, versioned public events | Production requires `RADAR_DATA_MODE=api`; fixture mode is development-only and visibly labeled | API failures or contract drift fail closed instead of falling back to demo facts. |

Radar, briefing, and coverage have named OpenAPI response models; timestamps satisfy `updated_at <= knowledge_cutoff <= generated_at`; each briefing envelope matches its ordered ID/version pins and cutoff; every key claim resolves supporting evidence; and every event action link resolves or degrades to the action index. These are protected by runtime validators, cross-layer route tests, and the checked-in OpenAPI drift test.

`RadarEventProjection` remains a localized presentation projection, never a second fact source. The fixture in `apps/web/data/radar.ts` exists solely for explicit non-production development mode.
