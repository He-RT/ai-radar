# Reproducible OpenAPI export

FastAPI/Pydantic is the only OpenAPI source. Do not hand-edit or maintain a second OpenAPI document in this package.

Export a deterministic document from the repository root:

```sh
apps/api/.venv/bin/python packages/contracts/scripts/export_openapi.py \
  --output packages/contracts/openapi/api-0.1.0.json
```

The exporter sorts object keys, strips no schemas, and refuses to overwrite an existing file unless `--force` is supplied. The initial `api-0.1.0.json` release snapshot is checked in. Review every regenerated diff together with:

```sh
apps/api/.venv/bin/pytest -q tests/integration/test_api_contract.py
```

Release rules:

1. The filename follows the backend `info.version`; the contract major remains encoded by `schemas/vN/` and `routes/vN/`.
2. Commit an export only at a release boundary. Routine tests inspect `app.openapi()` directly, so generated files cannot hide drift.
3. Removing an operation or successful-response field, narrowing an enum, or changing field meaning is a breaking contract change.
4. Authentication/error additions and new optional response fields are reviewed as additive changes.
5. `/docs`, `/openapi.json`, and other documentation endpoints are deployment surfaces, not entries in the operation inventory.
