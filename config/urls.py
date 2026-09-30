from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import include, path
from django.templatetags.static import static
from django.views.generic import RedirectView, TemplateView

from accounts.admin_site import feedback_admin_site
from accounts.views import dashboard
from config import csp, pwa


def healthz(_request) -> HttpResponse:
    return HttpResponse("ok\n", content_type="text/plain")


def privacy_policy(request) -> HttpResponse:
    return render(
        request,
        "legal/privacy.html",
        {"contact_email": settings.PRIVACY_CONTACT_EMAIL},
    )


urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("csp-report/", csp.report, name="csp_report"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("manifest.webmanifest", pwa.manifest, name="web_manifest"),
    # Browsers probe /favicon.ico regardless of <link rel="icon">.
    path("favicon.ico", RedirectView.as_view(url=static("icons/favicon.ico"), permanent=False)),
    path(
        "guide/canvas-token/",
        TemplateView.as_view(template_name="guide/canvas_token.html"),
        name="canvas_token_guide",
    ),
    path(
        "guide/home-screen/",
        TemplateView.as_view(template_name="guide/pwa_install.html"),
        name="pwa_install_guide",
    ),
    path("privacy/", privacy_policy, name="privacy_policy"),
    path(settings.ADMIN_PATH, feedback_admin_site.urls),
    path("", dashboard, name="dashboard"),
    path("accounts/", include("allauth.urls")),
    path("connection/", include("accounts.urls")),
]
