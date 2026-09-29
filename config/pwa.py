"""Root-scoped PWA files: the service worker must live at / to control the site."""

import json

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.views.decorators.http import require_GET


@require_GET
def service_worker(_request):
    body = render_to_string("pwa/sw.js", {"icon_url": static("icons/icon-192.png")})
    response = HttpResponse(body, content_type="text/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    # Browsers re-check the worker at most daily; keep it uncached so fixes land.
    response["Cache-Control"] = "no-cache"
    return response


@require_GET
def manifest(_request):
    data = {
        "name": "LearningX Alert",
        "short_name": "LX Alert",
        "description": "Canvas 과제와 LearningX 강의 마감 알림",
        "lang": "ko",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f5f7fa",
        "theme_color": "#2c4380",
        "icons": [
            {"src": static("icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {
                "src": static("icons/icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    return HttpResponse(
        json.dumps(data, ensure_ascii=False),
        content_type="application/manifest+json; charset=utf-8",
    )
