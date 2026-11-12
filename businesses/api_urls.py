from django.urls import path

from . import api_views

urlpatterns = [
    path("", api_views.my_businesses, name="my-businesses"),
    path("branches/", api_views.my_branches, name="my-branches"),
    path("employees/", api_views.employees, name="business-employees"),
    path(
        "employees/<uuid:membership_id>/",
        api_views.employee_detail,
        name="business-employee-detail",
    ),
    path(
        "<uuid:business_id>/",
        api_views.business_detail,
        name="business-detail",
    ),
]
