import datetime

from django.db import migrations


def add_default_schedule(apps, schema_editor):
    """Users who connected Canvas but never saved 알림 시각 had no alarms, so
    the scheduler never ran for them. Give them the default (3 days, 09:00 daily).
    """
    CanvasConnection = apps.get_model("accounts", "CanvasConnection")
    NotificationRule = apps.get_model("accounts", "NotificationRule")
    AlarmTime = apps.get_model("accounts", "AlarmTime")
    for connection in CanvasConnection.objects.all():
        rule, _ = NotificationRule.objects.get_or_create(user_id=connection.user_id)
        if not AlarmTime.objects.filter(rule=rule).exists():
            AlarmTime.objects.create(
                rule=rule,
                time=datetime.time(9, 0),
                weekdays=127,
                enabled=True,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_excluded_items"),
    ]

    operations = [
        # Reverse is a no-op: the added rows are ordinary user settings.
        migrations.RunPython(add_default_schedule, migrations.RunPython.noop),
    ]
