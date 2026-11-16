from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from businesses.models import Business, Branch, Membership
from inventory.models import Category, Product, Stock
from purchasing.models import Supplier, Purchase


User = get_user_model()


class BranchIsolationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        # One business with two branches.
        cls.business = Business.objects.create(
            name="Branch Security Test",
            slug="branch-security-test",
        )

        cls.branch_a = Branch.objects.create(
            business=cls.business,
            name="Assigned Branch",
            code="TEST-A",
        )

        cls.branch_b = Branch.objects.create(
            business=cls.business,
            name="Unassigned Branch",
            code="TEST-B",
        )

        # Create a product and stock records in both branches.
        cls.category = Category.objects.create(
            business=cls.business,
            name="Test Category",
            description="Temporary category for automated tests",
        )

        cls.product = Product.objects.create(
            business=cls.business,
            category=cls.category,
            name="Test Product",
            sku="TEST-PRODUCT-001",
            cost_price=Decimal("50.00"),
            selling_price=Decimal("75.00"),
        )

        cls.stock_a = Stock.objects.create(
            branch=cls.branch_a,
            product=cls.product,
            quantity=Decimal("20"),
            reorder_level=Decimal("5"),
        )

        cls.stock_b = Stock.objects.create(
            branch=cls.branch_b,
            product=cls.product,
            quantity=Decimal("40"),
            reorder_level=Decimal("5"),
        )

        # Create a supplier and purchases in both branches.
        cls.supplier = Supplier.objects.create(
            business=cls.business,
            name="Test Supplier",
        )

        cls.manager = cls.create_staff(
            username="branch_test_manager",
            role="manager",
        )

        cls.stock_manager = cls.create_staff(
            username="branch_test_stock_manager",
            role="stock_manager",
        )

        cls.purchase_a = Purchase.objects.create(
            business=cls.business,
            branch=cls.branch_a,
            supplier=cls.supplier,
            created_by=cls.manager.user,
            reference_number="TEST-PURCHASE-A",
            status="draft",
            total_amount=Decimal("500.00"),
            notes="Assigned branch purchase",
        )

        cls.purchase_b = Purchase.objects.create(
            business=cls.business,
            branch=cls.branch_b,
            supplier=cls.supplier,
            created_by=cls.manager.user,
            reference_number="TEST-PURCHASE-B",
            status="draft",
            total_amount=Decimal("800.00"),
            notes="Unassigned branch purchase",
        )

    @classmethod
    def create_staff(cls, username, role):
        user = User.objects.create_user(
            username=username,
            password="temporary-test-password",
        )

        membership = Membership.objects.create(
            user=user,
            business=cls.business,
            role=role,
            is_active=True,
        )

        # Assign this member to Branch A only.
        membership.staff_assignment.create(
            branch=cls.branch_a,
        )

        return membership

    def get_response_ids(self, response):
        self.assertEqual(response.status_code, 200, response.data)

        data = response.data

        # Support both paginated and unpaginated DRF responses.
        if isinstance(data, dict) and "results" in data:
            data = data["results"]

        return {str(item["id"]) for item in data}

    def test_manager_only_sees_assigned_branch_records(self):
        self.assert_branch_restrictions(self.manager)

    def test_stock_manager_only_sees_assigned_branch_records(self):
        self.assert_branch_restrictions(self.stock_manager)

    def assert_branch_restrictions(self, membership):
        self.client.force_authenticate(user=membership.user)

        business_id = str(self.business.id)

        endpoints = {
            "stock": "/api/inventory/stock/",
            "purchases": "/api/purchasing/purchases/",
        }

        expected_ids = {
            "stock": {str(self.stock_a.id)},
            "purchases": {str(self.purchase_a.id)},
        }

        forbidden_ids = {
            "stock": str(self.stock_b.id),
            "purchases": str(self.purchase_b.id),
        }

        for name, endpoint in endpoints.items():
            with self.subTest(role=membership.role, endpoint=name):
                response = self.client.get(
                    endpoint,
                    {"business_id": business_id},
                )

                returned_ids = self.get_response_ids(response)

                self.assertEqual(
                    returned_ids,
                    expected_ids[name],
                    (
                        f"{membership.role} received unexpected "
                        f"{name} records: {returned_ids}"
                    ),
                )

                self.assertNotIn(
                    forbidden_ids[name],
                    returned_ids,
                    (
                        f"{membership.role} can see records "
                        f"from an unassigned branch"
                    ),
                )
