"""Template context shared by every page."""

import hashlib
from functools import lru_cache

from django.conf import settings


@lru_cache(maxsize=1)
def _asset_version():
    """Short hash of the app's CSS/JS so each deploy gets fresh URLs.

    Static files are served without a version in their name, so browsers can
    keep a stale app.css/app.js after a deploy. Appending ?v=<hash> changes the
    URL exactly when the file contents change.
    """
    digest = hashlib.sha256()
    for name in ("app.css", "app.js"):
        for directory in settings.STATICFILES_DIRS:
            path = directory / name
            if path.is_file():
                digest.update(path.read_bytes())
                break
    return digest.hexdigest()[:12]


def assets(_request):
    return {"asset_version": _asset_version()}
