#!/bin/sh
# Development only: creates the role the API connects as. It owns nothing and has no BYPASSRLS,
# so PostgreSQL row-level security (migration 0002) applies to every API query.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE vision_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '${VISION_DEV_DB_APP_PASSWORD:-vision-app-dev}';
GRANT USAGE ON SCHEMA public TO vision_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO vision_app;
EOSQL
