"""Row-level security policies (CLD-02, the second lock).

Applied by the initial migration. All tables use FORCE ROW LEVEL SECURITY so the policies apply to
the table owner too; the API role must not be a superuser or have BYPASSRLS.
"""

from __future__ import annotations

from vision_cloud.models import TENANT_TABLES, USER_TABLES

ORG = "NULLIF(current_setting('app.org_id', true), '')::uuid"
USR = "NULLIF(current_setting('app.user_id', true), '')::uuid"
BYPASS = "coalesce(current_setting('app.bypass_rls', true), '') = 'on'"


def _enable(table: str) -> list[str]:
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
    ]


def policy_statements() -> list[str]:
    sql: list[str] = []
    for table in TENANT_TABLES:
        cond = f"({BYPASS} OR organisation_id = {ORG})"
        sql += _enable(table)
        sql.append(f"CREATE POLICY tenant_isolation ON {table} USING {cond} WITH CHECK {cond}")

    # A signed-in user may list their own memberships in every organisation (organisation picker).
    sql.append(f"CREATE POLICY own_memberships ON memberships FOR SELECT USING (user_id = {USR})")

    for table in USER_TABLES:
        cond = f"({BYPASS} OR user_id = {USR})"
        sql += _enable(table)
        sql.append(f"CREATE POLICY own_rows ON {table} USING {cond} WITH CHECK {cond}")

    sql += _enable("organisations")
    sql.append(
        "CREATE POLICY tenant_isolation ON organisations "
        f"USING ({BYPASS} OR id = {ORG} OR id IN "
        f"(SELECT organisation_id FROM memberships WHERE user_id = {USR})) "
        f"WITH CHECK ({BYPASS} OR id = {ORG})"
    )

    # Users are global; a user row is visible to itself and to members of a shared organisation.
    sql += _enable("users")
    sql.append(
        "CREATE POLICY visible_users ON users "
        f"USING ({BYPASS} OR id = {USR} OR id IN "
        f"(SELECT user_id FROM memberships WHERE organisation_id = {ORG})) "
        f"WITH CHECK ({BYPASS} OR id = {USR})"
    )
    return sql


def drop_statements() -> list[str]:
    sql = [
        "DROP POLICY IF EXISTS visible_users ON users",
        "DROP POLICY IF EXISTS tenant_isolation ON organisations",
        "DROP POLICY IF EXISTS own_memberships ON memberships",
    ]
    sql += [f"DROP POLICY IF EXISTS own_rows ON {t}" for t in USER_TABLES]
    sql += [f"DROP POLICY IF EXISTS tenant_isolation ON {t}" for t in TENANT_TABLES]
    for table in (*TENANT_TABLES, *USER_TABLES, "organisations", "users"):
        sql.append(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        sql.append(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    return sql
