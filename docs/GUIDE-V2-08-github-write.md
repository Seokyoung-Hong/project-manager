# 구현 지시서 V2-08: GitHub 쓰기와 관리 (8단계)

목표: 자주 하는 GitHub 관리 작업을 PM 안에서 끝낸다. 조직 초대, 팀 만들기, 팀 멤버 넣고 빼기, 태스크에서 이슈·브랜치 만들기.

`GUIDE-V2-07`이 끝나 있어야 한다. 여기서 새로 만드는 모델은 `GitHubTeamLink` 하나다.

---

## 1. 두 가지 원칙

### 원칙 1. 모든 쓰기는 **누른 사람의 토큰**으로 나간다

설치 토큰으로 쓰지 않는다. 이유가 셋이다.

- GitHub 쪽 기록이 그 사람 이름으로 남는다. 봇 이름으로 남지 않는다.
- 그 사람이 GitHub에서 못 하는 일은 GitHub가 거부한다. **PM이 권한 규칙을 따로 구현하지 않는다.**
- 설치 토큰이 유출돼도 쓰기에 쓰이지 않는다.

GitHub 미연결 사용자에게는 버튼을 비활성으로 두고 "GitHub를 연결하면 할 수 있습니다"를 보여 준다.

### 원칙 2. PM이 먼저, GitHub는 그 다음

PM 데이터가 먼저 바뀌고 그 뒤에 GitHub에 반영한다. GitHub가 거부하면 **PM 변경은 그대로 두고 경고를 보여 준다.**

```
GitHub에 반영하지 못했습니다 (403: You must be a team maintainer). PM 팀에만 적용됐습니다.
```

PM이 자기 데이터의 주인이고, GitHub 반영은 편의이기 때문이다. 되돌리기 애매한 절반 성공을 만들지 않는다. 나중에 [GitHub에 반영] 버튼으로 다시 맞출 수 있다.

---

## 2. 하는 것과 하지 않는 것

| 하는 것 | GitHub API | 필요한 앱 권한 |
|---|---|---|
| 조직에 초대 | `PUT /orgs/{org}/memberships/{login}` | 조직 Members 쓰기 |
| 조직에서 제거 | `DELETE /orgs/{org}/members/{login}` | 조직 Members 쓰기 |
| 팀 만들기·수정 | `POST`·`PATCH /orgs/{org}/teams[/{slug}]` | 조직 Members 쓰기 |
| 팀 멤버 추가·제거 | `PUT`·`DELETE /orgs/{org}/teams/{slug}/memberships/{login}` | 조직 Members 쓰기 |
| 이슈 만들기 | `POST /repos/{o}/{r}/issues` | 저장소 Issues 쓰기 |
| 이슈 닫기 | `PATCH /repos/{o}/{r}/issues/{n}` `{"state":"closed"}` | 저장소 Issues 쓰기 |
| 브랜치 만들기 | `POST /repos/{o}/{r}/git/refs` | 저장소 Contents 쓰기 |

| 하지 않는 것 | 왜 |
|---|---|
| **팀에 저장소 권한 주기** | 저장소 Administration 쓰기를 요구한다. 그 권한에는 저장소 삭제·설정 변경·브랜치 보호·배포 키가 전부 딸려 온다. 저장소를 만들 때 한 번 하는 일이라 **읽기 전용 표 + GitHub 링크**로 충분하다 |
| 개인에게 저장소 권한 주기 | 권한은 팀에 붙는다. 예외는 GitHub에서 |
| PR 병합, 커밋 | 리뷰와 CI 맥락이 GitHub에 있다 |
| 저장소 생성·삭제, 브랜치 보호, 시크릿·Actions | 드물거나 되돌리기 어렵다 |
| 조직 소유자 승격 | PM 역할과 GitHub 역할을 섞지 않는다 |
| **GitHub 팀 삭제** | PM 팀을 지워도 GitHub 팀은 남긴다. GitHub 팀에는 PM이 모르는 저장소 권한이 붙어 있을 수 있어 지우면 사람들이 접근을 잃는다. 게다가 `GitHubTeamLink`가 CASCADE라 PM 팀을 먼저 지우면 slug가 사라진다 |

---

## 3. Step 1. `GitHubTeamLink`

```python
class GitHubTeamLink(models.Model):
    """PM 팀 하나와 GitHub 팀 하나를 잇는다. 연결하지 않는 팀이 더 많다."""

    team = models.OneToOneField("orgs.Team", on_delete=models.CASCADE, related_name="github")
    github_team_id = models.BigIntegerField()
    slug = models.CharField(max_length=100)
    name = models.CharField(max_length=100, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["github_team_id"], name="githubteamlink_team_id"),
        ]
```

`github` 앱에 둔다. 마이그레이션 `github 0002`.

---

## 4. Step 2. 쓰기 서비스

`github/writes.py`. **여기 있는 함수는 전부 `actor`의 토큰을 쓴다.**

```python
def _org_login(org) -> str:
    inst = getattr(org, "github", None)
    if inst is None:
        raise ServiceError({"github": "이 조직에 GitHub 앱이 설치되어 있지 않습니다."})
    return inst.account_login


def _actor_token(actor) -> str:
    identity = getattr(actor, "github", None)
    if identity is None:
        raise ServiceError({"github": "GitHub를 연결해야 할 수 있습니다."})
    return user_token(identity)


def _login_of(user) -> str:
    identity = getattr(user, "github", None)
    return identity.login if identity else ""


def try_write(fn, *args, **kwargs) -> str:
    """GitHub 반영을 시도하고 실패하면 사람이 읽을 경고 문자열을 돌려준다.

    PM 변경은 이미 끝났다. 여기서 예외를 올리면 절반만 바뀐 상태가 된다.
    """
    try:
        fn(*args, **kwargs)
        return ""
    except GitHubError as e:
        return f"GitHub에 반영하지 못했습니다 ({e.status}: {e.message}). PM에만 적용됐습니다."
    except ServiceError as e:
        return " ".join(e.errors.values()) + " PM에만 적용됐습니다."
```

조직과 팀:

```python
def invite_to_org(org, login: str, *, actor):
    client.request("PUT", f"/orgs/{_org_login(org)}/memberships/{login}",
                   _actor_token(actor), body={"role": "member"})


def remove_from_org(org, login: str, *, actor):
    client.request("DELETE", f"/orgs/{_org_login(org)}/members/{login}", _actor_token(actor))


def list_org_teams(org, *, actor) -> list[dict]:
    return client.request("GET", f"/orgs/{_org_login(org)}/teams?per_page=100", _actor_token(actor))


def create_gh_team(team, *, actor) -> dict:
    return client.request("POST", f"/orgs/{_org_login(team.org)}/teams", _actor_token(actor),
                          body={"name": team.name, "description": team.purpose, "privacy": "closed"})


def rename_gh_team(link, team, *, actor):
    client.request("PATCH", f"/orgs/{_org_login(team.org)}/teams/{link.slug}", _actor_token(actor),
                   body={"name": team.name, "description": team.purpose})


def set_gh_team_member(link, org, login: str, *, actor, add: bool):
    path = f"/orgs/{_org_login(org)}/teams/{link.slug}/memberships/{login}"
    if add:
        client.request("PUT", path, _actor_token(actor), body={"role": "member"})
    else:
        client.request("DELETE", path, _actor_token(actor))
```

이슈와 브랜치:

```python
def create_issue(task, *, actor, body="") -> dict:
    conn = task.project.repo
    data = client.request("POST", f"/repos/{conn.full_name}/issues", _actor_token(actor),
                          body={"title": f"{task.title} ({task.number})", "body": body or task.description})
    link, _ = TaskGitLink.objects.get_or_create(task=task, defaults={"connection": conn})
    link.issue_number, link.issue_title, link.issue_state = data["number"], data["title"], "open"
    link.save(update_fields=["issue_number", "issue_title", "issue_state"])
    return data


def close_issue(task, *, actor):
    link = task.git
    client.request("PATCH", f"/repos/{link.connection.full_name}/issues/{link.issue_number}",
                   _actor_token(actor), body={"state": "closed"})
    link.issue_state = "closed"
    link.save(update_fields=["issue_state"])


def create_branch(task, name: str, *, actor) -> str:
    """기본 브랜치 끝에서 새 브랜치를 만든다. 이름에 태스크 번호가 들어가므로
    나중에 push·PR이 자동으로 이 태스크에 붙는다."""
    conn = task.project.repo
    token = _actor_token(actor)
    name = (name or "").strip().lstrip("/")
    if not name or ".." in name or name.endswith("/") or " " in name:
        raise ServiceError({"branch": "쓸 수 없는 브랜치 이름입니다."})
    repo = client.request("GET", f"/repos/{conn.full_name}", token)
    ref = client.request("GET", f"/repos/{conn.full_name}/git/ref/heads/{repo['default_branch']}", token)
    client.request("POST", f"/repos/{conn.full_name}/git/refs", token,
                   body={"ref": f"refs/heads/{name}", "sha": ref["object"]["sha"]})
    link, _ = TaskGitLink.objects.get_or_create(task=task, defaults={"connection": conn})
    link.branch = name
    link.save(update_fields=["branch"])
    return name
```

브랜치 기본 이름은 `feat/<제목 슬러그>(TASK-<id>)`(슬러그가 비면 `feat/TASK-<id>`)를 제안하고 사용자가 고칠 수 있게 한다. 이름 규칙을 강제하지는 않지만 **PM이 만들면 번호가 들어간다.**

---

## 5. Step 3. 화면

### 조직 → 팀

- 멤버 표의 [제거]가 PM에서 빼고 GitHub 조직에서도 뺀다. 확인 대화상자 문구: "조직에서 제거할까요? GitHub 조직에서도 빠집니다."
- 초대 폼에 체크: **"GitHub 조직에도 초대"**. 체크했으면 GitHub 로그인 입력칸이 함께 뜬다(그 사람은 아직 PM 계정이 없어 `GitHubIdentity`가 없다).
- 팀 표에 **GitHub 열**: 연결된 팀은 `@slug` 배지, 아닌 팀은 "미연결".
- 팀 만들기·이름 변경이 연결된 팀이면 GitHub에도 반영된다. **삭제는 PM 팀만 지운다.** 확인 대화상자에 "GitHub 팀은 남습니다"를 적는다.

### 팀 상세

- **GitHub 팀 연결** 카드: 미연결이면 조직의 GitHub 팀 select + [연결], 또는 [GitHub에 새 팀 만들기]. 연결됐으면 `@slug`와 [연결 해제], [GitHub에 반영].
- 멤버 추가·제거가 GitHub 팀에도 반영된다. 상대가 GitHub 미연결이면 PM에만 넣고 행에 "GitHub 미연결" 배지를 단다.
- [GitHub에 반영]은 PM 팀 멤버 중 GitHub 연결된 사람을 전부 GitHub 팀에 넣는다(이미 있으면 그대로).

```python
def reconcile_team(team, *, actor) -> tuple[int, list[str]]:
    """PM 팀 멤버를 GitHub 팀에 맞춘다. 뺄 사람은 건드리지 않는다."""
    link = getattr(team, "github", None)
    if link is None:
        raise ServiceError({"github": "연결된 GitHub 팀이 없습니다."})
    done, warns = 0, []
    for user in team.members.filter(is_active=True):
        login = _login_of(user)
        if not login:
            warns.append(f"{user.display_name}: GitHub 미연결")
            continue
        w = try_write(set_gh_team_member, link, team.org, login, actor=actor, add=True)
        if w:
            warns.append(f"{user.display_name}: {w}")
        else:
            done += 1
    link.synced_at = timezone.now()
    link.save(update_fields=["synced_at"])
    return done, warns
```

**연결 해제는 PM 연결만 끊는다.** GitHub 팀은 그대로 둔다.

### 태스크 패널

`tasks/_git.html`에 버튼 셋을 더한다. `repo_state`가 `ok`이고 사용자가 GitHub 연결돼 있을 때만 보인다.

| 버튼 | 자리 | 동작 |
|---|---|---|
| [이슈 만들기] | 이슈 단계가 비어 있을 때, [이슈 연결] 옆 | `create_issue` |
| [브랜치 만들기] | 브랜치 단계가 비어 있을 때, [브랜치 연결] 옆 | 이름 입력(기본 `feat/TASK-<id>`) → `create_branch` |
| [이슈 #N 닫기] | 태스크가 완료인데 `issue_state == "open"`일 때 | `close_issue` |

이슈 닫기가 자동이 아닌 이유: PR 본문의 `Closes #N`으로 **GitHub가 머지 때 알아서 닫는다**. 이 버튼은 PM에서 손으로 완료한 경우에만 쓰인다.

### 조직 → GitHub 탭

설치 카드 아래에 **앱이 가진 권한**을 그대로 적어 둔다. 무엇을 할 수 있고 없는지 사람이 알아야 한다.

```
이 앱이 할 수 있는 것: 저장소 내용 읽기·브랜치 만들기 · 이슈 읽기·쓰기 · PR 읽기 · 조직 멤버와 팀 관리
할 수 없는 것: 저장소 삭제·설정 변경, 브랜치 보호 규칙, 저장소 권한 부여, PR 병합
```

---

## 6. Step 4. GitHub → PM 방향 (웹훅)

`GUIDE-V2-07`에서 `GitEvent`에만 남기던 두 이벤트를 실제로 처리한다.

| 이벤트 | 처리 |
|---|---|
| `membership` `added` | `GitHubTeamLink`를 `team.id`로 찾고, `member.id`로 `GitHubIdentity`를 찾아 `TeamMembership` 생성. 그 사람이 조직 멤버가 아니면 아무것도 하지 않고 이벤트에만 남긴다 |
| `membership` `removed` | 같은 방식으로 `TeamMembership` 삭제 |
| `team` `edited` | `slug`·`name` 갱신 |
| `team` `deleted` | `GitHubTeamLink` 삭제. **PM 팀은 남긴다** |

양방향이지만 서로 밀고 당기지 않는다. 각자 "일어난 사실"을 반영할 뿐이고, 동시에 바꾸면 나중 것이 이긴다. PM에서 한 변경이 웹훅으로 되돌아와도 결과가 같으므로 루프가 생기지 않는다(추가는 추가, 삭제는 삭제).

---

## 7. Step 5. 오류 문구

GitHub가 준 메시지를 **그대로** 보여 준다. PM이 다시 쓰지 않는다.

| 상황 | 화면 |
|---|---|
| 사용자가 GitHub 미연결 | 버튼 비활성 + "GitHub를 연결하면 할 수 있습니다" |
| 403 | "GitHub에 반영하지 못했습니다 (403: …). PM에만 적용됐습니다." |
| 404 | 같은 형식. 대개 그 사람이 그 조직·저장소를 못 본다는 뜻이다 |
| 토큰 만료·갱신 실패 | "GitHub 연결이 만료됐습니다. 프로필에서 다시 연결하세요." |
| 앱 미설치 | "이 조직에 GitHub 앱이 설치되어 있지 않습니다." + 설치 링크 |

전부 `messages` 프레임워크로 띄운다. 성공은 `success`, 부분 성공은 `warning`(`error`가 아니다. PM 변경은 됐다).

---

## 8. 테스트

`client.request`를 `monkeypatch`한다. 호출된 method·path·body를 기록해 검사한다.

| 이름 | 확인 |
|---|---|
| `test_writes_use_actor_token` | 모든 쓰기가 설치 토큰이 아니라 그 사람 토큰을 쓴다 |
| `test_write_without_identity_raises` | GitHub 미연결 사용자가 부르면 `ServiceError` |
| `test_write_failure_keeps_pm_change` | GitHub가 403이어도 PM 팀 멤버십은 남고 경고가 생긴다 |
| `test_invite_to_org_optional` | 체크 안 하면 GitHub를 부르지 않는다 |
| `test_team_create_syncs_when_linked` | 연결된 팀만 GitHub를 부른다 |
| `test_team_member_add_skips_unlinked_user` | GitHub 미연결 멤버는 PM에만 |
| `test_unlink_keeps_github_team` | 연결 해제는 `DELETE`를 부르지 않는다 |
| `test_delete_team_keeps_github_team` | PM 팀 삭제도 GitHub `DELETE`를 부르지 않는다 |
| `test_reconcile_adds_all_linked_members` | [GitHub에 반영]이 연결된 사람만 넣는다 |
| `test_membership_webhook_adds_pm_member` | GitHub에서 넣으면 PM 팀에도 들어온다 |
| `test_membership_webhook_ignores_non_org_member` | 조직 멤버가 아니면 무시 |
| `test_team_deleted_webhook_keeps_pm_team` | 링크만 사라진다 |
| `test_create_issue_sets_link` | 이슈 번호가 `TaskGitLink`에 붙고 패널 1단계가 ✓ |
| `test_close_issue_button_only_when_done_and_open` | 조건이 맞을 때만 버튼 |
| `test_create_branch_uses_default_branch_sha` | 기본 브랜치 sha로 만든다 |
| `test_create_branch_rejects_bad_name` | 공백·`..`·끝 슬래시 거부 |
| `test_no_repo_permission_writes` | 저장소 권한 부여 API를 부르는 코드가 없다 |

마지막 항목은 `grep`으로 고정한다.

```bash
grep -rn "teams/.*/repos" core/github && echo "저장소 권한 쓰기가 들어왔다" && exit 1
grep -rn 'DELETE.*/teams/' core/github && echo "GitHub 팀 삭제가 들어왔다" && exit 1
```

## 9. 검증

```bash
cd core && uv run ruff check . && uv run pytest -q
```

실제 조직에서:

1. 조직 → 팀 → [새 팀] → GitHub에도 팀이 생긴다
2. 팀에 사람을 넣으면 GitHub 팀에도 들어간다
3. GitHub에서 그 사람을 빼면 PM 팀에서도 빠진다
4. 팀 유지관리자가 아닌 계정으로 시도하면 경고가 뜨고 PM에만 반영된다
5. 패널에서 [이슈 만들기] → GitHub에 그 사람 이름으로 이슈가 생긴다
6. [브랜치 만들기] → `feat/TASK-<n>` 생성 → 곧 웹훅이 돌아와 진행 중이 된다
7. 저장소 탭의 접근 팀 표는 읽기 전용이고 [GitHub에서 변경]이 GitHub로 보낸다

## 10. 완료 체크

- [ ] 쓰기가 전부 사용자 토큰으로 나간다
- [ ] 설치 토큰을 쓰는 곳에 쓰기가 없다
- [ ] GitHub 거부 시 PM 변경이 살아 있고 경고가 보인다
- [ ] 저장소 권한을 바꾸는 코드가 없다
- [ ] 팀 양방향 동기화가 루프를 만들지 않는다
- [ ] 앱 권한 목록이 조직 GitHub 화면에 적혀 있다

---

## 11. v1 완료

여기까지가 v1이다. `GUIDE-V2-00` §4의 "넣지 않는 것"이 그대로 남아 있는지 확인하고, [IMPL-PLAN-2.md](IMPL-PLAN-2.md) §3의 완료 조건을 점검한다.

- 테스트 전부 통과(SQLite·Postgres), `ruff` 오류 0
- 목업 `산돌이 신규 기능 목업.dc.html`과 나란히 놓고 화면 대조
- 검수 시나리오 A01~A14·A18·B01~B05
- 실제 저장소에서 브랜치 → PR → 머지 한 사이클이 태스크를 끝까지 옮긴다

그 다음은 배포와 2주 시범 운영이다([GUIDE-04](GUIDE-04-deploy.md)). `.env`에 GitHub App 설정 6개와 `CREDENTIAL_KEY`가 추가된 것 말고 배포 절차는 바뀌지 않는다.
