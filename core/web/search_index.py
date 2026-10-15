"""헤더 통합 검색의 화면·탭·설정 색인.

조직 설정 탭·섹션·항목은 orgs.settings(ORG_TABS·COPY_DRAFT·SPECS)와 설정 셸의 _settings_nav(관리자·연동 거름)에서,
개인 설정 항목은 specs_for("user")에서 만든다. 아래 세 메뉴 표만 템플릿에 손으로 적힌 메뉴를 옮긴 것이라
web/test_header_search.py가 base.html·orgs/_tabs.html·settings/_tabs.html과 대조한다(메뉴를 바꾸면 여기도).
"""

from django.conf import settings
from django.urls import reverse

from orgs.settings import COPY_DRAFT, ORG_TABS, SPECS, STT_KEYS, specs_for, tab_keys

from .views.common import can_admin
from .views.orgs import _settings_nav, _settings_url

# (이름, URL 이름) — base.html 주 메뉴
HEADER_NAV = [
    ("오늘", "today"),
    ("내 태스크", "me"),
    ("요청", "request_index"),
    ("프로젝트", "project_index"),
    ("조직", "org"),
]
# settings/_tabs.html 개인 설정 탭
SETTINGS_TABS = [
    ("프로필", "profile"),
    ("환경설정", "preferences"),
    ("API 토큰", "tokens"),
    ("내 PC 연결", "settings_stt"),
    ("AI", "settings_ai"),
]
# 프로필 안 섹션(탭이 아니라 앵커·하위 페이지)
PROFILE_SECTIONS = [
    ("연결(GitHub·Discord)", "profile", "#connections"),
    ("개인정보 동의", "consents", ""),
    ("탈퇴", "withdraw", ""),
]
# orgs/_tabs.html 조직 메뉴(조직 번호를 받는다)
ORG_MENU = [
    ("개요", "org_detail"),
    ("팀", "org_teams"),
    ("사람별 할 일 양", "org_capacity"),
    ("로드맵", "org_roadmap"),
    ("업무 규칙", "org_governance"),
    ("문서", "org_docs"),
    ("회의록", "org_notes"),
    ("전사", "org_transcribe"),
    ("이슈", "org_issues"),
    ("설정", "org_settings"),
]


def _entries(user, org):
    """보는 사람이 열 수 있는 화면·설정. (묶음 screen|setting, 이름, 위치, 주소, 설명)"""
    out = [("screen", label, "주 메뉴", reverse(n), "") for label, n in HEADER_NAV]
    out += [("screen", label, "개인 설정", reverse(n), "") for label, n in SETTINGS_TABS]
    out += [
        ("screen", label, "개인 설정 · 프로필", reverse(n) + a, "")
        for label, n, a in PROFILE_SECTIONS
    ]
    out.append(("screen", "내 포트폴리오", "내 메뉴", reverse("portfolio"), ""))
    if user.is_staff:
        out.append(("screen", "운영 콘솔", "내 메뉴", reverse("ops"), ""))
    out += [
        (
            "setting",
            s.label,
            "개인 설정 · 환경설정",
            reverse("preferences") + f"#setting-{s.key}",
            s.help,
        )
        for s in specs_for("user")
    ]
    if org is None:
        return out
    for label, n in ORG_MENU:
        if n == "org_issues" and not (settings.GITHUB_ENABLED and hasattr(org, "github")):
            continue
        out.append(("screen", label, f"조직 · {org.name}", reverse(n, args=[org.pk]), ""))
    sections = {code: secs for code, _, secs in ORG_TABS}
    for _, tabs in _settings_nav(org, None, can_admin(user, org)):
        for code, tab_label, url, _ in tabs:
            where = f"조직 설정 · {tab_label}"
            out.append(("screen", tab_label, "조직 설정", url, ""))
            for sec, sec_key, _ in sections[code]:
                sec_anchor = f"settings-{code}-{sec}"
                out.append(
                    ("setting", COPY_DRAFT.get(sec_key, sec_key), where,
                     _settings_url(org.pk, code, anchor=sec_anchor), "")
                )  # fmt: skip
                for k in tab_keys(code, sec):
                    # 전사 항목은 자기 폼이 따로 있어 행 id가 없을 수 있다 — 섹션으로 보낸다
                    anchor = sec_anchor if k in STT_KEYS else f"setting-{k}"
                    out.append(
                        ("setting", SPECS[k].label, where,
                         _settings_url(org.pk, code, anchor=anchor), SPECS[k].help)
                    )  # fmt: skip
    return out


def find(user, org, q: str) -> dict[str, list[dict]]:
    """이름이 맞는 것을 먼저, 설명만 맞는 것을 뒤에. {"screen": [...], "setting": [...]}"""
    q = (q or "").strip().lower()
    found = {"screen": [], "setting": []}
    if not q:
        return found
    seen = set()
    for pass_help in (False, True):
        for group, label, where, url, help_ in _entries(user, org):
            text = help_ if pass_help else label
            if url in seen or q not in text.lower():
                continue
            seen.add(url)
            found[group].append({"label": label, "hint": where, "url": url})
    return found
