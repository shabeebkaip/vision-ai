"""Roles and what they may do (CLD-02).

Code-Ox admin is a flag on the user (`is_platform_admin`) and may do everything in every
organisation. Inside an organisation:

| Permission          | owner | manager | site_manager | viewer |
| ------------------- | ----- | ------- | ------------ | ------ |
| read                | yes   | yes     | own sites    | own sites (or all) |
| give feedback       | yes   | yes     | own sites    | no     |
| manage site config  | yes   | yes     | own sites    | no     |
| manage recipients   | yes   | yes     | own sites    | no     |
| invite users        | yes   | yes (not owners) | no  | no     |
| manage members      | yes   | no      | no           | no     |
| manage organisation | yes   | no      | no           | no     |

"Own sites": a membership with `all_sites = false` is limited to the sites in `membership_sites`.
"""

from __future__ import annotations

from enum import Enum

from vision_cloud.models import Role


class Permission(str, Enum):
    READ = "read"
    FEEDBACK = "feedback"
    MANAGE_SITE_CONFIG = "manage_site_config"
    MANAGE_RECIPIENTS = "manage_recipients"
    INVITE_USERS = "invite_users"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_ORGANISATION = "manage_organisation"


_ALL = frozenset(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: _ALL,
    Role.MANAGER: frozenset(
        {
            Permission.READ,
            Permission.FEEDBACK,
            Permission.MANAGE_SITE_CONFIG,
            Permission.MANAGE_RECIPIENTS,
            Permission.INVITE_USERS,
        }
    ),
    Role.SITE_MANAGER: frozenset(
        {
            Permission.READ,
            Permission.FEEDBACK,
            Permission.MANAGE_SITE_CONFIG,
            Permission.MANAGE_RECIPIENTS,
        }
    ),
    Role.VIEWER: frozenset({Permission.READ}),
}

# Roles each role may hand out through an invitation.
INVITABLE_ROLES: dict[Role, frozenset[Role]] = {
    Role.OWNER: frozenset(Role),
    Role.MANAGER: frozenset({Role.MANAGER, Role.SITE_MANAGER, Role.VIEWER}),
    Role.SITE_MANAGER: frozenset(),
    Role.VIEWER: frozenset(),
}


def role_allows(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
