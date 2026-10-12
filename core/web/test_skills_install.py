"""/skills/ 한 줄 설치: 로그인 없이 받고, 스크립트에 요청한 서버 주소가 박히고, 묶음에 스킬이 다 든다."""

import io
import zipfile

import pytest


@pytest.mark.parametrize("ext", ["ps1", "sh"])
def test_install_script_carries_request_host(client, ext):
    r = client.get(f"/skills/install.{ext}", HTTP_HOST="localhost:8000")
    assert r.status_code == 200 and r["Content-Type"].startswith("text/")
    body = r.content.decode()
    assert "__BASE__" not in body and "\r" not in body
    assert (
        "http://localhost:8000/skills/udally-skills.zip" not in body
    )  # 주소는 변수로 한 번만 박는다
    assert "'http://localhost:8000'" in body
    assert "pm.py" in body and "login" in body


def test_unknown_script_is_404(client):
    assert client.get("/skills/install.bat").status_code == 404


def test_bundle_has_every_skill(client, settings):
    r = client.get("/skills/udally-skills.zip")
    assert r.status_code == 200 and r["Content-Type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "pm/SKILL.md" in names and "pm/scripts/pm.py" in names
    expected = {f"{d.name}/SKILL.md" for d in settings.SKILLS_DIR.glob("pm*")}
    assert expected <= set(names) and len(expected) > 5
    assert not any("README" in n or "test_pm" in n or "__pycache__" in n for n in names)


def test_token_page_offers_one_line_install(client, member):
    client.force_login(member)
    body = client.get("/settings/tokens", HTTP_HOST="localhost:8000").content.decode()
    assert 'data-copy-text="irm http://localhost:8000/skills/install.ps1 | iex"' in body
    assert 'data-copy-text="curl -fsSL http://localhost:8000/skills/install.sh | sh"' in body
