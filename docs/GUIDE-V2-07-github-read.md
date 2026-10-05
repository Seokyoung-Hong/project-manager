# 구현 지시서 V2-07: GitHub 읽기 (7단계)

목표: GitHub App을 조직에 설치하고, 각 사용자가 자기 GitHub 계정을 연결하고, 저장소 이벤트를 받아 태스크 상태를 자동으로 옮긴다. 그리고 **볼 권한이 있는 사람에게만** git 정보를 보여 준다.

이 단계에서 PM은 GitHub에 **아무것도 쓰지 않는다.** 쓰기는 `GUIDE-V2-08`이다.

> 여기서 처음이자 마지막으로 의존성이 하나 늘어난다. **`cryptography`** 다. 쓰는 곳은 둘뿐이다. 사용자 토큰 Fernet 암호화, 설치 토큰을 받기 위한 JWT의 RS256 서명. PyJWT·httpx·requests를 넣지 않는다. HTTP는 stdlib `urllib`로 한다.

---

## 1. 설계 요약

| 항목 | 결정 |
|---|---|
| 연결 방식 | **GitHub App.** 조직 관리자가 PM 화면에서 설치한다. 조직마다 저장하는 비밀은 없고 설치 번호만 남는다 |
| 앱 권한 | 저장소 Contents 읽기·쓰기 · Issues 읽기·쓰기 · Pull requests 읽기 · Metadata 읽기, 조직 Members 읽기·쓰기 |
| **받지 않는 권한** | 저장소 **Administration**. 저장소 삭제·설정 변경·브랜치 보호·배포 키·개인 협업자가 전부 딸려 오기 때문이다. 팀에 저장소 권한을 주는 API가 이 권한을 요구하므로 그 기능은 v1에서 빼고 GitHub 링크로 넘긴다 |
| 토큰 둘 | **설치 토큰**은 서버 혼자 쓰고 **읽기에만** 쓴다. **사용자 토큰**은 그 사람의 권한 확인과(V2-08의) 모든 쓰기에 쓴다 |
| 이벤트 | 앱 수준 웹훅 하나. 저장소마다 등록할 필요가 없다. 폴링하지 않는다 |
| 수신 주소 | `POST https://pm.<도메인>/api/integrations/github/webhook`. **새 공개 호스트를 만들지 않는다** |
| 새 파트 | **없다.** `github_service` 같은 컨테이너를 만들지 않는다 |
| 가시성 | 태스크는 조직 규칙으로, GitHub에서 온 데이터는 GitHub 권한으로 |

---

## 2. Step 1. 운영자 1회 설정

구현자가 아니라 **운영자가 GitHub에서** 하는 일이다. 지시서에 절차를 남기고, 코드는 이 값들을 환경 변수로 읽는다.

자세한 절차는 **[GITHUB-APP-SETUP.md](GITHUB-APP-SETUP.md)** 한 장에 있다. 다른 사람이나 다른 에이전트에게 등록을 맡길 때는 그 파일만 주면 된다. 코드가 기대하는 것만 요약하면:

1. 앱은 **두 개** 만든다. 운영용(`pm.<도메인>`)과 개발용(`project.dorm.sio2.kr`). **둘 다 공개 도메인이어야 한다** — GitHub가 `localhost`로는 웹훅을 보낼 수 없다. 값이 다를 뿐 설정은 같다.
2. 주소 셋. Callback URL `<SITE_URL>/settings/github/callback`, **Setup URL `<SITE_URL>/orgs/github/installed`**("Redirect on update" 켬), Webhook URL `<SITE_URL>/api/integrations/github/webhook` + Secret.
3. Permissions — Repository: Contents(Read and write) · Issues(Read and write) · Pull requests(Read) · Metadata(Read). Organization: Members(Read and write). **Administration은 고르지 않는다.**
4. Subscribe to events: Push · Create · Pull request · Issues · Membership · Team · Installation · Installation repositories.
5. **"Request user authorization (OAuth) during installation"은 끈다.** 켜면 GitHub가 설치를 마친 뒤 Setup URL이 아니라 OAuth 콜백으로 `code`와 `installation_id`를 함께 보내서, 아래 §5·§6의 두 흐름이 하나로 섞인다. 설치는 관리자가, 계정 연결은 각자가 따로 하는 편이 단순하다. "Expire user authorization tokens"는 **켠다**.
6. Where can this GitHub App be installed? → Any account.
7. 만든 뒤 App ID, 앱 슬러그, Client ID, Client secret, Private key(.pem), Webhook secret을 확보한다.

개발 서버도 공개 도메인 뒤에 둔다(예: `https://project.dorm.sio2.kr`). GitHub는 `localhost`로 웹훅을 보낼 수 없다. 리버스 프록시·방화벽·`.env` 설정은 [GITHUB-APP-SETUP.md](GITHUB-APP-SETUP.md) §4에 있다. 공개 주소가 없으면 웹훅을 빼고 §12의 테스트 픽스처로만 확인한다.


`.env`에 넣는다. `.env.example`에도 같은 키를 빈 값으로 넣는다.

```
GITHUB_APP_ID=
GITHUB_APP_SLUG=
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GITHUB_WEBHOOK_SECRET=
# .pem 파일 내용. 줄바꿈은 \n 으로 넣는다.
GITHUB_APP_PRIVATE_KEY=
# 사용자 GitHub 토큰 암호화 키. python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CREDENTIAL_KEY=
```

`config/settings.py`:

```python
GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID", "")
GITHUB_APP_SLUG = os.environ.get("GITHUB_APP_SLUG", "")
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
GITHUB_APP_PRIVATE_KEY = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n")
CREDENTIAL_KEY = os.environ.get("CREDENTIAL_KEY", "")
# 설정이 없으면 GitHub 화면과 버튼을 아예 그리지 않는다(개발·테스트 환경).
GITHUB_ENABLED = bool(GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY and CREDENTIAL_KEY)
```

`common/logging.py`의 `SecretFilter`에 `GITHUB_APP_PRIVATE_KEY`·`GITHUB_CLIENT_SECRET`·`GITHUB_WEBHOOK_SECRET`·`CREDENTIAL_KEY`와 `ghs_`·`ghu_`·`ghr_` 접두어를 더한다.

`core/pyproject.toml`의 `dependencies`에 `"cryptography>=43"`을 넣고 `uv lock`.

---

## 3. Step 2. `github` 앱과 모델

```bash
cd core && uv run python manage.py startapp github
```

`INSTALLED_APPS`에 `"github"`를 `notes` 뒤에 넣는다. 앱 이름이 PyGithub의 import 이름과 같지만 이 프로젝트는 그 라이브러리를 쓰지 않는다.

`github/models.py`:

```python
from django.conf import settings
from django.db import models


class GitHubInstallation(models.Model):
    """조직 하나에 설치 하나. 비밀은 없고 설치 번호만 있다."""

    org = models.OneToOneField(
        "orgs.Organization", on_delete=models.CASCADE, related_name="github"
    )
    installation_id = models.BigIntegerField(unique=True)
    account_login = models.CharField(max_length=100)     # GitHub 조직 이름
    account_type = models.CharField(max_length=20, blank=True)
    repo_selection = models.CharField(max_length=10, blank=True)   # all | selected
    installed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    installed_at = models.DateTimeField(auto_now_add=True)
    suspended_at = models.DateTimeField(null=True, blank=True)


class GitHubIdentity(models.Model):
    """사용자의 GitHub 계정. 토큰은 Fernet으로 암호화해 저장한다.

    토큰을 버리지 않는 이유: 그 사람이 접속하지 않은 동안에도 접근 가능 저장소를
    다시 확인해야 하기 때문이다(GitHub에서 권한이 바뀌면 PM이 알 길이 없다).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="github"
    )
    github_id = models.BigIntegerField(unique=True)
    login = models.CharField(max_length=100)
    token_enc = models.TextField(blank=True)
    refresh_enc = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    refresh_expires_at = models.DateTimeField(null=True, blank=True)
    repos = models.JSONField(default=list, blank=True)      # ["owner/repo", ...]
    repos_checked_at = models.DateTimeField(null=True, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)


class RepoConnection(models.Model):
    project = models.OneToOneField(
        "projects.Project", on_delete=models.CASCADE, related_name="repo"
    )
    url = models.CharField(max_length=300)                 # 사용자가 넣은 원문
    full_name = models.CharField(max_length=200)           # owner/repo
    import_label = models.CharField(max_length=50, default="task")
    assignee_default = models.CharField(max_length=5, default="issue")   # issue | none
    auto_import = models.BooleanField(default=False)
    rule_issue = models.BooleanField(default=True)
    rule_branch = models.BooleanField(default=True)
    rule_commit = models.BooleanField(default=True)
    rule_pr = models.BooleanField(default=True)
    rule_merge = models.BooleanField(default=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["full_name"])]


class RepoIssue(models.Model):
    connection = models.ForeignKey(RepoConnection, on_delete=models.CASCADE, related_name="issues")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=300)
    state = models.CharField(max_length=6, default="open")     # open | closed
    assignee_login = models.CharField(max_length=100, blank=True)
    labels = models.JSONField(default=list, blank=True)
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["connection", "number"], name="repoissue_conn_number"),
        ]


class TaskGitLink(models.Model):
    """네 단계(이슈·브랜치·PR·머지)는 모두 선택적이다. 없는 단계는 빈 값으로 둔다."""

    task = models.OneToOneField("tasks.Task", on_delete=models.CASCADE, related_name="git")
    connection = models.ForeignKey(RepoConnection, on_delete=models.CASCADE, related_name="links")
    issue_number = models.PositiveIntegerField(null=True, blank=True)
    issue_title = models.CharField(max_length=300, blank=True)
    issue_state = models.CharField(max_length=6, blank=True)
    branch = models.CharField(max_length=200, blank=True)
    pr_number = models.PositiveIntegerField(null=True, blank=True)
    pr_title = models.CharField(max_length=300, blank=True)
    pr_state = models.CharField(max_length=6, blank=True)      # open | merged | closed
    merged_at = models.DateTimeField(null=True, blank=True)
    commits = models.JSONField(default=list, blank=True)       # [{sha, message, item, at}]


class GitEvent(models.Model):
    connection = models.ForeignKey(RepoConnection, on_delete=models.CASCADE, related_name="events")
    delivery_id = models.CharField(max_length=64, unique=True)
    occurred_at = models.DateTimeField()
    kind = models.CharField(max_length=20)
    actor_login = models.CharField(max_length=100, blank=True)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    summary = models.CharField(max_length=200)
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    result = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
```

`GitEvent`는 저장 뒤 연결당 50건을 넘는 오래된 행을 지운다.
`# ponytail: 표 하나에 잘라 둔다. 감사 로그가 필요해지면 보관 정책으로 바꾼다.`

---

## 4. Step 3. `github/crypto.py`와 `github/client.py`

```python
# github/crypto.py
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    return Fernet(settings.CREDENTIAL_KEY.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt((value or "").encode()).decode()


def decrypt(value: str) -> str:
    """복호화에 실패하면 빈 문자열. 키를 갈았을 때 로그인 자체가 막히지 않게 한다."""
    try:
        return _fernet().decrypt((value or "").encode()).decode()
    except (InvalidToken, ValueError):
        return ""
```

```python
# github/client.py — HTTP는 stdlib로만 한다.
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from django.conf import settings

API = "https://api.github.com"
TIMEOUT = 15


class GitHubError(Exception):
    """GitHub가 거부했다. status와 사람이 읽을 메시지를 들고 있다."""

    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(f"GitHub {status}: {message}")


def request(method: str, path: str, token: str, *, body=None, accept="application/vnd.github+json"):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", accept)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "udally")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 — 고정 호스트
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("message", "")
        except Exception:  # noqa: BLE001 — 본문이 JSON이 아닐 수 있다
            msg = ""
        raise GitHubError(e.code, msg or e.reason) from None
    except urllib.error.URLError as e:
        raise GitHubError(0, str(e.reason)) from None


def _b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def app_jwt() -> str:
    """앱 개인키로 서명한 10분짜리 JWT. PyJWT 없이 직접 만든다."""
    key = serialization.load_pem_private_key(
        settings.GITHUB_APP_PRIVATE_KEY.encode(), password=None
    )
    now = int(time.time())
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64(
        json.dumps({"iat": now - 60, "exp": now + 540, "iss": settings.GITHUB_APP_ID}).encode()
    )
    signing_input = header + b"." + payload
    sig = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return (signing_input + b"." + _b64(sig)).decode()


_install_cache: dict[int, tuple[str, float]] = {}


def installation_token(installation_id: int) -> str:
    """1시간짜리 설치 토큰. 5분 여유를 두고 캐시한다. 읽기에만 쓴다."""
    hit = _install_cache.get(installation_id)
    if hit and hit[1] > time.time():
        return hit[0]
    data = request(
        "POST", f"/app/installations/{installation_id}/access_tokens", app_jwt()
    )
    token = data["token"]
    _install_cache[installation_id] = (token, time.time() + 3300)
    return token


def exchange_code(code: str) -> dict:
    """OAuth 코드를 사용자 토큰으로 바꾼다."""
    body = urllib.parse.urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
        }
    ).encode()
    return _oauth_post(body)


def refresh_user_token(refresh_token: str) -> dict:
    body = urllib.parse.urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode()
    return _oauth_post(body)


def _oauth_post(body: bytes) -> dict:
    req = urllib.request.Request(
        "https://github.com/login/oauth/access_token", data=body, method="POST"
    )
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "udally")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 — 고정 호스트
            data = json.loads(r.read())
    except urllib.error.URLError as e:
        raise GitHubError(0, str(e)) from None
    if "error" in data:
        raise GitHubError(400, data.get("error_description") or data["error"])
    return data
```

캐시는 프로세스 메모리다. gunicorn 워커가 둘이면 각자 받는다. 하루 요청 수가 적어 문제가 없다.
`# ponytail: 프로세스별 캐시. 워커가 많아지면 DB나 캐시 백엔드로 옮긴다.`

---

## 5. Step 4. 조직에 앱 설치

`orgs/_tabs.html`에 관리자 전용 탭을 더한다.

```html
  {% if is_admin %}<a href="{% url 'org_github' org.pk %}" {% if tab == "github" %}aria-current="page"{% endif %}>GitHub</a>{% endif %}
```

화면(`orgs/github.html`)은 카드 셋이다.

1. **설치 상태** — 미설치면 [GitHub 앱 설치] 버튼 하나와 안내. 설치되어 있으면 GitHub 조직 이름, 저장소 범위(전체/선택), 설치 시각, [GitHub에서 설정] 링크(`https://github.com/organizations/{login}/settings/installations/{id}`)
2. **내 GitHub 연결** — 현재 사용자의 연결 상태와 접근 가능 저장소 수, 마지막 확인 시각, [다시 확인]
3. **저장소 연결 현황** — 프로젝트마다 한 줄. "연결됨 · owner/repo" 또는 "미연결" + [저장소 설정](프로젝트 저장소 탭으로)

설치 흐름:

```python
@login_required
def github_install(request, org_id):
    org = _admin_only(request, org_id)
    request.session["gh_install_org"] = org.pk
    state = secrets.token_urlsafe(16)
    request.session["gh_state"] = state
    url = f"https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new?state={state}"
    return redirect(url)


@login_required
def github_installed(request):
    """GitHub가 되돌려 주는 곳. ?installation_id=&setup_action=&state="""
    if request.GET.get("state") != request.session.pop("gh_state", None):
        raise Http404
    org_id = request.session.pop("gh_install_org", None)
    org = _admin_only(request, org_id)
    iid = request.GET.get("installation_id", "")
    if not iid.isdecimal():
        messages.error(request, "설치를 확인하지 못했습니다.")
        return redirect("org_github", org_id=org.pk)
    services.save_installation(org, int(iid), actor=request.user)
    messages.success(request, "GitHub 앱을 설치했습니다.")
    return redirect("org_github", org_id=org.pk)
```

URL은 둘이다. 두 번째가 앱 설정의 **Setup URL**과 정확히 같아야 한다.

```
orgs/<int:org_id>/github/install     github_install
orgs/github/installed                github_installed      ← Setup URL
```

`save_installation`은 `GET /app/installations/{id}`(앱 JWT)로 계정 이름과 `repository_selection`을 읽어 저장한다. 다른 조직이 이미 그 설치를 쓰고 있으면 거부한다.

---

## 6. Step 5. 사용자 계정 연결

프로필(`settings/profile.html`)에 Discord 카드와 나란히 GitHub 카드를 둔다.

```
settings/github            github_connect     GET  → GitHub authorize로 redirect
settings/github/callback   github_callback    GET
settings/github/refresh    github_refresh     POST → 접근 가능 저장소 다시 확인
settings/github/unlink     github_unlink      POST
```

```python
def github_connect(request):
    state = secrets.token_urlsafe(16)
    request.session["gh_oauth_state"] = state
    q = urlencode({
        "client_id": settings.GITHUB_CLIENT_ID,
        "state": state,
        "redirect_uri": f"{settings.SITE_URL}/settings/github/callback",
    })
    return redirect(f"https://github.com/login/oauth/authorize?{q}")
```

콜백은 `state`를 확인하고 `exchange_code(code)` → `GET /user`로 id·login을 읽어 `GitHubIdentity`를 만들거나 갱신한다. 그 다음 `sync_repos(identity)`를 부르고, 마지막으로 **과거 이력을 소급해서 채운다.**

```python
def backfill_actor(identity):
    """이 로그인으로 남아 있던 GitHub 이력을 이 사람의 것으로 바꾼다."""
    ChangeLog.objects.filter(
        source="gh", actor__isnull=True, external_actor__iexact=identity.login
    ).update(actor_id=identity.user_id, external_actor="")
    GitEvent.objects.filter(actor_user__isnull=True, actor_login__iexact=identity.login).update(
        actor_user_id=identity.user_id
    )
```

토큰 만료 처리:

```python
def user_token(identity) -> str:
    """살아 있는 사용자 토큰. 만료됐으면 refresh 토큰으로 갱신한다."""
    now = timezone.now()
    if identity.token_expires_at and identity.token_expires_at > now + timedelta(minutes=2):
        return decrypt(identity.token_enc)
    refresh = decrypt(identity.refresh_enc)
    if not refresh or (identity.refresh_expires_at and identity.refresh_expires_at <= now):
        raise ServiceError({"github": "GitHub 연결이 만료됐습니다. 프로필에서 다시 연결하세요."})
    data = client.refresh_user_token(refresh)
    _store_tokens(identity, data)
    return decrypt(identity.token_enc)
```

접근 가능 저장소 갱신:

```python
REPO_TTL = timedelta(hours=6)


def sync_repos(identity) -> list[str]:
    """앱이 설치된 저장소 중 이 사람이 볼 수 있는 것. 설치마다 물어 합친다."""
    token = user_token(identity)
    names = []
    # 이 사람이 속한 조직의 설치만 묻는다. 남의 조직 설치는 어차피 403이다.
    installs = GitHubInstallation.objects.filter(
        suspended_at__isnull=True, org__in=orgs_of(identity.user)
    )
    for inst in installs:
        page = 1
        while True:
            data = client.request(
                "GET",
                f"/user/installations/{inst.installation_id}/repositories?per_page=100&page={page}",
                token,
            )
            names += [r["full_name"] for r in data.get("repositories", [])]
            if len(data.get("repositories", [])) < 100:
                break
            page += 1
    identity.repos = sorted(set(names))
    identity.repos_checked_at = timezone.now()
    identity.save(update_fields=["repos", "repos_checked_at"])
    return identity.repos
```

설치에 접근 권한이 없으면 GitHub가 403·404를 준다. 그 설치는 건너뛴다.

**로그인 때 갱신한다.** `django.contrib.auth.signals`는 쓰지 않는다(시그널 금지). 로그인 뷰를 감싸는 대신 `web/views/common.py`에 헬퍼를 두고 셸 context processor에서 부른다.

```python
def refresh_github_access(request):
    """마지막 확인이 오래됐으면 다시 물어본다. 실패는 조용히 넘긴다.

    # ponytail: 요청 경로에서 GitHub를 한 번 부른다(6시간에 한 번). 느껴지면
    # GitHub 화면 첫 진입으로 미룬다.
    """
    identity = getattr(request.user, "github", None)
    if identity is None or not settings.GITHUB_ENABLED:
        return
    last = identity.repos_checked_at
    if last and timezone.now() - last < REPO_TTL:
        return
    try:
        sync_repos(identity)
    except (GitHubError, ServiceError):
        pass
```

---

## 7. Step 6. 권한 필터

`github/services.py`에 **한 곳**을 두고 화면 전부가 이것을 지난다.

```python
def can_view_repo(user, full_name: str) -> bool:
    if not full_name:
        return False
    identity = getattr(user, "github", None)
    return bool(identity and full_name in (identity.repos or []))


def repo_state(user, project) -> dict:
    """패널·탭이 함께 쓰는 상태. 셋 중 하나다."""
    conn = getattr(project, "repo", None)
    if conn is None:
        return {"conn": None, "state": "none"}          # 저장소 미연결
    if getattr(user, "github", None) is None:
        return {"conn": conn, "state": "unlinked"}      # GitHub 미연결
    if not can_view_repo(user, conn.full_name):
        return {"conn": conn, "state": "denied"}        # 접근 권한 없음
    return {"conn": conn, "state": "ok"}
```

화면 문구는 상태마다 고정이다.

| 상태 | 패널 GitHub 블록 | 저장소 탭 |
|---|---|---|
| `none` | "저장소 미연결" + [저장소 연결] | 연결 폼 |
| `unlinked` | "GitHub를 연결하면 저장소 정보가 보입니다" + [GitHub 연결] | 같은 안내만 |
| `denied` | "저장소 접근 권한 없음" | "연결됨(접근 권한 없음)"만. 저장소 이름·이슈·이벤트 숨김 |
| `ok` | 4단계 전부 | 전부 |

**API와 MCP는 git 필드를 내보내지 않는다.** 같은 필터를 두 번 만들지 않기 위해서다.

---

## 8. Step 7. 웹훅 수신

`api/routers/github.py`. 라우터 인증을 서명 검증으로 바꿔 세션·토큰이 들어오지 못하게 한다.

```python
class WebhookAuth:
    """X-Hub-Signature-256만 믿는다. 세션 쿠키도 API 토큰도 이 경로에 들어오지 못한다."""

    def __call__(self, request):
        secret = settings.GITHUB_WEBHOOK_SECRET.encode()
        sent = request.headers.get("X-Hub-Signature-256", "")
        mine = "sha256=" + hmac.new(secret, request.body, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(sent, mine):
            return None
        return AnonymousUser()


# throttle=[]: 전역 UserRateThrottle은 request.auth.pk가 없으면 문자열 키 하나로 묶어
# 모든 웹훅을 분당 60건 공용 한도에 넣는다. push가 몰리면 429가 난다.
router = Router(tags=["github"], auth=WebhookAuth(), throttle=[])


@router.post("/webhook", response={200: dict, 202: dict})
def webhook(request):
    event = request.headers.get("X-GitHub-Event", "")
    delivery = request.headers.get("X-GitHub-Delivery", "")
    payload = json.loads(request.body or b"{}")
    return gh_services.handle_event(event, delivery, payload)
```

`api/api.py`에 `api.add_router("/integrations/github", github.router)`를 **`/integrations` 라우터보다 먼저** 등록한다(`/integrations/{name}/status`가 삼키지 않게).

`hmac.compare_digest`를 쓴다. `==` 비교는 쓰지 않는다.

처리하는 이벤트만 받고 나머지는 202로 흘린다.

| 이벤트 | 하는 일 |
|---|---|
| `installation` (created/deleted/suspend/unsuspend) | 설치 레코드 갱신 |
| `installation_repositories` | 저장소 범위가 바뀜. 모든 `GitHubIdentity.repos_checked_at`을 비워 다음 로그인에 다시 묻게 한다 |
| `create` (`ref_type == "branch"`) | 브랜치 규칙 |
| `push` | 커밋 규칙 |
| `pull_request` (opened / closed) | PR·머지 규칙 |
| `issues` (opened / closed / edited) | 이슈 동기화와 규칙 |
| `membership` · `team` | V2-08에서 쓴다. 지금은 `GitEvent`에만 남긴다 |

중복은 `GitEvent.delivery_id`의 unique가 막는다.

```python
def handle_event(event: str, delivery: str, payload: dict) -> tuple[int, dict]:
    if event in ("installation", "installation_repositories"):
        _installation_event(event, payload)
        return 200, {"ok": True}
    full_name = ((payload.get("repository") or {}).get("full_name")) or ""
    conns = list(RepoConnection.objects.filter(full_name__iexact=full_name).select_related("project"))
    if not conns:
        return 202, {"ignored": "연결되지 않은 저장소"}
    # delivery_id는 연결마다 f"{delivery}:{conn.pk}"로 저장되므로 접두어로 찾는다.
    if GitEvent.objects.filter(delivery_id__startswith=f"{delivery}:").exists():
        return 200, {"ok": True, "duplicate": True}
    handler = {"create": _on_create, "push": _on_push,
               "pull_request": _on_pr, "issues": _on_issues}.get(event)
    if handler is None:
        return 202, {"ignored": event}
    for conn in conns:          # 한 저장소를 두 프로젝트가 가리킬 수 있다
        handler(conn, delivery, payload)
    return 200, {"ok": True}
```

두 프로젝트가 같은 저장소를 가리킬 수 있으므로 `delivery_id`가 unique면 두 번째 연결에서 충돌한다. `delivery_id`를 `f"{delivery}:{conn.pk}"`로 저장한다. GitHub의 delivery GUID는 36자라 `max_length=64` 안에 든다.

`GitEvent.occurred_at`은 페이로드의 시각을 쓴다. `push`는 `head_commit.timestamp`, `pull_request`는 `pull_request.updated_at`, `issues`는 `issue.updated_at`, `create`는 없으므로 `timezone.now()`. 전부 ISO 8601이라 `datetime.fromisoformat()`으로 읽는다(`Z`는 `+00:00`으로 바꾼다).

행위자는 `payload["sender"]`에서 읽는다. `sender.id`로 `GitHubIdentity`를 찾으면 그 사람이 `actor_user`이고, 못 찾으면 `actor_login`만 남긴다.

---

## 9. Step 8. 자동 전환 규칙

태스크 번호는 `TASK-(\d+)`를 대소문자 무시로 찾는다. 체크리스트 항목은 `TASK-147:2`(콜론 + 1부터 세는 순번)다. **브랜치 이름 규칙을 강제하지 않는다.**

```python
TASK_RE = re.compile(r"TASK-(\d+)(?::(\d+))?", re.I)


def _find_task(conn, *texts):
    """연결된 프로젝트 안에서만 찾는다. 다른 프로젝트 번호를 적어도 움직이지 않는다."""
    for text in texts:
        for m in TASK_RE.finditer(text or ""):
            task = Task.objects.filter(pk=int(m.group(1)), project=conn.project).first()
            if task:
                return task, (int(m.group(2)) if m.group(2) else None)
    return None, None
```

| 규칙 | 조건 | 동작 |
|---|---|---|
| `rule_branch` | `create`, `ref_type=branch`, 이름에 태스크 번호 | `TaskGitLink.branch` 저장 + `transition(doing)` |
| `rule_commit` | `push`, 커밋 메시지 또는 브랜치로 태스크를 찾음 | `commits`에 추가. `:N`이 있으면 체크리스트 N번째를 체크 |
| `rule_pr` | `pull_request opened`, 제목·본문·브랜치에 번호 | PR 필드 저장 + `transition(review)` |
| `rule_merge` | `pull_request closed` && `merged` | `transition(done)` + `pr_state="merged"` |
| `rule_issue` | `issues opened` + 라벨 일치 + `auto_import` + **GitHub를 연결한 조직 멤버가 배정됨** | 태스크 생성(담당자=배정된 멤버) + 이슈 연결. 배정 없으면 기록만 |
| `rule_issue` | `issues closed` | 연결 태스크가 열려 있으면 `transition(done)` |

상태 전환은 **반드시 `tasks.services.transition()`을 지난다.** 규칙이 직접 `status`를 쓰지 않는다.

```python
def _apply(task, status, *, actor, actor_login, note=""):
    """규칙이 상태를 바꾸는 유일한 통로. 실패해도 연결은 남기고 사유만 기록한다."""
    if task.status == status:
        return "변경 없음"
    try:
        transition(
            task, status, actor=actor, source="gh", reason="",
            expected_version=task.version, external_actor=actor_login,
        )
        return dict(Task.STATUSES)[status]
    except (ServiceError, ConflictError) as e:
        return _reason(e)
```

기한 없는 태스크를 진행 중으로 못 바꾸는 경우가 여기 걸린다. 브랜치 연결은 유지하고 이벤트 표에 "기한이 없어 진행 중으로 못 바꿈"이 남는다.

### 이슈 자동 가져오기의 문턱, 행위자, 담당자

**2026-09-14 개정.** 자동 가져오기는 **GitHub를 연결한 조직 멤버가 배정된 이슈만** 가져온다. 이슈는 저장소를
볼 수 있는 누구나 열 수 있지만 배정은 협업자만 할 수 있다 — 이 문턱이 없으면 공개 저장소에서 이슈만 열어도
PM에 태스크가 쌓인다. 배정되지 않은 이슈는 `RepoIssue`와 이벤트(`담당자 미배정 · 가져오지 않음`)만 남기고,
저장소 탭에서 사람이 [태스크로 가져오기]를 누르면 그때는 누른 사람이 행위자다.

```python
def _assigned_member(conn, issue):
    """이슈에 배정된 사람이 GitHub를 연결한 조직 멤버면 그 사용자, 아니면 None."""
    login = ((issue.get("assignee") or {}).get("login")) or ""
    if not login:
        return None
    identity = GitHubIdentity.objects.filter(login__iexact=login).select_related("user").first()
    if identity and identity.user.is_active and is_member(identity.user, conn.project.org):
        return identity.user
    return None


def _import_actor(conn, payload):
    """행위자: sender가 PM 사용자면 그 사람 → 프로젝트 첫 관리자 → 없으면 None."""
    sender = _user_for_sender(payload)
    if sender is not None:
        return sender
    return conn.project.owners.filter(is_active=True).order_by("id").first()
```

담당자는 배정된 멤버다. 행위자는 `_import_actor(...) or member` — 배정된 멤버가 있는 한 행위자가 비어 막히는
일은 없다. `RepoConnection.assignee_default` 열은 더 이상 읽지 않는다(설정 라운드에서 마이그레이션과 함께 지운다).

### 커밋 목록 상한

`TaskGitLink.commits`는 push마다 늘어난다. 최근 100건만 남기고 앞을 버린다.
`# ponytail: JSON 목록 100건. 커밋 전체 이력이 필요해지면 별도 표로.`

### `actor=None`의 경계

`_require_member(None, …)`가 검사를 건너뛰는 것은 **웹훅 경로에서만** 허용된다. `github/services.py` 밖에서 `actor=None`을 넘기는 코드를 만들지 않는다. 테스트 `test_actor_none_only_from_github_services`가 `grep`으로 고정한다.

### `tasks/services.py`의 행위자 확장

`_log`와 `transition`·`update_task`·`extend_due`에 `external_actor: str = ""`를 받는 인자를 더한다. `actor`가 `None`이면 `external_actor`가 채워져 있어야 한다.

```python
def _log(task, field, old, new, actor, source, token=None, note="", external_actor=""):
    ChangeLog.objects.create(
        ..., actor=actor, external_actor=external_actor[:100], source=source, ...
    )
```

`_require_member`는 `actor`가 `None`일 때 건너뛴다(웹훅은 조직 멤버가 아닌 사람이 일으킬 수 있다). 대신 **저장소 연결이 곧 권한의 근거**다.

```python
def _require_member(actor, project):
    if actor is None:      # GitHub 웹훅. 연결된 저장소가 권한의 근거다.
        return
    if not is_member(actor, project.org):
        raise ServiceError({"project": "이 팀의 멤버가 아닙니다."})
```

`web/views/common.py`의 `history_rows`는 `actor`가 없으면 `f"@{log.external_actor} (GitHub)"`를 쓴다.

---

## 10. Step 9. 저장소 연결 탭

```
projects/<int:project_id>/repo                      project_repo        GET·POST(연결)
projects/<int:project_id>/repo/disconnect           repo_disconnect     POST
projects/<int:project_id>/repo/settings             repo_settings       POST(규칙·라벨·기본 담당자)
projects/<int:project_id>/repo/issues/sync          repo_issues_sync    POST
projects/<int:project_id>/repo/issues/<int:number>/import   repo_issue_import   POST
projects/<int:project_id>/repo/events/<int:event_id>/link   repo_event_link     POST
```

`projects/_tabs.html`에 한 줄 더한다(`저장소 연결`).

저장소 주소 파싱. `.git` 링크를 그대로 받는다.

```python
REPO_RE = re.compile(r"(?:github\.com[:/])([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", re.I)


def parse_repo_url(url: str) -> str:
    m = REPO_RE.search((url or "").strip())
    if not m:
        raise ServiceError({"url": "GitHub 저장소 주소를 넣으세요. 예: https://github.com/owner/repo.git"})
    return f"{m.group(1)}/{m.group(2)}"
```

연결할 때 **그 사람이 볼 수 있는 저장소인지 확인한다.**

```python
def connect_repo(*, project, url, actor):
    if not is_member(actor, project.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    full_name = parse_repo_url(url)
    if not can_view_repo(actor, full_name):
        raise ServiceError({"url": "그 저장소에 접근할 수 없습니다. GitHub 연결과 권한을 확인하세요."})
    ...
```

열린 이슈 목록은 **설치 토큰**으로 읽는다. 연결할 때 한 번, 저장소 탭의 [새로고침]을 누를 때, 그리고 `issues` 웹훅이 올 때 갱신된다.

```python
def sync_issues(conn) -> int:
    """열린 이슈를 RepoIssue에 맞춘다. PR은 이슈 API에도 섞여 오므로 뺀다."""
    inst = conn.project.org.github
    token = client.installation_token(inst.installation_id)
    q = urlencode({"state": "open", "per_page": 100, "labels": conn.import_label or ""})
    seen = set()
    for item in client.request("GET", f"/repos/{conn.full_name}/issues?{q}", token) or []:
        if "pull_request" in item:
            continue
        seen.add(item["number"])
        RepoIssue.objects.update_or_create(
            connection=conn, number=item["number"],
            defaults={
                "title": item["title"][:300], "state": "open",
                "assignee_login": ((item.get("assignee") or {}).get("login")) or "",
                "labels": [lb["name"] for lb in item.get("labels", []) if isinstance(lb, dict)],
            },
        )
    conn.issues.filter(state="open").exclude(number__in=seen).update(state="closed")
    return len(seen)
```

`import_label`이 비어 있으면 라벨 없이 전부 받는다. 100건을 넘는 저장소는 첫 페이지만 본다.
`# ponytail: 첫 100건. 이슈가 그보다 많은 저장소가 생기면 페이지를 돈다.`

화면 구성은 `IMPL-PLAN-2.md` §6.4 표를 따른다. 이 단계에서 만드는 것은 저장소 카드 · **접근 팀 표(읽기 전용)** · 이슈 가져오기 · 자동 전환 규칙 5개 토글 · 최근 이벤트 표 · 참고 자료다.

접근 팀 표는 `GET /orgs/{org}/teams/{slug}/repos`가 아니라 **저장소 쪽에서** 읽는다. 설치 토큰으로 `GET /repos/{owner}/{repo}/teams`를 부르고, 실패하면(권한 부족) 표 대신 안내 한 줄을 둔다. 표 옆에는 항상 링크가 있다.

```html
<a class="btn sm" target="_blank" rel="noopener"
   href="https://github.com/{{ conn.full_name }}/settings/access">GitHub에서 변경</a>
```

**PM에서 팀의 저장소 권한을 바꾸지 않는다.** 그 API는 저장소 Administration 쓰기를 요구하고, 그 권한에는 저장소 삭제까지 딸려 온다.

---

## 11. Step 10. 패널 GitHub 블록

`tasks/_git.html`을 만들고 `_panel.html`의 체크리스트와 진행 메모 사이에 넣는다.

- 저장소 이름은 **프로젝트 연결에서** 파생한다(`repo_state`).
- 4단계 목록. 각 단계는 연결됨(`✓`, accent 배경) · 진행 중(`•`, `#E3F1F4`) · 없음(빈 원, 회색 제목).
- 없는 단계에 버튼: [이슈 연결](`RepoIssue` select) · [브랜치 연결](이름 입력) · [PR 열기](GitHub compare 링크, 새 창).
- PR 줄: 상태 배지(Open `#CFE3F7`/`#0B3A66`, Merged `#E7DBF7`/`#3B1A66`) · 커밋 수. PR이 없으면 "연결된 PR 없음 · 커밋 N건".
- 커밋 목록: sha(monospace) · 메시지 · "항목 N 체크".
- 체크리스트 항목 옆에 커밋 sha 칩을 붙이고 안내 한 줄을 둔다: "커밋 메시지에 `TASK-147:2`처럼 적으면 그 항목이 자동으로 체크됩니다."

[PR 열기]는 GitHub의 PR 작성 화면을 새 창으로 연다. 제목과 본문을 미리 채운다.

```python
def pr_compare_url(link) -> str:
    q = urlencode({
        "quick_pull": "1",
        "title": f"{link.task.number} {link.task.title}",
        "body": f"Closes #{link.issue_number}" if link.issue_number else "",
    })
    return f"https://github.com/{link.connection.full_name}/compare/{link.branch}?{q}"
```

본문에 `Closes #84`가 들어가므로 **머지하면 GitHub가 이슈를 닫는다.** PM이 이슈를 닫지 않는 이유가 이것이다. 닫은 주체도 머지한 사람으로 정확히 남는다.

수동 연결 엔드포인트는 `tasks/<id>/git/issue`·`/git/branch`·`/git/unlink` 셋이다.

---

## 12. 테스트

웹훅은 **서명을 만들어서** 보낸다. 실제 GitHub를 부르지 않는다. `client.request`·`installation_token`·`exchange_code`는 `monkeypatch`한다.

테스트 설정은 pytest-django의 `settings` 픽스처로 준다. `conftest.py`에 픽스처와 헬퍼를 둔다.

```python
@pytest.fixture
def gh(settings):
    settings.GITHUB_ENABLED = True
    settings.GITHUB_WEBHOOK_SECRET = "test-secret"
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()
    settings.GITHUB_APP_ID = "1"
    settings.GITHUB_APP_SLUG = "udally-test"


def signed(client, payload: dict, event: str, delivery: str = "d-1"):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/integrations/github/webhook", body, content_type="application/json",
        headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": event, "X-GitHub-Delivery": delivery},
    )
```

| 이름 | 확인 |
|---|---|
| `test_webhook_rejects_bad_signature` | 서명이 틀리면 401, `GitEvent`가 안 생긴다 |
| `test_webhook_rejects_session_and_token` | 세션 쿠키·API 토큰으로는 못 들어온다 |
| `test_webhook_ignores_unconnected_repo` | 202, 아무것도 안 바뀐다 |
| `test_event_dedupe_by_delivery` | 같은 delivery를 두 번 보내도 한 번만 적용 |
| `test_same_repo_two_projects` | 두 프로젝트가 같은 저장소를 가리켜도 각각 기록된다 |
| `test_branch_rule_sets_doing` | 브랜치 이름의 번호로 연결 + 진행 중 |
| `test_branch_rule_without_due_records_reason` | 기한 없으면 연결은 되고 상태는 그대로, 사유가 이벤트에 남는다 |
| `test_commit_rule_checks_item` | `TASK-147:2`가 체크리스트 2번을 체크 |
| `test_commit_rule_unmatched_records_not_linked` | 번호 없는 커밋은 "연결 안 됨" |
| `test_pr_open_sets_review` · `test_pr_merge_sets_done` | 규칙대로 |
| `test_rules_off_do_nothing` | 토글을 끄면 상태가 안 바뀌고 이벤트만 남는다 |
| `test_issue_import_creates_task_and_link` | 이슈에서 태스크가 생기고 1단계가 ✓ |
| `test_issue_closed_closes_task` | 연결 태스크가 완료로 |
| `test_actor_mapping_from_sender` | `sender.id`가 매칭되면 이력 행위자가 그 사람 |
| `test_external_actor_when_unmapped` | 매칭 안 되면 `@login`으로 남는다 |
| `test_backfill_actor_on_connect` | 연결하면 과거 이력이 채워진다 |
| `test_can_view_repo_filters_panel` | 권한 없는 사람의 패널에 브랜치·PR이 없다 |
| `test_repo_state_four_cases` | none·unlinked·denied·ok |
| `test_connect_repo_requires_access` | 접근 권한 없는 저장소는 연결 거부 |
| `test_parse_repo_url_variants` | `https`·`git@`·`.git` 유무 |
| `test_installation_token_read_only` | 설치 토큰을 쓰는 코드가 GET 말고 없다(`grep` 또는 호출 기록 검사) |
| `test_user_token_refreshes_when_expired` | 만료되면 refresh를 쓴다 |
| `test_github_disabled_hides_ui` | `GITHUB_ENABLED=False`면 탭·버튼이 없고 화면이 깨지지 않는다 |
| `test_webhook_not_throttled` | 같은 초에 61건을 보내도 429가 없다 |
| `test_sync_repos_only_own_orgs` | 다른 조직의 설치는 묻지 않는다 |
| `test_import_actor_fallback` | sender → 첫 관리자 → 없으면 `RepoIssue`만 |
| `test_import_assignee_from_issue` | 이슈 assignee가 조직 멤버면 담당자 |
| `test_sync_issues_skips_prs` | `pull_request` 키가 있는 항목은 안 들어온다 |
| `test_commits_capped_at_100` | 101번째 push에서 첫 커밋이 빠진다 |
| `test_actor_none_only_from_github_services` | `actor=None`을 넘기는 호출이 `github/` 밖에 없다(`grep`) |
| `test_event_occurred_at_from_payload` | 페이로드 시각이 `occurred_at`에 들어간다 |

## 13. 검증

```bash
cd core && uv run ruff check . && uv run pytest -q
uv run python manage.py makemigrations --check --dry-run
grep -rn "innerHTML\|PyJWT\|import jwt\|httpx\|requests" core/github core/web/static | grep -v node_modules
```

실제 저장소로 한 사이클을 돈다.

1. 조직 → GitHub → [앱 설치] → 설치가 기록된다
2. 프로필 → [GitHub 연결] → 접근 가능 저장소가 잡힌다
3. 프로젝트 → 저장소 연결에 `.git` 주소를 넣는다
4. `feat/TASK-<n>-x` 브랜치를 만든다 → 태스크가 진행 중
5. `TASK-<n>:1 …` 커밋을 push → 체크리스트 1번 체크
6. 패널 [PR 열기] → PR 생성 → 태스크가 검토 대기
7. 머지 → 태스크가 완료, 이슈가 함께 닫힘
8. 권한 없는 계정으로 보면 그 블록이 안 보인다

## 14. 완료 체크

- [ ] 새 의존성은 `cryptography` 하나
- [ ] 새 컨테이너·새 공개 호스트가 없다
- [ ] 앱 권한에 저장소 Administration이 없다
- [ ] 설치 토큰으로 쓰기를 하지 않는다
- [ ] 웹훅 서명을 `hmac.compare_digest`로 검증한다
- [ ] 상태 변경이 전부 `transition()`을 지난다
- [ ] 권한 없는 사람에게 git 정보가 안 보인다
- [ ] `GITHUB_ENABLED=False`에서도 앱이 정상 동작한다
