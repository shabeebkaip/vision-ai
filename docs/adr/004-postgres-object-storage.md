# ADR 004: PostgreSQL plus S3-compatible object storage in the cloud

Status: accepted (2 Nov 2026)

**Decision.** Events, configuration and per-minute counts in PostgreSQL 16 (row-level security per
organisation); snapshots and clips in S3-compatible object storage with lifecycle rules.

**Why.** Relational data with strict tenant isolation fits PostgreSQL; clips are large blobs with
retention rules that object storage enforces cheaply. Both exist with every in-Kingdom cloud
provider and run locally in Docker for development (SeaweedFS, Apache-2.0; MinIO no longer publishes images).
