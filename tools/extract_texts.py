"""Collect every user-facing Korean string (templates, Python, JS) into .git/copy/*.csv and *.md.

Run from the repo root: .venv/bin/python tools/extract_texts.py. IDs (T001…) follow file order, so
re-running after edits renumbers them; map a user's edits against the file they were given.
"""
import ast
import csv
import html.parser
import pathlib
import re
from collections import Counter

ROOT = pathlib.Path(".")
OUT = pathlib.Path(".git/copy")  # scratch output, not committed
HANGUL = re.compile(r"[가-힣]")
PAGES = {
    "templates/base.html": "공통 레이아웃 (머리글·바닥글)",
    "templates/account/login.html": "로그인",
    "templates/accounts/dashboard.html": "대시보드",
    "templates/accounts/_dashboard_history.html": "대시보드 · 다음 알림/최근 실행 카드",
    "templates/accounts/_item_groups.html": "대시보드·미리보기 · 과제/강의 목록",
    "templates/accounts/course_settings.html": "과목 선택",
    "templates/accounts/_notification_tabs.html": "알림 설정 · 탭",
    "templates/accounts/notification_settings.html": "알림 설정 · 시각",
    "templates/accounts/_alarm_row.html": "알림 설정 · 시각 한 줄",
    "templates/accounts/destination_settings.html": "알림 설정 · 알림 대상",
    "templates/accounts/excluded_items.html": "알림 설정 · 끈 항목",
    "templates/accounts/_excluded_row.html": "알림 설정 · 끈 항목 한 줄",
    "templates/accounts/preview.html": "알림 미리보기",
    "templates/accounts/run_detail.html": "실행 상세",
    "templates/accounts/account_settings.html": "계정 설정",
    "templates/accounts/access_denied.html": "접근 거부 / 가입 마감",
    "templates/accounts/feedback.html": "의견 보내기 페이지",
    "templates/accounts/_feedback_widget.html": "의견 보내기 버튼·대화상자",
    "templates/accounts/_feedback_fields.html": "의견 보내기 입력칸",
    "templates/guide/canvas_token.html": "Canvas 토큰 발급 가이드",
    "templates/guide/pwa_install.html": "홈 화면 추가(PWA) 가이드",
    "templates/legal/privacy.html": "개인정보처리방침",
    "templates/pwa/sw.js": "푸시 알림 (서비스 워커)",
    "static/app.js": "화면 동작 메시지 (JS)",
    "accounts/views.py": "화면 알림 메시지 (저장·오류 안내)",
    "accounts/forms.py": "입력칸 이름·검증 오류",
    "accounts/models.py": "선택지·상태 이름",
    "accounts/notifications.py": "Discord·Slack·푸시로 가는 알림 본문",
    "accounts/collection.py": "과목별 확인 결과 문구",
    "accounts/courses.py": "학기 이름",
    "accounts/schools.py": "학교 이름",
    "accounts/throttle.py": "요청 제한 안내",
    "accounts/admin_site.py": "관리자 화면",
    "accounts/templatetags/course_names.py": "과목명 표시",
    "config/pwa.py": "앱 설치 정보 (manifest)",
}
# Not shown to users: tab-label matching patterns, CLI/admin-only tools.
SKIP = {"learningx_alert/learningx.py", "learningx_alert/feasibility.py",
        "accounts/management/commands/list_feedback.py"}
rows = []


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


class TemplateText(html.parser.HTMLParser):
    ATTRS = {"alt", "aria-label", "placeholder", "title", "content", "value",
             "data-confirm", "data-loading-text"}

    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.path, self.buf, self.start, self.skip = path, [], None, 0

    def flush(self):
        text = norm("".join(self.buf))
        if HANGUL.search(text):
            rows.append((self.path, self.start, "본문", text))
        self.buf, self.start = [], None

    def handle_starttag(self, tag, attrs):
        self.flush()
        if tag in ("script", "style"):
            self.skip += 1
        for name, value in attrs:
            if name in self.ATTRS and value and HANGUL.search(value):
                rows.append((self.path, self.getpos()[0], f"{tag}[{name}]", norm(value)))

    def handle_endtag(self, tag):
        self.flush()
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if self.skip:
            return
        if self.start is None and data.strip():
            lead = data[: len(data) - len(data.lstrip())]
            self.start = self.getpos()[0] + lead.count("\n")
        self.buf.append(data)


def strip_template_logic(src):
    keep_lines = lambda m: " " + "\n" * m.group(0).count("\n")
    src = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", keep_lines, src, flags=re.S)
    src = re.sub(r"\{#.*?#\}", keep_lines, src, flags=re.S)
    return re.sub(r"\{%.*?%\}", keep_lines, src, flags=re.S)


for path in sorted(ROOT.glob("templates/**/*.html")):
    parser = TemplateText(str(path))
    parser.feed(strip_template_logic(path.read_text()))
    parser.flush()

JS_STRING = re.compile(r"([\"'`])((?:\\.|(?!\1).)*?[가-힣](?:\\.|(?!\1).)*?)\1")
for path in (ROOT / "templates/pwa/sw.js", ROOT / "static/app.js"):
    for number, line in enumerate(path.read_text().splitlines(), 1):
        for match in JS_STRING.finditer(line):
            rows.append((str(path), number, "JS 문자열", match.group(2)))

py_files = sorted(ROOT.glob("accounts/**/*.py")) + sorted(ROOT.glob("config/*.py"))
for path in py_files:
    rel = str(path)
    if "/tests/" in rel or "/migrations/" in rel or rel in SKIP:
        continue
    tree = ast.parse(path.read_text())
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
        and node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    inside_fstring = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            parts = []
            for value in node.values:
                inside_fstring.add(id(value))
                if isinstance(value, ast.Constant):
                    parts.append(str(value.value))
                else:
                    parts.append("{" + ast.unparse(value.value) + "}")
            text = norm("".join(parts))
            if HANGUL.search(text):
                rows.append((rel, node.lineno, "Python f-string", text))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings and id(node) not in inside_fstring
                and HANGUL.search(node.value)
                # Regex patterns (term / tab-label matching) are not shown to users.
                and not re.search(r"\\[sdw]|\(\?|[가-힣a-z]\|[가-힣a-z]", node.value)):
            rows.append((rel, node.lineno, "Python 문자열", norm(node.value)))

order = list(PAGES)
unique, seen = [], set()
for row in sorted(rows, key=lambda r: (order.index(r[0]) if r[0] in order else 999, r[0], r[1])):
    key = (row[0], row[1], row[3])
    if key not in seen:
        seen.add(key)
        unique.append(row)


def area(path):
    return PAGES.get(path, path)


with open(OUT / "learningx-alert-texts.csv", "w", newline="", encoding="utf-8-sig") as handle:
    writer = csv.writer(handle)
    writer.writerow(["ID", "화면/영역", "파일:줄", "종류", "현재 텍스트", "수정안"])
    for index, (path, number, kind, text) in enumerate(unique, 1):
        writer.writerow([f"T{index:03d}", area(path), f"{path}:{number}", kind, text, ""])

lines = [
    "# LearningX Alert 사이트 텍스트 전체 목록",
    "",
    f"총 {len(unique)}개. 바꿀 줄의 ID와 새 문장만 알려 주면 그대로 반영한다.",
    "`{...}`, `{{ ... }}`는 실제 값(과목명, 날짜, 개수 등)이 들어가는 자리라 그대로 둔다.",
]
current = None
for index, (path, number, kind, text) in enumerate(unique, 1):
    if area(path) != current:
        current = area(path)
        lines += ["", f"## {current}", f"`{path}`", "", "| ID | 줄 | 텍스트 |", "|---|---|---|"]
    safe = text.replace("|", "\\|")
    lines.append(f"| T{index:03d} | {number} | {safe} |")
(OUT / "learningx-alert-texts.md").write_text("\n".join(lines) + "\n")
print(len(unique))
for name, count in Counter(area(r[0]) for r in unique).most_common():
    print(count, name)
