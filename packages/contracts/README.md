# `@zhenfu/contracts`

This package is the versioned boundary between the FastAPI domain responses and the Next.js route projections. It contains declarations and invariant checks only; ranking, confidence aggregation, localization, and personalization remain in their owning application layers.

## Versioning

- The package uses semantic versioning. Breaking field removals, renames, enum narrowing, or meaning changes require a new major version and a new `schemas/vN/` plus `routes/vN/` directory.
- Additive optional fields and new routes are minor changes. Documentation or validator corrections that do not change accepted data are patches.
- `schemas/v1/public-facts.schema.json` is the canonical JSON Schema for API-shaped public facts. `src/index.d.ts` is the TypeScript view of that schema. `openapi/api-0.1.0.json` is a generated release snapshot; FastAPI remains its only source.
- A response may use API version `0.1.0` while implementing contract major `v1`; these versions measure different things and must not be silently coupled.

## Public facts and personalization

`PublicFactEnvelope` owns the event, evidence, public confidence grade, claim confidence, event versions, and `knowledge_cutoff`. A personalized view may reorder or select events and add a `lens`, but its `fact` objects and cutoff must remain byte-for-byte equivalent after canonical selection. `validatePersonalizationBoundary` enforces that rule.

`generated_at` describes response generation and is not automatically a knowledge cutoff. Producers must supply the explicit, source-derived `knowledge_cutoff` required by `RadarResponse` and `PublicFactEnvelope`.

## Runtime use

```js
import {
  validatePublicEvent,
  validateRadarResponse,
  validatePersonalizationBoundary,
} from "@zhenfu/contracts";

const result = validatePublicEvent(payload);
if (!result.ok) throw new TypeError(JSON.stringify(result.errors));
```

The dependency-free validator covers the public endpoint wire shapes plus cross-layer invariants that JSON Schema cannot express cleanly: key claims require resolvable evidence, published facts require a version record, cutoff ordering is coherent, and personalized views cannot alter public facts. It is deliberately not a generic JSON Schema engine and does not implement publication scoring, confidence grading, ranking, or recommendation logic.

## Verification

From the repository root:

```sh
node --test tests/integration/contracts-runtime.test.mjs tests/integration/web-route-contract.test.mjs
apps/api/.venv/bin/pytest -q tests/integration/test_api_contract.py
apps/web/node_modules/.bin/tsc -p tests/integration/tsconfig.contracts.json
```

See `openapi/README.md` for reproducible OpenAPI export and compatibility checks.
