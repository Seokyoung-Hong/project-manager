"""마크다운 긴 글 칸은 모두 공용 편집기(md-field.js, textarea[data-md])를 쓴다. 서식 줄 위치만 칸마다 다르다."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parent
TPL = WEB_DIR / "templates"
HX = {"HX-Request": "true"}


@pytest.fixture
def logged(client, member):
    client.login(username="member1", password="pw12345678")
    return client


# 템플릿 → (data-md 칸 수, 서식 줄 위치)
TARGETS = {
    "tasks/_panel.html": (3, "bottom"),
    "tasks/_decisions.html": (4, "bottom"),
    "tasks/_stop.html": (2, "bottom"),
    "requests/new.html": (1, "bottom"),
    "projects/settings.html": (1, "top"),
    "orgs/governance.html": (1, "top"),
    "portfolio/index.html": (1, "top"),
}


def _md_textareas(src):
    return [t for t in re.findall(r"<textarea[^>]*>", src) if "data-md" in t]


def test_every_long_markdown_field_uses_the_shared_editor():
    for name, (count, pos) in TARGETS.items():
        tags = _md_textareas((TPL / name).read_text(encoding="utf-8"))
        assert len(tags) == count, name
        assert all(f'data-toolbar="{pos}"' in t for t in tags), name


def test_read_only_and_one_line_textareas_are_excluded():
    """복사용 프롬프트(readonly)와 한 줄짜리(프로젝트 목적, 운영 사유)는 일반 textarea로 둔다."""
    for path in TPL.rglob("*.html"):
        for tag in re.findall(r"<textarea[^>]*>", path.read_text(encoding="utf-8")):
            if "readonly" in tag:
                assert "data-md" not in tag, path
    for name in (
        "projects/_dialog.html",
        "ops/_confirm.html",
        "integrations/help.html",
        "projects/repo.html",
    ):
        assert not _md_textareas((TPL / name).read_text(encoding="utf-8")), name
    # AI 초안 붙여넣기 칸은 원문 그대로 받아야 하므로 일반 textarea다
    assert 'name="body_md" rows="18" placeholder' in (TPL / "portfolio/index.html").read_text(
        encoding="utf-8"
    )


def test_doc_editor_uses_shared_toolbar_without_text_buttons():
    """문서·회의록의 예전 글자 도구 막대는 없고, 공용 서식 줄(아이콘만)을 칸 위에 붙인다."""
    editor = (TPL / "docs" / "_editor.html").read_text(encoding="utf-8")
    assert "tt-bar" not in editor and "data-cmd" not in editor
    assert '<div class="mdf" data-toolbar="top">' in editor
    script = (WEB_DIR / "static" / "doc-tiptap.js").read_text(encoding="utf-8")
    assert 'import { load, toolbar } from "./md-field.js"' in script
    shared = (WEB_DIR / "static" / "md-field.js").read_text(encoding="utf-8")
    # 서식 줄 버튼은 아이콘(svg)만, 이름은 aria-label·title
    assert (
        'class="btn sm icon" data-k="${k}" aria-label="${INFO[k].label}" title="${tip(k)}"'
        in shared
    )


def test_panel_renders_md_fields_and_loads_script(logged, task):
    body = logged.get(f"/tasks/{task.pk}/panel").content.decode()
    assert body.count('data-md data-toolbar="bottom"') == 3
    assert 'hx-trigger="change"' in body  # 자동 저장은 원래 textarea의 change가 그대로 맡는다
    page = logged.get("/today").content.decode()
    assert "md-field.js" in page and 'type="module"' in page


def test_stop_reason_box_uses_md_field(logged, task):
    body = logged.get(f"/tasks/{task.pk}/panel?block=1").content.decode()
    assert re.search(
        r'<textarea id="stop-reason-\d+" class="textarea" name="reason"[^>]*data-md', body
    )
    assert f'<label class="label" for="stop-reason-{task.pk}">' in body


BUNDLE_DIR = WEB_DIR.parents[1] / "tools" / "tiptap-bundle"


@pytest.mark.skipif(
    not shutil.which("node") or not (BUNDLE_DIR / "node_modules" / "happy-dom").exists(),
    reason="node와 tools/tiptap-bundle의 npm install(happy-dom)이 있을 때만",
)
def test_bundle_roundtrip_keeps_code_and_html_and_checks_urls():
    """코드·HTML 원문 보존(물결표), 주소 검사 우회 차단, 예전 영상 문법은 링크(check.mjs)."""
    r = subprocess.run(
        ["node", str(BUNDLE_DIR / "check.mjs")], capture_output=True, text=True, timeout=120
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_doc_editor_stays_on_failed_save_and_flushes_before_finalize():
    script = (WEB_DIR / "static" / "doc-tiptap.js").read_text(encoding="utf-8")
    assert (
        "if (!(await settle())) return false;" in script
    )  # 저장 실패·409·조합 중이면 이동하지 않는다
    assert "root._mdDestroy = () => {" in script
    notes = (TPL / "notes" / "list.html").read_text(encoding="utf-8")
    assert "data-flush-first action=\"{% url 'note_finalize' note.pk %}\"" in notes
