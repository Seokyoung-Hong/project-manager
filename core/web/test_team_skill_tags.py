from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent


def test_member_skill_inputs_keep_an_editable_width():
    css = (WEB_DIR / "static" / "app.css").read_text(encoding="utf-8")

    assert ".member-skills-cell { min-width: 300px; }" in css
    assert ".member-skills-form { flex-wrap: nowrap; }" in css
    assert ".member-skills-input { width: 220px; min-width: 200px; max-width: 220px;" in css


def test_member_skill_inputs_have_member_specific_labels():
    template = (WEB_DIR / "templates" / "orgs" / "teams.html").read_text(encoding="utf-8")

    assert 'class="table-scroll member-table-scroll" tabindex="0" role="region"' in template
    assert 'aria-label="조직 멤버 관리, 좌우로 스크롤 가능"' in template
    assert 'class="grid member-table"' in template
    assert 'for="member-tags-{{ r.m.pk }}"' in template
    assert "{{ r.m.user.display_name }} 스킬 태그" in template
    assert 'id="member-tags-{{ r.m.pk }}"' in template
