import datetime

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def copy_times_to_alarms(apps, schema_editor):
    """Keep every existing schedule: each stored time becomes a daily alarm."""
    NotificationRule = apps.get_model("accounts", "NotificationRule")
    AlarmTime = apps.get_model("accounts", "AlarmTime")
    for rule in NotificationRule.objects.all():
        times = {rule.first_time, rule.second_time} - {None}
        AlarmTime.objects.bulk_create(
            [
                AlarmTime(rule=rule, time=value, weekdays=127, enabled=True)
                for value in sorted(times)
            ]
        )


def copy_alarms_to_times(apps, schema_editor):
    NotificationRule = apps.get_model("accounts", "NotificationRule")
    for rule in NotificationRule.objects.all():
        times = list(rule.alarms.order_by("time").values_list("time", flat=True)[:2])
        rule.first_time = times[0] if times else datetime.time(9, 0)
        rule.second_time = times[1] if len(times) > 1 else None
        rule.save(update_fields=("first_time", "second_time"))


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_multi_destination_webpush"),
    ]

    operations = [
        migrations.CreateModel(
            name="AlarmTime",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("time", models.TimeField(default=datetime.time(9, 0))),
                (
                    "weekdays",
                    models.PositiveSmallIntegerField(
                        default=127,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(127),
                        ],
                    ),
                ),
                ("enabled", models.BooleanField(default=True)),
                (
                    "rule",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="alarms",
                        to="accounts.notificationrule",
                    ),
                ),
            ],
            options={"ordering": ("time", "id")},
        ),
        migrations.AddConstraint(
            model_name="alarmtime",
            constraint=models.UniqueConstraint(fields=("rule", "time"), name="unique_rule_alarm_time"),
        ),
        migrations.AddConstraint(
            model_name="alarmtime",
            constraint=models.CheckConstraint(
                condition=models.Q(("weekdays__gte", 1), ("weekdays__lte", 127)),
                name="alarm_weekdays_in_range",
            ),
        ),
        migrations.RunPython(copy_times_to_alarms, copy_alarms_to_times),
        migrations.RemoveConstraint(
            model_name="notificationrule",
            name="notification_times_are_distinct",
        ),
        migrations.RemoveField(model_name="notificationrule", name="first_time"),
        migrations.RemoveField(model_name="notificationrule", name="second_time"),
    ]
