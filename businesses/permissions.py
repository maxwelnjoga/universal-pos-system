from rest_framework.exceptions import PermissionDenied


# Permissions assigned to the existing built-in roles.
# These preserve the six roles already used by your frontend.

BUILT_IN_ROLE_PERMISSIONS = {
    "owner": {"*"},

    "admin": {"*"},

    "manager": {
        "dashboard.view",
        "sales.view",
        "sales.create",
        "inventory.view",
        "inventory.create",
        "inventory.edit",
        "purchasing.view",
        "purchasing.create",
        "purchasing.receive",
        "reports.view",
    },

    "cashier": {
        "dashboard.view",
        "sales.view",
        "sales.create",
    },

    "stock_manager": {
        "dashboard.view",
        "inventory.view",
        "inventory.create",
        "inventory.edit",
        "inventory.adjust",
        "purchasing.view",
        "purchasing.create",
        "purchasing.receive",
    },

    "accountant": {
        "dashboard.view",
        "sales.view",
        "reports.view",
    },
}


def has_business_permission(membership, permission_code):
    """
    Check whether a business membership has a particular permission.
    """

    if not membership or not membership.is_active:
        return False

    if not membership.business.is_active:
        return False

    # Business owners and admins have full business-level access.
    if membership.role in ["owner", "admin"]:
        return True

    # A custom role takes precedence when assigned.
    custom_role = membership.custom_role

    if custom_role:
        if not custom_role.is_active:
            return False

        return custom_role.role_permissions.filter(
            permission__code=permission_code
        ).exists()

    # Otherwise, use the built-in role permissions.
    allowed_permissions = BUILT_IN_ROLE_PERMISSIONS.get(
        membership.role,
        set(),
    )

    return (
        "*" in allowed_permissions
        or permission_code in allowed_permissions
    )


def require_business_permission(membership, permission_code):
    """
    Raise an error if the membership lacks the requested permission.
    """

    if not has_business_permission(
        membership,
        permission_code,
    ):
        raise PermissionDenied(
            "You do not have permission to perform this action."
        )