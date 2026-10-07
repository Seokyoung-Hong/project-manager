# IMPL-PLAN-10 — 운영 콘솔 `/ops`: 서비스 운영자 전용 관리·감독 화면 (Fable, 2026-10-07)

기준: main `988d588`. 코드·git은 건드리지 않았다(읽기와 `pytest --collect-only`만, 1415개 수집). 이 문서는 구현 지시서 수준의 설계이며, 구현 단계는 §10의 표를 따른다. GUIDE-00의 규칙(함수형 뷰, services 경유, 새 의존성 금지, signals 금지)을 그대로 지킨다.

## 0. 사용자 결정(2026-10-07, 확정)과 반영 요지

| # | 결정 | 반영 |
|---|---|---|
| 1 | 운영 상태·디자인 시스템은 **서비스 운영자 전용**. 설정 탭에서 빼고 `/ops`를 별도 콘솔로 | §2 IA(자체 상단 내비게이션, 조직 셸과 분리), §6.7 디자인 시스템 이전, `settings/_tabs.html`의 staff 탭 2개 제거 |
| 2 | Django admin보다 안전한 관리 화면: 기본 읽기 전용, 변경은 사유 필수 + append-only 감사 기록, 위험 작업은 대상 재입력, 변경은 services 경유 | §4 `OpsAuditLog`(DB 트리거로 수정·삭제 차단), §5 변경 규칙·위험 작업 표·`ops/_confirm.html` |
| 3 | 열람 범위 = 집계만 | §5.3 허용 필드 목록(allowlist)과 금지 필드, 테스트 `test_ops_shows_no_content` |
| 4 | Django admin은 잠글 수 있게 하되 지금은 연다. 열려 있어도 superuser만, 접근은 감사 기록 | §7 `DJANGO_ADMIN_ENABLED`(기본 켬 → 끄면 URL 자체가 404), `admin.site.has_permission`·`admin_view` 덮어쓰기 |

### 0.1 용어 통일표 (사용자에게 보이는 글·문서·테스트 문자열 모두 이 표만 쓴다)

| 표준 용어 | 뜻 | 코드 | 쓰지 않는 말 |
|---|---|---|---|
| **서비스 운영자** | 유달리 서비스 전체를 운영하는 사람. 운영 콘솔을 본다 | `User.is_staff` | 스태프, 운영진, 관리자(단독) |
| **최고 운영자** | 서비스 운영자 중 운영자 권한 부여·회수와 Django 관리 화면을 쓸 수 있는 사람 | `User.is_superuser` | 슈퍼유저, 루트, 총괄 |
| **조직 관리자** | 한 조직 안에서 멤버·설정을 관리하는 사람(기존 용어 유지) | `OrgMembership.role == "admin"` | 조직 운영자, 오너 |
| **운영 콘솔** | `/ops` 아래 화면 전체 | `web/views/ops*.py`, `templates/ops/` | 운영 상태(화면 이름으로는 §6.6 "시스템"만), 어드민, 대시보드 |
| **Django 관리 화면** | `/admin` | `django.contrib.admin` | Django admin(문서 안에서만 허용), 관리자 페이지 |
| **감사 기록** | 서비스 운영자가 운영 콘솔·Django 관리 화면에서 한 일의 기록(append-only) | `OpsAuditLog` | 감사 로그, 운영 로그, 이력 |
| **변경 이력** | 조직 업무 데이터(태스크·프로젝트·설정)의 변경 기록(기존) | `ChangeLog` | 감사 기록과 섞어 쓰지 않는다 |
| **사유** | 변경·위험 작업 때 반드시 적는 이유(5자 이상 300자 이하) | `reason` | 메모, 코멘트, 비고 |
| **정지 / 재활성** | 사용자의 로그인·토큰을 막는 일 / 되돌리는 일 | `is_active=False/True` | 비활성화, 차단, 밴, 복구 |
| **비밀번호 재설정 링크** | 운영자가 발급해 사용자에게 전달하는 1회용 주소(24시간) | `default_token_generator` | 임시 비밀번호, 초기화 |
| **로그인 잠금 / 잠금 해제** | 시도 제한으로 막힌 아이디·IP / 푸는 일(기존 `/ops` 표) | `LoginLock`, `accounts.auth.unlock` | 락, 언락, 차단 해제 |
| **토큰 폐기** | API 토큰을 쓸 수 없게 하는 일(기존 용어) | `ApiToken.revoke` | 삭제, 취소 |
| **집계** | 건수·상태·용량·시각처럼 내용이 없는 값 | — | 통계(화면에서), 요약 |
| **마지막 백업 성공 시각** | `backup.sh`가 성공 보고한 가장 최근 시각 | `IntegrationStatus(name="backup").detail.last_ok_at` | 백업 시간, 백업 일시 |

코드 식별자는 영문 그대로(`is_staff`, `OpsAuditLog`). 격식체("…입니다", 요청만 "…해 주세요"), 감탄부호 없음(DESIGN.md §7).

---

## 1. 현황 조사 (파일:줄)

### 1.1 지금 `/ops`가 어디에 어떻게 섞여 있는가

| 항목 | 위치 | 내용 |
|---|---|---|
| 운영 상태 화면 | `core/web/views/ops.py:27-33` | `@staff_member_required` + `IntegrationStatus` 전부 + `active_locks()` |
| 잠금 해제 | `ops.py:36-41` | POST `key` → `accounts.auth.unlock`. 사유·기록 없음 |
| 운영 데이터 JSON 내보내기 | `ops.py:55-90` | staff면 누구나. **Task·ChangeLog 전체(제목·설명·old/new_value 포함)**를 내려준다 → 결정 3(집계만)과 충돌 |
| 디자인 시스템 | `ops.py:106-132`, `templates/ops_design.html` | `settings_tab="design"`(`:122`), 설정 탭 include(`ops_design.html:3`) |
| URL | `core/web/urls.py:199-202` | `ops`, `ops/unlock`, `ops/export.json`, `ops/design`. `healthz`는 `:37` |
| 설정 탭에 섞임 | `templates/settings/_tabs.html:7-8` | `{% if user.is_staff %}` 운영 상태·디자인 시스템 탭 |
| 아바타 메뉴 | `templates/base.html:60` | `{% if user.is_staff %}<a href="{% url 'ops' %}">운영 상태</a>` |
| `ops.html` | `templates/ops.html:3` | `settings_tab="ops"`로 설정 탭 include → "설정" 제목 아래 그려진다 |
| 테스트 | `core/web/tests.py:301-305, 312-320, 1852-1861`, `core/web/test_design_system.py:15-24`, `core/notes/test_voice.py:561-563` | `/ops` staff 가드, export.json 비밀 없음, 잠금 해제, `/ops/design` staff 전용 |
| 문서 | `DESIGN.md:4-5` "staff 전용 `/ops/design`(설정 → 디자인 시스템)" | 설정 경로 문구를 고친다 |

`staff_member_required`는 `ops.py:5`에서만 쓴다(그 밖의 `is_staff`·`is_superuser` 사용처는 테스트와 `accounts/admin.py:15`뿐).

### 1.2 재료가 되는 기존 모델·함수

| 재료 | 위치 | 운영 콘솔에서 쓰는 법 |
|---|---|---|
| `LoginLock`(kind·key·failures·locked_until) | `core/accounts/models.py:201-219`, 정책 `accounts/auth.py:29-37`, `active_locks()/unlock()` `:114-120`, 셸 명령 `accounts/management/commands/unlock_login.py` | §6.3 의심 로그인(잠금 + 실패 누적) |
| `IntegrationStatus`(name unique, ok, detail JSON) | `core/api/models.py:4-12`; 보고 API `api/routers/integrations.py:9` `ALLOWED={"discord","mcp"}`, 봇 토큰만 `:16-19`; 봇 보고 `discord_service/.../core_client.py:291-293`, `scheduler.py:121,126,150,155`(job=deadline/weekly) | §6.6 서비스 상태. **mcp는 보고 코드가 없다**(grep 0건) — "보고 없음"으로 표시. 백업도 같은 표에 `name="backup"`으로(§8) |
| `ChangeLog`(source: web/api/mcp/dc/gh) | `core/tasks/models.py:388-416` | 건수 집계만(§5.3). old/new_value는 내용이라 보이지 않는다 |
| `Notice`(sent_at null = 대기) | `tasks/models.py:494-511`; 봇이 `GET /notices`→`POST /notices/ack`(`api/routers/discord.py:589-603`) | §6.5 발송 대기열 건수·가장 오래된 대기 |
| `Attachment`(size, project/task) | `tasks/models.py:520-` | §6.2·6.6 용량 합계만. `name`·`file`은 보이지 않는다 |
| `ApiToken`(scope·for_ai·last_used_at·revoked_at) | `accounts/models.py:43-108` | §6.3 토큰 현황. `prefix[3:]…`만(기존 토큰 화면 `settings/tokens.html:19`과 같은 표기) |
| `Organization.discord_*`(guild_id·watch_at·intent_denied·bot_permissions) | `orgs/models.py:36-49`; 봇 보고 `api/routers/discord.py:462-470 guild_report` | §6.5 Discord 서버 연결·감시 상태 |
| `GitHubInstallation`(account_login·suspended_at) | `github/models.py:5-20`; `app_capabilities(org)` 1시간 캐시 `github/services.py:164-193` | §6.5 설치·권한 점검 |
| GitHub 쓰기 재시도 대기열 | `web/views/github_retries.py:44-74` — **로그인 세션에 ≤20개** 보관, `integrations.py:71-84 record_problem`도 세션 | **DB가 아니라 운영 콘솔에서 볼 수 없다**(§9 범위 밖). 다른 사람 세션을 열어 보는 것은 하지 않는다 |
| `VoiceRecording.STATUSES`(recording/transcribing/draft/done/failed) | `notes/models.py:46-98` | §6.6 회의 녹음 상태 건수·오래 멈춘 녹음 |
| AI 정책 거부 | `orgs/services.py:35-62 ai_denied/require_ai_enabled/_check_ai_*` — **예외만 던지고 어디에도 남기지 않는다** | 기록이 없어 집계 불가 → §9(2차) |
| Django 관리 화면 | `config/urls.py:8-23`(admin 로그인 폼 우회·로그아웃 교체), `:26` `admin/` | §7. 등록 모델: User·ApiToken **편집 가능**(`accounts/admin.py:7-37`), IntegrationStatus(`api/admin.py:5`), Installation·Identity·RepoConnection(`github/admin.py:6-20`), Organization·Team·Invite(`orgs/admin.py:16-31`), Project·Task **읽기 전용**(`projects/admin.py:8`, `tasks/admin.py:6-30`), ChangeLog 읽기 전용(`tasks/admin.py:32-53`), Link(`:56`), notes 미등록(`notes/admin.py:1-2`) |
| 백업 | `scripts/backup.sh:1-40`(성공 시 `echo "OK …"`만), cron `docs/BACKUP.md:7`, SPEC 11.3 "마지막 백업 성공 시각" `docs/SPEC.md:481`, BACKUP.md의 "구조화된 내보내기 별도 구현 필요" `:46` | §8 |
| 설정 | `config/settings.py:26-43` INSTALLED_APPS, `:106` MEDIA_ROOT, `:110` LOGIN_URL | 새 앱 `ops` 추가, `DJANGO_ADMIN_ENABLED`·`PASSWORD_RESET_TIMEOUT` 추가 |
| 레이아웃 부품 | `app.css:230-240 .tabs`, `:472-485 .tiles/.tile`, `:897-901 .settings-jump/.settings-split`, `base.html` 블록 `title:7 layout_class:114 main:122 panel:124` | §2.2 |
| 마이그레이션 최신 | accounts 0005, api 0001, tasks 0009, github 0007, orgs 0009, notes 0003, projects 0011, portfolio 0002 | 이번 라운드 새 마이그레이션은 **`ops 0001_initial` 하나** |

---

## 2. IA·내비게이션·화면

### 2.1 URL과 섹션

| 섹션(내비 표기) | URL | 보이는 것 | 변경 동작(사유 필수) |
|---|---|---|---|
| 개요 | `/ops` | 주의 타일(실패한 통합·오래된 백업·잠긴 계정·대기 알림·멈춘 녹음·미적용 마이그레이션) + 최근 감사 기록 10건 | 없음 |
| 사용자 | `/ops/users`, `/ops/users/<id>` | 검색(아이디·표시 이름), 상태·운영자 여부·조직 수·토큰 수·마지막 로그인 | 정지·재활성, 재설정 링크 발급, 잠금 해제, 운영자 부여·회수(최고 운영자) |
| 조직 | `/ops/orgs` | 조직별 인원·관리자(표시 이름)·프로젝트 수·미완료 태스크 수·첨부 용량·최근 활동·Discord/GitHub 연결 여부·비활성(90일 활동 없음) 표시 | 없음(1차) |
| 접근 | `/ops/access` | API 토큰 집계(활성·폐기·만료·AI용/사람용·봇), 사용자별 토큰 표, AI 토큰 사용(7일·30일 `ChangeLog.source="mcp"` 건수), 로그인 잠금·실패 누적 표 | 토큰 폐기(위험), 잠금 해제 |
| 연동 | `/ops/integrations` | GitHub 설치 표 + 앱 권한 점검, Discord 서버 표(감시 시각·인텐트·권한), 봇 하트비트, 알림 대기열 | 없음 |
| 시스템 | `/ops/system` | 통합 상태 표(기존), 백업(마지막 성공·마지막 실행·복구 시험), 디스크·첨부 용량, 마이그레이션, 회의 녹음, Django 관리 화면 켜짐 여부 | 운영 데이터 JSON 내보내기(최고 운영자, §11 Q2) |
| 감사 기록 | `/ops/audit`, `/ops/audit.csv` | 필터(기간·행위자·동작·대상), 100건씩 | CSV 내보내기(기록됨) |
| 디자인 시스템 | `/ops/design` | 기존 그대로 | 없음 |
| (공용) | `/ops/confirm/<action>/<target>` 없음 — 확인은 각 POST 경로의 GET이 대화상자를 돌려준다(§5.2) | | |

기존 `ops/unlock`·`ops/export.json`·`ops/design` URL 이름(`ops_unlock`, `export_json`, `ops_design`)은 유지한다(테스트가 쓴다). `/ops`의 URL 이름 `ops`도 유지.

### 2.2 레이아웃 — 조직 셸과 분리

`base.html`의 상단 바에서 **주 메뉴와 "빠른 추가"만 블록으로 감싼다**(2곳, 각 1줄):

```django
{# base.html:39 <nav class="nav" …> 앞·:46 </nav> 뒤 #}
{% block header_nav %} … 기존 nav 그대로 … {% endblock %}
{# base.html:48-52 빠른 추가 #}
{% block header_actions %} … 기존 그대로 … {% endblock %}
```

새 `templates/ops/base.html`:

```django
{% extends "base.html" %}
{% block header_nav %}
<nav class="nav" aria-label="운영 콘솔 메뉴">
  <a href="{% url 'ops' %}"{% if ops_nav == "home" %} aria-current="page"{% endif %}>개요</a>
  <a href="{% url 'ops_users' %}"{% if ops_nav == "users" %} aria-current="page"{% endif %}>사용자</a>
  <a href="{% url 'ops_orgs' %}"…>조직</a> <a href="{% url 'ops_access' %}"…>접근</a>
  <a href="{% url 'ops_integrations' %}"…>연동</a> <a href="{% url 'ops_system' %}"…>시스템</a>
  <a href="{% url 'ops_audit' %}"…>감사 기록</a> <a href="{% url 'ops_design' %}"…>디자인 시스템</a>
</nav>
{% endblock %}
{% block header_actions %}<a class="btn sm" href="{% url 'today' %}">앱으로 돌아가기</a>{% endblock %}
{% block main %}
<div class="page-head"><h1 class="t24">운영 콘솔 <span class="badge">서비스 운영자</span></h1></div>
{% block ops %}{% endblock %}
{% endblock %}
```

- 조직 전환기(로고)는 그대로 둔다(셸 공통). 프로젝트 레일은 `nav != "project"`라 그려지지 않는다(`context.py:58-59`).
- `web/context.py NAV_BY_URL`에 ops URL 이름을 넣지 않는다(주 메뉴 강조 없음). 대신 각 ops 뷰가 `ops_nav`를 넘긴다.
- 화면 유형은 DESIGN.md 3.1 "표가 주인 화면 → 기본 `.card`가 본문 폭을 채운다". 개요의 주의 타일은 `.tiles`(첫 칸 세이지, 위험 수치 `b.danger`만 코랄 — 색 돌림 금지). 연동 상태는 `.conn-state.{on|off|warn|bad}`. 장식(화분·메모)은 쓰지 않는다(1장 "쓰지 않는 곳: 설정·표·연동 관리").
- 긴 화면(시스템)은 카드 몇 장을 세로로. 목차(`.settings-jump`)는 두지 않는다 — 카드 6장이면 스크롤로 충분하다.
- 모바일: 상단 nav 8개는 ≤700px에서 머리줄이 2줄로 접히는 기존 규칙(`--header-h` 115px)을 그대로 따른다. 표는 `.table-scroll`.
- `ops/design` 페이지의 새 부품 견본: `.ops-confirm`(§5.2 대화상자)과 "주의 타일" 한 줄을 추가한다(DESIGN.md §11-9).

### 2.3 제거·이동

| 지금 | 뒤 |
|---|---|
| `settings/_tabs.html:7-8` staff 탭 2개 | 삭제. 설정 탭은 프로필·환경설정·API 토큰 3개 |
| `base.html:60` 아바타 메뉴 "운영 상태" | `{% if user.is_staff %}<a href="{% url 'ops' %}">운영 콘솔</a>{% endif %}` |
| `templates/ops.html`, `ops_design.html` | `templates/ops/system.html`(통합 상태·잠금 표는 접근으로), `templates/ops/design.html`(include를 `ops/base.html` 상속으로) |
| `web/views/ops.py` | `ops.py`(개요·system·design·healthz·export) + 섹션별 `ops_users.py`, `ops_access.py`, `ops_orgs.py`, `ops_integrations.py`, `ops_audit.py` |

---

## 3. 권한 모델

| 역할 | 조건 | 할 수 있는 것 |
|---|---|---|
| 서비스 운영자 | `is_active and is_staff` | 운영 콘솔 전부 읽기, §5.1의 변경 동작(사유 필수), 감사 기록 CSV |
| 최고 운영자 | `is_staff and is_superuser` | + 운영자 권한 부여·회수, 운영 데이터 JSON 내보내기, Django 관리 화면 |
| 조직 관리자 | 조직 안 역할 | 운영 콘솔 없음(지금과 같다) |

규칙:
- `is_superuser`인데 `is_staff`가 아닌 계정은 운영 콘솔에 못 들어간다(Django 기본과 같다). 개요 화면이 "최고 운영자 n명 중 운영 콘솔 권한 없는 계정 n명"을 경고 타일로 보여 준다.
- 운영자 권한 부여·회수는 **최고 운영자만**(§11 Q1). 자기 자신은 회수 못 한다. `is_superuser` 계정의 운영자 권한은 회수 못 한다(superuser 변경은 Django 관리 화면·셸 전용).
- 정지는 서비스 운영자가 할 수 있으나 **대상이 서비스 운영자면 최고 운영자만**. 자기 자신은 정지 못 한다.
- 다른 사람의 토큰 폐기는 서비스 운영자 누구나(토큰은 자격증명이므로 빨리 막는 쪽이 안전). 사유 필수 + 대상 재입력.

데코레이터(새 파일 `core/ops/access.py`, 12줄):

```python
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.http import Http404

def ops_required(view):            # 서비스 운영자. 아니면 404(존재를 숨긴다 — github_retries.py:181과 같은 규칙)
    @wraps(view)
    def inner(request, *a, **kw):
        if not request.user.is_staff:
            raise Http404
        return view(request, *a, **kw)
    return login_required(inner)

def superuser_required(view):      # 최고 운영자
    @wraps(view)
    def inner(request, *a, **kw):
        if not request.user.is_superuser:
            raise Http404
        return view(request, *a, **kw)
    return ops_required(inner)
```

`staff_member_required`는 더 쓰지 않는다(그 데코레이터는 `admin:login`으로 보내는데, §7에서 admin이 꺼질 수 있다). 기존 테스트의 `in (302, 403)`·`in (302, 403, 404)`는 404로 통과한다.

---

## 4. 감사 기록 `OpsAuditLog` (새 앱 `core/ops/`)

### 4.1 모델 (`core/ops/models.py`, 마이그레이션 `ops 0001_initial`)

```python
class OpsAuditLog(models.Model):
    """서비스 운영자가 한 일. append-only — save()는 삽입만, update()·delete()는 DB 트리거가 막는다."""
    ACTIONS = [
        ("user.suspend", "사용자 정지"), ("user.reactivate", "사용자 재활성"),
        ("user.reset_link", "비밀번호 재설정 링크 발급"), ("user.unlock", "로그인 잠금 해제"),
        ("user.grant_staff", "운영자 권한 부여"), ("user.revoke_staff", "운영자 권한 회수"),
        ("token.revoke", "토큰 폐기"), ("export.json", "운영 데이터 내보내기"),
        ("audit.export", "감사 기록 내보내기"), ("admin.access", "Django 관리 화면 접근"),
        ("backup.record", "백업 결과 기록"),
    ]
    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    actor_username = models.CharField(max_length=150)        # 계정이 바뀌어도 당시 이름이 남는다
    action = models.CharField(max_length=30, choices=ACTIONS)
    target_type = models.CharField(max_length=20, blank=True)  # user | token | org | admin | backup | audit
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    target_label = models.CharField(max_length=200, blank=True)  # username, 토큰 prefix[3:]+"…", admin 경로
    reason = models.CharField(max_length=300, blank=True)       # 사람이 한 변경은 필수(services가 검사)
    detail = models.JSONField(default=dict, blank=True)          # {"before": …, "after": …, "method": "POST"} 등. 비밀값 금지
    ip = models.CharField(max_length=45, blank=True)            # accounts.auth.client_ip
    class Meta:
        ordering = ["-id"]
        default_permissions = ()                                 # Django 관리 화면에 등록하지 않는다
        indexes = [models.Index(fields=["created_at"]), models.Index(fields=["action"]),
                   models.Index(fields=["target_type", "target_id"])]
    def save(self, *a, **kw):
        if self.pk:
            raise RuntimeError("감사 기록은 고칠 수 없습니다.")
        super().save(*a, **kw)
    def delete(self, *a, **kw):
        raise RuntimeError("감사 기록은 지울 수 없습니다.")
```

### 4.2 수정·삭제 불가 보장 — 3겹

1. **Python**: 위 `save()`·`delete()`. QuerySet `update()`·`delete()`는 막지 못하므로 2를 둔다.
2. **DB 트리거**(같은 마이그레이션의 `RunPython`, vendor별 SQL; 역방향은 DROP TRIGGER):
   - Postgres: `CREATE FUNCTION ops_audit_block() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'ops_auditlog is append-only'; END $$ LANGUAGE plpgsql; CREATE TRIGGER ops_audit_no_update BEFORE UPDATE OR DELETE ON ops_opsauditlog FOR EACH ROW EXECUTE FUNCTION ops_audit_block();`
   - SQLite(테스트): `CREATE TRIGGER ops_audit_no_update BEFORE UPDATE ON ops_opsauditlog BEGIN SELECT RAISE(ABORT, 'append-only'); END;` + 같은 꼴의 `BEFORE DELETE`.
   - 테스트 `test_audit_is_append_only`: `OpsAuditLog.objects.filter(pk=…).update(reason="x")`와 `.delete()`가 `IntegrityError/OperationalError`로 실패한다(두 vendor 모두).
   - `actor`가 `PROTECT`라 기록이 있는 운영자 계정은 삭제되지 않는다(정지로 대신한다).
3. **Django 관리 화면 미등록**(`default_permissions=()`, `admin.py` 없음) + 운영 콘솔에는 조회·CSV만.

보존: 삭제하지 않는다. 용량 상한이 보이면 §9의 "연 1회 아카이브"를 그때 설계한다(ponytail).

### 4.3 기록 함수 (`core/ops/services.py`)

```python
def audit(request, action, *, target=None, target_type="", target_label="", reason="", detail=None):
    """한 줄로 남긴다. request가 없으면(관리 명령) actor=None·actor_username="system"."""
    user = getattr(request, "user", None) if request else None
    return OpsAuditLog.objects.create(
        actor=user if user and user.is_authenticated else None,
        actor_username=user.get_username() if user and user.is_authenticated else "system",
        action=action, target_type=target_type or (type(target).__name__.lower() if target else ""),
        target_id=getattr(target, "pk", None), target_label=target_label or (str(target) if target else ""),
        reason=reason, detail=detail or {}, ip=client_ip(request) if request else "",
    )
```

`detail`에 넣지 않는 것: 토큰 원문·해시, 재설정 링크, 비밀번호, 초대 token, Discord 연결 코드(`common/logging.py SecretFilter`가 가리는 키 이름과 같은 목록을 `ops/services.py`에 `FORBIDDEN_DETAIL_KEYS`로 두고 `audit()`가 assert한다).

---

## 5. 안전장치

### 5.1 변경 규칙(모든 변경 동작 공통)

1. GET은 아무것도 바꾸지 않는다. 변경은 `@require_POST` + CSRF + `ops_required`.
2. **사유 필수**: `reason` 5~300자. 비면 폼 오류 "사유를 적어 주세요(5자 이상)."
3. **services 경유**: 뷰는 `ops/services.py`의 함수를 부르고, 그 함수가 기존 services(`accounts.auth.unlock`, `ApiToken.revoke`)를 부른 뒤 `audit()`를 **같은 트랜잭션**(`transaction.atomic`) 안에서 남긴다. 기록에 실패하면 변경도 되돌아간다.
4. **위험 작업은 대상 재입력**: 폼에 `confirm` 입력이 있고 값이 대상 식별자(아이디, 토큰 앞자리 `prefix[3:]`, 조직 이름)와 정확히 같아야 한다. 틀리면 "대상이 일치하지 않습니다." 오류, 아무것도 바뀌지 않는다.
5. 뷰에 업무 규칙을 쓰지 않는다(GUIDE-00 §3). 검사는 전부 `ops/services.py`에서 `ServiceError`로 던지고, 뷰는 메시지로 보여 준다.
6. 변경 뒤에는 같은 화면으로 redirect하고 `messages.success("…했습니다.")`.

### 5.2 위험 작업 표

| 동작 | 위험 | 확인 | 권한 | services 함수 | 기존 함수 |
|---|---|---|---|---|---|
| 사용자 정지 | 로그인·API·MCP 즉시 차단(`ModelBackend.get_user`가 비활성을 거르고 `ApiToken.is_valid`가 `is_active`를 본다 `accounts/models.py:99`) | 사유 + **아이디 재입력** | 운영자(대상이 운영자면 최고 운영자) | `suspend_user(request, user, reason)` | `User.objects.filter(pk).update(is_active=False)` — User는 services 제한 대상이 아니다 |
| 사용자 재활성 | 낮음 | 사유 | 운영자 | `reactivate_user` | 같은 꼴 |
| 비밀번호 재설정 링크 발급 | 중간(링크를 받는 사람이 계정을 갖는다) | 사유 + 아이디 재입력 | 운영자(대상이 운영자면 최고 운영자) | `issue_reset_link(request, user, reason) -> url` | `default_token_generator.make_token`, `urlsafe_base64_encode` |
| 로그인 잠금 해제 | 낮음 | 사유 | 운영자 | `unlock_login(request, key, reason)` | `accounts.auth.unlock` |
| 운영자 권한 부여 | 높음 | 사유 + 아이디 재입력 | **최고 운영자** | `grant_staff` | `update(is_staff=True)` |
| 운영자 권한 회수 | 높음(자기 자신·superuser 불가) | 사유 + 아이디 재입력 | 최고 운영자 | `revoke_staff` | `update(is_staff=False)` |
| 토큰 폐기(타인) | 중간(그 토큰으로 돌던 자동화가 멈춘다) | 사유 + **토큰 앞자리 재입력** | 운영자 | `revoke_token(request, token, reason)` | `ApiToken.revoke()` `accounts/models.py:105` |
| 운영 데이터 JSON 내보내기 | 높음(업무 내용 전체) | 사유 + "export" 재입력 | 최고 운영자(§11 Q2) | `export_json`(기존 뷰 이동) + `audit("export.json")` | `ops.py:55-90` 그대로 |
| 감사 기록 CSV | 낮음 | 없음(기록만) | 운영자 | `audit("audit.export", detail={"filters": …, "rows": n})` | — |

확인 대화상자는 템플릿 하나 `templates/ops/_confirm.html`(네이티브 `dialog`, HTMX `hx-get`으로 연다 — `common.dialog()` `web/views/common.py:119` 재사용):

```django
<form method="post" action="{{ action_url }}" class="stack">{% csrf_token %}
  <h2>{{ title }}</h2><p class="t13">{{ summary }}</p>
  <label class="field">사유 <textarea name="reason" class="textarea" required minlength="5" maxlength="300"></textarea></label>
  {% if confirm_value %}<label class="field">확인을 위해 <code>{{ confirm_value }}</code>를 그대로 입력해 주세요
    <input name="confirm" class="input" autocomplete="off" required></label>{% endif %}
  <div class="row"><button class="btn {% if danger %}danger{% else %}primary{% endif %}">{{ button }}</button>
    <button type="button" class="btn link" data-action="close-dialog">취소</button></div>
</form>
```

GET `/ops/users/<id>/suspend`가 이 대화상자를, POST가 실행을 맡는다(같은 URL, 메서드로 구분 — `today.auto_pull` 같은 기존 패턴).

### 5.3 집계만 보이게 하는 쿼리 규칙

**허용 필드(allowlist)** — 운영 콘솔 템플릿·뷰는 아래 값만 꺼낸다. 다른 필드를 쓰면 코드 리뷰에서 막고, 테스트 `test_ops_shows_no_content`가 대표 문자열로 검사한다.

| 모델 | 허용 | 금지(업무 내용) |
|---|---|---|
| User | username, display_name, is_active, is_staff, is_superuser, date_joined, last_login, discord_linked_at(여부만), 조직 수, 토큰 수 | email(가입 폼에 없지만 금지 명시), settings JSON |
| Organization | name, created_at, 인원 수, 관리자 표시 이름, 프로젝트 수, 미완료·완료 태스크 수, 첨부 용량 합, 최근 활동(`max(Task.updated_at)` `tasks/models.py:62`), discord_guild_id 유무·watch_at·intent_denied, GitHub 설치 유무 | purpose, governance, settings 값(비밀값 포함) |
| Project / Task | 건수(상태별), `max(updated_at)` | name, title, description, stop_reason, 체크리스트, 링크 |
| ChangeLog | 건수(source별·기간별) | field, old_value, new_value, note |
| Attachment | count, `Sum(size)` | name, file, note |
| Notice | 대기·발송 건수, 가장 오래된 `created_at` | text, user, channel_id |
| MeetingNote / VoiceRecording | 상태별 건수, `started_at`, `end_reason`, stats.segments 수 | title, body_md, transcript_md, participants |
| ApiToken | prefix[3:], scope, for_ai, created_at, expires_at, revoked_at, last_used_at, 소유자 username | name(사용자가 적은 라벨), key_hash |
| LoginLock | kind, key, failures, locked_until | — |
| IntegrationStatus | 전부(detail은 봇이 보내는 집계: job·org_id·건수) | — |
| GitHubInstallation | account_login, account_type, repo_selection, installed_at, suspended_at | — |
| OpsAuditLog | 전부 | — |

규칙: (1) 뷰는 `values()`/`annotate()`/`aggregate()`로 집계하고 **모델 인스턴스를 템플릿에 넘기지 않는다**(User·ApiToken·LoginLock·IntegrationStatus·GitHubInstallation·OpsAuditLog만 예외). (2) 템플릿에서 `.title`·`.description`·`.body_md`·`.text`·`.name`(Attachment·ApiToken)·`.old_value`·`.new_value`를 쓰지 않는다 — 테스트가 `templates/ops/*.html`을 정규식으로 훑는다(`test_ops_templates_touch_no_content_fields`). (3) 검색 입력은 사용자·조직 이름에만 있고 태스크·문서 검색은 없다.

---

## 6. 섹션별 설계

### 6.1 개요 `/ops` (`ops.py:home`)
타일(`.tiles`): 실패한 통합 수 / 마지막 백업 성공으로부터 경과(26시간 넘으면 `b.danger`) / 잠긴 아이디·IP 수 / 대기 알림 수(1시간 넘게 대기면 danger) / 멈춘 녹음(status=recording·transcribing이 6시간 초과) / 미적용 마이그레이션 수. 아래에 "최근 감사 기록 10건" 표(시각·행위자·동작·대상·사유)와 "운영 콘솔 권한 없는 최고 운영자 n명" 경고(`.notice.warn`, 있을 때만).

### 6.2 사용자 `/ops/users` (`ops_users.py`)
- 목록: `?q=`(username·display_name `icontains`), `?state=active|suspended|staff`. 열: 아이디 / 표시 이름 / 상태(`.badge`: 활성·정지·운영자·최고 운영자) / 조직 수 / 활성 토큰 수 / 가입 / 마지막 로그인. 50건씩, `?page=`.
- 상세 `/ops/users/<id>`: 위 값 + Discord 연결 여부(시각만) + GitHub 연결 여부(`GitHubIdentity` 존재·login) + 조직 목록(이름·역할) + 토큰 표(접근과 같은 열) + 이 사용자 대상 감사 기록 + 잠금 행(`LoginLock(kind="user", key=username.lower())`). 버튼: 정지/재활성, 재설정 링크 발급, 잠금 해제, 운영자 부여/회수(최고 운영자에게만 보임).
- POST `/ops/users/<id>/{suspend|reactivate|reset-link|unlock|grant-staff|revoke-staff}` — GET은 `_confirm.html`.
- 재설정 링크: `issue_reset_link`가 `reverse("password_reset_confirm", args=[uidb64, token])`를 만들어 **세션에 1회 넣고** 상세 화면이 꺼내 보여 준다(`settings.tokens`의 `new_token` 패턴 `web/views/settings.py:57,69`). 기록에는 링크를 넣지 않는다. 운영자가 링크를 본인 확인된 경로로 전달한다(이메일 발송 기능이 없다 — grep `EMAIL_BACKEND` 0건).
- 재설정 페이지 `GET/POST /reset/<uidb64>/<token>`(`web/views/auth.py`에 함수형 뷰 `password_reset_confirm`, 템플릿 `auth/reset.html`): `default_token_generator.check_token` 실패면 "링크가 만료되었거나 이미 사용되었습니다."; 성공이면 `SetPasswordForm` → `user.set_password` → `record_success("user", username)`(잠금 해제) → 로그인 화면으로. 로그인은 자동으로 하지 않는다. `PASSWORD_RESET_TIMEOUT = 24 * 3600`(settings.py). 토큰은 비밀번호 해시·last_login을 섞으므로 한 번 쓰면 무효(Django 기본).
- 정지된 사용자는 `/ops/users?state=suspended`에서만 기본 표시(목록 기본은 활성).

### 6.3 접근 `/ops/access` (`ops_access.py`)
- 카드 1 "API 토큰": 타일 — 활성 / AI용 / 사람용 / 봇 / 7일 내 사용 / 만료 예정(7일). 표(사용자별): 아이디 / 활성 n / AI n / 봇 n / 마지막 사용. 토큰 하나씩 펼치는 `details`: 앞자리·범위·용도·만료·마지막 사용 + [폐기](위험 대화상자, 확인값=앞자리).
- 카드 2 "AI 사용": `ChangeLog.filter(source="mcp")` 7일·30일 건수, 조직별 상위 5(조직 이름·건수). "AI 정책 거부 건수"는 기록이 없어 **표시하지 않는다**(§9).
- 카드 3 "로그인 잠금·실패": 기존 `/ops` 잠금 표를 옮기고 `failures >= 3`인 미잠금 행도 "실패 누적" 배지로 보인다(`LoginLock` 전체, `updated_at` 최근순, 1일 지난 행은 `record_failure`가 지운다 `auth.py:66`). [해제]는 사유 필수(위험 아님). URL 이름 `ops_unlock` 유지, redirect는 `ops_access`.
- 봇 토큰(scope=bot)은 발급·폐기 모두 셸 전용 원칙(GUIDE-00 §3) — 운영 콘솔에서도 폐기 버튼을 두지 않고 "셸에서 폐기" 안내만.

### 6.4 조직 `/ops/orgs` (`ops_orgs.py`)
한 쿼리셋 annotate: `Count("memberships")`, `Count("projects", distinct=True)`, 미완료 `Count("projects__tasks", filter=Q(status__in=Task.OPEN))`, `Sum("projects__attachments__size")`, `Max("projects__tasks__updated_at")`. 관리자 표시 이름은 `OrgMembership.filter(role="admin").values_list("org_id", "user__display_name")`를 dict로. 비활성 = 최근 활동이 90일 전이거나 없음 → `.badge` "비활성". Discord/GitHub 열은 `.conn-state on|off|warn`(감시 시각 10분 초과 → warn "감시 꺼짐", `intent_denied` → bad). 조직 이름은 링크가 아니다(운영자는 조직 화면에 들어가지 않는다). 변경 동작 없음.

### 6.5 연동 `/ops/integrations` (`ops_integrations.py`)
- 카드 "GitHub 설치": 조직 / `<code>account_login</code>` / 종류·저장소 범위 / 설치일 / `suspended_at` → `.conn-state.bad` / 권한 점검 요약(`app_capabilities(org)`: 전부 ok → on, 하나라도 missing → warn "n개 기능 꺼짐", None → warn "확인 불가"). 캐시 1시간(`CAPS_TTL`)이라 설치 10개 미만에서는 첫 로드만 느리다. `GITHUB_ENABLED`가 False면 카드 대신 `.notice` "GitHub 앱이 설정되지 않았습니다."
- 카드 "Discord": 봇 하트비트(`IntegrationStatus(name="discord")` — `last_run_at` 10분 초과면 warn "보고 없음"), 서버 표(조직 / `<code>guild_id</code>` / 알림 채널 지정 여부 / 감시 시각 / 인텐트 / 봇 권한 보고 여부). 채널 ID 자체는 식별자라 보여도 된다(DESIGN.md §6 `<code>` 알약).
- 카드 "알림 발송 대기열": 대기 n(가장 오래된 대기 시각), 24시간 발송 n, 7일 발송 n. 내용은 보이지 않는다.
- "웹훅 실패·재시도 대기열"은 로그인 세션에만 있어 싣지 않는다(§9). 대신 `GitEvent` 24시간 수신 건수와 마지막 수신 시각을 보여 준다(모델 `github/models.py:184`, 필드는 구현 때 확인).

### 6.6 시스템 `/ops/system` (`ops.py:system`)
- 카드 "서비스 상태": 기존 통합 상태 표(`IntegrationStatus` 전부). `backup`·`restore-test`도 같은 표에 나온다. 이름이 `mcp`인 행이 없으면 "mcp: 보고 없음(보고 기능 없음)" 한 줄.
- 카드 "백업": 마지막 성공 시각(`detail.last_ok_at`), 마지막 실행·결과, 파일 목록·용량(detail), 복구 시험 마지막 결과. 26시간 넘으면 `.notice.warn` "백업이 26시간 넘게 성공하지 않았습니다. 서버의 `/var/log/pm-backup.log`를 확인해 주세요."
- 카드 "저장소": `shutil.disk_usage(settings.MEDIA_ROOT)` 전체·사용·남음, 첨부 `count`·`Sum(size)`, 조직별 상위 5 용량. SQLite 개발 환경에서도 동작(경로만 있으면 된다).
- 카드 "데이터베이스·마이그레이션": `connection.vendor`, `MigrationExecutor(connection).migration_plan(loader.graph.leaf_nodes())` 길이 = 미적용 수(0이면 `.conn-state.on` "모두 적용됨"). 앱별 최신 적용 이름(`MigrationRecorder.applied_migrations()`).
- 카드 "회의 녹음": 상태별 건수(`VoiceRecording.STATUSES`), 6시간 넘게 `recording|transcribing`인 건수(`started_at` 기준), 최근 7일 `failed` 건수. 오디오는 core에 없다(`notes/models.py:47`).
- 카드 "Django 관리 화면": `settings.DJANGO_ADMIN_ENABLED` 켜짐/꺼짐(`.conn-state`), 켜져 있으면 "최고 운영자만 접근, 접근은 감사 기록에 남습니다." + 최근 접근 5건. 끄는 방법 안내 문구(환경 변수) — 운영 작업은 문서로만.
- 카드 "운영 데이터 내보내기"(최고 운영자에게만 그려짐): 기존 설명문 + [JSON 내보내기] → 위험 대화상자(확인값 `export`) → 기존 `export_json` + `audit`.

### 6.7 감사 기록 `/ops/audit` (`ops_audit.py`)
필터 폼(GET): 기간(`from`,`to` `<input type="date">`), 행위자(아이디), 동작(select = `ACTIONS`), 대상(아이디·라벨 `icontains`). 표: 시각 / 행위자 / 동작 / 대상 / 사유 / 상세(JSON을 `k: v` 줄로, `ops.html:11`의 detail 표기 재사용) / IP. 100건씩. `/ops/audit.csv`는 같은 필터로 `csv.writer`(stdlib) 스트리밍, 열 = 모델 필드 순, 내보내기 자체를 `audit.export`로 남긴다(행 수·필터).

### 6.8 디자인 시스템 `/ops/design`
`ops.py:design` 그대로. 템플릿 첫 3줄만 `{% extends "ops/base.html" %}`·`{% block ops %}`로 바꾸고 `settings_tab` 컨텍스트를 `ops_nav="design"`으로. `DESIGN.md:4-5` 문구를 "운영 콘솔 → 디자인 시스템"으로.

---

## 7. Django 관리 화면 잠금 스위치와 접근 기록

`config/settings.py`:
```python
# Django 관리 화면. 테스트 계정 만들기 등에 쓰므로 기본은 켠다. 끄면 /admin 경로 자체가 404다.
DJANGO_ADMIN_ENABLED = os.environ.get("DJANGO_ADMIN_ENABLED", "1") == "1"
PASSWORD_RESET_TIMEOUT = 24 * 3600   # 운영자가 발급한 재설정 링크의 유효 시간
```

`config/urls.py`(기존 `admin_login` 덮어쓰기 `:8-23` 바로 아래):
```python
# 최고 운영자만. is_staff만 있는 서비스 운영자는 운영 콘솔(/ops)을 쓴다.
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser

_admin_view = admin.site.admin_view
def admin_view(view, cacheable=False):
    inner = _admin_view(view, cacheable)
    def logged(request, *a, **kw):
        if request.user.is_authenticated and not request.path.endswith("/jsi18n/"):
            audit(request, "admin.access", target_type="admin", target_label=request.path[:200],
                  detail={"method": request.method, "allowed": admin.site.has_permission(request)})
        return inner(request, *a, **kw)   # 권한 없으면 Django가 로그인 화면(200)을 그린다 — 거부 시도도 위 한 줄로 남는다
    return logged
admin.site.admin_view = admin_view        # 모든 admin 뷰가 이 함수를 지난다(AdminSite.get_urls)

urlpatterns = [path("api/", api.urls), path("", include("web.urls"))]
if settings.DJANGO_ADMIN_ENABLED:
    urlpatterns.insert(0, path("admin/", admin.site.urls))
```
- `admin.site.urls`는 `get_urls()`가 import 시점에 `admin_view`를 호출해 감싸므로 **덮어쓰기는 `urlpatterns`를 만들기 전**에 해야 한다(지금 `admin_login` 덮어쓰기와 같은 자리).
- 세부 변경(add/change/delete)은 Django가 `django_admin_log`(LogEntry)에 이미 남긴다. 감사 기록은 "누가 언제 어느 화면에 들어갔는가(method 포함)"를 남긴다. 기록 폭주는 운영자 수가 한 자리라 문제 없다(ponytail: 하루 수백 건 이내).
- 테스트: `DJANGO_ADMIN_ENABLED=False`에서 `/admin/` 404(`override_settings` + `clear_url_caches`·`reload(config.urls)`); staff-only 사용자 GET `/admin/` → 관리 화면이 아니라 로그인 화면(200, 기존 `admin_login`이 GET만 원래 화면에 맡긴다 `config/urls.py:17-18`)이고 본문에 모델 목록(`"Organization"` 등)이 없으며 `admin.access` 1건이 `allowed=False`로 남는다; superuser GET `/admin/` 200 + `admin.access` 1건 `allowed=True`; `jsi18n` 미기록.
- 기존 `admin.py`는 그대로 둔다(사용자 결정 4). 단 `accounts/admin.py` `ApiTokenAdmin`의 `readonly_fields`에 `user`·`scope`·`expires_at`을 더해 **토큰 소유자·범위를 관리 화면에서 못 바꾸게** 한다(2줄, 권한 상승 경로 차단). 이 변경은 이 라운드에 포함한다.

---

## 8. 마지막 백업 성공 시각: `backup.sh` → core

선택: **관리 명령 `record_backup`** (볼륨 상태 파일 방식은 web 컨테이너가 호스트 파일을 읽어야 해서 compose 볼륨을 하나 더 만들어야 한다. 관리 명령은 이미 `exec -T db`를 쓰는 스크립트에 `exec -T web` 한 줄이다.)

`core/api/management/commands/record_backup.py`(IntegrationStatus가 api 앱에 있으므로 같은 앱):
```python
class Command(BaseCommand):
    help = "backup.sh·restore-test.sh의 결과를 IntegrationStatus에 남긴다."
    def add_arguments(self, p):
        p.add_argument("--job", default="backup", choices=["backup", "restore-test"])
        p.add_argument("--ok", action="store_true"); p.add_argument("--fail", action="store_true")
        p.add_argument("--detail", default="")   # "stamp=20261007-041500 files=4 bytes=123456"
    def handle(self, *a, job, ok, fail, detail, **kw):
        if ok == fail: raise CommandError("--ok 또는 --fail 하나를 주세요.")
        now = timezone.now()
        row = IntegrationStatus.objects.filter(name=job).first()
        d = dict(row.detail) if row else {}
        d.update(dict(kv.split("=", 1) for kv in detail.split() if "=" in kv))
        if ok: d["last_ok_at"] = now.isoformat()          # 실패해도 이전 성공 시각은 남는다
        IntegrationStatus.objects.update_or_create(name=job, defaults={"last_run_at": now, "ok": ok, "detail": d})
        audit(None, "backup.record", target_type="backup", target_label=job, detail={"ok": ok})
```
`IntegrationStatus.name`은 `max_length=20`이라 `restore-test`(12자)도 들어간다. API `ALLOWED`(`integrations.py:9`)는 바꾸지 않는다 — 봇 토큰으로 백업을 "성공"으로 덮어쓰는 길을 열지 않는다.

`scripts/backup.sh` 변경(문서로만 — 운영 서버 반영은 사용자 몫):
```bash
set -euo pipefail
report() { docker compose -f "$PM_DIR/compose.yml" exec -T web python manage.py record_backup --job backup "$@" || true; }
trap 'report --fail --detail "stamp=$STAMP"' ERR          # set -e 로 끝나는 모든 실패
…(기존 본문 그대로)…
bytes=$(du -cb "${files[@]}" | tail -1 | cut -f1)
report --ok --detail "stamp=$STAMP files=${#files[@]} bytes=$bytes offsite=$([ -n "$OFFSITE_DIR" ] && echo 1 || echo 0)"
echo "OK $STAMP ${files[*]}"
```
`restore-test.sh` 끝에도 `report --job restore-test --ok --detail "dump=$(basename "$DUMP") tasks=… users=…"`(행 수는 집계라 괜찮다). `|| true`라 core가 내려가 있어도 백업 자체는 실패하지 않는다(백업이 더 중요하다). `docs/BACKUP.md` 표에 "마지막 백업 성공 시각 | `record_backup` → 운영 콘솔 시스템 카드" 행을 추가.

운영 콘솔 판정: `last_ok_at` 없음 → "기록 없음"(warn), 26시간 초과 → warn, 마지막 실행 `ok=False` → bad + detail 표시.

---

## 9. 범위 밖·2차로 미룬 것(이유)

| 항목 | 이유·대안 |
|---|---|
| AI 정책 거부 기록 | 지금 어디에도 저장되지 않는다(`orgs/services.py:35-62`는 예외만). 저장하려면 7곳 이상의 `raise` 지점 또는 API 예외 처리기(`api/api.py:69-76`)에서 `"ai" in exc.errors`를 보고 행을 남겨야 한다. 1차에서는 뺀다. 2차 최소안: `api.py`의 `_service_error`·`_forbidden`에서 `ai` 키가 있으면 `OpsAuditLog`가 아닌 새 표 없이 `logger.info("ai_denied org=%s action=%s")`만 → 로그 집계. 화면이 꼭 필요해지면 그때 `AiDenial(org, action, created_at)` 모델 |
| GitHub 웹훅 실패·재시도 대기열 | 세션 저장(`github_retries.py:74`). 운영자가 남의 세션을 열어 보는 것은 하지 않는다. 대기열을 DB로 옮기는 일은 GitHub 쓰기 재설계와 함께 |
| 조직 비활성 처리(정지·보관) | `Organization`에 상태 필드가 없다. 1차는 "비활성(90일 활동 없음)" 표시만. 필요해지면 `is_archived` + services |
| 세션 강제 종료 | 정지가 다음 요청부터 익명으로 만든다(`ModelBackend.get_user`). 별도 세션 삭제는 불필요 |
| 감사 기록 아카이브·보존 기간 | 삭제하지 않는다. 연 수만 행 수준이라 상한이 보일 때 설계 |
| 운영 콘솔 읽기 열람 기록 | §11 Q3 |
| 이메일 발송 | 기능 자체가 없다. 재설정 링크는 운영자가 전달 |
| `/ops` API·MCP 노출 | 하지 않는다. 운영 콘솔은 세션 전용 |

---

## 10. 구현 단계 표

기준선: 1415개 테스트 전부 통과, `ruff` 0. 전체 테스트 재실행·병합은 오케스트레이터.

| 단계 | 내용 | 담당 | 선후 | 마이그레이션 | 주로 고치는 파일 | 충돌 주의 |
|---|---|---|---|---|---|---|
| **O0** 기반 | 새 앱 `core/ops/`(`models.py` §4.1, `migrations/0001_initial.py` + 트리거 RunPython §4.2, `services.py` `audit()`·`FORBIDDEN_DETAIL_KEYS`·§5.2 함수 8개, `access.py` 데코레이터), `settings.py`(INSTALLED_APPS `"ops"`, `DJANGO_ADMIN_ENABLED`, `PASSWORD_RESET_TIMEOUT`), `config/urls.py` §7, `accounts/admin.py` readonly 3개, `base.html` 블록 2개, `templates/ops/base.html`·`_confirm.html`, `web/views/ops.py`를 §2.3대로 정리(home·system·design·export·healthz), `urls.py`의 ops 블록(개요·system·design·export·unlock 경로), `settings/_tabs.html`·`base.html:60` 정리, 테스트 `core/ops/tests.py`(append-only·audit 금지 키·데코레이터·admin 가드·admin 스위치) | **Opus** | 바로 시작 | `ops 0001_initial` | 위 전부 | 마이그레이션은 여기서만. 이후 단계는 만들지 않는다 |
| **O1** 사용자·접근·재설정 | §6.2 `ops_users.py`+`templates/ops/users.html`·`user.html`, §6.3 `ops_access.py`+`access.html`, `auth.py password_reset_confirm`+`auth/reset.html`, 기존 잠금 테스트 이동, `urls.py` ops 블록에 경로 추가 | **Opus**(보안 경로) | O0 뒤 | 없음 | `web/views/{ops_users,ops_access,auth}.py`, 템플릿 4개, `core/web/test_ops_users.py`(새) | `urls.py`는 O1·O2·O3가 각자 블록 끝에 줄을 덧붙인다 → 오케스트레이터가 순차 병합 |
| **O2** 조직·연동·시스템 카드 | §6.4 `ops_orgs.py`+`orgs.html`, §6.5 `ops_integrations.py`+`integrations.html`, §6.6 `system.html` 카드 6장(뷰는 O0의 `ops.py:system` 확장), §6.1 개요 타일 | Sonnet | O0 뒤, O1과 병렬 | 없음 | `web/views/{ops_orgs,ops_integrations,ops}.py`, 템플릿 3개, `core/web/test_ops_system.py`(새) | `ops.py`는 O0가 끝난 뒤에만. O3와 `ops.py`를 같이 만지지 않는다(O3는 `ops_audit.py`만) |
| **O3** 감사 기록 화면·CSV·디자인 이전 | §6.7 `ops_audit.py`+`audit.html`, `ops/design.html` 상속 전환(§6.8), `/ops/design` 견본 2개 추가, `DESIGN.md:4-5` 문구 | Sonnet | O0 뒤, 병렬 | 없음 | `web/views/ops_audit.py`, 템플릿 2개, `DESIGN.md`, `core/web/test_ops_audit.py`(새) | `test_design_system.py`의 경로 검사(`/ops/design`)가 그대로 통과해야 한다 |
| **O4** 백업 보고 | §8 `api/management/commands/record_backup.py`, `scripts/backup.sh`·`restore-test.sh`, `docs/BACKUP.md`, `docs/OPERATIONS-DEPLOYMENT.md`에 `DJANGO_ADMIN_ENABLED` 한 줄, `.env.example` 주석 | Sonnet | O0 뒤, 병렬 | 없음 | 위 5개, `core/api/test_record_backup.py`(새) | 없음 |
| **O5** 검토·승인 | O1 보안 경로(정지·재설정·권한)와 O0 트리거를 다른 제조사 모델이 교차 검토 → Fable 최종 판단 | Sol 검토 → Fable | O1~O4 뒤 | — | — | 검토·수정 반복은 Claude |

병렬 묶음: **O0 → {O1, O2, O3, O4} → O5.**

### 10.1 테스트 목록(단계별 핵심)
- O0: `makemigrations --check` 변경 없음; `OpsAuditLog` update/delete가 DB 오류(두 vendor — CI는 SQLite, 운영 Postgres 트리거 SQL은 문자열 검사로); `audit()`가 `token`·`password`·`key_hash` 키를 거부; `ops_required`가 비로그인 302·멤버 404·staff 200; `superuser_required`가 staff 404; `/admin/`이 staff에게 로그인 화면(모델 목록 없음)·superuser 200, 둘 다 `admin.access` 1건(`allowed` False/True); `DJANGO_ADMIN_ENABLED=0`이면 404; `settings/_tabs.html`에 "운영 상태" 없음; `/ops`가 `ops/base.html`을 쓰고 설정 탭을 include하지 않음(`"설정 메뉴"` 문자열 부재); 기존 `test_ops_requires_staff`·`test_export_json_has_no_secrets`(export는 superuser + POST + reason + confirm으로 바꾼다 — 테스트 수정) 통과.
- O1: 정지 → `client.login` 실패·API 토큰 401·세션 사용자 익명; 재활성 복구; 자기 자신 정지 거부; 운영자 대상 정지는 superuser만; 사유 4자 거부; confirm 불일치 시 아무것도 안 바뀜·기록 없음; 재설정 링크 발급 → 기록에 링크 없음·세션에서 1회만·링크로 비밀번호 변경 성공·재사용 실패·25시간 뒤 실패(`freezegun` 없음 → `PASSWORD_RESET_TIMEOUT` override로 0초); 운영자 부여·회수(superuser만, 자기 회수 거부, superuser 회수 거부); 타인 토큰 폐기(confirm=앞자리); 잠금 해제 사유 필수 + 기록; 사용자 상세에 `Task.title`·`settings` 값이 없다.
- O2: 조직 표 annotate가 쿼리 수 상수(`CaptureQueriesContext`, 조직 3개·30개 같은 수); 비활성 배지 90일; Discord 감시 10분 초과 warn; `GITHUB_ENABLED=False`면 설치 카드 없음; `app_capabilities` None → "확인 불가"; 알림 대기 건수; 백업 없음 → "기록 없음", 27시간 전 성공 → warn; 미적용 마이그레이션 0 표시; 녹음 멈춤 6시간; `MEDIA_ROOT` 용량 값 존재; `test_ops_templates_touch_no_content_fields`(정규식 `\.(title|description|body_md|transcript_md|text|old_value|new_value|purpose|governance)\b` 가 `templates/ops/*.html`에 없음) + `test_ops_shows_no_content`(태스크 제목·회의록 본문·첨부 이름·토큰 이름·알림 문구를 심고 모든 ops 화면 본문에 없음).
- O3: 필터 4종 각각; 100건 페이지; CSV 헤더·행 수·`audit.export` 기록; `/ops/design` staff 전용 유지 + 설정 탭 없음.
- O4: `record_backup --ok`가 `last_ok_at` 기록·`--fail`이 `last_ok_at` 보존·둘 다/둘 다 아님 오류·`restore-test` 이름·`backup.record` 기록 actor "system"; `backup.sh`에 `record_backup` 호출과 `trap … ERR`이 있는지 문자열 검사.

### 10.2 수용 기준
1. 새 테스트 전부 + 기존 1415개 통과, `ruff check`·`ruff format --check` 0, `makemigrations --check` 변경 없음.
2. 설정 화면(프로필·환경설정·API 토큰)에 운영 항목이 하나도 없고, staff가 아닌 사용자는 `/ops*`에서 404.
3. 운영 콘솔의 모든 변경 동작이 사유 없이는 실패하고, 성공하면 `OpsAuditLog`가 정확히 1건 늘며, 그 행은 어떤 경로로도 고치거나 지울 수 없다.
4. 운영 콘솔 어느 화면에도 태스크 제목·설명·회의록·문서·첨부 이름·알림 문구·토큰 이름·설정 비밀값이 나오지 않는다(테스트 2종).
5. `DJANGO_ADMIN_ENABLED=0`이면 `/admin/`이 404, 켜져 있으면 superuser만 들어가고 접근이 기록된다.
6. `record_backup --ok` 뒤 시스템 카드에 마지막 백업 성공 시각이 보이고, 실패 보고가 그 시각을 지우지 않는다.
7. 390×844·1440×1050 라이트·다크에서 운영 콘솔 상단 메뉴·표가 가로로 넘치지 않는다(DESIGN.md §11-8).

---

## 11. 사용자에게 물을 것(3개)

| # | 질문 | 선택지 | 추천 |
|---|---|---|---|
| 1 | 서비스 운영자 권한(`is_staff`) 부여·회수를 누가 하는가 | (a) **최고 운영자만**(운영 콘솔에서, 대상 재입력) (b) 서비스 운영자도 다른 사람에게 부여 가능(회수는 최고 운영자만) (c) 운영 콘솔에서는 못 하고 Django 관리 화면·셸만 | **(a)** — 운영자 권한은 전체 사용자 정지·토큰 폐기까지 할 수 있는 권한이라 부여 주체를 가장 좁게 둔다. (c)는 감사 기록 없이(LogEntry만) 바뀌는 길을 남긴다 |
| 2 | 운영 데이터 JSON 내보내기(`ops.py:55-90`, 태스크·변경 이력 전문 포함)의 처리 | (a) **최고 운영자 전용 + 사유 + `export` 재입력 + 감사 기록**으로 유지 (b) 삭제(백업은 pg_dump가 담당, BACKUP.md가 "별도 구현 필요"라 적은 구조화 내보내기는 미구현으로 되돌림) (c) 지금처럼 staff 누구나 | **(a)** — SPEC 11.2 "관리자는 구조화된 내보내기를 실행할 수 있다"를 이 기능이 맡고 있다. 결정 3(집계만)의 유일한 예외이므로 최고 운영자·사유·기록으로 좁힌다 |
| 3 | 운영 콘솔의 **읽기** 열람을 감사 기록에 남길 범위 | (a) **변경·내보내기·Django 관리 화면 접근만** (b) (a) + 사용자 상세 화면 열람 (c) 모든 운영 콘솔 페이지 열람 | **(a)** — 집계 화면 열람은 민감 정보가 없고, 기록이 많아지면 정작 중요한 변경 기록이 묻힌다. (b)가 필요해지면 `ops_users.detail`에 `audit()` 한 줄 |

묻지 않고 추천대로 확정: 비운영자는 404 · 사유 5~300자 · 재설정 링크 24시간·1회·자동 로그인 없음 · 정지 대상이 운영자면 superuser만 · 봇 토큰은 콘솔에서 폐기 불가 · 조직 변경 동작 없음 · 비활성 조직 = 90일 · 백업 경고 26시간 · Discord 감시 경고 10분 · 녹음 멈춤 6시간 · 감사 기록 보존 무기한 · AI 정책 거부 기록은 2차 · 새 마이그레이션은 `ops 0001` 하나 · 새 의존성 없음.

## 12. 확인 불가
- 운영 서버의 cron·`backup.sh` 실제 버전과 `/var/log/pm-backup.log` 상태 — 서버는 보지 않았다(범위 밖). §8의 스크립트 변경은 사용자가 서버에 반영한다.
- 운영 DB에 지금 `is_staff`·`is_superuser`인 계정이 몇 개인지, mcp 통합 행이 있는지 — 서버 DB 미조회. 개요 타일이 배포 뒤 보여 준다.
- `GitEvent` 모델의 필드(수신 시각 이름) — `github/models.py:184`만 확인했다. O2가 구현 때 본다.
- Postgres 트리거 SQL은 테스트 환경(SQLite)에서 실행되지 않는다. 운영 배포 뒤 `psql`에서 `UPDATE ops_opsauditlog SET reason='x' WHERE id=1`이 거부되는지 1회 확인한다(운영 작업, 문서로만).
- SPEC 11.3 "AI 호출 실패와 사용량": core에 LLM 호출 코드가 없다(grep `openai|anthropic` 0건, 포트폴리오는 프롬프트만 만든다). AI 사용은 MCP 경유 `ChangeLog.source="mcp"` 건수로 대신한다.
