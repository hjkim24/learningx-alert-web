from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from .courses import CourseSyncError, sync_courses
from .forms import CanvasTokenForm, CourseSelectionFormSet
from .models import CanvasConnection, CourseSelection
from .services import CanvasConnectionError, verify_and_store_connection


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
