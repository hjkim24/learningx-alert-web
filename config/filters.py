from django.views.debug import SafeExceptionReporterFilter


class AlwaysSafeExceptionReporterFilter(SafeExceptionReporterFilter):
    def is_active(self, request):
        return True
