"""Shared helpers for building notification rules with alarm rows in tests."""

from datetime import time
from types import SimpleNamespace

from accounts.models import EVERY_DAY, AlarmTime, NotificationRule


def make_rule(user, *times, lookahead_days=3, weekdays=EVERY_DAY):
    """A saved rule with one daily alarm per given time (default 09:00)."""
    rule = NotificationRule.objects.create(user=user, lookahead_days=lookahead_days)
    for value in times or (time(9, 0),):
        AlarmTime.objects.create(rule=rule, time=value, weekdays=weekdays)
    return rule


def unsaved_rule(*times, weekdays=EVERY_DAY):
    """A rule stand-in exposing `alarms.all()`, for pure scheduling tests."""
    alarms = _AlarmList(
        AlarmTime(time=value, weekdays=weekdays, enabled=True) for value in times
    )
    return SimpleNamespace(alarms=alarms)


class _AlarmList(list):
    def all(self):
        return self


def alarm_post_data(*alarms, existing=()):
    """Formset POST data. Each alarm is "HH:MM" or ("HH:MM", days, enabled).

    `existing` lists AlarmTime pks for the first rows (initial forms).
    """
    data = {
        "alarms-TOTAL_FORMS": str(len(alarms)),
        "alarms-INITIAL_FORMS": str(len(existing)),
        "alarms-MIN_NUM_FORMS": "0",
        "alarms-MAX_NUM_FORMS": "5",
    }
    for index, alarm in enumerate(alarms):
        if isinstance(alarm, str):
            alarm = (alarm, range(7), True)
        value, days, enabled = alarm
        data[f"alarms-{index}-time"] = value
        data[f"alarms-{index}-days"] = [str(day) for day in days]
        if enabled:
            data[f"alarms-{index}-enabled"] = "on"
        if index < len(existing):
            data[f"alarms-{index}-id"] = str(existing[index])
    return data
