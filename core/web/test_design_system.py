"""디자인 시스템: 스타일 가이드 권한, 그리고 DESIGN.md·app.css·템플릿이 서로 어긋나지 않는지."""

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
