from django.http import HttpResponse
from django.urls import include, path

from accounts.views import dashboard


def healthz(_request) -> HttpResponse:
    return HttpResponse("ok\n", content_type="text/plain")


urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("", dashboard, name="dashboard"),
    path("accounts/", include("allauth.urls")),
    path("connection/", include("accounts.urls")),
]
