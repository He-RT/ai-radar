# 震幅 AI Radar API

Evidence-first FastAPI backend for a structured AI intelligence radar. The API can run immediately
against a coherent synthetic repository and has a PostgreSQL-oriented SQLAlchemy 2/Alembic schema
for production persistence.

## Run locally

Python 3.13 is required.

```bash
uv sync --extra test
uv run uvicorn zhenfu_api.main:app --reload
```

Then open `http://localhost:8000/docs`, `http://localhost:8000/openapi.json`, or
`http://localhost:8000/health`. The demo briefing date is `2026-08-12`.

Run the tests with:

```bash
uv run pytest
```

## Public API

- `GET /api/v1/radar` — ranked headline events, actions, latest briefing, and coverage
- `GET /api/v1/events` and `GET /api/v1/events/{slug}` — paginated events and evidence detail
- `GET /api/v1/actions` — executable action recipes
- `GET /api/v1/briefings/{date}` — immutable daily briefing snapshot
- `GET /api/v1/corrections` — public correction ledger
- `GET /api/v1/coverage` — category, source-tier, and claim-evidence coverage
- `GET /api/v1/search?q=...` — deterministic keyword search
- `POST /api/v1/ask` — local extractive answer with event citations; no network or LLM calls

Identity endpoints are `POST /api/v1/auth/register`, `POST /api/v1/auth/login`,
`GET /api/v1/users/me`, and `GET/POST /api/v1/teams`. Passwords use Argon2id. Access tokens are
opaque random values; only their SHA-256 digests are retained. Development uses a process-local
repository, while production fails closed unless `SqlIdentityRepository` is injected. SQL identity
persists users, roles, sessions, teams, and memberships; public registration can only create the
`user` role.

## Editorial invariants

The domain layer owns publication rules rather than HTTP handlers or persistence models:

- every key claim must cite at least one evidence object;
- every cited evidence ID must exist on the event;
- every published briefing stores ordered, schema-versioned event envelopes containing the complete
  public event, evidence, score, and event-version payload present at its cutoff;
- automatic publication requires two distinct supporting source items, key-claim confidence of at
  least 0.72, a deterministic score of at least 65, and risk below `high`;
- deterministic score `radar-score-v1` is the weighted sum of relevance (30%), evidence quality
  (25%), source independence (20%), recency (15%), and actionability (10%); component rounding uses
  decimal half-up arithmetic;
- URL canonicalization removes fragments/tracking parameters and sorts remaining query parameters;
  normalized content hashes and a weighted title/entity/time/source score support deduplication and
  event clustering.

The `POST /api/v1/internal/events/{slug}/publication-check` endpoint exposes the same domain gate
only to persisted `editor` or `admin` roles; a normal registered user receives `403`.

## Persistence and production configuration

Apply the initial schema with:

```bash
RADAR_DATABASE_URL='postgresql+psycopg://user:password@host/radar' \
  uv run alembic upgrade head
```

The schema includes sources, source items, evidence, claims, events and versions, score snapshots,
action recipes, briefing snapshots, corrections, users, teams, watches, outbox messages, and
idempotent job receipts. Revision `0002` adds persistent roles and hashed access sessions without
rewriting `0001`. Forward-only revision `0003` adds embedded briefing-event payloads; legacy
ID-only rows remain stored but fail closed because current events cannot truthfully reconstruct
history. Foreign keys use conservative delete policies, and migration/autogenerate uses deterministic
naming conventions.

Configuration uses `RADAR_`-prefixed environment variables. Production boot validation requires:

```text
RADAR_ENVIRONMENT=production
RADAR_DATABASE_URL=postgresql+psycopg://...
RADAR_PUBLIC_BASE_URL=https://radar.example.com
RADAR_SYNTHETIC_REPOSITORY=false
RADAR_CORS_ORIGINS=["https://app.example.com"]
```

When synthetic data is disabled, `create_app` deliberately requires persistent fact and identity
repositories; it will not silently serve demo data or in-memory accounts. Deploy behind HTTPS, keep
credentials in the server secret file, rate-limit identity and ask endpoints at the edge, and grant
the runtime database role no schema-migration permissions.

## Architecture

`domain/` contains Pydantic entities and editorial services. `catalog.py` validates the curated
500-source registry and deterministically selects due work. `repository.py` provides explicit test
fixtures behind a protocol. `adapters/` defines the answer boundary and extractive test adapter.
`persistence/` contains SQL repositories, tables, and engine helpers. `api.py` composes these through
constructor injection, keeping tests fast and external-service-free.
