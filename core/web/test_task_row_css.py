import re
from pathlib import Path


def test_mobile_copy_action_does_not_reserve_an_extra_action_row():
    css = (Path(__file__).resolve().parent / "static" / "app.css").read_text(encoding="utf-8")
    template = (Path(__file__).resolve().parent / "templates" / "tasks" / "_row.html").read_text(
        encoding="utf-8"
    )

    assert "{% if in_today_page %} today-task-row{% endif %}" in template
    assert ".task-row:not(.today-task-row) .main { padding-right: 48px; }" in css
    # 복사 버튼은 카드 모서리에 떠 있어야 한다(줄 하나를 따로 차지하지 않는다).
    rule = re.search(r"^\s*\.task-row:not\(\.today-task-row\) \[data-copy\] \{([^}]*)\}", css, re.M)
    assert rule and "position: absolute" in rule[1] and "top:" in rule[1]
    assert ".today-list-card .task-row [data-copy] { position: absolute;" in css
