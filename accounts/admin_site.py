"""A one-model admin for reading feedback.

Not ``django.contrib.admin.site``: that site would pick up every app's admin.py
(users, allauth accounts, tokens). This site registers Feedback only, and lets
in a user only if all of these hold:

* ``is_staff`` is set on the account (done once, by hand, on the server);
* one of the account's Google-verified emails is in ``ADMIN_EMAILS``.

There is no password login: accounts here have no usable password, and the
admin login page is sent to the normal Google sign-in instead. Caddy also
limits the admin path to the Tailscale network.
"""

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.urls import reverse

from .models import Feedback


def is_feedback_admin(user):
    if not (user.is_active and user.is_staff and settings.ADMIN_EMAILS):
        return False
    verified = EmailAddress.objects.filter(user=user, verified=True).values_list(
        "email", flat=True
    )
    return any(email.casefold() in settings.ADMIN_EMAILS for email in verified)


class FeedbackAdminSite(admin.AdminSite):
    site_header = "LearningX Alert 피드백"
    site_title = "피드백"
    index_title = "피드백"
    enable_nav_sidebar = False

    def has_permission(self, request):
        return is_feedback_admin(request.user)

    def login(self, request, extra_context=None):
        if request.user.is_authenticated:
            # Signed in but not an admin: answer as if nothing were here. (Sending
            # them to Google sign-in again would just bounce straight back.)
            raise Http404
        next_url = request.GET.get("next") or reverse("feedback_admin:index")
        return redirect_to_login(next_url, reverse("account_login"))


feedback_admin_site = FeedbackAdminSite(name="feedback_admin")


@admin.register(Feedback, site=feedback_admin_site)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "category", "status", "short_message", "user_email", "page_path")
    list_filter = ("status", "category")
    search_fields = ("message",)
    list_editable = ("status",)
    readonly_fields = (
        "user_email",
        "category",
        "message",
        "page_path",
        "client",
        "standalone",
        "app_revision",
        "latest_run_id",
        "created_at",
    )
    fields = readonly_fields + ("status",)
    ordering = ("-created_at",)

    @admin.display(description="내용")
    def short_message(self, obj):
        return obj.message[:60] + ("…" if len(obj.message) > 60 else "")

    @admin.display(description="사용자")
    def user_email(self, obj):
        return obj.user.email or obj.user.username

    # Every permission check goes through the site gate above; within it the
    # admin may read and mark feedback, never add or delete rows by hand.
    def has_view_permission(self, request, obj=None):
        return is_feedback_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_feedback_admin(request.user)

    def has_module_permission(self, request):
        return is_feedback_admin(request.user)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
