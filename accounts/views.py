from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_POST

from .collection import collect_for_user
from .courses import CourseSyncError, sync_courses
from .forms import CanvasTokenForm, CourseSelectionFormSet, DestinationForm
from .models import CanvasConnection, CourseSelection, Destination
from .notifications import (
    AmbiguousDeliveryError,
    DefiniteDeliveryError,
    WebhookValidationError,
    save_destination,
    send_webhook_part,
)
from .services import (
    CanvasConnectionError,
    decrypt_secret,
    verify_and_store_connection,
)


@login_required
def dashboard(request):
    connection = (
        CanvasConnection.objects.filter(user=request.user)
        .values("canvas_user_id", "canvas_name", "verified_at")
        .first()
    )
    return render(
        request,
        "accounts/dashboard.html",
        {"connection": connection, "form": CanvasTokenForm()},
    )


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
                "Canvas 연결을 확인하지 못했습니다. 토큰을 다시 확인해 주세요.",
            )
        else:
            messages.success(request, "Canvas 계정을 연결했습니다.")
    return redirect("dashboard")


@login_required
@require_POST
def canvas_disconnect(request):
    CanvasConnection.objects.filter(user=request.user).delete()
    messages.success(request, "Canvas 연결을 해제했습니다.")
    return redirect("dashboard")


@login_required
def course_settings(request):
    try:
        sync_courses(request.user)
    except CanvasConnection.DoesNotExist:
        messages.error(request, "Canvas 계정을 먼저 연결해 주세요.")
    except CourseSyncError:
        messages.error(
            request,
            "과목 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
        )

    formset = CourseSelectionFormSet(
        queryset=CourseSelection.objects.filter(user=request.user)
    )
    return render(
        request,
        "accounts/course_settings.html",
        {"formset": formset},
    )


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
        messages.success(request, "과목 알림 설정을 저장했습니다.")
        return redirect("course_settings")

    if forged_id:
        messages.error(request, "유효하지 않은 과목이 포함되어 있습니다.")
    return render(
        request,
        "accounts/course_settings.html",
        {"formset": formset},
        status=400,
    )


@login_required
@require_POST
def preview(request):
    try:
        result = collect_for_user(request.user, timezone.now())
    except CanvasConnection.DoesNotExist:
        messages.error(request, "먼저 Canvas 계정을 연결해 주세요.")
        return redirect("dashboard")
    return render(request, "accounts/preview.html", {"result": result})


@sensitive_post_parameters("webhook_url")
@sensitive_variables("webhook_url")
@login_required
@require_POST
def destination_save(request):
    existing = Destination.objects.filter(user=request.user).first()
    form = DestinationForm(request.POST, existing=existing)
    if not form.is_valid():
        return HttpResponseBadRequest("알림 대상 설정을 확인해 주세요.")

    webhook_url = form.cleaned_data["webhook_url"]
    if webhook_url:
        try:
            save_destination(
                request.user,
                form.cleaned_data["kind"],
                webhook_url,
            )
        except WebhookValidationError:
            return HttpResponseBadRequest("유효한 웹훅 URL을 입력해 주세요.")
    messages.success(request, "알림 대상을 저장했습니다.")
    return redirect("dashboard")


@login_required
@require_POST
def destination_delete(request):
    Destination.objects.filter(user=request.user).delete()
    messages.success(request, "알림 대상을 삭제했습니다.")
    return redirect("dashboard")


@sensitive_variables("webhook_url")
@login_required
@require_POST
def destination_test(request):
    destination = Destination.objects.filter(user=request.user).first()
    if not destination:
        messages.error(request, "알림 대상을 먼저 저장해 주세요.")
        return redirect("dashboard")

    webhook_url = decrypt_secret(destination.encrypted_webhook_url)
    try:
        send_webhook_part(
            destination.kind,
            webhook_url,
            "LearningX Alert 시험 알림입니다.",
        )
    except DefiniteDeliveryError:
        destination.status = Destination.Status.DEFINITELY_FAILED
        messages.error(request, "시험 알림 전송에 실패했습니다.")
    except AmbiguousDeliveryError:
        destination.status = Destination.Status.NEEDS_REVIEW
        messages.warning(
            request,
            "전송 결과를 확인할 수 없습니다. 대상 채널을 직접 확인해 주세요.",
        )
    else:
        destination.status = Destination.Status.SUCCEEDED
        messages.success(request, "시험 알림 전송을 확인했습니다.")
    destination.last_tested_at = timezone.now()
    destination.save(update_fields=("status", "last_tested_at"))
    return redirect("dashboard")
