"""디자인 시스템: 스타일 가이드 권한, 그리고 DESIGN.md·app.css·템플릿이 서로 어긋나지 않는지."""

import ast
import re
from pathlib import Path

import pytest

from accounts.models import User
from web.views.ops import css_tokens

WEB = Path(__file__).resolve().parent
DESIGN_MD = WEB.parent.parent / "DESIGN.md"


def test_design_page_is_staff_only(client, member):
    assert client.get("/ops/design").status_code == 302  # 비로그인
    client.force_login(member)
    assert client.get("/ops/design").status_code in (302, 403, 404)  # 일반 멤버
    User.objects.filter(pk=member.pk).update(is_staff=True)
    r = client.get("/ops/design")
    assert r.status_code == 200
    body = r.content.decode()
    light, _ = css_tokens()
    for name in light:
        if name.startswith("--c-"):
            assert f"<code>{name}</code>" in body  # 견본은 app.css를 그대로 읽는다


def test_every_light_token_has_dark_value_for_colors():
    light, dark = css_tokens()
    missing = [k for k in light if k.startswith(("--c-", "--plant-")) and k not in dark]
    assert missing == []


@pytest.mark.skipif(not DESIGN_MD.exists(), reason="저장소 루트 DESIGN.md가 없는 배포 이미지")
def test_design_md_documents_every_token():
    light, _ = css_tokens()
    doc = DESIGN_MD.read_text(encoding="utf-8")
    assert [k for k in light if f"`{k}`" not in doc] == []


def test_templates_have_no_hardcoded_colors():
    """색은 토큰 클래스로만. 템플릿에 #RRGGBB를 직접 적지 않는다."""
    hits = []
    for p in (WEB / "templates").rglob("*.html"):
        for m in re.finditer(r"#[0-9A-Fa-f]{6}\b", p.read_text(encoding="utf-8")):
            hits.append(f"{p.name}:{m.group()}")
    assert hits == []


# ---------- 문구·접근성 자동 검증 (c-writing-a11y C2, systemization 5단계) ----------

TEMPLATES = sorted((WEB / "templates").rglob("*.html"))
SCRIPTS = sorted((WEB / "static").glob("*.js"))  # vendor/ 밑은 남의 코드라 뺀다
BUTTON = re.compile(r"<button\b((?:[^>{]|\{[^}]*\})*)>(.*?)</button>", re.S)
FIELD = re.compile(r"<(input|textarea|select)\b((?:[^>{]|\{[^}]*\})*)>", re.S)
NAMED = re.compile(r"\baria-label(?:ledby)?=")


def _where(p, s, pos):
    return f"{p.relative_to(WEB).as_posix()}:{s.count(chr(10), 0, pos) + 1}"


def _button_text(inner):
    return re.sub(r"<[^>]+>|\{#.*?#\}", "", inner).strip()


def test_no_browser_confirm_left():
    """(a) 확인은 공용 확인 창(data-confirm)으로만. <dialog>를 못 쓰는 브라우저용 대체 한 곳만 허용한다."""
    hits = []
    for p in TEMPLATES + SCRIPTS:
        s = p.read_text(encoding="utf-8")
        hits += [_where(p, s, m.start()) for m in re.finditer(r"hx-confirm|\bconfirm\(", s)]
    fallback = [h for h in hits if h.startswith("static/app.js")]
    assert len(fallback) == 1  # app.js askConfirm의 window.confirm 대체 경로
    assert [h for h in hits if h not in fallback] == []


def test_no_bare_ok_cancel_button_labels():
    """(b) 버튼은 대상+동사로. "확인"·"취소"·"OK" 단독은 결과를 알 수 없다(가이드 DESIGN_SYSTEM 231-233)."""
    banned = {
        "확인",
        "취소",
        "OK",
        "저장",
        "선택",
        "완료",
        "확정",
        "추가",
        "삭제",
        "연결",
        "만들기",
        "적용",
        "내보내기",
    }
    hits = []
    for p in TEMPLATES:
        s = p.read_text(encoding="utf-8")
        for m in BUTTON.finditer(s):
            if _button_text(m.group(2)) in banned:
                hits.append(_where(p, s, m.start()))
        for m in re.finditer(r'data-confirm-(?:ok|cancel)="([^"]*)"', s):
            if m.group(1).strip() in banned:
                hits.append(_where(p, s, m.start()))
    assert hits == []


COPY_BANNED = re.compile(
    r"목표일|목표 기한|마감|부하 현황|거버넌스|백링크|결과 선반|"
    r"업로드|비활성화된 계정|비활성 사용자|막힌 이유|멈춘 이유|"
    r"하세요|올리세요|고르세요|넣으세요|적으세요|받으세요|쓰세요|보세요|"
    r"나누세요|떼어내세요|바꾸세요|가져오세요|해요|했어요"
)


def _python_copy_literals(path):
    """모델 필드·주석·docstring·로그·테스트를 제외한 사용자 문구 리터럴."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    excluded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            excluded.add(id(node.value))  # docstring
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if (
                isinstance(owner, ast.Name) and owner.id in {"log", "logger", "logging", "models"}
            ) or (
                isinstance(owner, ast.Call)
                and isinstance(owner.func, ast.Attribute)
                and owner.func.attr == "getLogger"
            ):
                excluded.update(id(child) for child in ast.walk(node))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in excluded
        and re.search(r"[가-힣]", node.value)
    ]


def test_user_copy_uses_standard_terms_and_tone():
    """DESIGN.md 용어표. 식별자·모델 필드명·주석은 검사하지 않는다."""
    hits = []
    for path in TEMPLATES:
        if path.name == "landing.html":
            continue  # 랜딩 홍보 문구는 해요체를 섞는 예외(DESIGN.md 랜딩 절)
        source = path.read_text(encoding="utf-8")
        copy = re.sub(
            r"\{#.*?#\}|\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}|<!--.*?-->",
            "",
            source,
            flags=re.S,
        )
        hits.extend(
            f"{path.relative_to(WEB)}:{match.group()}" for match in COPY_BANNED.finditer(copy)
        )
    for path in WEB.parent.rglob("*.py"):
        if any(
            part in {".venv", "migrations", "skills", "mcp_server", "discord_service"}
            for part in path.parts
        ):
            continue
        if path.name == "models.py" or path.name == "tests.py" or path.name.startswith("test_"):
            continue
        for line, copy in _python_copy_literals(path):
            hits.extend(
                f"{path.relative_to(WEB.parent)}:{line}:{match.group()}"
                for match in COPY_BANNED.finditer(copy)
            )
    assert hits == []


def test_copy_scan_ignores_code_comments_and_model_fields(tmp_path):
    sample = tmp_path / "copy.py"
    sample.write_text(
        "# 목표일을 바꾸세요\n"
        '"""마감·거버넌스 구현 메모"""\n'
        'due_date = models.DateField("목표일")\n'
        'logger.warning("업로드 실패")\n'
        'message = f"{task_id} 목표일을 선택하세요."\n',
        encoding="utf-8",
    )
    assert _python_copy_literals(sample) == [(5, " 목표일을 선택하세요.")]


def test_inputs_have_labels_not_just_placeholders():
    """(c) 입력에는 label(감싸기·for) 또는 aria-label이 있어야 한다. placeholder는 라벨이 아니다."""
    label_for = {
        f for p in TEMPLATES for f in re.findall(r'\bfor="([^"]+)"', p.read_text(encoding="utf-8"))
    }
    hits = []
    for p in TEMPLATES:
        s = p.read_text(encoding="utf-8")
        for m in FIELD.finditer(s):
            attrs = m.group(2)
            if re.search(r'type="(?:hidden|submit|checkbox|radio|file)"', attrs) or NAMED.search(
                attrs
            ):
                continue
            idm = re.search(r'\bid="([^"]+)"', attrs)
            if idm and idm.group(1) in label_for:
                continue
            before = s[: m.start()]
            if before.rfind("<label") > before.rfind("</label>"):
                continue  # <label>로 감쌌다
            hits.append(_where(p, s, m.start()))
    assert hits == []


def test_icon_only_buttons_have_aria_label():
    """(d) 글자 없는 버튼(✕, «, × …)은 대상까지 넣은 aria-label이 있어야 한다."""
    hits = []
    for p in TEMPLATES:
        s = p.read_text(encoding="utf-8")
        for m in BUTTON.finditer(s):
            text = _button_text(m.group(2))
            if "{{" in text or "{%" in text or re.search(r"[가-힣A-Za-z0-9]", text):
                continue
            if not NAMED.search(m.group(1)):
                hits.append(_where(p, s, m.start()))
    assert hits == []


def _luminance(hex_color):
    h = hex_color.lstrip("#")
    ch = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def contrast(fg, bg):
    """WCAG 대비. 디자인 검토 가이드 scripts/check-contrast.py와 같은 공식."""
    a, b = _luminance(fg), _luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


# (전경, 배경, 최소 대비, 쓰임) — 글자는 4.5, 입력 경계·초점 같은 비텍스트는 3.0(WCAG 1.4.11)
CONTRAST_PAIRS = [
    ("ink", "bg", 4.5, "본문"),
    ("ink", "surface", 4.5, "카드 위 본문"),
    ("ink", "yellow", 4.5, "집계 면 hover"),
    ("ink", "sage", 4.5, "알림·대표 지표"),
    ("ink", "coral", 4.5, "막힘·메모"),
    ("muted", "bg", 4.5, "보조 글자"),
    ("muted", "surface", 4.5, "카드 위 보조 글자"),
    ("muted", "soft", 4.5, "보드 빈 열·배지"),
    ("accent", "bg", 4.5, "링크"),
    ("accent", "surface", 4.5, "카드 위 링크"),
    ("on-accent", "accent", 4.5, "주 버튼"),
    ("danger", "surface", 4.5, "위험 버튼 글자"),
    ("danger", "danger-soft", 4.5, "오류 알림"),
    ("success", "success-soft", 4.5, "완료 배지"),
    ("warning", "warning-soft", 4.5, "경고 알림"),
    ("info", "info-soft", 4.5, "정보 배지"),
    ("line-strong", "bg", 3.0, "입력 경계"),
    ("line-strong", "surface", 3.0, "카드 안 입력 경계"),
    ("line-strong", "soft", 3.0, "soft 면 위 입력 경계"),
    ("accent", "surface", 3.0, "초점 테두리"),
]


def test_color_pairs_meet_wcag_contrast():
    """(e) 쓰는 글자·바탕 조합이 라이트·다크 모두 AA를 넘는다. 토큰을 바꾸면 DESIGN.md 2.1 표도 고친다."""
    light, dark = css_tokens()
    failed = []
    for mode, tokens in (("light", light), ("dark", {**light, **dark})):
        for fg, bg, need, why in CONTRAST_PAIRS:
            got = contrast(tokens[f"--c-{fg}"].strip(), tokens[f"--c-{bg}"].strip())
            if got < need:
                failed.append(f"[{mode}] {fg}/{bg} {got:.2f} < {need} ({why})")
    assert failed == []


def test_warning_message_gets_warn_style_and_glyph(client, member, org):
    """B4: messages.warning은 일반 알림이 아니라 ⚠ + .notice.warn으로 보인다."""
    client.force_login(member)
    body = client.get(f"/orgs/{org.pk}/requests/1", follow=True).content.decode()
    m = re.search(
        r'<div class="notice warn" role="status">\s*<span aria-hidden="true">⚠</span>', body
    )
    assert m and "조직 관리자만" in body


def test_shared_confirm_dialog_is_on_every_page(client, member, org):
    client.force_login(member)
    body = client.get("/today").content.decode()
    assert '<dialog id="confirm"' in body and 'value="ok"' in body and "그대로 두기" in body


def test_project_link_delete_asks_first(client, admin, org):
    """B6: 참고 링크 삭제도 확인을 받고, 버튼 이름에 대상이 들어간다."""
    from projects.services import create_project
    from tasks.models import Link

    p = create_project(org=org, name="앱", actor=admin)
    Link.objects.create(project=p, title="기획서", url="https://example.com", created_by=admin)
    client.force_login(admin)
    body = client.get(f"/projects/{p.pk}").content.decode()
    assert 'data-confirm-ok="링크 삭제"' in body and 'aria-label="링크 기획서 삭제"' in body


def test_contrast_formula_matches_known_values():
    assert round(contrast("#000000", "#FFFFFF"), 1) == 21.0
    assert round(contrast("#777777", "#FFFFFF"), 2) == 4.48
