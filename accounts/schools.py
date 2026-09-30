"""Schools this deployment can connect to.

The list lives in code, not the database: a school's Canvas URL and LearningX
hosts are the boundary of what the server will request on a user's behalf
(SSRF), so they change only through a reviewed PR. ``ENABLED_SCHOOLS`` only
chooses which of these the connect form offers.
"""

from dataclasses import dataclass

from django.conf import settings

DEFAULT_SCHOOL = "skku"


@dataclass(frozen=True)
class School:
    code: str
    name: str
    canvas_base_url: str
    # Hosts the LearningX LTI launch may visit. Empty disables lecture alerts.
    learningx_hosts: frozenset

    @property
    def lectures_available(self):
        return bool(self.learningx_hosts)


def _registry():
    # Built per call so the SKKU entry follows CANVAS_BASE_URL and
    # LEARNINGX_ALLOWED_HOSTS (existing deployment config and test overrides).
    return {
        "skku": School(
            code="skku",
            name="성균관대학교",
            canvas_base_url=settings.CANVAS_BASE_URL,
            learningx_hosts=frozenset(settings.LEARNINGX_ALLOWED_HOSTS),
        ),
        "hanyang": School(
            code="hanyang",
            name="한양대학교",
            canvas_base_url="https://learning.hanyang.ac.kr",
            learningx_hosts=frozenset({"learning.hanyang.ac.kr"}),
        ),
    }


ALL_CODES = ("skku", "hanyang")
CODE_CHOICES = (("skku", "성균관대학교"), ("hanyang", "한양대학교"))


def get_school(code):
    """The school for a stored code. Unknown codes fail loudly: a row pointing
    at a school we no longer know must not fall back to another school's URL."""
    return _registry()[code]


def enabled_schools():
    registry = _registry()
    codes = [code for code in settings.ENABLED_SCHOOLS if code in registry]
    return [registry[code] for code in codes] or [registry[DEFAULT_SCHOOL]]


def is_enabled(code):
    return any(school.code == code for school in enabled_schools())


def school_of(connection):
    return get_school(connection.school)


def school_full(code, *, exclude_user=None):
    """Whether ``code`` has reached SCHOOL_MAX_USERS connections (0 = no cap).

    A user already connected to that school (a token swap) is not counted
    against it. Two connects racing at the limit can both pass, so the cap may
    overshoot by one, the same trade-off as the sign-up cap.
    """
    from .models import CanvasConnection

    limit = settings.SCHOOL_MAX_USERS
    if not limit:
        return False
    connections = CanvasConnection.objects.filter(school=code)
    if exclude_user is not None:
        connections = connections.exclude(user=exclude_user)
    return connections.count() >= limit
