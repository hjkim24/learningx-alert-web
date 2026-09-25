from django.urls import include, path

from accounts.views import dashboard


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("accounts/", include("allauth.urls")),
    path("connection/", include("accounts.urls")),
]
