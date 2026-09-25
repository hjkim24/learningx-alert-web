from urllib.error import HTTPError, URLError

from django.conf import settings
from django.db import transaction
from django.views.decorators.debug import sensitive_variables

from learningx_alert.canvas import CanvasClient, PaginationError

from .models import CanvasConnection, CourseSelection
from .services import decrypt_secret


class CourseSyncError(Exception):
    pass


@sensitive_variables("token")
def sync_courses(user, client_class=CanvasClient):
    connection = CanvasConnection.objects.get(user=user)
    token = decrypt_secret(connection.encrypted_token)
    try:
        courses = client_class(settings.CANVAS_BASE_URL, token).courses()
    except (
        HTTPError,
        URLError,
        TimeoutError,
        PaginationError,
        ValueError,
        TypeError,
        KeyError,
    ) as error:
        raise CourseSyncError("course_sync_failed") from error

    active_ids = [course.id for course in courses]
    with transaction.atomic():
        for course in courses:
            CourseSelection.objects.update_or_create(
                user=user,
                canvas_course_id=course.id,
                defaults={"course_name": course.name},
            )
        CourseSelection.objects.filter(user=user).exclude(
            canvas_course_id__in=active_ids
        ).delete()
    return CourseSelection.objects.filter(user=user)
