from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent


def test_editable_documents_expose_a_keyboard_entry_button():
    for relative in ("notes/list.html", "projects/docs.html"):
        template = (WEB_DIR / "templates" / relative).read_text(encoding="utf-8")
        assert 'class="btn sm doc-edit-start"' in template
        assert 'type="button"' in template
        assert 'aria-controls="doc-body"' in template
        assert "본문 편집을 눌러 작성하세요." in template
        assert "키보드에서는 Enter로 편집을 시작하고 Esc로 편집을 마칩니다." in template


def test_document_editor_enters_and_returns_focus_to_the_button():
    script = (WEB_DIR / "static" / "notes.js").read_text(encoding="utf-8")

    assert 'editStart.addEventListener("click", beginEditing)' in script
    assert "function beginEditing()" in script
    assert "function exitEditing()" in script
    assert "if (editStart) editStart.focus();" in script
    assert script.count("e.preventDefault(); exitEditing();") == 2
