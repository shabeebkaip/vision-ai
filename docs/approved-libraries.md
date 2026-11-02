# Approved libraries

Only libraries listed here may be added (root `CLAUDE.md`, rule 1). Add a row in the same pull
request as the dependency. CI's licence guard (`scripts/licence_check.py`) blocks copyleft and
banned packages regardless. The full seed list for every component is REP-08; this file starts
with the cloud backend.

## Cloud (`cloud/`)

| Library | Licence | Why |
| --- | --- | --- |
| fastapi | MIT | HTTP API, OpenAPI generation for the dashboard client |
| uvicorn | BSD-3-Clause | ASGI server |
| sqlalchemy | MIT | ORM and query builder |
| alembic | MIT | Database migrations |
| psycopg (binary) | LGPL-3.0 (dynamically linked) | PostgreSQL driver |
| pydantic, pydantic-settings | MIT | Schemas and settings (shared with edge) |
| structlog | MIT / Apache-2.0 | Structured JSON logs |
| redis | MIT | Shared rate-limit buckets; job queue later (CLD-17) |
| boto3 | Apache-2.0 | S3-compatible storage, pre-signed upload forms |
| argon2-cffi | MIT | argon2id password hashing (ADR 0001) |
| pyjwt | MIT | Access tokens (ADR 0001) |
| pyotp | MIT | Authenticator-app codes (ADR 0001) |
| cryptography | Apache-2.0 / BSD | Fernet encryption of stream URLs and 2FA secrets |
