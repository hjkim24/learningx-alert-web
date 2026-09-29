from django.http import HttpResponse
from django.urls import include, path
from django.views.generic import TemplateView

from accounts.views import dashboard
from config import pwa


def healthz(_request) -> HttpResponse:
    return HttpResponse("ok\n", content_type="text/plain")


urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("manifest.webmanifest", pwa.manifest, name="web_manifest"),
    path(
        "guide/canvas-token/",
        TemplateView.as_view(template_name="guide/canvas_token.html"),
        name="canvas_token_guide",
    ),
    path("", dashboard, name="dashboard"),
    path("accounts/", include("allauth.urls")),
    path("connection/", include("accounts.urls")),
]
