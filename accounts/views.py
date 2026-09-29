import json
from datetime import datetime

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from .collection import TRANSIENT_ERROR_CODES, alert_selection_filter, collect_for_user
from .courses import CourseSyncError, group_forms_by_term, sync_courses
from .forms import (
    AlarmFormSet,
    CanvasTokenForm,
    CourseSelectionFormSet,
    DestinationForm,
    NotificationRuleForm,
)
from .models import (
    WEEKDAY_LABELS,
    ensure_default_rule,
    AlarmTime,
    CanvasConnection,
    CourseRunResult,
    CourseSelection,
    Delivery,
    Destination,
    ExcludedItem,
    NotificationRule,
    ScheduledRun,
)
from . import webpush
from .notifications import (
    AmbiguousDeliveryError,
    DefiniteDeliveryError,
    DestinationLimitError,
    DuplicateDestinationError,
    SubscriptionGoneError,
    WebhookValidationError,
    render_notification,
    save_destination,
    save_push_subscription,
    send_to_destination,
    target_fingerprint,
    test_message_for,
)
from .services import (
    CanvasConnectionError,
    decrypt_secret,
    verify_and_store_connection,
)
from .scheduling import SEOUL, active_alarms, next_alarm_at


@login_required
@require_GET
def dashboard(request):
    connection = (
        CanvasConnection.objects.filter(user=request.user)
        .values("canvas_user_id", "canvas_name", "verified_at", "needs_reconnect")
        .first()
    )
    selected_course_count = CourseSelection.objects.filter(
        alert_selection_filter(),
        user=request.user,
    ).count()
    destinations = list(
        Destination.objects.filter(user=request.user).values("kind", "label", "status")
    )
    rule = NotificationRule.objects.filter(user=request.user).first()
    next_run = None
    if (
        connection
        and not connection["needs_reconnect"]
        and selected_course_count
        and destinations
        and rule
    ):
        now = timezone.now()
        current_slot_claimed = ScheduledRun.objects.filter(
            user=request.user,
            scheduled_for=now.replace(second=0, microsecond=0),
        ).exists()
        next_run = next_alarm_at(
            rule,
            now,
            current_slot_claimed=current_slot_claimed,
        )

    recent_runs = list(
        ScheduledRun.objects.filter(user=request.user)
        .only(
            "id",
            "scheduled_for",
            "status",
            "safe_error_code",
            "finished_at",
        )[:5]
    )
    latest_run = recent_runs[0] if recent_runs else None
    course_failures = CourseRunResult.objects.none()
    delivery_problems = Delivery.objects.none()
    if latest_run:
        course_failures = CourseRunResult.objects.filter(
            run=latest_run,
            run__user=request.user,
            status=CourseRunResult.Status.FAILED,
        ).only("course_name", "error_code", "safe_summary")
        delivery_problems = Delivery.objects.filter(
            run=latest_run,
            run__user=request.user,
            status__in=(
                Delivery.Status.DEFINITELY_FAILED,
                Delivery.Status.NEEDS_REVIEW,
            ),
        ).only(
            "part_number",
            "status",
            "safe_error_code",
            "destination_kind",
            "destination_label",
        )
    return render(
        request,
        "accounts/dashboard.html",
        {
            "connection": connection,
            "destinations": destinations,
            "destination_kinds": sorted(
                {Destination.Kind(entry["kind"]).label for entry in destinations}
            ),
            "course_failures": course_failures,
            "delivery_problems": delivery_problems,
            "form": CanvasTokenForm(),
            "next_run": next_run,
            "recent_runs": recent_runs,
            "rule": rule,
            "active_alarms": active_alarms(rule) if rule else [],
            "selected_course_count": selected_course_count,
        },
    )


@login_required
@require_GET
def run_detail(request, pk):
    run = get_object_or_404(
        ScheduledRun.objects.prefetch_related(
            "course_results",
            "items",
            "deliveries",
        ),
        pk=pk,
        user=request.user,
    )
    return render(request, "accounts/run_detail.html", {"run": run})


@login_required
@require_POST
def account_delete(request):
    user = request.user
    logout(request)
    user.delete()
    return redirect("account_login")


@sensitive_post_parameters("token")
@login_required
@require_POST
def canvas_connect(request):
    form = CanvasTokenForm(request.POST)
    if form.is_valid():
        try:
            verify_and_store_connection(
                user=request.user,
                token=form.cleaned_data["token"],
            )
        except CanvasConnectionError:
            messages.error(
                request,
                "Canvas에 연결하지 못했어요. 토큰을 다시 확인해 주세요.",
            )
        else:
            # New users get a working schedule right away (3 days, daily 09:00);
            # without one the scheduler would silently never run for them.
            ensure_default_rule(request.user)
            messages.success(request, "Canvas를 연결했어요.")
            try:
                courses = sync_courses(request.user)
            except CourseSyncError:
                messages.warning(
                    request,
                    "과목은 불러오지 못했어요. 과목 선택에서 새로고침해 주세요.",
                )
            else:
                messages.success(
                    request,
                    f"수강 과목 {courses.count()}개를 불러왔어요. 과목 선택에서 알림을 켜 주세요.",
                )
    return redirect("dashboard")


@login_required
@require_POST
def canvas_disconnect(request):
    CanvasConnection.objects.filter(user=request.user).delete()
    messages.success(request, "Canvas 연결을 해제했어요.")
    return redirect("dashboard")


@login_required
@require_GET
def course_settings(request):
    formset = CourseSelectionFormSet(
        queryset=CourseSelection.objects.filter(user=request.user)
    )
    return render(
        request,
        "accounts/course_settings.html",
        _course_settings_context(formset),
    )


def _course_settings_context(formset):
    return {
        "formset": formset,
        "term_groups": group_forms_by_term(formset.forms, timezone.now()),
    }


@login_required
@require_POST
def course_sync(request):
    try:
        sync_courses(request.user)
    except CanvasConnection.DoesNotExist:
        messages.error(request, "Canvas를 먼저 연결해 주세요.")
    except CourseSyncError:
        messages.error(
            request,
            "과목을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.",
        )
    else:
        messages.success(request, "과목 목록을 새로고침했어요.")
    return redirect("course_settings")


@login_required
@require_POST
def course_settings_save(request):
    queryset = CourseSelection.objects.filter(user=request.user)
    formset = CourseSelectionFormSet(request.POST, queryset=queryset)
    formset_is_valid = formset.is_valid()
    allowed_ids = {str(pk) for pk in queryset.values_list("pk", flat=True)}
    submitted_ids = {
        request.POST.get(f"form-{index}-id") for index in range(len(formset.forms))
    }
    forged_id = bool(submitted_ids - allowed_ids)

    if formset_is_valid and not forged_id:
        formset.save()
        messages.success(request, "저장했어요.")
        return redirect("course_settings")

    if forged_id:
        messages.error(request, "저장할 수 없는 과목이 섞여 있어요. 새로고침한 뒤 다시 시도해 주세요.")
    return render(
        request,
        "accounts/course_settings.html",
        _course_settings_context(formset),
        status=400,
    )


@login_required
@require_POST
def preview(request):
    now = timezone.now()
    try:
        result = collect_for_user(request.user, now)
    except CanvasConnection.DoesNotExist:
        messages.error(request, "Canvas를 먼저 연결해 주세요.")
        return redirect("dashboard")
    return render(
        request,
        "accounts/preview.html",
        {
            "result": result,
            "day_groups": _group_items_by_day(result.items, now),
            "failed_outcomes": [o for o in result.outcomes if o.status == "failed"],
            "transient_failure": any(o.error_code in TRANSIENT_ERROR_CODES for o in result.outcomes),
            "message_text": render_notification(result, now),
        },
    )


def _group_items_by_day(items, now):
    """Group alert items by KST due date with a D-day label, soonest first."""
    today = now.astimezone(SEOUL).date()
    groups = []
    for item in sorted(items, key=lambda entry: entry.due_at):
        day = item.due_at.astimezone(SEOUL).date()
        if not groups or groups[-1]["date"] != day:
            delta = (day - today).days
            label = "오늘" if delta == 0 else f"D-{delta}" if delta > 0 else f"D+{-delta}"
            groups.append(
                {"date": day, "dday": label, "urgent": delta <= 3, "items": []}
            )
        groups[-1]["items"].append(item)
    return groups


WEBHOOK_URL_ERROR = "Discord나 Slack 웹훅 URL(https://…)을 넣어 주세요."
DUPLICATE_ERROR = "이미 등록한 웹훅이에요."
LIMIT_ERROR = f"알림 대상은 최대 {Destination.MAX_PER_USER}개까지 등록할 수 있어요."


def _alarm_formset(rule, data=None):
    """Alarm rows for a rule; a user with none starts with one 09:00 daily row."""
    formset = AlarmFormSet(data, instance=rule or NotificationRule(), prefix="alarms")
    if data is None and not (rule and rule.pk and rule.alarms.exists()):
        formset.extra = 1
    return formset


def _save_schedule(request, rule_form, alarm_formset):
    saved_rule = rule_form.save(commit=False)
    saved_rule.user = request.user
    saved_rule.save()
    alarm_formset.instance = saved_rule
    alarm_formset.save()
    return saved_rule


def _notification_settings_context(request, *, rule_form=None, alarm_formset=None):
    rule = NotificationRule.objects.filter(user=request.user).first()
    if rule_form is None:
        rule_form = NotificationRuleForm(instance=rule or NotificationRule())
    if alarm_formset is None:
        alarm_formset = _alarm_formset(rule)
    return {
        "destination_count": Destination.objects.filter(user=request.user).count(),
        "excluded_count": ExcludedItem.objects.filter(
            user=request.user, due_at__gte=timezone.now()
        ).count(),
        "rule_form": rule_form,
        "alarm_formset": alarm_formset,
        "alarm_limit": AlarmTime.MAX_PER_RULE,
        "weekday_labels": WEEKDAY_LABELS,
    }


def _destination_settings_context(request, *, destination_form=None):
    destinations = list(Destination.objects.filter(user=request.user))
    push_enabled = webpush.web_push_enabled()
    return {
        "destinations": destinations,
        "destination_count": len(destinations),
        "destination_form": destination_form or DestinationForm(),
        "destination_limit": Destination.MAX_PER_USER,
        "push_enabled": push_enabled,
        "vapid_public_key": webpush.vapid_public_key() if push_enabled else "",
    }


def _render_destinations(request, destination_form, status=400):
    return render(
        request,
        "accounts/destination_settings.html",
        _destination_settings_context(request, destination_form=destination_form),
        status=status,
    )


def _add_webhook(request, form):
    """Save the form's webhook as a new destination; report errors on the form."""
    try:
        save_destination(
            request.user,
            form.cleaned_data["kind"],
            form.cleaned_data["webhook_url"],
            form.cleaned_data.get("label", ""),
        )
    except WebhookValidationError:
        form.add_error("webhook_url", WEBHOOK_URL_ERROR)
    except DuplicateDestinationError:
        form.add_error("webhook_url", DUPLICATE_ERROR)
    except DestinationLimitError:
        form.add_error(None, LIMIT_ERROR)
    else:
        return True
    return False


@login_required
@require_GET
def notification_settings(request):
    return render(
        request,
        "accounts/notification_settings.html",
        _notification_settings_context(request),
    )


@login_required
@require_GET
def destination_settings(request):
    return render(
        request,
        "accounts/destination_settings.html",
        _destination_settings_context(request),
    )


@login_required
@require_GET
def account_settings(request):
    return render(request, "accounts/account_settings.html")


@login_required
@require_POST
def notification_settings_save(request):
    """Save the lookahead range and alarm rows together, or nothing at all."""
    rule = NotificationRule.objects.filter(user=request.user).first()
    rule_form = NotificationRuleForm(request.POST, instance=rule)
    alarm_formset = _alarm_formset(rule, request.POST)

    rule_valid = rule_form.is_valid()
    alarms_valid = alarm_formset.is_valid()
    if not (rule_valid and alarms_valid):
        return render(
            request,
            "accounts/notification_settings.html",
            _notification_settings_context(
                request, rule_form=rule_form, alarm_formset=alarm_formset
            ),
            status=400,
        )

    with transaction.atomic():
        _save_schedule(request, rule_form, alarm_formset)

    if Destination.objects.filter(user=request.user).exists():
        messages.success(request, "저장했어요.")
    else:
        messages.warning(
            request,
            "저장했어요. 알림을 받으려면 알림 대상을 추가해 주세요.",
        )
    return redirect("notification_settings")


@login_required
@require_POST
def notification_rule_save(request):
    rule = NotificationRule.objects.filter(user=request.user).first()
    form = NotificationRuleForm(request.POST, instance=rule)
    alarm_formset = _alarm_formset(rule, request.POST)
    rule_valid = form.is_valid()
    alarms_valid = alarm_formset.is_valid()
    if not (rule_valid and alarms_valid):
        return render(
            request,
            "accounts/notification_settings.html",
            _notification_settings_context(
                request, rule_form=form, alarm_formset=alarm_formset
            ),
            status=400,
        )
    with transaction.atomic():
        _save_schedule(request, form, alarm_formset)
    messages.success(request, "저장했어요.")
    return redirect("notification_settings")


@sensitive_post_parameters("webhook_url")
@sensitive_variables("webhook_url")
@login_required
@require_POST
def destination_save(request):
    """Add one Discord/Slack webhook destination."""
    form = DestinationForm(request.POST, require_url=True)
    if form.is_valid() and _add_webhook(request, form):
        messages.success(request, "알림 대상을 추가했어요.")
        return redirect("destination_settings")
    return _render_destinations(request, form)


@login_required
@require_POST
def destination_delete(request, pk):
    deleted, _ = Destination.objects.filter(user=request.user, pk=pk).delete()
    if deleted:
        messages.success(request, "알림 대상을 삭제했어요.")
    else:
        messages.error(request, "알림 대상을 찾을 수 없어요.")
    return redirect("destination_settings")


@sensitive_variables("secret")
@login_required
@require_POST
def destination_test(request, pk):
    destination = Destination.objects.filter(user=request.user, pk=pk).first()
    if not destination:
        messages.error(request, "알림 대상을 먼저 추가해 주세요.")
        return redirect("destination_settings")

    secret = decrypt_secret(destination.encrypted_webhook_url)
    try:
        send_to_destination(
            destination.kind,
            secret,
            test_message_for(destination.kind),
        )
    except WebhookValidationError:
        destination.status = Destination.Status.DEFINITELY_FAILED
        messages.error(
            request,
            "저장된 웹훅을 쓸 수 없어요. 새 URL로 다시 추가해 주세요.",
        )
    except SubscriptionGoneError:
        destination.delete()
        messages.error(
            request,
            "이 브라우저의 푸시 등록이 만료돼서 삭제했어요. 그 기기에서 다시 켜 주세요.",
        )
        return redirect("destination_settings")
    except DefiniteDeliveryError:
        destination.status = Destination.Status.DEFINITELY_FAILED
        messages.error(request, "시험 알림을 보내지 못했어요.")
    except AmbiguousDeliveryError:
        destination.status = Destination.Status.NEEDS_REVIEW
        messages.warning(
            request,
            "전송됐는지 확인하지 못했어요. 채널에 도착했는지 직접 봐 주세요.",
        )
    else:
        destination.status = Destination.Status.SUCCEEDED
        messages.success(
            request,
            "시험 알림을 보냈어요. 기기에 떴는지 확인해 보세요."
            if destination.kind == Destination.Kind.WEBPUSH
            else "시험 알림을 보냈어요.",
        )
    destination.last_tested_at = timezone.now()
    destination.save(update_fields=("status", "last_tested_at"))
    return redirect("destination_settings")


MAX_PUSH_BODY_BYTES = 8192


def _json_body(request):
    if len(request.body) > MAX_PUSH_BODY_BYTES:
        raise ValueError
    data = json.loads(request.body)
    if not isinstance(data, dict):
        raise ValueError
    return data


@sensitive_variables()
@login_required
@require_POST
def push_subscribe(request):
    """Register this browser's PushSubscription (JSON body, CSRF header)."""
    if not webpush.web_push_enabled():
        return JsonResponse({"ok": False, "error": "push_disabled"}, status=404)
    try:
        data = _json_body(request)
        label = str(data.get("label", ""))[:64]
        destination, created = save_push_subscription(
            request.user,
            data.get("subscription"),
            label,
        )
    except (ValueError, UnicodeDecodeError, webpush.PushValidationError):
        return JsonResponse({"ok": False, "error": "subscription_invalid"}, status=400)
    except DestinationLimitError:
        return JsonResponse({"ok": False, "error": "destination_limit"}, status=409)
    except DuplicateDestinationError:
        return JsonResponse({"ok": False, "error": "duplicate"}, status=409)
    # The settings page re-syncs an existing browser subscription on every
    # load; only a real registration deserves a flash message.
    if created:
        messages.success(request, "이 브라우저를 알림 대상에 추가했어요. 시험 알림으로 확인해 보세요.")
    elif not data.get("silent"):
        messages.success(request, "이 브라우저의 푸시 등록을 갱신했어요.")
    return JsonResponse({"ok": True, "id": destination.pk, "created": created})


@sensitive_variables()
@login_required
@require_POST
def push_unsubscribe(request):
    """Remove the destination matching this browser's endpoint, if any."""
    try:
        endpoint = str(_json_body(request).get("endpoint", ""))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "subscription_invalid"}, status=400)
    deleted, _ = Destination.objects.filter(
        user=request.user,
        kind=Destination.Kind.WEBPUSH,
        target_fingerprint=target_fingerprint(Destination.Kind.WEBPUSH, endpoint),
    ).delete()
    if deleted:
        messages.success(request, "이 브라우저의 푸시 알림을 껐어요.")
    return JsonResponse({"ok": True, "deleted": bool(deleted)})


EXCLUDABLE_TYPES = {"assignment", "lecture", "material"}


def _wants_json(request):
    return "application/json" in request.headers.get("Accept", "")


@login_required
@require_POST
def item_exclude(request):
    """Mute one alert item (from the preview) until its deadline changes."""
    data = request.POST
    try:
        course_id = int(data.get("canvas_course_id", ""))
        item_type = data.get("item_type", "")
        external_id = data.get("external_id", "").strip()
        due_at = datetime.fromisoformat(data.get("due_at", ""))
        if (
            item_type not in EXCLUDABLE_TYPES
            or not external_id
            or len(external_id) > 128
            or due_at.tzinfo is None
        ):
            raise ValueError
    except (TypeError, ValueError):
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": "invalid_item"}, status=400)
        messages.error(request, "알림을 끌 항목을 찾지 못했어요.")
        return redirect("excluded_items")

    # Only courses the user actually has; the title is display-only.
    selection = CourseSelection.objects.filter(
        user=request.user, canvas_course_id=course_id
    ).first()
    if selection is None:
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": "unknown_course"}, status=404)
        messages.error(request, "알림을 끌 항목을 찾지 못했어요.")
        return redirect("excluded_items")

    ExcludedItem.objects.update_or_create(
        user=request.user,
        canvas_course_id=course_id,
        item_type=item_type,
        external_id=external_id,
        defaults={
            "course_name": selection.course_name[:255],
            "title": data.get("title", "")[:500] or "제목 없음",
            "due_at": due_at,
            "created_at": timezone.now(),
        },
    )
    if _wants_json(request):
        count = ExcludedItem.objects.filter(user=request.user).count()
        return JsonResponse({"ok": True, "excluded_count": count})
    messages.success(request, "이 항목의 알림을 껐어요.")
    return redirect("excluded_items")


@login_required
@require_POST
def item_include(request, pk):
    deleted, _ = ExcludedItem.objects.filter(user=request.user, pk=pk).delete()
    if _wants_json(request):
        return JsonResponse({"ok": bool(deleted)}, status=200 if deleted else 404)
    if deleted:
        messages.success(request, "다시 켰어요. 다음 예약 알림부터 들어가요.")
    return redirect("excluded_items")


@login_required
@require_GET
def excluded_items(request):
    now = timezone.now()
    items = list(ExcludedItem.objects.filter(user=request.user))
    return render(
        request,
        "accounts/excluded_items.html",
        {
            "upcoming": [item for item in items if item.due_at >= now],
            "past": [item for item in items if item.due_at < now],
        },
    )
