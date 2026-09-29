"""Per-user rate limits for actions that make this server call someone else.

Open sign-up means any Google account can make the server hit Canvas, LearningX
or a webhook on demand. These limits keep one account from turning the server
into a request pump (and getting its IP blocked by the school).

Counts live in Django's cache. The default local-memory cache is per process,
so with N gunicorn workers the effective ceiling is at most N times the limit.
That is still bounded, which is the point.
"""

from django.conf import settings
from django.core.cache import cache

LIMITS = {
    # action: (max attempts, window seconds)
    "canvas_connect": (5, 600),
    "preview": (20, 600),
    "destination_test": (10, 600),
}


def allow(user, action):
    """Record one attempt; return False once the user is over the limit."""
    if not getattr(settings, "RATE_LIMITS_ENABLED", True):
        return True
    limit, window = LIMITS[action]
    key = f"throttle:{action}:{user.pk}"
    if cache.add(key, 1, timeout=window):
        return True
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.add(key, 1, timeout=window)
        return True
    return count <= limit


LIMITED_MESSAGE = "요청이 너무 많아요. 몇 분 뒤에 다시 시도해 주세요."
