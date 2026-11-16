from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    BusinessRole,
    Membership,
    Permission,
    RolePermission,
)
from .permission_catalogue import PERMISSION_CATALOGUE
from .role_serializers import PermissionSerializer


def get_business_membership(request, business_id):
    """
    Find the authenticated user's active membership
    in the requested business.
    """

    membership = Membership.objects.filter(
        user=request.user,
        business_id=business_id,
        is_active=True,
        business__is_active=True,
    ).first()

    if not membership:
        raise PermissionDenied(
            "You do not have access to this business."
        )

    return membership


def require_role_management_access(membership):
    """
    Only business owners and admins can manage custom roles.
    """

    if membership.role not in ["owner", "admin"]:
        raise PermissionDenied(
            "You are not allowed to manage business roles."
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def permission_catalogue(request):
    """
    Return the available system permissions.
    """

    permissions = Permission.objects.all().order_by(
        "category",
        "name",
    )

    serializer = PermissionSerializer(
        permissions,
        many=True,
    )

    return Response(serializer.data)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def business_roles(request):

    business_id = request.query_params.get(
        "business_id"
    ) or request.data.get("business_id")

    if not business_id:
        raise ValidationError({
            "business_id": "This field is required."
        })

    membership = get_business_membership(
        request,
        business_id,
    )

    if request.method == "GET":
        roles = BusinessRole.objects.filter(
            business_id=business_id,
            is_active=True,
        ).order_by("name")

        data = []

        for role in roles:
            data.append({
                "id": str(role.id),
                "business_id": str(role.business_id),
                "name": role.name,
                "description": role.description,
                "is_system_role": role.is_system_role,
                "is_active": role.is_active,
                "permission_ids": list(
                    role.role_permissions.values_list(
                        "permission_id",
                        flat=True,
                    )
                ),
            })

        return Response(data)

    require_role_management_access(membership)

    name = request.data.get("name", "").strip()
    description = request.data.get("description", "")
    permission_ids = request.data.get("permission_ids", [])

    if not name:
        raise ValidationError({
            "name": "Role name is required."
        })

    if not isinstance(permission_ids, list):
        raise ValidationError({
            "permission_ids": "Expected a list of permission IDs."
        })

    permissions = list(
        Permission.objects.filter(
            id__in=permission_ids
        )
    )

    if len(permissions) != len(set(permission_ids)):
        raise ValidationError({
            "permission_ids": "One or more permissions are invalid."
        })

    if BusinessRole.objects.filter(
        business_id=business_id,
        name__iexact=name,
    ).exists():
        raise ValidationError({
            "name": "A role with this name already exists."
        })

    with transaction.atomic():
        role = BusinessRole.objects.create(
            business_id=business_id,
            name=name,
            description=description,
            is_system_role=False,
        )

        RolePermission.objects.bulk_create([
            RolePermission(
                role=role,
                permission=permission,
            )
            for permission in permissions
        ])

    return Response(
        {
            "id": str(role.id),
            "business_id": str(role.business_id),
            "name": role.name,
            "description": role.description,
            "is_system_role": role.is_system_role,
            "is_active": role.is_active,
            "permission_ids": [
                str(permission.id)
                for permission in permissions
            ],
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def business_role_detail(request, role_id):

    role = get_object_or_404(
        BusinessRole,
        id=role_id,
    )

    membership = get_business_membership(
        request,
        role.business_id,
    )

    require_role_management_access(membership)

    if role.is_system_role:
        raise PermissionDenied(
            "System roles cannot be modified or deactivated here."
        )

    if request.method == "DELETE":
        role.is_active = False
        role.save(update_fields=["is_active"])

        return Response(
            {"message": "Role deactivated successfully."},
            status=status.HTTP_200_OK,
        )

    name = request.data.get("name", role.name).strip()
    description = request.data.get(
        "description",
        role.description,
    )
    permission_ids = request.data.get(
        "permission_ids",
        None,
    )

    if not name:
        raise ValidationError({
            "name": "Role name cannot be empty."
        })

    if BusinessRole.objects.filter(
        business_id=role.business_id,
        name__iexact=name,
    ).exclude(id=role.id).exists():
        raise ValidationError({
            "name": "A role with this name already exists."
        })

    with transaction.atomic():
        role.name = name
        role.description = description
        role.save()

        if permission_ids is not None:
            if not isinstance(permission_ids, list):
                raise ValidationError({
                    "permission_ids": "Expected a list of permission IDs."
                })

            permissions = list(
                Permission.objects.filter(
                    id__in=permission_ids
                )
            )

            if len(permissions) != len(set(permission_ids)):
                raise ValidationError({
                    "permission_ids": "One or more permissions are invalid."
                })

            role.role_permissions.all().delete()

            RolePermission.objects.bulk_create([
                RolePermission(
                    role=role,
                    permission=permission,
                )
                for permission in permissions
            ])

    return Response({
        "id": str(role.id),
        "business_id": str(role.business_id),
        "name": role.name,
        "description": role.description,
        "is_system_role": role.is_system_role,
        "is_active": role.is_active,
        "permission_ids": list(
            role.role_permissions.values_list(
                "permission_id",
                flat=True,
            )
        ),
    })