from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.shortcuts import render


def _verified_emails(sociallogin):
    return [
        address.email.strip().casefold()
        for address in sociallogin.email_addresses
        if address.verified
    ]


def has_access(sociallogin):
    """A Google login needs at least one verified email.

    With SIGNUP_OPEN any verified address is accepted; otherwise (the default,
    so a missing setting fails closed) it must be on PILOT_ALLOWED_EMAILS.
    """
    emails = _verified_emails(sociallogin)
    if not emails:
        return False
    if settings.SIGNUP_OPEN:
        return True
    return any(email in settings.PILOT_ALLOWED_EMAILS for email in emails)


# Kept for callers/tests that still use the old name.
has_pilot_access = has_access


class PilotSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return has_access(sociallogin)

    def pre_social_login(self, request, sociallogin):
        if not has_access(sociallogin):
            raise ImmediateHttpResponse(
                render(request, "accounts/access_denied.html", status=403)
            )
