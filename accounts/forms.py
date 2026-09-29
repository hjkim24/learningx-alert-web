from django import forms
from django.conf import settings
from django.forms import modelformset_factory

from .models import CourseSelection, Destination, NotificationRule


class CanvasTokenForm(forms.Form):
    token = forms.CharField(
        label="Canvas 액세스 토큰",
        max_length=4096,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}),
    )


class CourseSelectionForm(forms.ModelForm):
    class Meta:
        model = CourseSelection
        fields = ("enabled", "include_assignments", "include_lectures")
        labels = {
            "enabled": "이 과목 알림 사용",
            "include_assignments": "과제",
            "include_lectures": "강의·학습자료 (LearningX 출석 대상)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lectures_available = bool(settings.LEARNINGX_ALLOWED_HOSTS)
        if not self.lectures_available:
            # Disabled fields keep their stored value and ignore posted data.
            self.fields["include_lectures"].disabled = True

    def clean(self):
        cleaned = super().clean()
        if not self.lectures_available:
            cleaned["include_lectures"] = False
        if cleaned.get("enabled") and not (
            cleaned.get("include_assignments") or cleaned.get("include_lectures")
        ):
            raise forms.ValidationError(
                "알림을 사용할 항목을 하나 이상 선택해 주세요."
            )
        if not cleaned.get("enabled"):
            cleaned["include_assignments"] = False
            cleaned["include_lectures"] = False
        return cleaned


CourseSelectionFormSet = modelformset_factory(
    CourseSelection,
    form=CourseSelectionForm,
    extra=0,
)


class DestinationForm(forms.Form):
    kind = forms.ChoiceField(label="알림 서비스", choices=Destination.Kind.choices)
    webhook_url = forms.CharField(
        label="웹훅 URL",
        required=False,
        strip=True,
        widget=forms.PasswordInput(
            attrs={"autocomplete": "off"},
            render_value=False,
        ),
    )

    def __init__(self, *args, existing=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.existing = existing
        if existing and not self.is_bound:
            self.initial["kind"] = existing.kind

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        webhook_url = cleaned.get("webhook_url")
        if not webhook_url and not self.existing:
            self.add_error("webhook_url", "웹훅 URL을 입력해 주세요.")
        elif not webhook_url and kind != self.existing.kind:
            self.add_error(
                "webhook_url",
                "알림 서비스를 바꾸려면 새 웹훅 URL을 입력해 주세요.",
            )
        return cleaned


class NotificationRuleForm(forms.ModelForm):
    lookahead_days = forms.IntegerField(
        label="마감 조회 범위",
        min_value=1,
        max_value=14,
        error_messages={
            "min_value": "마감 조회 범위는 1일 이상이어야 합니다.",
            "max_value": "마감 조회 범위는 14일 이하여야 합니다.",
        },
        widget=forms.NumberInput(attrs={"min": 1, "max": 14}),
    )
    first_time = forms.TimeField(
        label="첫 번째 알림 시간",
        input_formats=("%H:%M",),
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
    )
    second_time = forms.TimeField(
        label="두 번째 알림 시간",
        required=False,
        input_formats=("%H:%M",),
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
    )

    class Meta:
        model = NotificationRule
        fields = ("lookahead_days", "first_time", "second_time")

    def clean(self):
        cleaned = super().clean()
        first_time = cleaned.get("first_time")
        second_time = cleaned.get("second_time")
        if second_time and first_time == second_time:
            self.add_error(
                "second_time",
                "첫 번째 알림 시간과 다른 시간을 선택해 주세요.",
            )
        return cleaned
