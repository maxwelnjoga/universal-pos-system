from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.models import Business, Branch, Membership
from inventory.models import Product, Stock, StockMovement

from .models import Supplier, Purchase, PurchaseItem
from .serializers import (
    SupplierSerializer,
    PurchaseSerializer,
    CreatePurchaseSerializer,
)


PURCHASING_ROLES = {
    "owner",
    "admin",
    "manager",
    "stock_manager",
}


def get_membership(user, business_id):
    membership = Membership.objects.filter(
        user=user,
        business_id=business_id,
        is_active=True,
        business__is_active=True,
    ).first()

    if membership is None:
        raise PermissionDenied(
            "You do not have access to this business."
        )

    return membership


def check_branch_access(membership, branch):
    if branch.business_id != membership.business_id:
        raise PermissionDenied(
            "This branch does not belong to your business."
        )

    if membership.role in ["owner", "admin"]:
        return

    if not membership.staff_assignment.filter(
        branch=branch
    ).exists():
        raise PermissionDenied(
            "You are not assigned to this branch."
        )


class SupplierViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        business_ids = Membership.objects.filter(
            user=self.request.user,
            is_active=True,
            business__is_active=True,
            role__in=PURCHASING_ROLES,
        ).values_list("business_id", flat=True)

        return Supplier.objects.filter(
            business_id__in=business_ids,
            business__is_active=True,
        ).select_related("business")

    def perform_create(self, serializer):
        business = serializer.validated_data["business"]

        membership = get_membership(
            self.request.user,
            business.id,
        )

        if membership.role not in PURCHASING_ROLES:
            raise PermissionDenied(
                "You cannot create suppliers."
            )

        serializer.save()

    def perform_update(self, serializer):
        supplier = self.get_object()

        membership = get_membership(
            self.request.user,
            supplier.business_id,
        )

        if membership.role not in PURCHASING_ROLES:
            raise PermissionDenied(
                "You cannot update suppliers."
            )

        new_business = serializer.validated_data.get(
            "business",
            supplier.business,
        )

        new_membership = get_membership(
            self.request.user,
            new_business.id,
        )

        if new_membership.role not in PURCHASING_ROLES:
            raise PermissionDenied(
                "You cannot move suppliers to this business."
            )

        serializer.save()

    def perform_destroy(self, instance):
        membership = get_membership(
            self.request.user,
            instance.business_id,
        )

        if membership.role not in PURCHASING_ROLES:
            raise PermissionDenied(
                "You cannot delete suppliers."
            )

        if instance.purchases.exists():
            raise ValidationError(
                "This supplier has purchase records. "
                "Deactivate it instead."
            )

        instance.delete()


class PurchaseViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PurchaseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        memberships = Membership.objects.filter(
            user=self.request.user,
            is_active=True,
            business__is_active=True,
            role__in=PURCHASING_ROLES,
        )

        admin_business_ids = memberships.filter(
            role__in=["owner", "admin"],
        ).values_list("business_id", flat=True)

        assigned_branch_ids = memberships.filter(
            role__in=["manager", "stock_manager"],
        ).values_list(
            "staff_assignment__branch_id",
            flat=True,
        )

        return Purchase.objects.filter(
            Q(business_id__in=admin_business_ids)
            | Q(branch_id__in=assigned_branch_ids),
            business__is_active=True,
            branch__is_active=True,
        ).select_related(
            "business",
            "branch",
            "supplier",
            "created_by",
        ).prefetch_related("items", "items__product")


class CreatePurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreatePurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        membership = get_membership(
            request.user,
            data["business_id"],
        )

        if membership.role not in PURCHASING_ROLES:
            raise PermissionDenied(
                "You cannot create purchases."
            )

        branch = Branch.objects.filter(
            id=data["branch_id"],
            business_id=data["business_id"],
            is_active=True,
        ).first()

        if branch is None:
            raise ValidationError(
                {"branch_id": "Invalid or inactive branch."}
            )

        check_branch_access(membership, branch)

        supplier = Supplier.objects.filter(
            id=data["supplier_id"],
            business_id=data["business_id"],
            is_active=True,
        ).first()

        if supplier is None:
            raise ValidationError(
                {"supplier_id": "Invalid or inactive supplier."}
            )

        items = data["items"]

        product_ids = [item["product_id"] for item in items]

        if len(product_ids) != len(set(product_ids)):
            raise ValidationError(
                "Each product may appear only once per purchase."
            )

        with transaction.atomic():
            purchase = Purchase.objects.create(
                business_id=data["business_id"],
                branch=branch,
                supplier=supplier,
                created_by=request.user,
                reference_number=data.get(
                    "reference_number", ""
                ),
                notes=data.get("notes", ""),
            )

            total = Decimal("0.00")

            for item in items:
                product = Product.objects.filter(
                    id=item["product_id"],
                    business_id=data["business_id"],
                    is_active=True,
                ).first()

                if product is None:
                    raise ValidationError({
                        "product_id": (
                            f"Product {item['product_id']} "
                            "does not exist in this business."
                        )
                    })

                quantity = item["quantity"]
                unit_cost = item["unit_cost"]
                line_total = (quantity * unit_cost).quantize(
                    Decimal("0.01")
                )

                PurchaseItem.objects.create(
                    purchase=purchase,
                    product=product,
                    quantity=quantity,
                    unit_cost=unit_cost,
                    line_total=line_total,
                )

                total += line_total

            purchase.total_amount = total.quantize(
                Decimal("0.01")
            )
            purchase.save(update_fields=["total_amount"])

        return Response(
            {
                "message": "Draft purchase created successfully.",
                "purchase": PurchaseSerializer(purchase).data,
            },
            status=status.HTTP_201_CREATED,
        )


class ReceivePurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, purchase_id):
        with transaction.atomic():
            purchase = Purchase.objects.select_for_update().filter(
                id=purchase_id
            ).first()

            if purchase is None:
                return Response(
                    {"error": "Purchase not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            membership = get_membership(
                request.user,
                purchase.business_id,
            )

            if membership.role not in PURCHASING_ROLES:
                raise PermissionDenied(
                    "You cannot receive purchases."
                )

            check_branch_access(membership, purchase.branch)

            if purchase.status != "draft":
                raise ValidationError(
                    "Only draft purchases can be received."
                )

            purchase_items = list(
                purchase.items.select_related("product")
            )

            if not purchase_items:
                raise ValidationError(
                    "Cannot receive a purchase without items."
                )

            for item in purchase_items:
                if item.product.business_id != purchase.business_id:
                    raise ValidationError(
                        "A purchase contains a product "
                        "from another business."
                    )

                stock, created = Stock.objects.get_or_create(
                    branch=purchase.branch,
                    product=item.product,
                    defaults={"quantity": Decimal("0.000")},
                )

                stock = Stock.objects.select_for_update().get(
                    pk=stock.pk
                )

                stock.quantity += item.quantity
                stock.save(update_fields=["quantity", "updated_at"])

                StockMovement.objects.create(
                    stock=stock,
                    movement_type="receipt",
                    quantity_change=item.quantity,
                    reference=(
                        purchase.reference_number
                        or str(purchase.id)
                    ),
                    notes="Stock received from purchase.",
                )

            purchase.status = "received"
            purchase.received_at = timezone.now()
            purchase.save(
                update_fields=["status", "received_at"]
            )

        return Response({
            "message": "Purchase received and stock updated.",
            "purchase_id": str(purchase.id),
            "status": purchase.status,
            "received_at": purchase.received_at.isoformat(),
        })
