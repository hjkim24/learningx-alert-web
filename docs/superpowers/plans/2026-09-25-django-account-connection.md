# Django Account Connection Implementation Plan

> **REQUIRED SUB-SKILL:** Use superpowers:executing-plans to implement this plan task-by-task with TDD checkpoints.

**Goal:** Add a visible, local Django web application where an allowlisted user signs in with Google and securely connects, replaces, or disconnects one SKKU Canvas access token.

**Architecture:** Keep the existing `learningx_alert.CanvasClient` as the only Canvas API boundary. Add one Django project (`config`) and one app (`accounts`) using Django's built-in user model, django-allauth for Google-only login, SQLite for the pilot, and Fernet encryption for stored Canvas tokens. The browser only submits a token; the service validates it with `CanvasClient.profile()` before an atomic one-to-one connection update and never renders it back.

**Tech Stack:** Python 3.12, Django 5.2 LTS, django-allauth 65.x, cryptography 50.x, Django templates, plain CSS, SQLite, existing stdlib Canvas client.

**Spec:** `docs/superpowers/specs/2026-09-25-learningx-alert-web-design.md`

**Global Constraints:** Work in the repository root on the visible `feat/django-account-connection` branch. Keep Google credentials, Django secret, Fernet keys, and Canvas tokens out of Git and logs. `CANVAS_BASE_URL` is operator-controlled and never accepted from a browser. Use the existing outbound-network protections in `learningx_alert.network`. Do not add course selection, notification delivery, scheduling, OCI deployment, or multi-account pilot claims in this slice. Preserve all existing feasibility-probe behavior and tests.

**Review Focus:**

1. Missing production secrets or malformed Fernet keys fail closed without exposing values.
2. Google allowlist matching normalizes whitespace/case and accepts only verified provider email addresses.
3. Invalid or expired Canvas tokens never create or overwrite a stored connection.
4. Canvas tokens are encrypted at rest, never echoed in HTML/errors, and remain decryptable during ordered key rotation.
5. Connect, replace, and disconnect operations are authenticated, CSRF-protected, POST-only, and scoped exclusively to `request.user`.

## Frontend Design Direction

- **Palette:** ink `#17211B`, paper `#F4F7F2`, signal blue `#3268D9`, moss `#6E8B65`, alert `#B94A3B`, line `#CBD5CC`.
- **Typography:** `Apple SD Gothic Neo`, `Pretendard`, `Noto Sans KR`, system sans-serif. Use weight and spacing instead of decorative fonts or remote font dependencies.
- **Layout:** A narrow page frame with a timetable-like status rail. Login uses a two-column headline/action composition; dashboard stacks a connection workspace and a restrained “다음 단계” note. Below 760px, all regions become a single column.
- **Interaction:** Native forms and buttons, visible keyboard focus, minimum 44px controls, status communicated by text plus color, no gradients, no ornamental animation, and a `prefers-reduced-motion` safeguard.
- **Voice:** Plain Korean. Describe Google sign-in and Canvas token connection as separate steps. Never imply that alerts are already running.

Wireframe:

```text
Login
┌──────────────────────────────────────────┐
│ LearningX Alert              안전한 연결 │
├───────────────────────┬──────────────────┤
│ 놓치지 않도록,        │  1 Google 로그인 │
│ 한 번만 설정하세요.   │  2 Canvas 연결   │
│                       │ [Google로 계속]  │
└───────────────────────┴──────────────────┘

Dashboard
┌──────────────────────────────────────────┐
│ LearningX Alert   user@example.com 로그아웃│
├──────────────────────────────────────────┤
│ Google 확인됨 ───── Canvas 연결 상태      │
├───────────────────────────┬──────────────┤
│ Canvas 연결/교체 폼       │ 다음 단계    │
│ 또는 연결된 사용자 정보   │ 과목 선택    │
└───────────────────────────┴──────────────┘
```

The design review rejects generic SaaS card grids, excessive rounded containers, gradients, decorative uppercase labels, and unsupported “실시간/자동 알림 중” language.

---

### Task 1: Bootstrap the minimal Django application

**Files:**

- Modify: `pyproject.toml`
- Create: `manage.py`
- Create: `config/__init__.py`
- Create: `config/settings.py`
- Create: `config/urls.py`
- Create: `config/wsgi.py`
- Create: `accounts/__init__.py`
- Create: `accounts/apps.py`
- Create: `accounts/urls.py`
- Create: `accounts/views.py`
- Create: `accounts/tests/__init__.py`
- Create: `accounts/tests/test_shell.py`

**Step 1: Write the failing shell test**

```python
# accounts/tests/test_shell.py
from django.test import TestCase
from django.urls import reverse


class DashboardShellTests(TestCase):
    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, f'{reverse("account_login")}?next=/')
```

**Step 2: Create the environment and prove the test cannot run yet**

Run:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python manage.py test accounts.tests.test_shell
```

Expected: installation or test import fails because Django/project files are not configured yet.

**Step 3: Add pinned-compatible dependencies**

```toml
# pyproject.toml [project]
dependencies = [
  "Django>=5.2.17,<5.3",
  "django-allauth[socialaccount]>=65.19.4,<66",
  "cryptography>=50.0.1,<51",
]
```

**Step 4: Add the Django shell**

```python
# manage.py
#!/usr/bin/env python3
import os
import sys


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
```

```python
# config/settings.py
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-development-only")
if not DEBUG and SECRET_KEY == "local-development-only":
    raise RuntimeError("DJANGO_SECRET_KEY is required when DJANGO_DEBUG=0")

ALLOWED_HOSTS = [item.strip() for item in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if item.strip()]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TIME_ZONE = "Asia/Seoul"
USE_TZ = True
LANGUAGE_CODE = "ko-kr"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "accounts",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.environ.get("DATABASE_PATH", BASE_DIR / "db.sqlite3")}}
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "account_login"
AUTHENTICATION_BACKENDS = ["allauth.account.auth_backends.AuthenticationBackend"]
SOCIALACCOUNT_ONLY = True
SOCIALACCOUNT_STORE_TOKENS = False
SOCIALACCOUNT_LOGIN_ON_GET = False
```

```python
# accounts/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    return render(request, "accounts/dashboard.html")
```

```python
# config/urls.py
from django.urls import include, path

from accounts.views import dashboard


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("accounts/", include("allauth.urls")),
    path("connection/", include("accounts.urls")),
]
```

Create the standard `config.wsgi.application`, `AccountsConfig`, empty package files, and an empty `accounts.urlpatterns` list.

**Step 5: Run the focused test**

Run:

```bash
.venv/bin/python -m pip install -e .
.venv/bin/python manage.py test accounts.tests.test_shell
```

Expected: PASS.

**Step 6: Commit**

```bash
git add pyproject.toml manage.py config accounts
git commit -m "feat: bootstrap django web app"
```

---

### Task 2: Enforce Google-only pilot access

**Files:**

- Modify: `config/settings.py`
- Modify: `accounts/views.py`
- Create: `accounts/adapters.py`
- Create: `accounts/tests/test_google_access.py`
- Create: `templates/account/login.html`
- Create: `templates/accounts/access_denied.html`
- Create: `templates/accounts/dashboard.html`

**Step 1: Write failing allowlist tests**

```python
# accounts/tests/test_google_access.py
from types import SimpleNamespace
from unittest.mock import patch

from allauth.core.exceptions import ImmediateHttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from accounts.adapters import PilotSocialAccountAdapter


def social_login(*addresses):
    return SimpleNamespace(email_addresses=[SimpleNamespace(email=email, verified=verified) for email, verified in addresses])


@override_settings(PILOT_ALLOWED_EMAILS={"pilot@example.com"})
class PilotSocialAccountAdapterTests(SimpleTestCase):
    def setUp(self):
        self.adapter = PilotSocialAccountAdapter()
        self.request = RequestFactory().get("/")

    def test_verified_allowlisted_email_is_open(self):
        login = social_login((" Pilot@Example.com ", True))

        self.assertTrue(self.adapter.is_open_for_signup(self.request, login))

    def test_unverified_email_is_closed(self):
        login = social_login(("pilot@example.com", False))

        self.assertFalse(self.adapter.is_open_for_signup(self.request, login))

    @patch("accounts.adapters.render")
    def test_existing_disallowed_login_is_denied_too(self, render):
        render.return_value.status_code = 403

        with self.assertRaises(ImmediateHttpResponse):
            self.adapter.pre_social_login(self.request, social_login(("other@example.com", True)))
```

**Step 2: Run the test to verify failure**

Run: `.venv/bin/python manage.py test accounts.tests.test_google_access`

Expected: FAIL because `PilotSocialAccountAdapter` does not exist.

**Step 3: Implement normalized verified-email access**

```python
# accounts/adapters.py
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.shortcuts import render


def has_pilot_access(sociallogin):
    return any(
        address.verified and address.email.strip().casefold() in settings.PILOT_ALLOWED_EMAILS
        for address in sociallogin.email_addresses
    )


class PilotSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return has_pilot_access(sociallogin)

    def pre_social_login(self, request, sociallogin):
        if not has_pilot_access(sociallogin):
            raise ImmediateHttpResponse(render(request, "accounts/access_denied.html", status=403))
```

Add to settings:

```python
PILOT_ALLOWED_EMAILS = {
    email.strip().casefold()
    for email in os.environ.get("PILOT_ALLOWED_EMAILS", "").split(",")
    if email.strip()
}
SOCIALACCOUNT_ADAPTER = "accounts.adapters.PilotSocialAccountAdapter"
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "key": "",
        },
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "OAUTH_PKCE_ENABLED": True,
    }
}
```

Use a POST form with `{% provider_login_url 'google' process='login' %}` and `{% csrf_token %}` in `templates/account/login.html`. The access-denied template must only say the account is not in the pilot; it must not print provider payloads. Add a temporary signed-in dashboard heading so Task 1 remains renderable.

**Step 4: Run the focused tests**

Run:

```bash
.venv/bin/python manage.py test accounts.tests.test_google_access accounts.tests.test_shell
```

Expected: PASS.

**Step 5: Commit**

```bash
git add config/settings.py accounts/adapters.py accounts/tests templates
git commit -m "feat: restrict google login to pilot users"
```

---

### Task 3: Encrypt and validate the Canvas connection

**Files:**

- Create: `accounts/models.py`
- Create: `accounts/services.py`
- Create: `accounts/migrations/0001_initial.py`
- Create: `accounts/migrations/__init__.py`
- Create: `accounts/tests/test_connection_service.py`

**Step 1: Write failing service tests**

```python
# accounts/tests/test_connection_service.py
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts.models import CanvasConnection
from accounts.services import CanvasConnectionError, decrypt_secret, encrypt_secret, verify_and_store_connection


KEY = Fernet.generate_key().decode()


class FakeCanvasClient:
    def __init__(self, base_url, token):
        self.token = token

    def profile(self):
        if self.token == "invalid":
            raise RuntimeError("upstream detail containing invalid")
        return {"id": 1234, "name": "김학재"}


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY], CANVAS_BASE_URL="https://canvas.skku.edu")
class CanvasConnectionServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")

    def test_round_trip_is_encrypted(self):
        ciphertext = encrypt_secret("token value")

        self.assertNotIn("token value", ciphertext)
        self.assertEqual(decrypt_secret(ciphertext), "token value")

    def test_valid_token_creates_one_connection(self):
        connection = verify_and_store_connection(user=self.user, token="  good token  ", client_class=FakeCanvasClient)

        self.assertEqual(connection.canvas_user_id, "1234")
        self.assertEqual(connection.canvas_name, "김학재")
        self.assertEqual(decrypt_secret(connection.encrypted_token), "good token")

    def test_invalid_replacement_keeps_previous_ciphertext(self):
        existing = verify_and_store_connection(user=self.user, token="good", client_class=FakeCanvasClient)

        with self.assertRaisesMessage(CanvasConnectionError, "canvas_verification_failed"):
            verify_and_store_connection(user=self.user, token="invalid", client_class=FakeCanvasClient)

        existing.refresh_from_db()
        self.assertEqual(decrypt_secret(existing.encrypted_token), "good")
        self.assertEqual(CanvasConnection.objects.count(), 1)
```

Also add a `MultiFernet` rotation test where `[new_key, old_key]` decrypts ciphertext produced with `[old_key]`.

**Step 2: Run the test to verify failure**

Run: `.venv/bin/python manage.py test accounts.tests.test_connection_service`

Expected: FAIL because model/service modules do not exist.

**Step 3: Add the one-to-one model**

```python
# accounts/models.py
from django.conf import settings
from django.db import models


class CanvasConnection(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="canvas_connection")
    canvas_user_id = models.CharField(max_length=128)
    canvas_name = models.CharField(max_length=255)
    encrypted_token = models.TextField()
    verified_at = models.DateTimeField()

    def __str__(self):
        return f"Canvas connection for user {self.user_id}"
```

Generate and inspect the migration:

```bash
.venv/bin/python manage.py makemigrations accounts
```

**Step 4: Implement encryption and validate-before-write**

```python
# accounts/services.py
import json
from urllib.error import HTTPError, URLError

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from learningx_alert.canvas import CanvasClient

from .models import CanvasConnection


class CanvasConnectionError(Exception):
    pass


def _fernet():
    try:
        return MultiFernet([Fernet(key.encode()) for key in settings.CREDENTIAL_ENCRYPTION_KEYS])
    except (AttributeError, ValueError) as exc:
        raise ImproperlyConfigured("CREDENTIAL_ENCRYPTION_KEYS must contain valid Fernet keys") from exc


def encrypt_secret(value):
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value):
    return _fernet().decrypt(value.encode()).decode()


def verify_and_store_connection(*, user, token, client_class=CanvasClient):
    normalized_token = token.strip()
    try:
        profile = client_class(settings.CANVAS_BASE_URL, normalized_token).profile()
        canvas_user_id = str(profile["id"])
        canvas_name = str(profile["name"])
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise CanvasConnectionError("canvas_verification_failed") from exc

    with transaction.atomic():
        connection, _ = CanvasConnection.objects.update_or_create(
            user=user,
            defaults={
                "canvas_user_id": canvas_user_id,
                "canvas_name": canvas_name,
                "encrypted_token": encrypt_secret(normalized_token),
                "verified_at": timezone.now(),
            },
        )
    return connection
```

In settings, parse only non-empty keys and keep the fixed base URL operator-side:

```python
CANVAS_BASE_URL = os.environ.get("CANVAS_BASE_URL", "https://canvas.skku.edu")
CREDENTIAL_ENCRYPTION_KEYS = [key.strip() for key in os.environ.get("CREDENTIAL_ENCRYPTION_KEYS", "").split(",") if key.strip()]
```

The explicit exception tuple covers the current stdlib Canvas/network and response-shape failures while leaving programming errors visible during development. Keep the outward error fixed and secret-free.

**Step 5: Run migrations and tests**

Run:

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test accounts.tests.test_connection_service
```

Expected: PASS.

**Step 6: Commit**

```bash
git add config/settings.py accounts/models.py accounts/services.py accounts/migrations accounts/tests/test_connection_service.py
git commit -m "feat: store verified canvas tokens securely"
```

---

### Task 4: Add authenticated connect, replace, and disconnect actions

**Files:**

- Create: `accounts/forms.py`
- Modify: `accounts/views.py`
- Modify: `accounts/urls.py`
- Modify: `templates/accounts/dashboard.html`
- Create: `accounts/tests/test_connection_views.py`

**Step 1: Write failing view tests**

```python
# accounts/tests/test_connection_views.py
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import CanvasConnection


class CanvasConnectionViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.other = get_user_model().objects.create_user(username="other@example.com")

    def test_connect_requires_login(self):
        response = self.client.post(reverse("canvas_connect"), {"token": "secret"})

        self.assertEqual(response.status_code, 302)

    @patch("accounts.views.verify_and_store_connection")
    def test_connect_passes_only_current_user_and_token(self, verify):
        self.client.force_login(self.user)

        response = self.client.post(reverse("canvas_connect"), {"token": " secret "})

        self.assertRedirects(response, reverse("dashboard"))
        verify.assert_called_once_with(user=self.user, token="secret")
        self.assertNotContains(response, "secret")

    def test_disconnect_deletes_only_current_users_connection(self):
        CanvasConnection.objects.create(user=self.user, canvas_user_id="1", canvas_name="A", encrypted_token="a", verified_at="2026-09-25T00:00:00Z")
        other_connection = CanvasConnection.objects.create(user=self.other, canvas_user_id="2", canvas_name="B", encrypted_token="b", verified_at="2026-09-25T00:00:00Z")
        self.client.force_login(self.user)

        response = self.client.post(reverse("canvas_disconnect"))

        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(CanvasConnection.objects.filter(user=self.user).exists())
        self.assertTrue(CanvasConnection.objects.filter(pk=other_connection.pk).exists())

    def test_disconnect_rejects_get(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(reverse("canvas_disconnect")).status_code, 405)
```

Add one `Client(enforce_csrf_checks=True)` test that obtains the dashboard CSRF cookie and proves a POST without the token returns 403. Add an invalid-token test asserting the generic Korean error is rendered and the submitted token is absent.

**Step 2: Run the test to verify failure**

Run: `.venv/bin/python manage.py test accounts.tests.test_connection_views`

Expected: FAIL because the form/routes do not exist.

**Step 3: Implement the smallest native form and actions**

```python
# accounts/forms.py
from django import forms


class CanvasTokenForm(forms.Form):
    token = forms.CharField(
        label="Canvas 액세스 토큰",
        max_length=4096,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}),
    )
```

```python
# accounts/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import CanvasTokenForm
from .models import CanvasConnection
from .services import CanvasConnectionError, verify_and_store_connection


@login_required
def dashboard(request):
    connection = CanvasConnection.objects.filter(user=request.user).first()
    return render(request, "accounts/dashboard.html", {"connection": connection, "form": CanvasTokenForm()})


@login_required
@require_POST
def canvas_connect(request):
    form = CanvasTokenForm(request.POST)
    if form.is_valid():
        try:
            verify_and_store_connection(user=request.user, token=form.cleaned_data["token"])
        except CanvasConnectionError:
            messages.error(request, "Canvas 연결을 확인하지 못했습니다. 토큰을 다시 확인해 주세요.")
        else:
            messages.success(request, "Canvas 계정을 연결했습니다.")
    return redirect("dashboard")


@login_required
@require_POST
def canvas_disconnect(request):
    CanvasConnection.objects.filter(user=request.user).delete()
    messages.success(request, "Canvas 연결을 해제했습니다.")
    return redirect("dashboard")
```

```python
# accounts/urls.py
from django.urls import path

from . import views


urlpatterns = [
    path("canvas/", views.canvas_connect, name="canvas_connect"),
    path("canvas/disconnect/", views.canvas_disconnect, name="canvas_disconnect"),
]
```

Render only `canvas_name`, `canvas_user_id`, and `verified_at`; never pass decrypted token material to a template. Label the same form “연결하기” or “새 토큰으로 교체” based on connection presence.

**Step 4: Run the focused tests**

Run:

```bash
.venv/bin/python manage.py test accounts.tests.test_connection_views accounts.tests.test_connection_service
```

Expected: PASS.

**Step 5: Commit**

```bash
git add accounts/forms.py accounts/views.py accounts/urls.py accounts/tests/test_connection_views.py templates/accounts/dashboard.html
git commit -m "feat: manage canvas connection from dashboard"
```

---

### Task 5: Finish the responsive UI and operator setup

**Files:**

- Create: `templates/base.html`
- Modify: `templates/account/login.html`
- Modify: `templates/accounts/access_denied.html`
- Modify: `templates/accounts/dashboard.html`
- Create: `static/app.css`
- Create: `.env.example`
- Modify: `README.md`
- Create: `accounts/tests/test_pages.py`

**Step 1: Write failing page-contract tests**

```python
# accounts/tests/test_pages.py
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class PageContractTests(TestCase):
    def test_login_explains_the_two_separate_connections(self):
        response = self.client.get(reverse("account_login"))

        self.assertContains(response, "Google로 계속")
        self.assertContains(response, "Canvas 연결")
        self.assertContains(response, "아직 알림은 시작되지 않습니다")

    def test_dashboard_has_accessible_token_form(self):
        user = get_user_model().objects.create_user(username="pilot@example.com")
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, 'type="password"')
        self.assertContains(response, 'autocomplete="off"')
        self.assertContains(response, "과목 선택은 다음 단계에서 진행합니다")
```

**Step 2: Run the test to verify failure**

Run: `.venv/bin/python manage.py test accounts.tests.test_pages`

Expected: FAIL until the final content and base template exist.

**Step 3: Build the reviewed visual direction**

Use semantic `<header>`, `<main>`, `<section>`, `<aside>`, `<form>`, and `<dl>` elements. Define the palette as CSS custom properties, keep content width near `68rem`, use a grid-line/status-rail motif instead of a card grid, and include:

```css
:root {
  --ink: #17211b;
  --paper: #f4f7f2;
  --signal: #3268d9;
  --moss: #6e8b65;
  --alert: #b94a3b;
  --line: #cbd5cc;
}

*:focus-visible {
  outline: 3px solid var(--signal);
  outline-offset: 3px;
}

@media (max-width: 760px) {
  .split,
  .workspace {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
  }
}
```

Review the result against the design rejection list before considering the task complete.

**Step 4: Document safe local configuration**

`.env.example` contains names and non-secret defaults only:

```dotenv
DJANGO_DEBUG=1
DJANGO_SECRET_KEY=
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
PILOT_ALLOWED_EMAILS=
CANVAS_BASE_URL=https://canvas.skku.edu
CREDENTIAL_ENCRYPTION_KEYS=
DATABASE_PATH=db.sqlite3
```

README setup must include:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

Document the Google callback as `http://127.0.0.1:8000/accounts/google/login/callback/`, explain that `.env` is never committed, and state that course selection/alerts are not in this slice.

**Step 5: Run the full verification**

Run:

```bash
.venv/bin/python manage.py test
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
git diff --check
```

Expected: all Django and existing feasibility tests pass, system check reports no issues, no pending migrations, and no whitespace errors.

**Step 6: Perform a secret and placeholder scan**

Run:

```bash
rg -n "(AIza|client_secret|BEGIN PRIVATE|TODO|FIXME|placeholder)" --glob '!docs/superpowers/plans/**' .
```

Expected: no committed credential or unfinished implementation marker. Configuration field names in `.env.example` are acceptable because values are empty.

**Step 7: Commit**

```bash
git add templates static .env.example README.md accounts/tests/test_pages.py
git commit -m "feat: finish account connection experience"
```

---

## Final Review Gate

Before pushing or opening a pull request:

1. Re-read the spec and map every implemented item to this plan; record course selection, notifications, scheduling, OCI, and second-account validation as intentionally deferred.
2. Re-run the five review-focus cases, including an invalid replacement and two distinct local users.
3. Confirm no Canvas token, Google secret, Django secret, Fernet key, `.env`, or SQLite database is tracked by Git.
4. Inspect the login and dashboard at desktop and mobile widths, keyboard-only, with errors and connected/disconnected states.
5. Request a code review focused on authentication boundaries, encryption/key rotation, cross-user isolation, and truthfulness of UI claims; fix Critical and Important findings before merge.
