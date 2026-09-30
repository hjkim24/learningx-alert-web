from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib.auth import get_user_model
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


def signup_full():
    """Open sign-up stops creating accounts at SIGNUP_MAX_USERS (0 = no cap).

    Only new accounts are affected; existing users keep logging in. Two sign-ups
    racing at the limit can both pass, so the cap may overshoot by a user or two.
    """
    limit = settings.SIGNUP_MAX_USERS
    return bool(settings.SIGNUP_OPEN and limit and get_user_model().objects.count() >= limit)


class PilotSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return has_access(sociallogin) and not signup_full()

    def pre_social_login(self, request, sociallogin):
        if not has_access(sociallogin):
            raise ImmediateHttpResponse(
                render(request, "accounts/access_denied.html", status=403)
            )
        if not sociallogin.is_existing and signup_full():
            raise ImmediateHttpResponse(
                render(
                    request,
                    "accounts/access_denied.html",
                    {"signup_full": True},
                    status=403,
                )
            )
