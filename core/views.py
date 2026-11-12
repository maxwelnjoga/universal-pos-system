from django.http import JsonResponse


def api_root(request):
    """API index, served at / and /api/ (the React app is a separate project)."""
    return JsonResponse(
        {
            "name": "Universal POS API",
            "status": "ok",
            "admin": "/admin/",
            "endpoints": {
                "auth": "/api/auth/",
                "businesses": "/api/businesses/",
                "sales": "/api/sales/",
                "inventory": "/api/inventory/",
                "inventory_management": "/api/inventory-management/",
                "purchasing": "/api/purchasing/",
                "purchasing_management": "/api/purchasing-management/",
                "reports": "/api/reports/",
                "payments": "/api/payments/",
            },
        }
    )
