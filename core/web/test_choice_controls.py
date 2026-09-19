from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent


def test_choice_inputs_stay_keyboard_focusable_and_show_focus():
    css = (WEB_DIR / "static" / "app.css").read_text(encoding="utf-8")

    assert ".chip input { display: none; }" not in css
    assert ".radio-card input { display: none; }" not in css
    assert ".chip input, .radio-card input" in css
    assert "clip-path: inset(50%)" in css
    assert ".chip:has(input:focus-visible), .radio-card:has(input:focus-visible)" in css


def test_choice_groups_use_fieldset_and_legend():
    project_dialog = (WEB_DIR / "templates" / "projects" / "_dialog.html").read_text(
        encoding="utf-8"
    )
    milestone_dialog = (WEB_DIR / "templates" / "orgs" / "_milestone_dialog.html").read_text(
        encoding="utf-8"
    )

    assert project_dialog.count('<fieldset class="choice-fieldset">') == 3
    assert "<legend>관리자 (여러 명 가능)</legend>" in project_dialog
    assert "<legend>담당 팀</legend>" in project_dialog
    assert "<legend>상태</legend>" in project_dialog
    assert milestone_dialog.count('<fieldset class="choice-fieldset">') == 1
    assert "<legend>상태</legend>" in milestone_dialog
