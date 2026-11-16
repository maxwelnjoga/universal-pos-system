from django.http import JsonResponse
from django.contrib.auth import get_user_model
from django.db import transaction

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    Membership,
    Branch,
    BranchAssignment,
    BusinessRole,
)


MANAGER_ROLES = {"owner", "admin"}

VALID_ROLES = {
    code for code, _ in Membership.ROLE_CHOICES
}


# ---------------------------------------------------------------------
# Business and branch retrieval
# ---------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_businesses(request):
    """
    Return the active businesses belonging to the logged-in user.
    """

    memberships = (
        Membership.objects
        .filter(
            user=request.user,
            is_active=True,
            business__is_active=True,
        )
        .select_related("business")
        .order_by("business__name")
    )

    businesses = [
        {
            "id": str(membership.business_id),
            "name": membership.business.name,
            "role": membership.role,
            "currency": membership.business.currency,
        }
        for membership in memberships
    ]

    return JsonResponse({"results": businesses})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_branches(request):
    """
    Return active branches the user is permitted to access.
    """

    business_id = request.GET.get("business_id")

    if not business_id:
        return JsonResponse(
            {"detail": "business_id is required."},
            status=400,
        )

    membership = (
        Membership.objects
        .filter(
            user=request.user,
            business_id=business_id,
            is_active=True,
            business__is_active=True,
        )
        .select_related("business")
        .first()
    )

    if membership is None:
        return JsonResponse(
            {"detail": "You do not have access to this business."},
            status=403,
        )

    branches = Branch.objects.filter(
        business=membership.business,
        is_active=True,
    )

    if membership.role not in {"owner", "admin"}:
        assigned_branch_ids = membership.staff_assignment.values_list(
            "branch_id",
            flat=True,
        )
        branches = branches.filter(
            id__in=assigned_branch_ids
        )

    branches = branches.order_by("name")

    results = [
        {
            "id": str(branch.id),
            "name": branch.name,
            "code": branch.code,
        }
        for branch in branches
    ]

    return JsonResponse({"results": results})


# ---------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------

def _get_membership(request, business_id):
    return (
        Membership.objects
        .filter(
            user=request.user,
            business_id=business_id,
            is_active=True,
            business__is_active=True,
        )
        .select_related("business")
        .first()
    )


def _business_payload(business):
    return {
        "id": str(business.id),
        "name": business.name,
        "industry": business.industry,
        "currency": business.currency,
        "tax_rate": str(business.tax_rate),
        "is_active": business.is_active,
    }


def _employee_payload(membership):
    user = membership.user

    full_name = (
        f"{user.first_name} {user.last_name}"
    ).strip()

    branches = [
        {
            "id": str(assignment.branch_id),
            "name": assignment.branch.name,
        }
        for assignment in (
            membership.staff_assignment
            .select_related("branch")
            .all()
        )
    ]

    custom_role = getattr(
        membership,
        "custom_role",
        None,
    )

    return {
        "membership_id": str(membership.id),
        "user_id": str(user.pk),
        "username": user.username,
        "name": full_name or user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "phone_number": getattr(
            user,
            "phone_number",
            "",
        ),
        "role": membership.role,
        "custom_role_id": (
            str(custom_role.id)
            if custom_role else None
        ),
        "custom_role_name": (
            custom_role.name
            if custom_role else None
        ),
        "is_active": membership.is_active,
        "branches": branches,
    }


def _validate_branch_ids(branch_ids, business_id):
    if not isinstance(branch_ids, list):
        return None, {
            "branch_ids": "Expected a list of branch IDs."
        }

    branches = list(
        Branch.objects.filter(
            id__in=branch_ids,
            business_id=business_id,
            is_active=True,
        )
    )

    if len(branches) != len(set(branch_ids)):
        return None, {
            "branch_ids": "One or more branches are invalid."
        }

    return branches, None


def _validate_custom_role(custom_role_id, business_id):
    if not custom_role_id:
        return None, None

    custom_role = BusinessRole.objects.filter(
        id=custom_role_id,
        business_id=business_id,
        is_active=True,
    ).first()

    if custom_role is None:
        return None, {
            "custom_role_id": (
                "Invalid custom role for this business."
            )
        }

    return custom_role, None


# ---------------------------------------------------------------------
# Business settings
# ---------------------------------------------------------------------

@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def business_detail(request, business_id):

    membership = _get_membership(
        request,
        business_id,
    )

    if membership is None:
        return Response(
            {
                "detail": (
                    "You do not have access to this business."
                )
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    business = membership.business

    if request.method == "PATCH":

        if membership.role not in MANAGER_ROLES:
            return Response(
                {
                    "detail": (
                        "Only owners and admins can change settings."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        for field in (
            "name",
            "industry",
            "currency",
            "tax_rate",
        ):
            if field in request.data:
                setattr(
                    business,
                    field,
                    request.data[field],
                )

        try:
            business.full_clean(
                exclude=["slug"]
            )
        except Exception as exc:
            messages = (
                getattr(exc, "message_dict", None)
                or {"detail": str(exc)}
            )

            return Response(
                messages,
                status=status.HTTP_400_BAD_REQUEST,
            )

        business.save()

    return Response(
        _business_payload(business)
    )


# ---------------------------------------------------------------------
# Employee listing and creation
# ---------------------------------------------------------------------

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def employees(request):

    business_id = (
        request.query_params.get("business_id")
        if request.method == "GET"
        else request.data.get("business_id")
    )

    if not business_id:
        return Response(
            {
                "business_id": (
                    "This field is required."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    membership = _get_membership(
        request,
        business_id,
    )

    if (
        membership is None
        or membership.role not in MANAGER_ROLES
    ):
        return Response(
            {
                "detail": (
                    "Only owners and admins can manage employees."
                )
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # List employees.
    if request.method == "GET":

        members = (
            Membership.objects
            .filter(business_id=business_id)
            .select_related("user", "custom_role")
            .prefetch_related(
                "staff_assignment__branch"
            )
            .order_by("user__username")
        )

        return Response([
            _employee_payload(member)
            for member in members
        ])

    # Create employee.
    data = request.data

    username = (
        data.get("username") or ""
    ).strip()

    password = data.get("password") or ""

    role = data.get("role") or "cashier"

    custom_role_id = data.get("custom_role_id")

    errors = {}

    if not username:
        errors["username"] = (
            "This field is required."
        )

    if len(password) < 8:
        errors["password"] = (
            "Password must be at least 8 characters."
        )

    if role not in VALID_ROLES:
        errors["role"] = "Invalid role."

    if (
        role in MANAGER_ROLES
        and membership.role != "owner"
    ):
        errors["role"] = (
            "Only the owner can create owners or admins."
        )

    custom_role = None

    if custom_role_id:
        custom_role, role_error = _validate_custom_role(
            custom_role_id,
            business_id,
        )

        if role_error:
            errors.update(role_error)

    User = get_user_model()

    if (
        username
        and User.objects.filter(
            username=username
        ).exists()
    ):
        errors["username"] = (
            "This username is already taken."
        )

    branch_ids = data.get("branch_ids") or []

    branches, branch_error = _validate_branch_ids(
        branch_ids,
        business_id,
    )

    if branch_error:
        errors.update(branch_error)

    if errors:
        return Response(
            errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():

        user = User.objects.create_user(
            username=username,
            password=password,
            email=data.get("email", ""),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
        )

        if hasattr(user, "phone_number"):
            user.phone_number = data.get(
                "phone_number",
                "",
            )
            user.save(
                update_fields=["phone_number"]
            )

        new_membership = Membership.objects.create(
            user=user,
            business=membership.business,
            role=role,
            custom_role=custom_role,
        )

        for branch in branches:
            BranchAssignment.objects.create(
                membership=new_membership,
                branch=branch,
            )

    return Response(
        _employee_payload(new_membership),
        status=status.HTTP_201_CREATED,
    )


# ---------------------------------------------------------------------
# Employee updates
# ---------------------------------------------------------------------

@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def employee_detail(request, membership_id):

    target = (
        Membership.objects
        .select_related(
            "user",
            "business",
            "custom_role",
        )
        .filter(pk=membership_id)
        .first()
    )

    if target is None:
        return Response(
            {"detail": "Not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    actor = _get_membership(
        request,
        target.business_id,
    )

    if (
        actor is None
        or actor.role not in MANAGER_ROLES
    ):
        return Response(
            {
                "detail": (
                    "Only owners and admins can manage employees."
                )
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # Users may edit their own profile, but not their access privileges.
    if target.pk == actor.pk and any(
        field in request.data
        for field in (
            "role",
            "custom_role_id",
            "is_active",
            "branch_ids",
        )
    ):
        return Response(
            {
                "detail": (
                    "You cannot change your own role, "
                    "activation status or branch assignments."
                )
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    if (
        target.role in MANAGER_ROLES
        and actor.role != "owner"
    ):
        return Response(
            {
                "detail": (
                    "Only the owner can change owners or admins."
                )
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    data = request.data

    # Validate built-in role.
    new_role = data.get(
        "role",
        target.role,
    )

    if new_role not in VALID_ROLES:
        return Response(
            {"role": "Invalid role."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if (
        new_role in MANAGER_ROLES
        and actor.role != "owner"
    ):
        return Response(
            {
                "role": (
                    "Only the owner can assign owner or admin."
                )
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # Validate custom role if supplied.
    custom_role = target.custom_role

    if "custom_role_id" in data:

        custom_role_id = data["custom_role_id"]

        if custom_role_id is None:
            custom_role = None

        else:
            custom_role, role_error = _validate_custom_role(
                custom_role_id,
                target.business_id,
            )

            if role_error:
                return Response(
                    role_error,
                    status=status.HTTP_400_BAD_REQUEST,
                )

    # Validate activation.
    new_is_active = target.is_active

    if "is_active" in data:

        if not isinstance(data["is_active"], bool):
            return Response(
                {
                    "is_active": (
                        "Expected true or false."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_is_active = data["is_active"]

        if (
            target.pk == actor.pk
            and not new_is_active
        ):
            return Response(
                {
                    "detail": (
                        "You cannot deactivate your own account."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    # Validate branches before saving anything.
    branches = None

    if "branch_ids" in data:

        branch_ids = data["branch_ids"] or []

        branches, branch_error = _validate_branch_ids(
            branch_ids,
            target.business_id,
        )

        if branch_error:
            return Response(
                branch_error,
                status=status.HTTP_400_BAD_REQUEST,
            )

    # Save membership and user changes together.
    with transaction.atomic():

        target.role = new_role
        target.custom_role = custom_role
        target.is_active = new_is_active

        target.save(
            update_fields=[
                "role",
                "custom_role",
                "is_active",
            ]
        )

        user = target.user
        changed_fields = []

        for field in (
            "first_name",
            "last_name",
            "email",
        ):
            if field in data:
                setattr(
                    user,
                    field,
                    data[field],
                )
                changed_fields.append(field)

        if changed_fields:
            user.save(
                update_fields=changed_fields
            )

        if branches is not None:

            target.staff_assignment.all().delete()

            for branch in branches:
                BranchAssignment.objects.create(
                    membership=target,
                    branch=branch,
                )

    return Response(
        _employee_payload(target)
    )
