from datetime import timedelta

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts import scheduling
from accounts.collection import collect_for_user, default_learningx_factory
from accounts.courses import sync_courses
from accounts.forms import CourseSelectionFormSet, lectures_available_for
from accounts.models import CanvasConnection, CourseSelection, ScheduledRun
from accounts.schools import enabled_schools, get_school, school_full
from accounts.services import CanvasConnectionError, encrypt_secret, verify_and_store_connection
from learningx_alert.canvas import CanvasClient
from learningx_alert.models import CanvasProfile

KEY = Fernet.generate_key().decode()
HANYANG = "https://learning.hanyang.ac.kr"


class RecordingClient:
    """Canvas stand-in that records which base URL each request targeted."""

    urls = []

    def __init__(self, base_url, token):
        RecordingClient.urls.append(base_url)

    def profile(self):
        return CanvasProfile(id=7, name="학생")

    def courses(self):
        return []


def make_user(name):
    return get_user_model().objects.create_user(username=f"{name}@example.com")


def connect(user, school):
    return CanvasConnection.objects.create(
        user=user,
        school=school,
        canvas_user_id="1",
        canvas_name="학생",
        encrypted_token=encrypt_secret("token"),
        verified_at=timezone.now(),
    )


@override_settings(
    CREDENTIAL_ENCRYPTION_KEYS=[KEY],
    CANVAS_BASE_URL="https://canvas.skku.edu",
    LEARNINGX_ALLOWED_HOSTS=frozenset({"canvas.skku.edu"}),
    ENABLED_SCHOOLS=("skku", "hanyang"),
    SCHOOL_MAX_USERS=50,
)
class SchoolRegistryTests(TestCase):
    def setUp(self):
        RecordingClient.urls = []

    def test_existing_style_connection_defaults_to_skku(self):
        user = make_user("old")
        connection = CanvasConnection.objects.create(
            user=user,
            canvas_user_id="1",
            canvas_name="x",
            encrypted_token=encrypt_secret("t"),
            verified_at=timezone.now(),
        )
        self.assertEqual(connection.school, "skku")

    @override_settings(ENABLED_SCHOOLS=("hanyang", "nowhere"))
    def test_unknown_enabled_codes_are_ignored(self):
        self.assertEqual([s.code for s in enabled_schools()], ["hanyang"])

    @override_settings(ENABLED_SCHOOLS=())
    def test_nothing_enabled_falls_back_to_skku(self):
        self.assertEqual([s.code for s in enabled_schools()], ["skku"])

    def test_connect_verifies_against_the_chosen_school_and_stores_it(self):
        user = make_user("hy")
        connection = verify_and_store_connection(
            user=user, token="t", school="hanyang", client_class=RecordingClient
        )
        self.assertEqual(connection.school, "hanyang")
        self.assertEqual(RecordingClient.urls, [HANYANG])

    def test_token_swap_keeps_the_existing_school(self):
        user = make_user("swap")
        connect(user, "hanyang")
        connection = verify_and_store_connection(
            user=user, token="new", school="skku", client_class=RecordingClient
        )
        self.assertEqual(connection.school, "hanyang")
        self.assertEqual(RecordingClient.urls, [HANYANG])

    @override_settings(ENABLED_SCHOOLS=("skku",))
    def test_disabled_school_is_refused_before_any_request(self):
        with self.assertRaisesMessage(CanvasConnectionError, "school_unavailable"):
            verify_and_store_connection(
                user=make_user("off"), token="t", school="hanyang", client_class=RecordingClient
            )
        self.assertEqual(RecordingClient.urls, [])

    @override_settings(SCHOOL_MAX_USERS=1)
    def test_full_school_refuses_new_users_but_not_existing_or_other_schools(self):
        existing = make_user("first")
        connect(existing, "hanyang")
        self.assertTrue(school_full("hanyang"))

        with self.assertRaisesMessage(CanvasConnectionError, "school_full"):
            verify_and_store_connection(
                user=make_user("second"), token="t", school="hanyang", client_class=RecordingClient
            )
        self.assertEqual(RecordingClient.urls, [])
        # The connected user can still swap tokens; another school is unaffected.
        verify_and_store_connection(user=existing, token="t2", client_class=RecordingClient)
        verify_and_store_connection(
            user=make_user("skku"), token="t", school="skku", client_class=RecordingClient
        )
        self.assertEqual(CanvasConnection.objects.filter(school="hanyang").count(), 1)

    @override_settings(SCHOOL_MAX_USERS=0)
    def test_zero_means_no_cap(self):
        connect(make_user("a"), "hanyang")
        self.assertFalse(school_full("hanyang"))

    def test_sync_and_collect_use_the_users_school(self):
        user = make_user("collect")
        connect(user, "hanyang")
        sync_courses(user, client_class=RecordingClient)
        collect_for_user(user, timezone.now(), client_class=RecordingClient)
        self.assertEqual(RecordingClient.urls, [HANYANG, HANYANG])

    def test_learningx_hosts_are_per_school(self):
        hanyang = default_learningx_factory(CanvasClient(HANYANG, "t"), get_school("hanyang"))
        skku = default_learningx_factory(CanvasClient("https://canvas.skku.edu", "t"), get_school("skku"))
        # A Hanyang launch can never be steered to SKKU hosts, and vice versa.
        self.assertEqual(hanyang.allowed_hosts, {"learning.hanyang.ac.kr"})
        self.assertEqual(skku.allowed_hosts, {"canvas.skku.edu"})

    @override_settings(LEARNINGX_ALLOWED_HOSTS=frozenset())
    def test_lecture_toggle_follows_the_school(self):
        skku_user, hy_user = make_user("s"), make_user("h")
        connect(skku_user, "skku")
        connect(hy_user, "hanyang")
        self.assertFalse(lectures_available_for(skku_user))
        self.assertTrue(lectures_available_for(hy_user))
        CourseSelection.objects.create(user=hy_user, canvas_course_id=1, course_name="c")
        formset = CourseSelectionFormSet(queryset=CourseSelection.objects.filter(user=hy_user))
        self.assertTrue(formset.forms[0].lectures_available)


@override_settings(
    CREDENTIAL_ENCRYPTION_KEYS=[KEY],
    ENABLED_SCHOOLS=("skku", "hanyang"),
    SCHOOL_MAX_USERS=50,
)
class SchoolConnectViewTests(TestCase):
    def setUp(self):
        self.user = make_user("view")
        self.client.force_login(self.user)

    def test_dashboard_offers_radio_choice_when_several_schools_are_on(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'type="radio" form="canvas-token-form" name="school" value="skku"')
        self.assertContains(response, 'value="hanyang"')

    @override_settings(ENABLED_SCHOOLS=("skku",))
    def test_single_school_hides_the_choice(self):
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, 'name="school"')

    @override_settings(SCHOOL_MAX_USERS=1)
    def test_full_school_is_shown_disabled(self):
        connect(make_user("other"), "hanyang")
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'value="hanyang" required disabled')
        self.assertContains(response, "한양대학교 (정원 마감)")

    def test_missing_or_unknown_school_is_rejected_without_storing(self):
        for data in ({"token": "t"}, {"school": "evil", "token": "t"}):
            response = self.client.post(reverse("canvas_connect"), data, follow=True)
            self.assertContains(response, "학교를 골라 주세요.")
        self.assertFalse(CanvasConnection.objects.exists())

    @override_settings(SCHOOL_MAX_USERS=1)
    def test_full_school_message(self):
        connect(make_user("other"), "hanyang")
        response = self.client.post(
            reverse("canvas_connect"), {"school": "hanyang", "token": "t"}, follow=True
        )
        self.assertContains(response, "이 학교는 정원이 다 찼어요.")
        self.assertFalse(CanvasConnection.objects.filter(user=self.user).exists())

    def test_connected_card_shows_school_name(self):
        connect(self.user, "hanyang")
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "한양대학교")
        self.assertNotContains(response, 'name="school"')

    @override_settings(CANVAS_BASE_URL="https://canvas.skku.edu/")
    def test_dashboard_links_each_schools_token_settings(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'href="https://canvas.skku.edu/profile/settings"')
        self.assertContains(response, 'href="https://learning.hanyang.ac.kr/profile/settings"')
        self.assertContains(response, "성균관대학교 Canvas 설정 열기")

    @override_settings(SCHOOL_MAX_USERS=1)
    def test_full_school_gets_no_settings_link(self):
        connect(make_user("other"), "hanyang")
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "learning.hanyang.ac.kr/profile/settings")

    def test_reconnect_links_only_the_connected_school(self):
        connection = connect(self.user, "hanyang")
        connection.needs_reconnect = True
        connection.save()
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'href="https://learning.hanyang.ac.kr/profile/settings"')
        self.assertNotContains(response, "canvas.skku.edu/profile/settings")

    def test_healthy_connection_hides_the_settings_link(self):
        connect(self.user, "hanyang")
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "/profile/settings")

    def test_privacy_lists_enabled_schools(self):
        response = self.client.get(reverse("privacy_policy"))
        self.assertContains(response, "성균관대학교(canvas.skku.edu)")
        self.assertContains(response, "한양대학교(learning.hanyang.ac.kr)")


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY])
class SchoolSchedulingTests(TestCase):
    def test_runs_are_interleaved_by_school(self):
        users = [make_user(f"u{i}") for i in range(4)]
        for user, school in zip(users, ("skku", "skku", "skku", "hanyang")):
            connect(user, school)
        slot = timezone.now().replace(second=0, microsecond=0)
        runs = [
            ScheduledRun.objects.create(user=user, scheduled_for=slot - timedelta(minutes=i))
            for i, user in enumerate(users)
        ]
        schools = scheduling._run_schools(runs)
        ordered = scheduling._interleave_by_school(runs, schools)

        self.assertEqual([schools[r.user_id] for r in ordered], ["skku", "hanyang", "skku", "skku"])
        self.assertEqual(sorted(r.pk for r in ordered), sorted(r.pk for r in runs))


class SchoolGateTests(TestCase):
    def test_gate_caps_concurrent_runs_of_one_school(self):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from types import SimpleNamespace
        from unittest import mock

        active, peak, lock = 0, 0, threading.Lock()

        def fake_run_one(*_args):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1

        gate = threading.BoundedSemaphore(2)
        with mock.patch.object(scheduling, "_run_one", fake_run_one), \
                mock.patch.object(scheduling.connections, "close_all"):
            with ThreadPoolExecutor(max_workers=4) as pool:
                for future in [
                    pool.submit(scheduling._run_in_thread, SimpleNamespace(pk=i), None, None, None, "skku", gate)
                    for i in range(6)
                ]:
                    future.result()

        self.assertEqual(peak, 2)


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY], ENABLED_SCHOOLS=("skku", "hanyang"), SCHOOL_MAX_USERS=50)
class SchoolGaugeTests(TestCase):
    def test_gauges_report_count_and_cap_per_enabled_school(self):
        from unittest import mock

        from accounts import telemetry
        from accounts.schools import record_school_gauges

        connect(make_user("a"), "hanyang")
        connect(make_user("b"), "hanyang")
        with mock.patch.object(telemetry, "school_connections") as conns, \
                mock.patch.object(telemetry, "school_capacity") as cap:
            record_school_gauges()

        self.assertEqual(
            sorted(c.args for c in conns.set.call_args_list),
            [(0, {"school": "skku"}), (2, {"school": "hanyang"})],
        )
        self.assertEqual({c.args[0] for c in cap.set.call_args_list}, {50})
