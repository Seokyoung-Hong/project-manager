from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent


def test_editable_documents_expose_a_keyboard_entry_button():
    """문서·회의록이 같이 쓰는 편집기 조각에 키보드로 편집을 시작하는 버튼이 있다."""
    template = (WEB_DIR / "templates" / "docs" / "_editor.html").read_text(encoding="utf-8")
    assert 'class="btn sm md-edit-start" aria-controls="doc-body"' in template
    assert 'id="doc-body" class="md-editor' in template
    assert "Esc로 편집을 마칩니다." in template
    for page in ("docs/index.html", "notes/list.html"):
        assert '"docs/_editor.html"' in (WEB_DIR / "templates" / page).read_text(encoding="utf-8")


def test_document_editor_enters_and_returns_focus_to_the_button():
    script = (WEB_DIR / "static" / "doc-tiptap.js").read_text(encoding="utf-8")
    assert 'editStart.addEventListener("click"' in script
    assert 'if (e.key !== "Escape") return;' in script
    assert "if (editStart && editStart.getClientRects().length) editStart.focus();" in script
    assert "else dom.focus();" in script  # 좁은 화면: 숨은 버튼 대신 보기 상태 본문으로
