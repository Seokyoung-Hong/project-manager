"""IMPL-PLAN-14 D: 연동·회의·전사 탭 조각과 옛 주소 리다이렉트."""

import pytest
from django.template.loader import render_to_string
from django.test import RequestFactory

from orgs.services import set_org_settings
from web.views.discord import discord_ctx
from web.views.github import github_ctx
from web.views.transcribe import stt_ctx

pytestmark = pytest.mark.django_db

_PARTS = {
    "github": ("orgs/settings/_github.html", github_ctx),
    "discord": ("orgs/settings/_discord.html", discord_ctx),
    "stt": ("orgs/settings/_stt.html", stt_ctx),
}


def frag(name, user, org) -> str:
    """탭 조각을 B의 셸 없이 그대로 그린다."""
    tpl, ctx = _PARTS[name]
    request = RequestFactory().get("/")
    request.user = user
    request.session = {}
    return render_to_string(tpl, ctx(request, org), request)


def test_old_urls_redirect_to_tabs(client, org, admin, settings):
    settings.GITHUB_ENABLED = True
    settings.DISCORD_CLIENT_ID = "123"
    client.force_login(admin)
    base = f"/orgs/{org.pk}/settings"
    for old, new in [
        (f"/orgs/{org.pk}/github", f"{base}?tab=integrations#github"),
        (f"/orgs/{org.pk}/discord", f"{base}?tab=integrations#discord"),
        (f"/orgs/{org.pk}/transcribe?view=server", f"{base}?tab=meeting#stt"),
    ]:
        r = client.get(old)
        assert r.status_code == 302 and r["Location"] == new


def test_non_admin_transcribe_server_view_shows_jobs(client, org, member):
    client.force_login(member)
    assert client.get(f"/orgs/{org.pk}/transcribe?view=server").status_code == 200


def test_github_fragment_has_no_self_connect_card(org, admin):
    html = frag("github", admin, org)
    assert "내 GitHub 연결" not in html and "프로필" in html and 'id="github"' in html


def test_stt_save_keeps_other_settings_and_returns_to_tab(client, org, admin):
    set_org_settings(org, {"meeting.stt_model": "small"}, admin)
    client.force_login(admin)
    r = client.post(f"/orgs/{org.pk}/transcribe/server", {})
    assert r.status_code == 302 and r["Location"].endswith("?tab=meeting#stt")
