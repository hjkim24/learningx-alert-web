"""Plain-language labels for run results: users see these, codes stay in data-error-code."""

from django import template

from accounts.notifications import ITEM_TYPE_LABELS

register = template.Library()

# Every safe_error_code a run or delivery can carry (accounts/scheduling.py).
ERROR_LABELS = {
    "delivery_definite": "받는 곳에서 전송을 거부했어요",
    "delivery_ambiguous": "전송됐는지 확인하지 못했어요",
    "delivery_unexpected": "전송 중 예상하지 못한 오류가 났어요",
    "delivery_state_conflict": "같은 알림이 두 번 가지 않도록 멈췄어요",
    "push_subscription_gone": "브라우저 푸시 구독이 만료됐어요",
    "destination_missing": "알림 대상이 없어서 보내지 못했어요",
    "run_failed": "실행 중 오류가 났어요",
    "interrupted_sending": "보내는 도중 중단됐어요",
    "interrupted_definite_failure": "중단된 뒤 전송 실패로 끝났어요",
    "interrupted_after_confirmation": "중단돼서 일부 전송을 확인하지 못했어요",
}


@register.filter
def error_label(code):
    return ERROR_LABELS.get(code, "원인을 확인하지 못했어요")


@register.filter
def item_kind(item_type):
    return ITEM_TYPE_LABELS.get(item_type, "알림")
