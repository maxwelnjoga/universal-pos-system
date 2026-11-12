from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from .models import Membership, Branch


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_businesses(request):
    """
    Return the active businesses the logged-in user belongs to.
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

    If the user's membership has branch assignments, only those
    assigned branches are returned. If no assignments exist, all
    active branches belonging to that business are returned.
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

    assignments = membership.staff_assignment.all()

    if assignments.exists():
        assigned_branch_ids = assignments.values_list(
            "branch_id",
            flat=True,
        )
        branches = branches.filter(id__in=assigned_branch_ids)

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


# ---------------------------------------------------------------------------
# Business settings and staff management (used by the React frontend)
# ---------------------------------------------------------------------------
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response

from .models import BranchAssignment

MANAGER_ROLES = {"owner", "admin"}
VALID_ROLES = {code for code, _ in Membership.ROLE_CHOICES}


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
    full_name = f"{user.first_name} {user.last_name}".strip()
    branches = [
        {"id": str(a.branch_id), "name": a.branch.name}
        for a in membership.staff_assignment.select_related("branch")
    ]
    return {
        "membership_id": str(membership.id),
        "user_id": str(user.pk),
        "username": user.username,
        "name": full_name or user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "phone_number": getattr(user, "phone_number", ""),
        "role": membership.role,
        "is_active": membership.is_active,
        "branches": branches,
    }


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def business_detail(request, business_id):
    membership = _get_membership(request, business_id)

    if membership is None:
        return Response(
            {"detail": "You do not have access to this business."},
            status=status.HTTP_403_FORBIDDEN,
        )

    business = membership.business

    if request.method == "PATCH":
        if membership.role not in MANAGER_ROLES:
            return Response(
                {"detail": "Only owners and admins can change settings."},
                status=status.HTTP_403_FORBIDDEN,
            )

        for field in ("name", "industry", "currency", "tax_rate"):
            if field in request.data:
                setattr(business, field, request.data[field])

        try:
            business.full_clean(exclude=["slug"])
        except Exception as exc:  # ValidationError
            messages = getattr(exc, "message_dict", None) or {"detail": str(exc)}
            return Response(messages, status=status.HTTP_400_BAD_REQUEST)

        business.save()

    return Response(_business_payload(business))


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
            {"business_id": "This field is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    membership = _get_membership(request, business_id)

    if membership is None or membership.role not in MANAGER_ROLES:
        return Response(
            {"detail": "Only owners and admins can manage employees."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == "GET":
        members = (
            Membership.objects
            .filter(business_id=business_id)
            .select_related("user")
            .order_by("user__username")
        )
        return Response([_employee_payload(m) for m in members])

    data = request.data
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = data.get("role") or "cashier"

    errors = {}
    if not username:
        errors["username"] = "This field is required."
    if len(password) < 8:
        errors["password"] = "Password must be at least 8 characters."
    if role not in VALID_ROLES:
        errors["role"] = "Invalid role."
    if role in MANAGER_ROLES and membership.role != "owner":
        errors["role"] = "Only the owner can create owners or admins."

    User = get_user_model()
    if username and User.objects.filter(username=username).exists():
        errors["username"] = "This username is already taken."

    branch_ids = data.get("branch_ids") or []
    branches = Branch.objects.filter(
        id__in=branch_ids, business_id=business_id, is_active=True
    )
    if len(branch_ids) != branches.count():
        errors["branch_ids"] = "One or more branches are invalid."

    if errors:
        return Response(errors, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            password=password,
            email=data.get("email", ""),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
        )
        if hasattr(user, "phone_number"):
            user.phone_number = data.get("phone_number", "")
            user.save(update_fields=["phone_number"])

        new_membership = Membership.objects.create(
            user=user, business=membership.business, role=role
        )
        for branch in branches:
            BranchAssignment.objects.create(
                membership=new_membership, branch=branch
            )

    return Response(
        _employee_payload(new_membership), status=status.HTTP_201_CREATED
    )


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def employee_detail(request, membership_id):
    target = (
        Membership.objects
        .select_related("user", "business")
        .filter(pk=membership_id)
        .first()
    )

    if target is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    actor = _get_membership(request, target.business_id)

    if actor is None or actor.role not in MANAGER_ROLES:
        return Response(
            {"detail": "Only owners and admins can manage employees."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if target.role in MANAGER_ROLES and actor.role != "owner":
        return Response(
            {"detail": "Only the owner can change owners or admins."},
            status=status.HTTP_403_FORBIDDEN,
        )

    data = request.data

    if "role" in data:
        new_role = data["role"]
        if new_role not in VALID_ROLES:
            return Response({"role": "Invalid role."}, status=status.HTTP_400_BAD_REQUEST)
        if new_role in MANAGER_ROLES and actor.role != "owner":
            return Response(
                {"role": "Only the owner can assign owner or admin."},
                status=status.HTTP_403_FORBIDDEN,
            )
        target.role = new_role

    if "is_active" in data:
        if target.pk == actor.pk and not data["is_active"]:
            return Response(
                {"detail": "You cannot deactivate your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        target.is_active = bool(data["is_active"])

    target.save()

    user = target.user
    changed = []
    for field in ("first_name", "last_name", "email"):
        if field in data:
            setattr(user, field, data[field])
            changed.append(field)
    if changed:
        user.save(update_fields=changed)

    if "branch_ids" in data:
        branches = Branch.objects.filter(
            id__in=data["branch_ids"],
            business_id=target.business_id,
            is_active=True,
        )
        with transaction.atomic():
            target.staff_assignment.all().delete()
            for branch in branches:
                BranchAssignment.objects.create(membership=target, branch=branch)

    return Response(_employee_payload(target))
