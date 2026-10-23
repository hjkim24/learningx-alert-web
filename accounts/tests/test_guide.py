from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse


GUIDE_IMAGES = [f"guide/canvas-token-0{index}.jpg" for index in range(1, 8)]


class CanvasTokenGuideTests(TestCase):
    def test_guide_is_public_and_lists_every_step(self):
        page = Client().get(reverse("canvas_token_guide"))

        self.assertEqual(page.status_code, 200)
        for step in range(1, 7):
            self.assertContains(page, f'id="step-{step}"')
        self.assertContains(page, "나의 과목 바로가기")
        self.assertContains(page, "승인된 통합")
        self.assertContains(page, "만료일을 정하면")
        self.assertContains(page, "로그인하고 시작하기")

    def test_every_screenshot_is_referenced_exists_and_has_alt_text(self):
        page = Client().get(reverse("canvas_token_guide")).content.decode()

        for name in GUIDE_IMAGES:
            with self.subTest(image=name):
                self.assertIn(f"/static/{name}", page)
                path = Path(settings.STATICFILES_DIRS[0]) / name
                self.assertTrue(path.is_file())
                self.assertLess(path.stat().st_size, 400_000)
        self.assertEqual(page.count("<img "), page.count('alt="'))

    @override_settings(ENABLED_SCHOOLS=("skku", "hanyang"), CANVAS_BASE_URL="https://canvas.skku.edu")
    def test_guide_links_each_schools_token_settings(self):
        page = Client().get(reverse("canvas_token_guide"))

        self.assertContains(page, 'href="https://canvas.skku.edu/profile/settings"')
        self.assertContains(page, 'href="https://learning.hanyang.ac.kr/profile/settings"')
        self.assertContains(page, "한양대학교 Canvas 설정 열기")

    def test_logged_in_user_gets_dashboard_cta(self):
        user = get_user_model().objects.create_user(username="pilot@example.com")
        self.client.force_login(user)

        page = self.client.get(reverse("canvas_token_guide"))

        self.assertContains(page, "대시보드로 가서 연결하기")

    def test_dashboard_and_login_link_to_the_guide(self):
        login = Client().get(reverse("account_login"))
        self.assertContains(login, reverse("canvas_token_guide"))

        user = get_user_model().objects.create_user(username="new@example.com")
        self.client.force_login(user)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, reverse("canvas_token_guide"))


PWA_IMAGES = [f"guide/pwa-install-0{index}.jpg" for index in range(1, 4)]


class PwaInstallGuideTests(TestCase):
    def test_guide_is_public_and_lists_every_step(self):
        page = Client().get(reverse("pwa_install_guide"))

        self.assertEqual(page.status_code, 200)
        for step in range(1, 5):
            self.assertContains(page, f'id="step-{step}"')
        for phrase in ("홈 화면에 추가", "웹 앱으로 열기", "이 브라우저에서 알림 받기", "로그인하고 시작하기"):
            self.assertContains(page, phrase)

    def test_every_screenshot_is_referenced_small_and_stripped(self):
        page = Client().get(reverse("pwa_install_guide")).content.decode()

        for name in PWA_IMAGES:
            with self.subTest(image=name):
                self.assertIn(f"/static/{name}", page)
                path = Path(settings.STATICFILES_DIRS[0]) / name
                self.assertLess(path.stat().st_size, 400_000)
                self.assertNotIn(b"Exif", path.read_bytes()[:4096])
        self.assertEqual(page.count("<img "), page.count('alt="'))

    def test_logged_in_user_gets_destination_cta_and_settings_link_back(self):
        user = get_user_model().objects.create_user(username="pwa@example.com")
        self.client.force_login(user)

        page = self.client.get(reverse("pwa_install_guide"))
        self.assertContains(page, reverse("destination_settings"))
        settings_page = self.client.get(reverse("destination_settings"))
        self.assertContains(settings_page, reverse("pwa_install_guide"))
