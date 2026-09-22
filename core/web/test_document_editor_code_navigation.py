from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent


def test_fenced_code_can_move_to_adjacent_blocks_with_arrow_keys():
    script = (WEB_DIR / "static" / "notes.js").read_text(encoding="utf-8")

    assert "var plainArrow = !e.shiftKey && !e.altKey && !e.metaKey && !e.ctrlKey;" in script
    assert "var collapsed = ta.selectionStart === ta.selectionEnd;" in script
    assert 'plainArrow && collapsed && e.key === "ArrowUp" && at === 0 && u.start > 0' in script
    assert "editing = u.start - 1; caret = null; render();" in script
    assert (
        'plainArrow && collapsed && e.key === "ArrowDown" && at === ta.value.length '
        "&& u.end < lines.length - 1" in script
    )
    assert "editing = u.end + 1; caret = 0; render();" in script
