"""Split SKKU Canvas course names into a readable title and metadata line."""

import re

from django import template

register = template.Library()

# e.g. "디지털시스템_ICE3024_42(임완수)", "안전교육_SFE7262_I1",
# "Advanced Materials Design(CapstoneDesign)_EAM3098_41(조형균)".
COURSE_NAME = re.compile(
    r"^(?P<title>.+?)\s*_(?P<code>[A-Z]{2,5}\d{3,5})_(?P<section>[A-Z0-9]{1,4})"
    r"(?:\((?P<professor>[^()]*)\))?\s*$"
)


def split_course_name(name):
    """Return {"title", "code", "section", "professor"}; unknown shapes keep the raw name."""
    raw = " ".join(str(name or "").split())
    match = COURSE_NAME.match(raw)
    if not match:
        return {"title": raw, "code": "", "section": "", "professor": ""}
    return {
        "title": match["title"].strip(),
        "code": match["code"],
        "section": match["section"],
        "professor": (match["professor"] or "").strip(),
    }


@register.filter
def course_parts(name):
    return split_course_name(name)


@register.filter
def course_title(name):
    return split_course_name(name)["title"]
