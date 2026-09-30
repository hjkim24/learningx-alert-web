from django.conf import settings
from django.test.runner import DiscoverRunner


class AppTestRunner(DiscoverRunner):
    """Rate-limit counters live in a cache that is not reset between tests, so
    they are off by default; tests that exercise them turn them back on.

    Scheduler runs are serial by default too: worker threads open their own DB
    connections, which cannot see a TestCase's uncommitted rows. The threaded
    path has its own TransactionTestCase."""

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        settings.RATE_LIMITS_ENABLED = False
        settings.SCHEDULER_CONCURRENCY = 1
