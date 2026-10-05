# 구현 지시서 V2-02: 셸과 내비게이션 (2단계)

목표: 내비게이션 레벨을 **한 화면에 최대 2개**로 정리한다. 헤더 5영역, 조직·프로젝트 하위 탭, 프로젝트 영역에서만 나타나는 접이식 레일. 그리고 조직 → 팀 화면을 만든다.

근거: `NewMock/README.md`의 "내비게이션 정책", `유달리 신규 기능 목업.dc.html`.

---

## 1. Step 1. 헤더 5영역

`templates/base.html`의 내비를 다섯으로 만든다.

| 라벨 | 링크 | `nav` 값 |
|---|---|---|
| 오늘 | `{% url 'today' %}` | `today` |
| 내 태스크 | `{% url 'me' %}` | `me` |
| **프로젝트** | `{% url 'project_index' %}` | `project` |
| 조직 | `{% url 'org' %}` | `org` |
| 검색 | `{% url 'search' %}` | `search` |

오른쪽은 그대로다(빠른 추가 · 아바타 메뉴).

`web/context.py`의 `NAV_BY_URL`에 프로젝트·조직 화면 이름을 전부 넣는다.

```python
NAV_BY_URL = {
    "today": "today", "today_quick": "today",
    "me": "me",
    "project_index": "project", "project_detail": "project",
    "project_repo": "project", "project_api": "project",
    "org": "org", "org_list": "org", "org_detail": "org", "org_new": "org",
    "org_members": "org", "org_teams": "org", "team_detail": "org",
    "org_capacity": "org", "org_roadmap": "org", "org_notes": "org", "org_github": "org",
    "search": "search",
}
```

뒤 단계에서 만드는 이름(`org_capacity`·`org_roadmap`·`org_notes`·`org_github`·`project_repo`·`project_api`)을 지금 넣어 둔다. URL이 아직 없어도 이 dict는 문자열 조회라 문제가 없다.

---

## 2. Step 2. `/projects` 진입점

`web/views/projects.py`:

```python
@login_required
def project_index(request):
    """헤더의 '프로젝트'. 마지막으로 본 프로젝트 → 조직의 첫 프로젝트 → 빈 화면."""
    org = current_org(request)
    if org is None:
        return redirect("org_list")
    pid = request.session.get("project_id")
    project = None
    if pid:
        project = Project.objects.filter(pk=pid, org=org, is_archived=False).first()
    if project is None:
        project = org.projects.filter(is_archived=False).order_by("name").first()
    if project is None:
        return render(
            request,
            "projects/empty.html",
            {"org": org, "is_admin": can_admin(request.user, org)},
        )
    return redirect("project_detail", project_id=project.pk)
```

`project_detail`은 이미 `request.session["team_id"]`를 쓰고 있다. 이를 두 줄로 바꾼다.

```python
    request.session["org_id"] = project.org_id
    request.session["project_id"] = project.pk
```

`projects/empty.html`은 카드 하나다. "이 조직에는 아직 프로젝트가 없습니다." + 관리자면 [새 프로젝트] 버튼(기존 `project_new` 모달).

URL: `path("projects", projects.project_index, name="project_index")`. `projects/new`보다 **뒤에** 두지 않아도 된다(정확히 일치하는 경로다).

---

## 3. Step 3. 프로젝트 레일

목업 기준: 프로젝트 영역에서만 나타난다. 펼침 200px / 접힘 56px. 목록은 `max-height: calc(100vh - 248px)`, `min-height: 120px`, 세로 스크롤, 이름은 말줄임. 각 항목 오른쪽에 **미완료 건수**. 하단에 `＋ 새 프로젝트`.

`web/context.py`:

```python
def shell(request):
    if not request.user.is_authenticated:
        return {}
    org = current_org(request)
    match = request.resolver_match
    url_name = match.url_name if match else ""
    nav = NAV_BY_URL.get(url_name, "")
    projects = []
    if nav == "project" and org is not None:
        projects = (
            org.projects.filter(is_archived=False)
            .annotate(open_count=Count("tasks", filter=Q(tasks__status__in=Task.OPEN)))
            .order_by("name")
        )
    return {
        "current_org": org,
        "nav_projects": projects,          # 프로젝트 영역이 아니면 빈 목록이라 레일이 렌더되지 않는다
        "nav": nav,
        "current_project_id": match.kwargs.get("project_id") if match else None,
        "page_url": request.get_full_path(),
        "org_count": request.user.orgs.count(),
    }
```

`base.html`:

```html
{% if nav == "project" %}
<nav class="rail" aria-label="프로젝트" data-rail>
  <div class="rail-head">
    <span class="t13 muted grow">프로젝트 {{ nav_projects|length }}</span>
    <span class="t12 muted rail-only">미완료</span>
    <button type="button" class="btn sm icon" data-action="toggle-rail"
            aria-expanded="true" aria-label="프로젝트 목록 접기" title="목록 접기">«</button>
  </div>
  <div class="rail-list">
    {% for p in nav_projects %}
    <a href="{% url 'project_detail' p.pk %}" title="{{ p.name }}"
       {% if p.pk == current_project_id %}aria-current="page"{% endif %}>
      <span class="initial">{{ p.name|slice:":1" }}</span>
      <span class="label">{{ p.name }}</span>
      <span class="count t12 muted">{{ p.open_count }}</span>
    </a>
    {% empty %}<span class="muted t13 rail-only" style="padding:0 10px">프로젝트 없음</span>{% endfor %}
  </div>
  <button type="button" class="btn link rail-only rail-new"
          hx-get="{% url 'project_new' %}?org={{ current_org.pk }}" hx-target="#dialog" hx-swap="innerHTML">＋ 새 프로젝트</button>
</nav>
{% endif %}
```

`app.js`에 접기를 붙인다. 상태는 `localStorage`에만 둔다(서버 상태가 아니다).

```js
  // 프로젝트 레일 접기. 아이콘 열(56px)과 목록(200px)을 오간다.
  function applyRail() {
    var rail = document.querySelector("[data-rail]");
    if (!rail) return;
    var off = localStorage.getItem("rail-collapsed") === "1";
    rail.classList.toggle("collapsed", off);
    var b = rail.querySelector("[data-action='toggle-rail']");
    if (b) {
      b.textContent = off ? "»" : "«";
      b.setAttribute("aria-expanded", off ? "false" : "true");
      b.setAttribute("aria-label", off ? "프로젝트 목록 펼치기" : "프로젝트 목록 접기");
    }
  }
  applyRail();
```

`data-action` 처리에 한 갈래를 더한다.

```js
    } else if (a === "toggle-rail") {
      localStorage.setItem("rail-collapsed", localStorage.getItem("rail-collapsed") === "1" ? "0" : "1");
      applyRail();
    }
```

`app.css`:

```css
.rail { position: sticky; top: 64px; flex: none; width: 200px; padding: 16px 8px; display: flex; flex-direction: column; gap: 2px; }
.rail.collapsed { width: 56px; }
.rail-head { display: flex; align-items: center; gap: 8px; padding: 0 6px 6px; }
.rail-head .grow { flex: 1; min-width: 0; }
.rail-list { display: flex; flex-direction: column; gap: 2px; max-height: calc(100vh - 248px); min-height: 120px; overflow-y: auto; padding-right: 2px; }
.rail a { display: flex; align-items: center; gap: 8px; min-height: 40px; padding: 0 10px; border-radius: 8px; color: var(--text-primary); text-decoration: none; font-size: 13px; }
.rail a .label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rail a[aria-current="page"] { background: var(--primary-bg); color: var(--primary); font-weight: 700; }
.rail .initial { flex: none; width: 24px; height: 24px; border-radius: 6px; background: var(--bg-fill); display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; }
.rail.collapsed .rail-only, .rail.collapsed a .label, .rail.collapsed a .count { display: none; }
.rail.collapsed .rail-head { justify-content: center; padding: 0 0 6px; }
.rail-new { height: 40px; padding: 0 10px; text-align: left; }
```

700px 이하 가로 스크롤 규칙(`@media (max-width: 700px)`의 `.rail`)은 그대로 두고 `.rail.collapsed`에도 같은 폭이 적용되도록 `width: 100%`를 유지한다.

---

## 4. Step 4. 하위 탭

`templates/orgs/_tabs.html`:

```html
<nav class="tabs" aria-label="조직 메뉴">
  <a href="{% url 'org_detail' org.pk %}" {% if tab == "overview" %}aria-current="page"{% endif %}>개요</a>
  {% if is_admin %}<a href="{% url 'org_teams' org.pk %}" {% if tab == "teams" %}aria-current="page"{% endif %}>팀</a>{% endif %}
</nav>
```

`templates/projects/_tabs.html`:

```html
<nav class="tabs" aria-label="프로젝트 메뉴">
  <a href="{% url 'project_detail' project.pk %}" {% if tab == "tasks" %}aria-current="page"{% endif %}>태스크</a>
</nav>
```

**뒤 단계가 자기 탭을 여기에 한 줄씩 추가한다.** V2-04가 부하 현황·로드맵, V2-05가 회의록, V2-06이 API 문서, V2-07이 저장소 연결, V2-08이 GitHub를 넣는다. 지금은 없는 화면의 링크를 만들지 않는다.

각 화면 뷰는 context에 `tab`과 `is_admin`을 넣고, 템플릿은 카드 위에서 `{% include "orgs/_tabs.html" %}`을 부른다.

```css
.tabs { display: flex; gap: 4px; flex-wrap: wrap; border-bottom: 1px solid var(--border); }
.tabs a { height: 44px; padding: 0 14px; display: inline-flex; align-items: center; border-bottom: 2px solid transparent; color: var(--text-secondary); font-size: 14px; font-weight: 500; text-decoration: none; white-space: nowrap; }
.tabs a[aria-current="page"] { border-bottom-color: var(--primary); color: var(--primary); font-weight: 700; }
```

---

## 5. Step 5. 조직 개요 타일 교체

목업의 타일 6개는 **미완료 · 진행 중 · 검토 대기 · 기한 초과 · 막힘 · 완료**다. 지금의 "이번 주 마감"·"기한 미정"을 "진행 중"·"완료"로 바꾼다. 숫자는 전부 `org_status()["counts"]`에서 온다(V2-01에서 `doing`·`done`을 넣었다).

```python
    tiles = [
        ("미완료", c["open"], f"{me_url}?member=0"),
        ("진행 중", c["doing"], f"{me_url}?member=0&status=doing"),
        ("검토 대기", c["review"], f"{me_url}?member=0&status=review"),
        ("기한 초과", c["overdue"], f"{me_url}?member=0&due=overdue", True),
        ("막힘", c["blocked"], f"{me_url}?member=0&status=blocked", True),
        ("완료", c["done"], f"{me_url}?member=0&status=done_7d"),
    ]
```

네 번째 요소는 "0보다 크면 빨강"이라는 뜻이다. 템플릿에서 `{% if t.3 and t.1 %}danger{% endif %}`. 없는 항목은 3-튜플이므로 뷰에서 전부 4-튜플로 맞춰 넘긴다.

프로젝트 표에 **담당 팀** 열을 더한다. `org_status()["by_project"]`의 `teams`를 칩으로 그린다(팀이 없으면 빈칸).

```html
<td>{% for t in p.teams %}<span class="badge">{{ t.name }}</span> {% endfor %}</td>
```

---

## 6. Step 6. 조직 → 팀 화면

기존 `/orgs/<id>/members`(멤버 관리)를 **`/orgs/<id>/teams` 한 화면으로 합친다.** 카드 세 개다.

### 카드 1. 멤버

열: 이름 · 역할 select · **소속 팀 칩** · **스킬 태그** · Discord · 미완료 · [제거]

스킬 태그는 쉼표로 입력하는 인라인 폼이다.

```html
<form method="post" action="{% url 'member_tags' m.pk %}" class="row">{% csrf_token %}
  <input class="input" name="tags" value="{{ m.tags|join:', ' }}" placeholder="백엔드, Django">
  <button class="btn sm">저장</button>
</form>
```

뷰는 `tags.split(",")`를 `orgs.services.set_tags(membership, parts, actor)`에 넘긴다. 정규화는 services가 한다.

### 카드 2. 초대 링크

기존과 같다. "GitHub 조직에도 초대" 체크는 `GUIDE-V2-08`에서 붙인다.

### 카드 3. 팀

| 열 | 내용 |
|---|---|
| 이름 | `/teams/<tid>` 링크 |
| 멤버 | 수 |
| 담당 프로젝트 | 수 |
| GitHub | V2-08에서 배지가 붙는다. 지금은 빈 칸 |
| | [수정] [삭제] |

[새 팀]은 `<dialog>`로 연다(프로젝트 모달과 같은 패턴, `templates/orgs/_team_dialog.html`). 필드는 이름과 목적 둘뿐이다.

### 팀 상세 `/teams/<tid>`

조직 탭을 유지하고 `tab="teams"`로 표시한다.

- 헤더: 조직 링크 · 팀 이름 · 목적 · [수정] [삭제]
- 멤버 표: 이름 · [제거]. 아래에 조직 멤버 중 아직 안 들어온 사람 select + [추가]
- 담당 프로젝트 목록(읽기 전용. 담당 팀 지정은 프로젝트 수정 모달에서 한다)

### URL과 뷰

```
orgs/<int:org_id>/teams            org_teams          목록+멤버
orgs/<int:org_id>/teams/new        team_new           dialog
teams/<int:team_id>                team_detail
teams/<int:team_id>/edit           team_edit          dialog
teams/<int:team_id>/delete         team_delete        POST
teams/<int:team_id>/members        team_member_add    POST
teams/<int:team_id>/members/<int:user_id>/remove   team_member_remove  POST
orgs/memberships/<int:membership_id>/tags          member_tags         POST
```

전부 `_admin_only(request, org_id)` 관문을 지난다(기존 `members` 뷰가 쓰던 것과 같은 함수). 팀 관련 뷰는 `team.org`로 조직을 찾아 같은 검사를 한다.

`web/views/orgs.py`에 둔다. 파일이 300줄을 넘으면 `web/views/teams.py`로 팀 부분만 뺀다.

프로젝트 수정 모달(`projects/_dialog.html`)에 **담당 팀 체크 칩**을 더한다. 관리자 칩과 같은 모양이고 `name="teams"`다. `ProjectForm`에 `teams = forms.ModelMultipleChoiceField(queryset=Team.objects.none(), required=False)`를 넣고 `__init__`에서 `org.teams.all()`로 채운다.

---

## 7. Step 7. 패널 "크게 보기"

목업은 전체 오버레이 + 중앙 820px 카드다. 지금은 본문을 숨기고 `aside`를 2열로 늘린다. CSS만 바꾼다.

```css
.layout.wide { position: relative; }
.layout.wide > main { display: none; }
.layout.wide aside#panel {
  position: fixed; inset: 64px 0 0 0; z-index: 20; max-width: none; max-height: none;
  overflow: auto; padding: 24px; background: rgba(25, 31, 40, .28);
}
.layout.wide aside#panel .panel { max-width: 820px; margin: 0 auto; padding: 32px; gap: 20px; }
```

`app.js`의 토글 라벨을 "옆으로 보기" → **"작게 보기"**로 바꾼다(두 곳: `htmx:afterSwap`과 `toggle-wide`).

---

## 8. 테스트

| 이름 | 확인 |
|---|---|
| `test_project_index_uses_session_then_first` | 세션 프로젝트 → 조직 첫 프로젝트 → 빈 화면 순서 |
| `test_project_index_empty_screen` | 프로젝트가 없으면 안내 화면이 200으로 뜬다 |
| `test_rail_only_in_project_area` | `/today`·`/orgs/<id>` 응답에 `class="rail"`이 없고 `/projects/<id>`에는 있다 |
| `test_rail_shows_open_counts` | 레일 항목에 미완료 건수가 들어간다 |
| `test_org_tabs_hidden_for_member` | 일반 멤버에게 팀 탭 링크가 안 보인다 |
| `test_org_teams_requires_admin` | 멤버가 `/orgs/<id>/teams`에 가면 404 |
| `test_team_crud_via_web` | 만들고 이름 바꾸고 지운다 |
| `test_team_member_add_remove_via_web` | 조직 멤버만 추가된다 |
| `test_member_tags_saved_and_normalized` | 쉼표 입력이 목록으로 저장된다 |
| `test_project_dialog_sets_teams` | 프로젝트 수정으로 담당 팀이 바뀌고 이력이 남는다 |
| `test_org_overview_tiles` | 타일 6개 라벨과 숫자가 `org_status`와 같다 |

## 9. 검증

```bash
cd core && uv run ruff check . && uv run pytest -q
```

화면: 레일이 프로젝트 화면에서만 보이고 « » 로 접힌다. 새로고침해도 접힌 상태가 유지된다. 조직 탭에서 개요 ↔ 팀이 오간다. 팀을 만들고 멤버를 넣고 프로젝트에 담당 팀을 지정하면 조직 개요 표에 칩이 나온다.

## 10. 완료 체크

- [ ] 헤더 5영역, 프로젝트 진입점 동작
- [ ] 레일이 프로젝트 영역에서만, 접기와 미완료 건수 포함
- [ ] 조직·프로젝트 탭 partial이 있고 뒤 단계가 한 줄씩 더할 수 있다
- [ ] 조직 개요 타일이 목업과 같다
- [ ] 조직 → 팀 화면에서 멤버·태그·팀을 관리한다
- [ ] 크게 보기가 오버레이로 뜬다
