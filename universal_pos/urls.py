"""
URL configuration for universal_pos project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from core.views import api_root


urlpatterns = [
    path("", api_root, name="root"),
    path("api/", api_root, name="api-root"),
    path("api/auth/", include("accounts.urls")),
    path("api/businesses/", include("businesses.api_urls")),
    path('admin/', admin.site.urls),
    path("api/sales/", include("sales.urls")),
    path("api/inventory/", include("inventory.urls")),
    path("api/purchasing/", include("purchasing.urls")),
    path("api/reports/", include("reporting.urls")),
    path("api/payments/", include("payments.urls")),
    path("api/inventory-management/", include("inventory.api_urls")),
    path("api/purchasing-management/", include("purchasing.api_urls")),
]
