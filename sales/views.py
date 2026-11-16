from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.models import Branch, Membership
from .models import Sale
from .serializers import CreateSaleSerializer, SaleListSerializer
from .services import process_sale


SALES_ROLES = {"owner", "admin", "manager", "cashier"}


def get_sales_membership(user, business):
    return Membership.objects.filter(
        user=user,
        business=business,
        is_active=True,
        business__is_active=True,
        role__in=SALES_ROLES,
    ).first()


def validate_checkout_access(membership, branch):
    if branch.business_id != membership.business_id:
        raise PermissionDenied(
            "This branch does not belong to your business."
        )

    if not branch.is_active:
        raise PermissionDenied(
            "This branch is inactive."
        )

    if membership.role in ["owner", "admin"]:
        return

    if not membership.staff_assignment.filter(
        branch=branch
    ).exists():
        raise PermissionDenied(
            "You are not assigned to this branch."
        )


def perform_checkout(request, data, membership):
    validate_checkout_access(
        membership,
        data["branch"],
    )

    try:
        sale = process_sale(
            business=data["business"],
            branch=data["branch"],
            cashier=request.user,
            items=[
                {
                    "product_id": str(item["product_id"]),
                    "quantity": item["quantity"],
                }
                for item in data["items"]
            ],
            customer_id=data.get("customer_id") or None,
            discount_amount=data["discount_amount"],
            tax_amount=data["tax_amount"],
            notes=data.get("notes", ""),
            checkout_key=data["checkout_key"],
        )
    except DjangoValidationError as exc:
        return Response(
            {"detail": exc.messages},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {
            "id": str(sale.pk),
            "sale_id": str(sale.pk),
            "receipt_number": sale.receipt_number,
            "status": sale.status,
            "subtotal": str(sale.subtotal),
            "discount_amount": str(sale.discount_amount),
            "tax_amount": str(sale.tax_amount),
            "total_amount": str(sale.total_amount),
            "checkout_key": str(sale.checkout_key),
        },
        status=status.HTTP_200_OK,
    )


class SaleViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Sale.objects.none()
    serializer_class = SaleListSerializer

    def get_queryset(self):
        memberships = Membership.objects.filter(
            user=self.request.user,
            is_active=True,
            business__is_active=True,
            role__in=SALES_ROLES,
        )

        access_filter = Q(pk__in=[])

        for membership in memberships:
            business_filter = Q(
                business_id=membership.business_id
            )

            if membership.role in ["owner", "admin"]:
                access_filter |= business_filter

            elif membership.role == "manager":
                branch_ids = membership.staff_assignment.values_list(
                    "branch_id",
                    flat=True,
                )

                access_filter |= business_filter & Q(
                    branch_id__in=branch_ids
                )

            elif membership.role == "cashier":
                access_filter |= business_filter & Q(
                    cashier=self.request.user
                )

        queryset = Sale.objects.filter(
            access_filter
        ).select_related(
            "business",
            "branch",
            "cashier",
        ).order_by("-created_at")

        business_id = self.request.query_params.get("business_id")

        if business_id:
            queryset = queryset.filter(
                business_id=business_id
            )

        return queryset

    @action(detail=False, methods=["post"], url_path="checkout")
    def checkout(self, request):
        serializer = CreateSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        membership = get_sales_membership(
            request.user,
            data["business"],
        )

        if membership is None:
            raise PermissionDenied(
                "You do not have permission to make sales for this business."
            )

        return perform_checkout(
            request,
            data,
            membership,
        )


class CheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        membership = get_sales_membership(
            request.user,
            data["business"],
        )

        if membership is None:
            raise PermissionDenied(
                "You do not have permission to make sales for this business."
            )

        return perform_checkout(
            request,
            data,
            membership,
        )
