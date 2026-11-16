from django.db.models import F
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.models import Branch, Membership
from .models import Category, Product, Stock
from .api_serializers import (
    CategorySerializer,
    ProductSerializer,
    StockSerializer,
)


INVENTORY_ROLES = {
    "owner",
    "admin",
    "manager",
    "stock_manager",
}

PRODUCT_MANAGEMENT_ROLES = {
    "owner",
    "admin",
    "manager",
    "stock_manager",
}


class InventoryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_membership(self, request, business_id):
        membership = Membership.objects.filter(
            user=request.user,
            business_id=business_id,
            is_active=True,
            business__is_active=True,
        ).first()

        if membership is None:
            raise PermissionDenied(
                "You do not have access to this business."
            )

        return membership

    def require_inventory_access(self, membership):
        if membership.role not in INVENTORY_ROLES:
            raise PermissionDenied(
                "You do not have permission to access inventory."
            )

    def require_product_management(self, membership):
        if membership.role not in PRODUCT_MANAGEMENT_ROLES:
            raise PermissionDenied(
                "You are not allowed to manage products or categories."
            )

    def get_accessible_branches(self, membership, business_id):
        branches = Branch.objects.filter(
            business_id=business_id,
            is_active=True,
        )

        if membership.role not in ["owner", "admin"]:
            branches = branches.filter(
                id__in=membership.staff_assignment.values_list(
                    "branch_id",
                    flat=True,
                )
            )

        return branches


class ProductListCreateView(InventoryAPIView):

    def get(self, request):
        business_id = request.query_params.get("business_id")

        if not business_id:
            raise ValidationError({
                "business_id": "This query parameter is required."
            })

        self.get_membership(request, business_id)

        # Product catalogue remains readable by cashiers
        # because checkout requires product information.
        products = Product.objects.filter(
            business_id=business_id,
        ).order_by("name")

        category_id = request.query_params.get("category_id")

        if category_id:
            products = products.filter(
                category_id=category_id
            )

        active = request.query_params.get("active")

        if active in ["true", "false"]:
            products = products.filter(
                is_active=(active == "true")
            )

        return Response(
            ProductSerializer(products, many=True).data
        )

    def post(self, request):
        business_id = request.data.get("business_id")

        if not business_id:
            raise ValidationError({
                "business_id": "This field is required."
            })

        membership = self.get_membership(
            request,
            business_id,
        )

        self.require_product_management(membership)

        data = request.data.copy()

        if data.get("category"):
            get_object_or_404(
                Category,
                id=data["category"],
                business_id=business_id,
            )

        serializer = ProductSerializer(data=data)
        serializer.is_valid(raise_exception=True)

        product = serializer.save(
            business_id=business_id
        )

        return Response(
            ProductSerializer(product).data,
            status=status.HTTP_201_CREATED,
        )


class StockListView(InventoryAPIView):

    def get(self, request):
        business_id = request.query_params.get("business_id")

        if not business_id:
            raise ValidationError({
                "business_id": "This query parameter is required."
            })

        membership = self.get_membership(
            request,
            business_id,
        )

        # Cashiers and accountants cannot access stock records.
        self.require_inventory_access(membership)

        branches = self.get_accessible_branches(
            membership,
            business_id,
        )

        stock = Stock.objects.filter(
            branch__in=branches,
            product__business_id=business_id,
        ).select_related(
            "product",
            "branch",
        ).order_by(
            "product__name"
        )

        branch_id = request.query_params.get("branch_id")

        if branch_id:
            if not branches.filter(id=branch_id).exists():
                raise PermissionDenied(
                    "You cannot access inventory for this branch."
                )

            stock = stock.filter(
                branch_id=branch_id
            )

        low_stock = request.query_params.get("low_stock")

        if low_stock == "true":
            stock = stock.filter(
                quantity__lte=F("reorder_level"),
                product__is_active=True,
            )

        return Response(
            StockSerializer(stock, many=True).data
        )


class CategoryListCreateView(InventoryAPIView):

    def get(self, request):
        business_id = request.query_params.get("business_id")

        if not business_id:
            raise ValidationError({
                "business_id": "This query parameter is required."
            })

        self.get_membership(request, business_id)

        # Cashiers can read categories for POS product filtering.
        categories = Category.objects.filter(
            business_id=business_id,
        ).order_by("name")

        return Response(
            CategorySerializer(categories, many=True).data
        )

    def post(self, request):
        business_id = request.data.get("business_id")

        if not business_id:
            raise ValidationError({
                "business_id": "This field is required."
            })

        membership = self.get_membership(
            request,
            business_id,
        )

        self.require_product_management(membership)

        serializer = CategorySerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        category = serializer.save(
            business_id=business_id
        )

        return Response(
            CategorySerializer(category).data,
            status=status.HTTP_201_CREATED,
        )
