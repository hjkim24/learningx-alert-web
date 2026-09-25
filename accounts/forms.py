from django import forms
from django.forms import modelformset_factory

from .models import CourseSelection, Destination


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
        fields = ("enabled", "include_assignments")
        labels = {
            "enabled": "이 과목 알림 사용",
            "include_assignments": "과제",
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled") and not cleaned.get("include_assignments"):
            raise forms.ValidationError(
                "알림을 사용할 항목을 하나 이상 선택해 주세요."
            )
        if not cleaned.get("enabled"):
            cleaned["include_assignments"] = False
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
