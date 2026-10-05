# I — 라운드 8 설계: GitHub 연동 확장 (IMPL-PLAN-8 초안, Fable, 2026-10-05)

기준 커밋 `5d9b7bc`. 조사 보고서 `H-github-expansion.md`의 후보 #1~#13(#14·#15 제외)을 구현 지시서 수준으로 적는다.
GUIDE-00 규칙(업무 규칙은 `services`에만, 함수형 뷰, 새 의존성 없음, signals 금지, 테스트 skip 금지)과
라운드 7 규칙(가시성 관문 `visible_projects`/`can_view_project`/`visible_tasks`/`visible_teams`, `is_user_install` 분기,
웹훅 연결별 atomic 격리, `Task.reviewer`, 알림 메시지 형식, Idempotency 재생 검사)이 그대로 적용된다.
경로는 `core/` 기준. `services` = `github/services.py`. 코드 조각은 **그대로 옮긴다**(이름·시그니처 변경 금지).

## 0. 전제

### 0.1 사용자 결정(2026-10-05, 확정)
- 범위 = #1~#13 전부. #14 브랜치 보호·#15 GitHub Projects 제외.
- **PR·이슈가 다시 열리면 닫힌 태스크를 재개하지 않고 신규 태스크로 재개**(§4).
- 운영 서버·GitHub 앱 설정 변경은 사용자가 한다. 이 문서는 필요한 변경 목록(§1)만 정확히 적는다.
- 권한·구독이 아직 없을 때 기능은 **조용히 꺼진다**(이벤트가 오지 않으면 아무 일도 없고, 화면은 "정보 없음"으로 그린다).

### 0.2 동시 진행 중인 다른 에이전트
| 에이전트 | 소유 파일 | 이 라운드의 대응 |
|---|---|---|
| 디자인 시스템 | `DESIGN.md`, `web/static/app.css`, 템플릿 일부, `/design` 화면 | **템플릿 변경은 전부 마지막 단계(G9)**. 그 전 단계는 `.py`·`SKILL.md`·`discord_service`만 고친다 |

### 0.3 공통 원칙(이 라운드)
- 새 모델은 **`GitRelease` 하나**(릴리스는 `GitEvent` 50건 상한에 잘려 선반에 남길 수 없다). 나머지는 기존 모델의 열 추가.
- 쓰기는 누른 사람의 사용자 토큰(`writes.py`), 설치 토큰은 읽기만 — 그대로. 웹훅 경로의 PM 변경은 `actor=None`+`external_actor`.
- `actor=None` 호출은 `github/` 아래 파일에서만(`test_actor_none_only_from_github_services`가 `github/` 접두어로 허용한다). 새 파일 `github/ci.py`·`github/sync.py`는 이 규칙 안에 있다.
- 웹훅 디스패치는 `handle_event` 한 곳. 새 이벤트 처리기는 파일을 나누되(병렬 구현을 위해) 디스패치 표는 G0에서 한 번에 늘린다.
- 알림은 `tasks.work_requests.notify`(Notice 발송함)로만 만든다. core는 Discord로 직접 나가지 않는다. `discord_service`의 `deliver_notices`가 그대로 보낸다.

### 0.4 기준선
`cd core && uv run pytest -q` → **1268 passed**(2026-10-05, HEAD `5d9b7bc`, xfail 0). `ruff check .` 0이어야 한다.

---

## 1. GitHub 앱 권한·이벤트 변경 목록(사용자가 앱 설정에서 할 일)

GitHub 공식 문서로 확인한 것만 "확인"으로 적는다.

### 1.1 권한
| 권한 | 지금 | 필요 | 쓰는 기능 | 재승인 | 근거 |
|---|---|---|---|---|---|
| Pull requests | Read | Read(그대로) | #1·#2·#3(읽기)·#5·#11 | 없음 | `pull_request_review` 구독은 "at least read-level access for the 'Pull requests' repository permission" — https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request_review |
| **Checks** | 없음 | **Read** | #6·#7 | **재승인** | `check_suite`/`check_run`: "at least read-level access for the 'Checks' permission" — 같은 문서 `#check_suite` |
| **Commit statuses** | 없음 | **Read** | #6·#7(Actions가 아닌 외부 CI가 status API를 쓸 때) | **재승인** | `status`: "at least read-level access for the 'Commit statuses' repository permission" — 같은 문서 `#status` |
| Actions | 없음 | 추가하지 않음 | (#7에서 워크플로 이름까지 보여 주려면 필요하나 제외) | — | `workflow_run`은 Actions Read 필요. check_suite로 충분하다 |
| Contents | R/W | 그대로 | #10 | 없음 | `release`: "at least read-level access for the 'Contents' repository permission" — 같은 문서 `#release` |
| Issues | R/W | 그대로 | #8·#9(마일스톤 API는 Issues 범위) | 없음 | `milestone`: "at least read-level access for the 'Issues' or 'Pull requests' repository permissions" — 같은 문서 `#milestone` |
| Pull requests **Write** | 없음 | **추가하지 않음** | PM→GitHub 리뷰어 지정(#3 쓰기)은 범위 밖 | — | IMPL-PLAN-2 §4.3의 "PR은 읽기" 결정 유지. 리뷰 요청은 GitHub에서 한다 |

### 1.2 이벤트 구독 추가
| 이벤트 | 액션 | 기능 | 필요 권한(§1.1) |
|---|---|---|---|
| `pull_request` | 기존 + `reopened`·`ready_for_review`·`converted_to_draft`·`synchronize`·`review_requested`·`review_request_removed`·`edited` | #1·#3·#5·#6(head sha) | 이미 있음 |
| **`pull_request_review`** | `submitted`·`dismissed`·`edited` | #2·#5 | Pull requests Read(이미 있음) |
| **`check_suite`** | `requested`·`rerequested`·`completed` | #6·#7 | Checks Read |
| **`status`** | (액션 없음) | #6·#7 | Commit statuses Read |
| `issues` | 기존 + `reopened`·`edited`·`assigned`·`unassigned` | #8, 재개 | 이미 있음 |
| **`milestone`** | `created`·`edited`·`closed`·`opened`·`deleted` | #9 | 이미 있음(Issues) |
| **`release`** | `published`·`edited`·`deleted` | #10 | 이미 있음(Contents) |

`installation` 이벤트의 `new_permissions_accepted` 액션(재승인 완료)을 추가로 처리한다(§3.0).

### 1.3 재승인 영향(확인된 것)
- 권한을 **추가**하면 설치 계정마다 승인해야 한다: "each account where the app is installed will need to approve the new permissions", "Updated permissions won't take effect on an installation or user authorization until the new permissions are approved" — https://docs.github.com/en/apps/maintaining-github-apps/modifying-a-github-app-registration
- 승인 전에는 기존 권한으로 계속 동작한다: "The GitHub App will still retain its current permissions" — https://docs.github.com/en/apps/using-github-apps/approving-updated-permissions-for-a-github-app
- 따라서 **Checks·Commit statuses 추가 → 조직마다 재승인**. 승인 전에는 check_suite·status 이벤트가 오지 않아 #6·#7이 조용히 꺼진 상태로 나머지 기능은 그대로 돈다.
- **이벤트 구독만 추가할 때 재승인이 필요한지는 공식 문서에 명시가 없다 → "확인 불가"**(§10). 구독은 앱 등록 설정이라 통상 즉시 적용되는 것으로 알려져 있으나 문서로 확인하지 못했다. 구현은 어느 쪽이든 동작하도록 §3.0의 점검 화면으로 "구독 중/아님"을 보여 준다.

### 1.4 권장 순서(사용자)
1. 이벤트 구독 7종 추가(§1.2) — 권한 불필요한 것부터 켜진다.
2. Checks Read + Commit statuses Read 추가 → 조직 관리자가 GitHub 알림에서 승인.
3. PM 조직 GitHub 탭의 "앱 권한·이벤트 점검"(§3.0)에서 전부 ✓인지 확인.

---

## 2. 공통 설계

### 2.1 모델 변경(마이그레이션 4개, 번호 고정)

**`github/models.py` — `github 0006_round8`**
```python
# RepoConnection — 규칙 스위치 3개(기본 켬). REPO_SETTING_FIELDS에는 G9에서 넣는다(§7 주의).
rule_review = models.BooleanField(default=True)     # 리뷰 요청→검토자, 변경 요청→진행 중
rule_sync = models.BooleanField(default=True)       # 이슈 제목·담당자 ↔ 태스크
rule_milestone = models.BooleanField(default=True)  # GitHub 마일스톤 → PM 마일스톤

# TaskGitLink — PR·리뷰·CI 상태. 전부 선택적(빈 값 = 모름).
pr_draft = models.BooleanField(default=False)
pr_opened_at = models.DateTimeField(null=True, blank=True)
head_sha = models.CharField(max_length=40, blank=True)
# {login: "approved"|"changes_requested"|"commented"} — 리뷰어별 **마지막** 리뷰. dismissed면 지운다.
reviews = models.JSONField(default=dict, blank=True)
review_state = models.CharField(max_length=20, blank=True)  # ''|approved|changes_requested
review_requested_at = models.DateTimeField(null=True, blank=True)
reviewed_at = models.DateTimeField(null=True, blank=True)
# {"suite:<id>"|"status:<context>": "pending"|"success"|"failure"} — head_sha 기준. sha가 바뀌면 비운다.
ci_checks = models.JSONField(default=dict, blank=True)
ci_state = models.CharField(max_length=8, blank=True)  # ''|pending|success|failure
ci_url = models.CharField(max_length=300, blank=True)
ci_at = models.DateTimeField(null=True, blank=True)
# PM→GitHub로 이슈 필드를 마지막으로 쓴 시각. 그 전 updated_at의 issues 이벤트는 메아리로 보고 버린다(§2.5).
issue_synced_at = models.DateTimeField(null=True, blank=True)


class GitRelease(models.Model):
    """릴리스·태그. GitEvent는 50건에 잘리므로 선반에 남기려면 표가 따로 있어야 한다."""

    connection = models.ForeignKey(RepoConnection, on_delete=models.CASCADE, related_name="releases")
    tag = models.CharField(max_length=100)
    name = models.CharField(max_length=200, blank=True)
    url = models.CharField(max_length=300)
    prerelease = models.BooleanField(default=False)
    published_at = models.DateTimeField()
    # 이름이 같은 마일스톤이 있으면 잇는다(§3.10). 완료 처리는 사람이 한다.
    milestone = models.ForeignKey(
        "projects.Milestone", on_delete=models.SET_NULL, null=True, blank=True, related_name="releases"
    )

    class Meta:
        ordering = ["-published_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["connection", "tag"], name="gitrelease_conn_tag")]
```

**`tasks/models.py` — `tasks 0009_task_status_since`**
```python
# Task. 상태가 바뀐 시각. 검토 대기 경과일(에스컬레이션)·보드 "N일째"가 쓴다. null이면 옛 행(stopped_at으로 대체).
status_since = models.DateTimeField(null=True, blank=True)
```
`transition`의 `fields`에 `fields["status_since"] = timezone.now()` 한 줄(상태가 실제로 바뀔 때 — 같은 상태 재요청은 이미 앞에서 return).
데이터 마이그레이션 없음(null 허용, 대체 규칙은 §3.5).

**`projects/models.py` — `projects 0011_milestone_gh_number`**
```python
# Milestone. GitHub 마일스톤 번호. 저장소 하나가 프로젝트 둘에 이어지면 프로젝트마다 한 행씩 생긴다.
gh_number = models.PositiveIntegerField(null=True, blank=True)
# Meta.constraints += UniqueConstraint(fields=["project", "gh_number"], condition=Q(gh_number__isnull=False), name="milestone_project_gh_number")
```

**`portfolio/models.py` — `portfolio 0002_portfoliosource_pr_snapshot`**
```python
# PortfolioSource. 선택 시점의 병합 PR 근거 스냅샷. 번호·주소·병합일만 — 제목·본문·커밋 메시지는 담지 않는다(§6).
pr_url = models.CharField("병합 PR 주소 스냅샷", max_length=300, blank=True)
pr_merged_at = models.DateTimeField("병합 시각 스냅샷", null=True, blank=True)
```

### 2.2 설정 항목(`orgs/settings.py`, `notify` 그룹 **끝**에 덧붙인다)
```python
Spec("notify.github_channel_events", "set", (), "org", True, "notify", "GitHub 사건 채널 게시",
     "채널이 연결된 프로젝트만 해당합니다. 멘션은 넣지 않습니다.",
     choices=(("pr_opened", "PR 열림"), ("pr_merged", "PR 병합"), ("pr_changes", "PR 변경 요청"),
              ("ci_failed", "CI 실패"), ("issue_imported", "이슈 자동 가져옴"), ("release", "릴리스 발행"),
              ("reopened", "PR·이슈 재개로 새 태스크"))),
Spec("notify.github_dm", "bool", True, "org", True, "notify", "GitHub 개인 DM",
     "리뷰 요청은 검토자에게, 변경 요청·CI 실패·재개는 담당자에게 DM을 보냅니다. 개인 설정 '개인 DM 받기'를 끈 사람에게는 가지 않습니다."),
```
기본값: 채널 게시는 **꺼짐**(기존 `notify.project_channel_events`와 같은 원칙 — 소음은 조직이 켠다), DM은 켬.
`user.notify_dm`의 도움말에 "GitHub DM" 한 단어를 더한다(문구만).

### 2.3 알림 공통 함수(새 파일 `github/notify.py`, G0)
```python
from orgs.settings import effective
from tasks.work_requests import _due_text, _link, notify

def _line(task) -> str:
    """알림 메시지 형식(라운드 7): 제목·프로젝트·D-n·상태·링크. 격식체."""
    title = task.title.replace("[", "\\[").replace("]", "\\]")
    return (f"**{task.project.name}**\n• [{task.number} {title}](<{_link(f'/tasks/{task.pk}')}>)"
            f" · {_due_text(task.due_date)} · {task.get_status_display()}")

def channel(conn, kind: str, head: str, task=None, extra: str = "") -> None:
    """`notify.github_channel_events`에 kind가 있고 프로젝트 채널이 있을 때만. 비공개 프로젝트도 자기 채널이면 올린다."""
    project = conn.project
    if kind not in effective("notify.github_channel_events", org=project.org, project=project):
        return
    if not project.discord_channel_id:
        return
    text = head + ("\n" + _line(task) if task else "") + (f"\n{extra}" if extra else "")
    notify(project.org, text, channel_id=project.discord_channel_id)

def dm(task, user, head: str, extra: str = "") -> None:
    """`notify.github_dm`(조직·프로젝트)과 `user.notify_dm`(개인) 둘 다 켜져 있고, 그 사람이 프로젝트를 볼 수 있을 때만."""
    from tasks.services import can_see
    if user is None or not can_see(user, task.project):
        return
    if not effective("notify.github_dm", org=task.project.org, project=task.project):
        return
    if not effective("user.notify_dm", user=user):
        return
    notify(task.project.org, head + "\n" + _line(task) + (f"\n{extra}" if extra else ""), user=user)
```
`notify`는 Discord 미연결이면 만들지 않는다(기존). 메시지 머리말 예: `🔀 PR #12 열림`, `✅ PR #12 승인`, `✏️ PR #12 변경 요청`, `❌ CI 실패 (PR #12)`, `🔖 릴리스 v1.2 발행`, `🔁 PR #12 재개 → TASK-31 생성`.

### 2.4 상태 매핑 표(PM 상태 ↔ GitHub 사건)
`_apply`(services:693)가 유일한 통로다 — 닫힌 태스크는 바꾸지 않고 "닫힌 태스크"를 남긴다(재개는 §4가 따로 처리). 실패는 사유만 기록.

| GitHub 사건 | 조건 | PM 변화 | 스위치 |
|---|---|---|---|
| PR `opened` (draft=false) | 태스크 열림 | `review`, `pr_opened_at`·`review_requested_at`=now | `rule_pr` |
| PR `opened` (draft=true) | | `doing`(기한 없으면 "기한…" 사유로 변경 없음), `pr_draft=True` | `rule_pr` |
| PR `ready_for_review` | | `review`, `pr_draft=False`, `review_requested_at`=now(비어 있을 때) | `rule_pr` |
| PR `converted_to_draft` | status==review | `doing`, `pr_draft=True` | `rule_pr` |
| PR `synchronize` | | 상태 불변. `head_sha` 갱신, `ci_checks={}`·`ci_state=''`. `review_state=="changes_requested"`면 `review_requested_at=now`, `reviewed_at=None`(새 라운드) | — |
| PR `edited` | | 제목 캐시(`pr_title`) 갱신. 태스크 재탐색은 하지 않는다 | — |
| PR `review_requested` | 요청받은 사람이 PM 사용자·활성 멤버 | `Task.reviewer`=그 사람(update_task), `review_requested_at`=now | `rule_review` |
| PR `review_request_removed` | reviewer가 그 사람일 때 | `Task.reviewer=None` | `rule_review` |
| review `submitted` approved | | `reviews[login]="approved"`, 재계산. 상태 불변. `reviewed_at`=now | `rule_review` |
| review `submitted` changes_requested | status==review | `doing`(사유 "PR #n 변경 요청"), `reviewed_at`=now | `rule_review` |
| review `submitted` commented | | `reviews[login]="commented"`, 상태 불변 | — |
| review `dismissed` | | `reviews.pop(login)`, 재계산 | `rule_review` |
| PR `closed` merged | | `done`, `pr_state=merged` | `rule_merge` |
| PR `closed` unmerged | | 상태 불변, `pr_state=closed` | — |
| PR `reopened` | 태스크 열림 | `review`(draft면 `doing`), `pr_state=open` | `rule_pr` |
| PR `reopened` | 태스크 닫힘 | **신규 태스크**(§4) | `rule_pr` |
| issue `closed` | | `done` | `rule_issue` |
| issue `reopened` | 태스크 열림 | 상태 불변, `issue_state=open` | `rule_issue` |
| issue `reopened` | 태스크 닫힘 | **신규 태스크**(§4) | `rule_issue` |
| issue `edited`·`assigned`·`unassigned` | | 제목·담당자 동기화(§2.5) | `rule_sync` |
| `check_suite`·`status` | sha 또는 브랜치 일치 | `ci_checks`·`ci_state`·`ci_url`·`ci_at`. 상태 불변 | — |
| `release` published | | `GitRelease` upsert, 마일스톤 이름 일치 시 연결 | — |
| `milestone` * | | PM `Milestone` 동기화(§3.9) | `rule_milestone` |

`review_state` 재계산: `changes_requested`가 하나라도 있으면 `changes_requested`, 아니면 `approved`가 하나라도 있으면 `approved`, 아니면 `''`.
`ci_state` 재계산: `failure`(failure·timed_out·cancelled·action_required·error 포함)가 하나라도 있으면 `failure`, 아니면 `pending`이 있으면 `pending`, 아니면 값이 있으면 `success`.

### 2.5 양방향 동기화의 충돌·루프 규칙(#8 이슈 필드, #9 마일스톤)

| 방향 | 대상 | 언제 | 토큰 | 거부·실패 |
|---|---|---|---|---|
| GitHub → PM | 이슈 제목 → `Task.title` | `issues.edited`(changes.title 있음) | — | 값이 같으면 "변경 없음" |
| GitHub → PM | 이슈 assignee → `Task.assignee` | `issues.assigned`·`unassigned`·`edited` | — | 매핑 안 되는 로그인·미배정은 바꾸지 않는다(PM은 담당자 필수) |
| PM → GitHub | `Task.assignee` → 이슈 assignees | `update_task`가 assignee를 바꾼 직후 | **행위자** | 행위자 GitHub 미연결·새 담당자 미연결·GitHub 거부 → PM은 바뀐 채 `task.gh_warning`에 경고 |
| PM → GitHub | 제목 | **자동 반영하지 않는다**(제목은 `update_text` 자동 저장 경로라 저장마다 GitHub를 부르게 된다) | — | 질문 1 |
| PM → GitHub | 마일스톤 | 로드맵 대화상자의 "GitHub에도 반영" 체크를 켠 저장만 | 행위자 | 경고 |

**이기는 쪽**: 같은 필드를 양쪽에서 바꾸면 **나중에 쓴 쪽이 이긴다(last-write-wins)**. 단 메아리 차단 두 겹:
1. **값 동일 → 무시.** GH→PM: 정규화한 제목(`_strip_task_suffix`: 끝의 ` (TASK-n)` 제거)·담당자가 지금 값과 같으면 "변경 없음". PM→GH: 쓰기 전 `link.issue_title`·캐시된 assignee와 같으면 부르지 않는다.
2. **시각 역전 → 무시.** PM→GH 쓰기 성공 직후 `link.issue_synced_at = now`. `issues.*` 이벤트의 `issue.updated_at <= issue_synced_at`이면 "메아리"로 기록만 한다.
제목 변환: PM→GH `f"{task.title} ({task.number})"`(create_issue와 같은 꼴), GH→PM `_strip_task_suffix(title)[:200]`.
PM 담당자 변경이 **담당 요청**으로 돌 때(`can_assign_directly`가 False)는 실제 담당자가 바뀐 게 아니므로 GitHub에 쓰지 않는다.

---

## 3. 기능별 설계

### 3.0 디스패치·점검(G0, `github/services.py`)
```python
def _handlers() -> dict:
    """이벤트 → 처리기. 새 처리기 파일이 services를 import하므로 늦게 묶는다(순환 import 회피)."""
    from . import ci, sync
    return {
        "create": _on_create, "push": _on_push, "pull_request": _on_pr, "issues": _on_issues,
        "pull_request_review": _on_pr_review,
        "check_suite": ci.on_check_suite, "status": ci.on_status,
        "milestone": sync.on_milestone, "release": sync.on_release,
    }
```
`handle_event`의 `handler = {...}.get(event)` → `handler = _handlers().get(event)`. 그 밖은 그대로(연결별 atomic, 실패 기록, delivery 중복).
`_occurred_at`에 `pull_request_review`(review.submitted_at), `check_suite`(check_suite.updated_at), `status`(updated_at), `release`(release.published_at), `milestone`(milestone.updated_at) 추가.
`_installation_event`: `action == "new_permissions_accepted"`면 `cache.delete(f"gh-app-caps:{inst_id}")`.

**앱 권한·이벤트 점검**(G8 서비스, G9 화면):
```python
REQUIRED_CAPS = {  # 기능 → (권한 키, 최소 수준, 이벤트들)
    "ci": ("checks", "read", ("check_suite",)),
    "ci_status": ("statuses", "read", ("status",)),
    "review": ("pull_requests", "read", ("pull_request_review",)),
    "milestone": ("issues", "read", ("milestone",)),
    "release": ("contents", "read", ("release",)),
}

def app_capabilities(org) -> dict | None:
    """GET /app/installations/{id}(앱 JWT)의 permissions·events로 기능별 사용 가능 여부. 1시간 캐시.
    설치가 없거나 GitHub 오류면 None(화면은 '확인 불가'로 그린다). 쓰는 곳: 조직 GitHub 탭(관리자)."""
```
반환 예: `{"ci": {"ok": False, "missing": ["Checks 읽기 권한", "check_suite 구독"]}, ...}`. 화면 문구: "Checks 읽기 권한이 없어 CI 배지가 꺼져 있습니다. 앱 설정에서 권한을 추가하고 조직에서 승인해 주세요."

### 3.1 #1 PR 상태 처리 확장(G1, `services._on_pr`)
- `action not in ("opened","closed")`를 지우고 §2.4 표대로 분기한다. `task is None`이면 지금처럼 "연결 안 됨".
- 공통: `link.pr_number/pr_title/pr_state/pr_draft/head_sha(pr.head.sha)/branch` 갱신. `opened`일 때 `pr_opened_at=parse_ts(pr.created_at)`.
- `reopened`이고 `not task.is_open` → `reopen_as_new(conn, delivery, payload, old=task, kind="pr")`(§4) 뒤 return.
- `synchronize`: CI 초기화·리뷰 라운드 규칙(§2.4). `edited`: 제목만.
- 결과 문구는 `_apply` 반환 그대로. 이벤트 `summary=f"PR #{number} {action}"`.
- 채널: `opened`→`notify.channel(conn,"pr_opened","🔀 PR #n 열림",task, extra=pr_url)`, merged→`"pr_merged"`.

### 3.2 #2 PR 리뷰 상태(G1, 새 처리기 `services._on_pr_review`)
```python
def _on_pr_review(conn, delivery, payload):
    """pull_request_review submitted|dismissed|edited. 태스크는 pr_number로 찾는다(제목 재탐색 안 함)."""
```
- 찾기: `TaskGitLink.objects.filter(connection=conn, pr_number=pr.number).select_related("task").order_by("-task_id").first()` — 같은 PR에 링크가 둘(재개로 생긴 새 태스크)이면 **열린 태스크 우선**, 없으면 최신.
- `reviews[login]` 갱신 → `review_state` 재계산 → 저장. `submitted` approved/changes_requested면 `reviewed_at=parse_ts(review.submitted_at)`.
- `rule_review`이고 `changes_requested`이고 `task.status=="review"` → `_apply(task,"doing",note="PR #n 변경 요청")`. 기한이 없으면 실패 사유가 남는다(검토 대기였던 태스크는 보통 기한이 있다).
- DM: approved → `notify.dm(task, task.assignee, "✅ PR #n 승인")`, changes_requested → `"✏️ PR #n 변경 요청"`; 채널 `"pr_changes"`.
- 자기 PR에 자기 리뷰(코멘트)는 GitHub가 approve를 막으므로 별도 규칙 없음.

### 3.3 #3 리뷰 요청 ↔ 검토자(G1, `_on_pr`의 `review_requested`/`review_request_removed`)
- `requested_reviewer.id` → `GitHubIdentity.github_id` → 활성 사용자. 팀 리뷰어(`requested_team`)는 무시(기록만).
- `update_task(task, {"reviewer": user}, actor=user_for_sender(payload), source="gh", expected_version=task.version, external_actor=_sender_login(payload))` — `_validate`가 조직 멤버·`can_see`·`self_review`(담당자=검토자 금지)를 검사하고 거부하면 사유가 이벤트에 남는다. 비공개 프로젝트 가시성 검사는 여기서 자동으로 걸린다.
- 제거: `task.reviewer_id == user.pk`일 때만 `{"reviewer": None}`.
- DM: `notify.dm(task, user, "👀 PR #n 리뷰 요청")`(설정 §2.2). PM→GitHub 리뷰어 지정은 하지 않는다(PR Write 없음, §1.1).

### 3.4 #4 프로젝트 채널 게시(G0 helper + 각 처리기)
§2.3 `notify.channel`을 각 사건에서 부른다. 종류·호출 지점: `pr_opened`(_on_pr), `pr_merged`(_on_pr), `pr_changes`(_on_pr_review), `ci_failed`(ci.py), `issue_imported`(`_on_issues` 자동 가져오기 성공 지점, "📥 이슈 #n → TASK-m 가져옴"), `release`(sync.py), `reopened`(§4). `discord_service`는 바꾸지 않는다(`deliver_notices`가 채널 id로 보낸다). 같은 delivery는 웹훅 단계에서 중복 제거되므로 알림도 한 번이다.

### 3.5 #5 리뷰 지연 독촉(G0 brief·G6 봇)
- 발견한 불일치: `escalate.py:158`은 `stopped_at`으로 경과일을 재는데 `transition`은 `review`에 `stopped_at`을 두지 않는다(STOPPED만). **지금 검토 독촉은 사실상 나가지 않는다.** `status_since`(§2.1)가 이를 고친다.
- `tasks/brief.py task_brief`에 `"status_since": iso(t.status_since)`, `"review_requested_at": getattr(t, "review_requested_at", None)` 추가. 후자는 **annotate된 경우에만** 값이 있다: `api/routers/orgs.py org_tasks` → `list_tasks` 결과 쿼리에 `.annotate(review_requested_at=F("git__review_requested_at"))`(LEFT JOIN, N+1 없음). 다른 경로는 None.
- `discord_service/escalate.py`: REVIEW 경과일 = `_days_since(t.get("review_requested_at") or t.get("status_since") or t.get("stopped_at"), today)`. BLOCKED는 그대로 `stopped_at`. 수신자 규칙(검토자 우선)은 기존.
- 설정은 `notify.review_nudge_days` 재사용. 새 항목 없음.

### 3.6 #6 CI 배지(G2, 새 파일 `github/ci.py`)
```python
FAIL = {"failure", "timed_out", "cancelled", "action_required", "error", "startup_failure", "stale"}

def _links_for(conn, sha: str, branches: list[str]) -> list[TaskGitLink]:
    """head_sha가 같은 링크 → 없으면 branch가 같은 링크. 열린 태스크 우선."""

def on_check_suite(conn, delivery, payload): ...   # action requested|rerequested → pending, completed → conclusion
def on_status(conn, delivery, payload): ...        # state pending|success|failure|error, context, target_url, branches[]
def recompute(link) -> None:                       # ci_checks → ci_state (§2.4), 저장
```
- 키: `f"suite:{check_suite.id}"` / `f"status:{context}"`. `ci_url`: check_suite는 `https://github.com/{full_name}/commit/{sha}/checks`, status는 `target_url`.
- `head_sha`가 비어 있는 링크(PR 전, 브랜치만)도 브랜치 이름으로 맞춘다 → PR 열기 전 CI도 보인다.
- 상태 전이 없음. `record_event(kind="check", summary=f"CI {state} {sha[:7]}", task=..., result=ci_state)`.
- 권한이 없으면 이벤트가 오지 않을 뿐이다. 화면은 `ci_state==''`면 배지를 그리지 않는다.

### 3.7 #7 CI 실패 알림(G2, `ci.recompute` 직후)
- `recompute` 전후를 비교해 **`failure`로 바뀐 순간**만: `notify.dm(task, task.assignee, "❌ CI 실패", extra=ci_url)` + `notify.channel(conn, "ci_failed", "❌ CI 실패 · PR #n", task, extra=ci_url)`. `synchronize`가 `ci_checks`를 비우므로 새 커밋의 실패는 다시 알린다. 같은 sha의 재실패(rerequested→failure)는 `failure→pending→failure`로 다시 알린다(의도: 재실행 결과를 알고 싶다).
- 닫힌 태스크(병합 뒤 main CI 등)는 알리지 않는다(`task.is_open` 검사).

### 3.8 #8 이슈 ↔ 태스크 필드 동기화(G1 GH→PM, G4 PM→GH)
GH→PM(`services._on_issues`, `edited`·`assigned`·`unassigned` 분기, `row.task`가 있고 `conn.rule_sync`일 때):
```python
TASK_SUFFIX_RE = re.compile(r"\s*\(TASK-\d+\)\s*$", re.I)
def _strip_task_suffix(title: str) -> str: ...

def _sync_issue_fields(conn, link, task, issue: dict, payload: dict) -> str:
    """제목·담당자를 태스크에 맞춘다. 메아리·동일 값은 건너뛴다(§2.5). 결과 문구를 돌려준다."""
```
- 메아리: `parse_ts(issue.updated_at) <= link.issue_synced_at` → "메아리".
- 제목: `update_text(task, "title", new, actor=user_for_sender(payload) , source="gh")` — `update_text`는 actor None을 받는가? `_require_member(None)`은 통과하고 `_log`는 actor None+external_actor를 지원하므로 `update_text`에 `external_actor=""` 인자를 **추가**한다(G0, 기본값 빈 문자열이라 호출부 불변).
- 담당자: 로그인 → `GitHubIdentity(login__iexact)` → 활성·`is_member`·`can_see` → `update_task(task, {"assignee": user}, actor=None, source="gh", expected_version=task.version, external_actor=login)`. `can_assign_directly(source="gh")`가 True라 요청으로 돌지 않는다. 미배정·매핑 실패는 "담당자 유지".
- 닫힌 태스크는 제목·담당자를 바꾸지 않는다(이력 보존).
- `reopened` → §4.

PM→GH(G4, `github/sync.py` + `tasks/services.update_task` 끝에 훅):
```python
# tasks/services.update_task — `_apply` 뒤, 담당자 로그 뒤에:
task.gh_warning = ""
if "assignee" in fields and actor is not None:
    from github.sync import after_assignee_change  # 늦은 import: github가 tasks.services를 import한다
    task.gh_warning = after_assignee_change(task, actor=actor)

# github/sync.py
def after_assignee_change(task, *, actor) -> str:
    """연결된 열린 이슈가 있고 rule_sync면 행위자 토큰으로 assignees를 바꾼다. 경고 문자열(없으면 '')."""
    # link·issue_state=='open'·rule_sync 아니면 '' / 새 담당자 GitHub 미연결 → "담당자가 GitHub 미연결이라 이슈 담당자는 바꾸지 않았습니다."
    # 성공: link.issue_synced_at = now. 실패: writes.try_write 문구 그대로.
```
`writes.py`에 추가(전부 행위자 토큰):
```python
def set_issue_assignees(link, logins: list[str], *, actor): ...   # PATCH /repos/{o}/{r}/issues/{n} {"assignees": logins}
def create_gh_milestone(ms, *, actor) -> dict: ...                # POST /repos/{o}/{r}/milestones {title, due_on, state}; ms.gh_number 저장
def update_gh_milestone(ms, *, actor): ...                        # PATCH /repos/{o}/{r}/milestones/{gh_number}
```
`task.gh_warning`은 모델 열이 아니라 인스턴스 속성이다. 표면화: 웹 `task_meta`(담당자 변경 응답)에 `messages.warning`, API `PATCH /api/tasks/{id}` 응답 `TaskOut`에 `warning: str|None`(스키마에 Optional 추가), MCP·Discord는 API를 지나므로 자동.

### 3.9 #9 마일스톤 동기화(G4, `github/sync.py` + `projects/services.py`)
```python
# projects/services.py — 웹훅용. 권한 검사 없음(연결된 저장소가 근거). ChangeLog 없음(Milestone은 원래 이력이 없다).
def sync_milestone(project, *, gh_number: int, name: str, target_date, status: str, created_by) -> Milestone:
    """gh_number로 찾아 갱신, 없으면 만든다. target_date가 None이고 새로 만들어야 하면 ServiceError({"target_date": "GitHub 마일스톤에 목표일이 없습니다."})."""

# github/sync.py
def on_milestone(conn, delivery, payload):
    """created|edited|opened|closed → sync_milestone, deleted → gh_number만 비운다(PM 행은 남긴다)."""
```
- 매핑: `title→name[:100]`, `due_on→target_date`(없으면 기존 값 유지), `state closed→done`, `open→(status가 done이면 active, 아니면 유지)`. `created_by = _import_actor(conn, payload) or conn.created_by`.
- `rule_milestone` 꺼짐 → 기록만. 개인 계정 설치도 동작한다(마일스톤은 저장소 자원).
- 메아리: `sync_milestone` 결과가 모든 필드 동일이면 "변경 없음". PM→GH는 체크박스로만(§2.5) 쓰고 성공 시 `gh_number`를 저장하므로 되돌아온 `created` 이벤트는 동일 값으로 무시된다.
- 로드맵 대화상자(`web/views/roadmap.py milestone_new/edit`): 프로젝트에 저장소가 있고 행위자가 GitHub 연결 상태면 체크박스 `github` → `try_write(create_gh_milestone|update_gh_milestone, ms, actor=request.user)` → 경고는 `messages.warning`. 템플릿 체크박스는 G9.
- 이슈의 `milestoned`/`demilestoned`는 다루지 않는다 — `Task`에 마일스톤 FK가 없다(IMPL-PLAN-2 §3 "후속"). 이 라운드에 FK를 더하지 않는다.

### 3.10 #10 릴리스 → 마일스톤·결과 선반(G4, `github/sync.py`)
```python
def on_release(conn, delivery, payload):
    """published|edited → GitRelease upsert(태그 기준). deleted → 삭제. draft는 무시."""
```
- 마일스톤 연결: `Milestone.objects.filter(project=conn.project).filter(Q(name__iexact=tag)|Q(name__iexact=name)).first()` → `release.milestone`. 완료 처리는 하지 않는다(제안만).
- 채널 `release`: "🔖 릴리스 v1.2 발행" + 주소 + (마일스톤이 있고 done이 아니면) "마일스톤 'v1.2'를 완료로 표시할 수 있습니다."
- 화면(G9): `projects/_shelf.html` 상단 "릴리스" 띠(최근 5건: 태그·이름·날짜·prerelease 배지·링크, 프로젝트 저장소를 볼 수 있는 사람만 — `repo_state(...)["state"]=="ok"`). `orgs/roadmap.html` 마일스톤 막대에 릴리스 태그 칩 + status≠done이면 [완료로 표시] 버튼(기존 `milestone_edit`에 `status=done`만 보내는 작은 폼).
- 서비스: `github/services.releases_for(project, user) -> list[GitRelease]`(가시성 검사 포함, 선반·API가 쓴다).

### 3.11 #11 주간 보고 GitHub 지표(G6, 새 파일 `github/metrics.py`)
```python
def weekly_metrics(projects, start, end) -> dict | None:
    """저장소가 연결된 프로젝트가 없으면 None. 모두 TaskGitLink에서 센다(GitEvent는 50건에 잘린다).
    {"merged": n, "opened": n, "open": n, "avg_review_hours": float|None, "ci_failing": n}"""
```
- merged: `merged_at∈[start,end)`, opened: `pr_opened_at∈[start,end)`, open: `pr_state=="open"`, avg_review_hours: `reviewed_at∈[start,end)`이고 `review_requested_at`이 있는 링크의 평균(시간, 소수 1자리), ci_failing: `pr_state=="open" and ci_state=="failure"`.
- `reports/services.weekly(...)` 반환에 `"github": weekly_metrics(shown_projects, start, end)` 추가(비공개 프로젝트 제외 규칙은 `shown_projects`가 이미 적용). `org_status`는 건드리지 않는다.
- `discord_service/summarize.py` 고정 형식에 한 줄(값이 있을 때만): `GitHub: 병합 PR 3건 · 새 PR 5건 · 열린 PR 4건 · 평균 리뷰 6.5시간 · CI 실패 1건`.
- `skills/pm-weekly/SKILL.md`에 "`github` 블록이 있으면 한 줄로 넣는다, 없으면 생략" 추가. 웹 주간 화면이 있으면 같은 줄(없으면 생략).

### 3.12 #12 Discord 슬래시로 GitHub 동작 → §5
### 3.13 #13 포트폴리오 → §6

---

## 4. 재개 = 신규 태스크(사용자 결정)

### 4.1 규칙
- 대상: PR `reopened` 또는 이슈 `reopened`가 **닫힌(done·cancelled) 태스크**에 연결돼 있을 때. 열린 태스크면 §2.4의 보통 규칙.
- 스위치: PR은 `rule_pr`, 이슈는 `rule_issue`. 꺼져 있으면 기록만("규칙 꺼짐").
- 템플릿(`is_template`)은 닫힐 수 없으므로 해당 없음. 보관 프로젝트는 `create_task`가 거부 → 실패 사유 기록.

### 4.2 함수(G1, `services.py`)
```python
def reopen_as_new(conn, delivery, payload, *, old, kind: str) -> Task | None:
    """닫힌 태스크에 연결된 PR·이슈가 다시 열렸다. 원 태스크는 두고 계열(parent)로 이어지는 새 태스크를 만들어 그 PR·이슈에 잇는다.

    중복 방지: 같은 PR·이슈 번호에 **열린** 태스크가 이미 이 연결에 있으면 그것을 돌려주고 만들지 않는다
    (재전송·연속 reopen 모두 여기서 걸린다. delivery 중복은 handle_event가 먼저 거른다).
    """
    number = (payload.get("pull_request") or payload.get("issue") or {}).get("number")
    field = "pr_number" if kind == "pr" else "issue_number"
    existing = (TaskGitLink.objects.filter(connection=conn, **{field: number}, task__status__in=Task.OPEN)
                .select_related("task").first())
    if existing:
        record_event(conn, delivery, kind=..., payload=payload, summary=..., task=existing.task, result="이미 재개됨")
        return existing.task
    actor = _import_actor(conn, payload) or old.assignee   # created_by가 NOT NULL이라 None일 수 없다
    new = duplicate_task(old, actor=actor, source="gh", title=old.title, due_date=None,
                         no_due_reason=f"{'PR' if kind=='pr' else '이슈'} #{number} 재개로 생성", assignee=old.assignee)
    ...
```
- `duplicate_task`가 하는 것(기존 규칙 그대로): 설명·완료 조건·다음 행동·중요도·체크리스트(**전부 미완료**)·링크·문서 복사, `parent = old.parent or old`(평평한 계열), `reviewer`는 담당자와 다를 때만 복사, 첨부는 복사 안 함. 행위자는 `_import_actor`(sender가 PM 사용자면 그 사람 → 프로젝트 첫 관리자) → 없으면 원 담당자. `source="gh"`라 담당 요청으로 돌지 않는다(`can_assign_directly`).
- 링크: `link = _link_for(conn, new)`; 원 링크의 `issue_number/issue_title/branch`를 복사. PR 재개면 `pr_number/pr_title/pr_state="open"/pr_draft/head_sha/pr_opened_at=원값`. 이슈 재개면 `issue_state="open"`이고 `RepoIssue(connection, number).task = new`(이슈 하나는 열린 태스크 하나만 가리킨다). 원 태스크의 링크는 **그대로 둔다**(이력).
- 상태: PR 재개 → `_apply(new, "review")`(draft면 `"doing"` — 기한이 없어 "기한…" 사유로 todo에 남는다; 사람이 기한을 넣고 시작한다). 이슈 재개 → todo 유지.
- 이력: 원 태스크에 `_log(old, "reopened_as", "", new.number, actor, "gh", note=f"{kind} #{number} 재개", external_actor=login)`. 새 태스크에는 `duplicate_task`가 `parent` 로그("TASK-n에서 복제")를 남긴다.
- 알림: `notify.dm(new, new.assignee, f"🔁 {kind} #{number} 재개 → {new.number} 생성")`, 채널 `reopened`.
- 이벤트: `record_event(..., task=new, result=f"{new.number} 생성")`.
- 세 번째 reopen(새 태스크도 닫힌 뒤 또 reopen) → 같은 규칙으로 계열에 또 하나. `parent`는 항상 뿌리.

### 4.3 원 태스크 표시(G9)
- 패널 "같은 계열" 블록(`_series.html`)에 둘 다 보인다(기존).
- `_git.html`: 태스크가 닫혀 있고 같은 연결·같은 번호의 열린 링크가 있으면 "이 PR은 다시 열려 **TASK-m**에서 이어집니다." 한 줄(`_git_ctx`에 `continued_by` 추가: `TaskGitLink.objects.filter(connection=link.connection, pr_number=link.pr_number, task__status__in=Task.OPEN).exclude(task=task).first()`; 이슈도 같은 꼴).
- API `GET /api/tasks/{id}/github`에 `"continued_by": {"id","number"}|None`.

---

## 5. #12 Discord 슬래시로 GitHub 동작(G5)

### 5.1 원칙
- **GitHub 쓰기는 누른 사람의 GitHub 사용자 토큰**(`writes.py` 그대로 호출). 봇 토큰은 core API 인증에만 쓴다.
- 신원 3단: Discord 사용자 → PM 사용자(`_actor`, 연결 필수) → GitHub 신원(`actor.github`, 없으면 "GitHub를 연결해야 할 수 있습니다." 문구 그대로).
- PM 권한: `get_visible_task`(가시성), `task.project.dev_tools`, `repo_state(actor, project)["state"] == "ok"`(저장소 접근 권한). 등급 검사는 기존 웹 뷰와 같이 **없음**(이슈·브랜치 만들기는 멤버 누구나, GitHub가 최종 거부).
- Discord 서버 권한(`orgs.channels.require_discord`)은 **적용하지 않는다** — 그 검사는 Discord 자원(채널·권한)을 바꾸는 동작용이고, GitHub 동작은 Discord 자원을 건드리지 않으며 GitHub 토큰이 곧 권한이다. 명령은 길드 전용 등록(`guild=guild`)이라 조직에 연결된 서버 안에서만 뜬다(DM 불가). → 질문 2.
- AI 정책 무관(source="dc").

### 5.2 core API(`api/routers/discord.py`, `BotTokenAuth`)
```python
@router.post("/tasks/{task_id}/github/branch", response=dict)   # DiscordBranchIn(discord_user_id, name: str|None)
@router.post("/tasks/{task_id}/github/issue", response=dict)    # DiscordActorIn
@router.post("/tasks/{task_id}/github/pr-url", response=dict)   # DiscordActorIn → {"url": pr_compare_url(link)}
```
- 공통 `_github_task(actor, task_id)`: `_task` → `dev_tools` 아니면 404 "개발 도구를 끈 프로젝트입니다." → `repo_state` ok 아니면 400(상태별 기존 문구: 저장소 미연결 / GitHub 미연결 / 접근 권한 없음).
- branch: `name or default_branch_name(task)` → `gh_writes.create_branch(task, name, actor=actor)`; 이미 브랜치가 있으면 400 "이미 브랜치 X가 연결돼 있습니다."
- issue: 이미 `issue_number`면 400 "이미 이슈 #n이 연결돼 있습니다."; `gh_writes.create_issue(task, actor=actor)`.
- pr-url: `link.branch` 없으면 400 "브랜치를 먼저 만들어 주세요."
- `GitHubError`·`ServiceError` → `HttpError(400, 문구)`(ServiceError는 라우터 공통 처리기가 있으면 그대로).

### 5.3 봇(`discord_service`)
- `core_client.py`: `gh_branch(did, task_id, name)`, `gh_issue(did, task_id)`, `gh_pr_url(did, task_id)`.
- `slash.py`: `/브랜치 번호 [이름]`, `/이슈만들기 번호`, `/pr 번호`(자동완성 `ac_task`). 응답은 ephemeral: "브랜치 `feat/...(TASK-12)`를 만들었습니다." / "이슈 #34를 만들었습니다. https://github.com/o/r/issues/34" / "PR 작성 화면: <url>". 오류는 core 문구 한 줄.
- `messages.SLASH_HELP`에 한 줄 추가. 분당 20회 제한은 `respond`가 이미 건다.

### 5.4 테스트
`core/api/test_discord_github.py`(새): 미연결 Discord 404, dev_tools 끈 프로젝트 404, 저장소 접근 없음 400, 브랜치 생성이 `writes.create_branch`를 행위자 토큰으로 부름(monkeypatch, `installation_token` 미호출), 이미 연결된 이슈 400, pr-url 반환. `discord_service/tests/test_slash_github.py`(새): 세 명령이 core_client를 올바른 인자로 부르고 응답 문구가 맞음.

---

## 6. #13 포트폴리오에 병합 PR 근거(G7)

- 근거 연결 규칙: 포트폴리오 출처(결정 기록)의 태스크에 **병합된 PR**(`TaskGitLink.pr_state=="merged"`)이 있으면 그 PR을 근거로 붙인다. 열린·닫힌 PR은 붙이지 않는다(결과가 아니다).
- 노출 규칙: **번호·주소·병합일만.** PR 제목·본문·커밋 메시지·브랜치 이름은 내보내지 않는다(GitHub 원문은 GitHub 권한 영역). 비공개 프로젝트는 `visible_projects`가 이미 거른다(`sources._allowed_source_records`). 추가로 **초안 소유자가 `can_view_repo(owner, conn.full_name)`일 때만** 붙인다 — 저장소를 못 보는 사람의 포트폴리오에 저장소 이름이 들어가면 안 된다.
- `sources._serialize_source`: `"pr": {"url", "merged_at"}|None`(위 두 검사). `drafts._snapshot`: `PortfolioSource.pr_url/pr_merged_at` 채움(선택 시점 스냅샷, 이후 연결 해제돼도 유지 — 결정 기록 스냅샷과 같은 원칙). `_check_sources`는 PR을 재검증하지 않는다(사실은 변하지 않는다).
- `drafts.export_markdown`: 출처 항목 끝에 `— 근거: PR #12 (2026-10-01 병합) <url>`. `api/portfolio.py _source_out`·MCP `list_portfolio_sources`는 직렬화를 지나므로 자동.
- 테스트 `portfolio/test_pr_evidence.py`(새): 병합 PR만 붙음, 저장소 권한 없는 소유자에겐 None, 비공개 프로젝트 제외, 스냅샷이 해제 뒤에도 남음, 마크다운 한 줄, verbatim·제목 미포함.

---

## 7. 구현 단계 표

| 단계 | 내용 | 담당 | 선후 | 마이그레이션 | 주로 고치는 파일 | 충돌 주의 |
|---|---|---|---|---|---|---|
| **G0** 기반 | §2.1 모델 4곳·§2.2 설정·§2.3 `github/notify.py`·§3.0 `_handlers`/`_occurred_at`/`new_permissions_accepted`·`transition` status_since·`update_text(external_actor="")`·`task_brief` 2필드·`org_tasks` annotate·새 파일 `ci.py`·`sync.py`는 **빈 처리기(기록만)**로 생성 | Opus | 바로 시작 | `github 0006`, `tasks 0009`, `projects 0011`, `portfolio 0002` | `github/{models,services,notify,ci,sync}.py`, `tasks/{models,services,brief}.py`, `projects/models.py`, `portfolio/models.py`, `orgs/settings.py`(notify 끝), `api/routers/orgs.py` | 마이그레이션은 전부 여기서 한 번에. 이후 단계는 마이그레이션을 만들지 않는다 |
| **G1** PR·리뷰·재개·이슈 GH→PM | §3.1 §3.2 §3.3 §3.8(GH→PM) §4 + 각 지점 알림 호출(§3.4) | Opus | G0 뒤 | 없음 | `github/services.py`, `github/test_pr_round8.py`(새) | `services.py`는 G1만 만진다 |
| **G2** CI | §3.6 §3.7 | Sonnet | G0 뒤, G1과 병렬 | 없음 | `github/ci.py`, `github/test_ci.py`(새) | 없음 |
| **G4** 동기화·릴리스·PM→GH | §3.8(PM→GH) §3.9 §3.10, `writes.py` 3함수, `projects/services.sync_milestone`, `update_task` 훅, 로드맵 뷰 체크박스 처리(템플릿은 G9) | Opus | G0 뒤, G1·G2와 병렬 | 없음 | `github/{sync,writes}.py`, `projects/services.py`, `tasks/services.py`(update_task 끝 4줄), `web/views/{roadmap,tasks}.py`(경고 표시), `api/routers/tasks.py`(PATCH warning)·`api/schemas.py`, `github/test_sync.py`(새) | `tasks/services.py`는 G0가 먼저 끝난 뒤. `api/routers/tasks.py`는 G8과 순차 |
| **G5** Discord 슬래시 | §5 | Sonnet | G0 뒤, 병렬 | 없음 | `api/routers/discord.py`, `api/schemas.py`(Discord*In), `discord_service/{core_client,slash,messages}.py`, 테스트 2개(새) | `api/schemas.py`는 G4도 만진다(다른 클래스) → 순차 병합 |
| **G6** 주간 지표·독촉 | §3.11, §3.5 봇 쪽 | Sonnet | G0 뒤, 병렬 | 없음 | `github/metrics.py`(새), `reports/services.py`, `discord_service/{summarize,escalate}.py`, `skills/pm-weekly/SKILL.md`, 테스트 | `discord_service`는 G5와 다른 파일 |
| **G7** 포트폴리오 | §6 | Sonnet | G0 뒤, 병렬 | 없음 | `portfolio/{sources,drafts}.py`, `portfolio/test_pr_evidence.py`(새) | 없음 |
| **G8** API·MCP·스킬·점검 | `GET /api/tasks/{id}/github`에 pr(draft·review_state·reviews·ci_state·ci_url·head_sha)·`continued_by`, `GET /api/projects/{id}/repo`에 규칙 3개·`releases`, `app_capabilities`(§3.0), `mcp_server/skill/SKILL.md`·`skills/pm-done`("`ci_state`가 failure거나 `review_state`가 changes_requested면 완료를 제안하지 않는다")·`skills/pm/SKILL.md` 표 | Sonnet | G1·G2·G4 뒤 | 없음 | `api/routers/{tasks,projects}.py`, `github/services.py`(app_capabilities만, G1 병합 뒤), `mcp_server/skill/SKILL.md`, `skills/*` | — |
| **G9** 화면(디자인 병합 뒤) | `_git.html`(draft·리뷰 "승인 n · 변경 요청 n"·CI 배지·`continued_by` 안내), `repo.html`·`settings.html` 규칙 3개 체크박스 + **`REPO_SETTING_FIELDS`에 3개 추가**, `orgs/_milestone_dialog.html` "GitHub에도 반영" 체크박스, `orgs/roadmap.html` 릴리스 칩·[완료로 표시], `projects/_shelf.html` 릴리스 띠, `orgs/github.html` 권한·이벤트 점검 표, `_row.html` CI 점(선택) | Opus | **디자인 시스템 병합 뒤** + G8 뒤 | 없음 | 템플릿 7개, `web/views/{tasks,github,roadmap,projects}.py` | `REPO_SETTING_FIELDS`를 G9 전에 늘리면 `repo_settings` POST가 체크박스 없는 규칙을 False로 덮어쓴다 — 반드시 템플릿과 같은 단계 |

병렬 묶음: **G0 → {G1, G2, G4, G5, G6, G7} → G8 → G9(디자인 병합 뒤).**
전체 테스트 재실행·병합은 오케스트레이터. 검토는 G1(§4 재개·§2.5 루프)과 G4(PM→GH 쓰기)에 한 번씩.

마이그레이션 번호 고정: `github 0006_round8` · `tasks 0009_task_status_since` · `projects 0011_milestone_gh_number` · `portfolio 0002_portfoliosource_pr_snapshot`. 전부 G0.

### 7.1 테스트 목록(단계별 핵심)
- G0: 마이그레이션 적용·`makemigrations --check` 0, `transition`이 `status_since`를 찍음, `task_brief` 필드, `org_tasks` annotate가 N+1 없이 값을 줌(`CaptureQueriesContext`), `notify.channel/dm` 설정 3단 게이트(조직 set·조직 bool·개인 bool·`can_see`), 미지원 이벤트 202 유지.
- G1: draft opened→doing/비draft→review, ready_for_review, converted_to_draft, synchronize가 CI·리뷰 라운드 초기화, review_requested→reviewer(비공개 프로젝트 못 보는 사람 거부), removed, approved/changes_requested/dismissed 상태 재계산, changes_requested→doing(`rule_review` 끔이면 기록만), **재개**: 닫힌 태스크+PR reopened→새 태스크(parent·체크리스트 미완료·링크 복사·RepoIssue.task 이동·원 태스크 로그·DM·채널), 같은 delivery 재전송 1건, 다른 delivery 연속 reopen "이미 재개됨", 보관 프로젝트 실패 기록, 열린 태스크 reopened는 review, 이슈 edited 제목/담당자 동기화·메아리(updated_at ≤ issue_synced_at)·동일 값 무시·닫힌 태스크 불변·미매핑 로그인 유지.
- G2: check_suite pending→success→failure 집계, status 이벤트, sha 매칭·브랜치 매칭, 실패 전환 시 DM·채널 1회, 닫힌 태스크 무알림, synchronize 뒤 재실패 재알림.
- G4: assignee 변경이 행위자 토큰으로 PATCH(설치 토큰 미호출), 미연결 담당자 경고 문구, `gh_warning`이 API PATCH 응답에 실림, 마일스톤 created/edited/closed/deleted 동기화·due_on 없는 신규 거부·프로젝트 2개면 행 2개, 체크박스 PM→GH 생성이 `gh_number` 저장, release published→GitRelease·마일스톤 이름 매칭·채널, deleted 삭제.
- G5·G6·G7: §5.4·§3.11·§6.
- G8: `/github` 응답 필드, `continued_by`, `app_capabilities` 캐시·오류 None.
- G9: 템플릿 렌더(배지·체크박스·점검 표), `repo_settings` POST가 규칙 3개를 저장.

**수용 기준**: 새 테스트 전부 통과 + 기존 전부 통과(기준선 §0.4), `ruff` 0, `makemigrations --check` 변경 없음. Checks 권한이 없는 설치에서(이벤트 미수신) 기존 PR 흐름·화면이 한 줄도 달라지지 않는다(테스트: check 이벤트 없이 `ci_state==''`이고 패널에 배지 없음).

---

## 8. 사용자에게 물을 것(3개)

| # | 질문 | 선택지 | 추천 |
|---|---|---|---|
| 1 | #8 PM→GitHub 방향의 범위 | (a) **담당자만 자동**(update_task 훅), 제목은 GitHub→PM만 (b) (a)+패널에 [이슈 제목 맞추기] 버튼 (c) 제목도 자동(자동 저장마다 GitHub 호출) | **(a)** — 제목은 `update_text` 자동 저장 경로라 타자마다 GitHub를 부르게 된다. 이슈 제목은 보통 GitHub에서 정하고, PM 제목이 바뀌는 일은 드물다. (b)는 G9에 버튼 하나로 나중에 추가 가능 |
| 2 | #12 Discord GitHub 명령에 Discord 서버 권한 검사 적용 여부 | (a) **적용 안 함**(PM 가시성 + 저장소 접근 + 본인 GitHub 토큰; 조직 길드 안에서만 명령 노출) (b) `require_discord`로 서버 권한(예: 메시지 관리)까지 요구 | **(a)** — 그 검사는 Discord 자원을 바꾸는 동작용이다. GitHub가 그 사람 토큰으로 최종 거부한다 |
| 3 | 재개로 생긴 새 태스크의 담당자 | (a) **원 태스크 담당자** (b) PR·이슈를 다시 연 사람(PM 사용자일 때, 아니면 원 담당자) (c) 원 담당자, 다시 연 사람이 다르면 담당 요청 발송 | **(a)** — 다시 연 사람은 리뷰어·관리자인 경우가 많다. 담당 변경은 사람이 패널에서 한다 |

묻지 않고 추천대로 확정: 채널 게시 기본 꺼짐·DM 기본 켬 · 규칙 스위치 3개 기본 켬 · 재개 태스크 기한 없음(사유 고정)·체크리스트 전부 미완료 · 리뷰어 팀 요청 무시 · PR Write 권한 추가 안 함 · Actions 권한 추가 안 함 · 마일스톤 PM→GH는 체크박스만 · 릴리스는 마일스톤 완료를 제안만 · 포트폴리오 PR 근거는 번호·주소·병합일만 · `Task` 마일스톤 FK 없음 · `status_since` 백필 없음 · 새 모델은 `GitRelease` 하나.

## 9. 확인 불가
- **이벤트 구독만 추가할 때 설치 조직의 재승인이 필요한지** — 공식 문서 두 편(§1.3)은 권한 변경만 다룬다. 운영 앱에서 구독을 추가한 뒤 §3.0 점검 표로 확인하는 수밖에 없다.
- 운영 앱에 지금 실제로 구독된 이벤트 목록·설치별 승인 상태 — 서버·GitHub 설정은 보지 않았다(범위 밖).
- GitHub `status` 이벤트의 `branches[]`가 PR head 브랜치를 항상 담는지(포크 PR은 담지 않을 수 있다) — 포크 PR의 CI는 sha 매칭에만 의존한다.
- 디자인 시스템 에이전트가 실제로 바꾼 템플릿 목록 — G9 착수 시 다시 대조.
