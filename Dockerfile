FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

COPY pyproject.toml manage.py ./
COPY accounts ./accounts
COPY config ./config
COPY learningx_alert ./learningx_alert
COPY templates ./templates
COPY static ./static

RUN python -m pip install --no-cache-dir .
# Content-hashed static copies + staticfiles.json manifest (read by the app at
# runtime; the deploy copies the same directory out for Caddy to serve).
RUN STATIC_MANIFEST=1 python manage.py collectstatic --noinput

USER 10001:10001

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "60", "--error-logfile", "-", "--access-logfile", "-", "--access-logformat", "{\"ts\":\"%(t)s\",\"logger\":\"gunicorn.access\",\"method\":\"%(m)s\",\"path\":\"%(U)s\",\"status\":%(s)s,\"dur_ms\":%(M)s,\"bytes\":\"%(B)s\"}"]
