from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.shortcuts import render


def has_pilot_access(sociallogin):
    return any(
        address.verified
        and address.email.strip().casefold() in settings.PILOT_ALLOWED_EMAILS
        for address in sociallogin.email_addresses
    )


class PilotSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return has_pilot_access(sociallogin)

    def pre_social_login(self, request, sociallogin):
        if not has_pilot_access(sociallogin):
            raise ImmediateHttpResponse(
                render(request, "accounts/access_denied.html", status=403)
            )
