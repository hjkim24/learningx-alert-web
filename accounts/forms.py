from django import forms
from django.forms import modelformset_factory

from .models import CourseSelection


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
