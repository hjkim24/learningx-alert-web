from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts.models import Destination
from accounts.notifications import (
    DuplicateDestinationError,
    _create_destination,
    target_fingerprint,
)


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[Fernet.generate_key().decode()])
class DestinationUniquenessTests(TestCase):
    """The app, not the DB, guarantees one destination per target: MySQL skips
    the conditional unique constraint on target_fingerprint (models.W036)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="dup@example.com")
        self.url = "https://discord.com/api/webhooks/1/abc"
        self.fingerprint = target_fingerprint(Destination.Kind.DISCORD, self.url)

    def test_second_identical_target_is_refused(self):
        _create_destination(self.user, Destination.Kind.DISCORD, self.url, self.fingerprint)

        with self.assertRaises(DuplicateDestinationError):
            _create_destination(self.user, Destination.Kind.DISCORD, self.url, self.fingerprint)
        self.assertEqual(Destination.objects.filter(user=self.user).count(), 1)

    def test_same_target_for_another_user_is_allowed(self):
        other = get_user_model().objects.create_user(username="other@example.com")
        _create_destination(self.user, Destination.Kind.DISCORD, self.url, self.fingerprint)
        _create_destination(other, Destination.Kind.DISCORD, self.url, self.fingerprint)

        self.assertEqual(Destination.objects.count(), 2)
