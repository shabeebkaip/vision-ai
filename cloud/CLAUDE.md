# cloud/ — local rules

FastAPI + PostgreSQL 16 backend (Phase 4). Read the root `CLAUDE.md` first.

- **Tenancy is two locks.** Every query filters on `organisation_id` (and on the member's sites via
  `OrgAccess.site_clause`), *and* PostgreSQL row-level security filters on `app.org_id`. Never
  remove either. A new customer-owned table gets an `organisation_id` column, composite foreign keys
  `(parent_id, organisation_id)`, an entry in `models.TENANT_TABLES` and a migration that applies
  the policy (`tenancy.policy_statements` shows the SQL). `test_every_customer_table_has_forced_rls`
  fails if you forget.
- **`system_session()` bypasses RLS.** Use it only for lookups that must happen before the tenant is
  known (credential and token lookups, enrolment) and for Code-Ox admin endpoints. Say why in a
  comment.
- **Return 404, not 403, for another organisation's ids** so ids do not leak.
- **Device API types**: `vision_shared.schemas` (Event, SiteConfig) are the contract. Device messages
  not yet in `shared/` live in `vision_cloud/contract.py` and are proposed in
  `docs/proposals/shared-device-api-schemas.md`. Do not edit `shared/` from a cloud-only change.
- **Migrations**: change `models.py`, then
  `uv run alembic -c cloud/alembic.ini revision --autogenerate -m "..."`, review it, and run the
  tests (`test_migration_matches_models` fails on drift). Never edit a released migration.
- **Secrets**: stream URLs and TOTP secrets are `EncryptedString`; one-time tokens are stored as
  SHA-256 only. Never return `Camera.stream_url` from a dashboard endpoint.
- **Errors**: raise `errors.APIError(status, code, message)`; the handler gives every response the
  same `{"error": {...}, "request_id"}` shape.
- **User-facing text** (emails) goes in `vision_cloud/i18n/en.json` and `ar.json`, same keys.
- Tests need PostgreSQL (`VISION_TEST_DATABASE_URL`, a non-superuser role with CREATEDB); they
  are skipped when none is reachable.
