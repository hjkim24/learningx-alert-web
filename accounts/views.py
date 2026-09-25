from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import CanvasTokenForm
from .models import CanvasConnection
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
