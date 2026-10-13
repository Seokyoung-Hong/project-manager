from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent


def test_member_skill_inputs_keep_an_editable_width():
    css = (WEB_DIR / "static" / "app.css").read_text(encoding="utf-8")

    assert ".member-skills-cell { min-width: 300px; }" in css
    assert ".member-skills-form { flex-wrap: nowrap; }" in css
    assert ".member-skills-input { width: 220px; min-width: 200px; max-width: 220px;" in css


def test_member_skill_input_is_labeled_in_panel():
    # 구성원 표의 태그 칸은 설정 → 구성원 관리의 구성원 패널(한 사람)로 옮겼다(IMPL-PLAN-14 §8.2)
    path = WEB_DIR / "templates" / "orgs" / "settings" / "_member_panel.html"
    template = path.read_text(encoding="utf-8")
    assert '<label class="field">스킬 태그<input class="input" name="tags"' in template
