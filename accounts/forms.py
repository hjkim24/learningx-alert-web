from datetime import time

from django import forms
from django.conf import settings
from django.forms import modelformset_factory

from .models import (
    EVERY_DAY,
    WEEKDAY_LABELS,
    AlarmTime,
    CourseSelection,
    Destination,
    NotificationRule,
)


class LabelSuffixMixin:
    """Render labels without Django's default trailing colon."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)


class CanvasTokenForm(LabelSuffixMixin, forms.Form):
    token = forms.CharField(
        label="Canvas 액세스 토큰",
        max_length=4096,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}),
    )


class CourseSelectionForm(LabelSuffixMixin, forms.ModelForm):
    """A course alerts when at least one item type is on; `enabled` follows that."""

    class Meta:
        model = CourseSelection
        fields = ("include_assignments", "include_lectures")
        labels = {
            "include_assignments": "과제",
            "include_lectures": "강의",
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
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.enabled = bool(
            instance.include_assignments or instance.include_lectures
        )
        if commit:
            instance.save()
        return instance


CourseSelectionFormSet = modelformset_factory(
    CourseSelection,
    form=CourseSelectionForm,
    extra=0,
)


WEBHOOK_KINDS = (
    (Destination.Kind.DISCORD, Destination.Kind.DISCORD.label),
    (Destination.Kind.SLACK, Destination.Kind.SLACK.label),
)


class DestinationForm(LabelSuffixMixin, forms.Form):
    """A new Discord/Slack webhook destination. Browser push registers via JS."""

    kind = forms.ChoiceField(label="알림 서비스", choices=WEBHOOK_KINDS)
    label = forms.CharField(
        label="이름 (선택)",
        required=False,
        max_length=64,
        strip=True,
        widget=forms.TextInput(attrs={"placeholder": "예: 개인 서버 #과제"}),
    )
    webhook_url = forms.CharField(
        label="웹훅 URL",
        required=False,
        strip=True,
        widget=forms.PasswordInput(
            attrs={"autocomplete": "off"},
            render_value=False,
        ),
    )

    def __init__(self, *args, require_url=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_url = require_url

    def clean(self):
        cleaned = super().clean()
        if self.require_url and not cleaned.get("webhook_url"):
            self.add_error("webhook_url", "웹훅 URL을 넣어 주세요.")
        return cleaned


class NotificationRuleForm(LabelSuffixMixin, forms.ModelForm):
    lookahead_days = forms.IntegerField(
        label="마감 조회 범위",
        min_value=1,
        max_value=14,
        error_messages={
            "min_value": "조회 범위는 1일 이상이어야 해요.",
            "max_value": "조회 범위는 14일 이하여야 해요.",
        },
        widget=forms.NumberInput(
            attrs={"min": 1, "max": 14, "class": "input-short", "inputmode": "numeric"}
        ),
    )
    class Meta:
        model = NotificationRule
        fields = ("lookahead_days",)


WEEKDAY_CHOICES = tuple((str(index), label) for index, label in enumerate(WEEKDAY_LABELS))


class AlarmTimeForm(LabelSuffixMixin, forms.ModelForm):
    time = forms.TimeField(
        label="시각",
        input_formats=("%H:%M",),
        error_messages={"required": "알림 시각을 넣어 주세요."},
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time", "class": "alarm-time-input"}),
    )
    days = forms.MultipleChoiceField(
        label="요일",
        choices=WEEKDAY_CHOICES,
        error_messages={"required": "요일을 하나 이상 선택해 주세요."},
        widget=forms.CheckboxSelectMultiple(attrs={"class": "weekday-input"}),
    )
    enabled = forms.BooleanField(label="켜기", required=False)

    class Meta:
        model = AlarmTime
        fields = ("time", "enabled")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        mask = self.instance.weekdays if self.instance.pk else EVERY_DAY
        self.initial.setdefault(
            "days", [str(index) for index in range(7) if mask & (1 << index)]
        )
        if not self.instance.pk:
            self.initial.setdefault("enabled", True)
            self.initial.setdefault("time", time(9, 0))

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.weekdays = sum(1 << int(day) for day in self.cleaned_data["days"])
        if commit:
            instance.save()
        return instance


DUPLICATE_ALARM_MESSAGE = "같은 시각의 알림이 두 개 있어요. 시각을 바꾸거나 하나를 지워 주세요."


class BaseAlarmFormSet(forms.BaseInlineFormSet):
    def get_unique_error_message(self, unique_check):
        return DUPLICATE_ALARM_MESSAGE

    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        if i >= self.initial_form_count():
            # A new row prefilled with 09:00 is a real alarm even if untouched.
            form.empty_permitted = False
            form.has_changed = lambda: True
        return form

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen = set()
        kept = 0
        for form in self.forms:
            if not form.cleaned_data or self._should_delete_form(form):
                continue
            kept += 1
            value = form.cleaned_data["time"].replace(second=0, microsecond=0)
            if value in seen:
                raise forms.ValidationError(DUPLICATE_ALARM_MESSAGE)
            seen.add(value)
        if kept < 1:
            raise forms.ValidationError("알림 시각이 하나 이상 있어야 해요.")
        if kept > AlarmTime.MAX_PER_RULE:
            raise forms.ValidationError(f"알림 시각은 최대 {AlarmTime.MAX_PER_RULE}개까지 만들 수 있어요.")


AlarmFormSet = forms.inlineformset_factory(
    NotificationRule,
    AlarmTime,
    form=AlarmTimeForm,
    formset=BaseAlarmFormSet,
    extra=0,
    can_delete=True,
    max_num=AlarmTime.MAX_PER_RULE,
    validate_max=True,
    absolute_max=AlarmTime.MAX_PER_RULE,
)
