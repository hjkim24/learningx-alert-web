"""Context for the install/push banner shown on signed-in pages."""

from . import webpush
from .models import Destination

# Pages that already handle push themselves, or where a banner is out of place.
_SKIP_VIEWS = {"destination_settings", "feedback", "privacy_policy"}


def install_banner(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not webpush.web_push_enabled():
        return {}
    match = getattr(request, "resolver_match", None)
    if match is not None and match.url_name in _SKIP_VIEWS:
        return {}
    return {
        "install_banner": {
            "vapid_key": webpush.vapid_public_key(),
            # Any browser-push destination at all: iPhone Safari then stops
            # nagging about "add to home screen" (the phone app is set up).
            "has_push": Destination.objects.filter(
                user=user, kind=Destination.Kind.WEBPUSH
            ).exists(),
        }
    }
