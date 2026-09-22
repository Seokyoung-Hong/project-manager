from pathlib import Path


def test_mobile_copy_action_does_not_reserve_an_extra_action_row():
    css = (Path(__file__).resolve().parent / "static" / "app.css").read_text(encoding="utf-8")
    template = (Path(__file__).resolve().parent / "templates" / "tasks" / "_row.html").read_text(
        encoding="utf-8"
    )

    assert "{% if in_today_page %} today-task-row{% endif %}" in template
    assert ".task-row:not(.today-task-row) .main { padding-right: 48px; }" in css
    assert (
        ".task-row:not(.today-task-row) [data-copy] {\n"
        "    position: absolute; top: 12px; right: 12px; width: 40px;\n"
        "  }" in css
    )
    assert ".today-list-card .task-row [data-copy] { position: absolute;" in css
