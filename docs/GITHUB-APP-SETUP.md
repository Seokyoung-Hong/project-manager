# GitHub App 등록 절차

이 문서 한 장으로 등록이 끝나야 한다. 다른 사람이나 다른 에이전트에게 맡길 때 이 파일만 준다. 코드 쪽 근거는 [GUIDE-V2-07](GUIDE-V2-07-github-read.md) §1·§2, 권한을 이렇게 정한 이유는 [IMPL-PLAN-2.md](IMPL-PLAN-2.md) §4.3에 있다.

---

## 0. 알아 둘 것

- 앱은 **PM 운영자의 GitHub 계정(또는 조직) 아래에 한 번** 등록한다. 산돌이 조직이든 다른 조직이든 나중에 "설치"만 하면 된다.
- **두 개** 만든다. 운영용과 개발용. 주소만 다르고 나머지는 같다. 아래 표의 `<SITE_URL>`에 각각 넣는다.

| | `<SITE_URL>` | 앱 이름 예 |
|---|---|---|
| 운영용 | `https://pm.<도메인>` | `udally` |
| 개발용 | `https://project.dorm.sio2.kr` | `sandol-pm-dev` |

- 개발 서버도 **공개 도메인 뒤에 둔다.** GitHub는 `localhost`로 웹훅을 보낼 수 없다. 리버스 프록시가 TLS를 끝내고 Django로 넘긴다(§4).
- 등록 화면에서 **Administration 권한을 고르지 않는다.** 이 권한은 저장소 삭제·설정 변경·브랜치 보호까지 딸려 온다. PM은 그 권한 없이 동작하도록 만들어져 있다.

---

## 1. 등록 화면 입력값

GitHub → 오른쪽 위 프로필 → Settings → Developer settings → GitHub Apps → **New GitHub App**

| 항목 | 값 |
|---|---|
| GitHub App name | 위 표의 이름. 전역 유일이라 겹치면 뒤에 숫자를 붙인다 |
| Homepage URL | `<SITE_URL>` |
| **Callback URL** | `<SITE_URL>/settings/github/callback` |
| "Expire user authorization tokens" | **켬** |
| "Request user authorization (OAuth) during installation" | **끔** (켜면 설치와 계정 연결 흐름이 섞여 PM 코드가 기대하는 두 갈래가 깨진다) |
| **Setup URL** | `<SITE_URL>/orgs/github/installed` |
| "Redirect on update" | **켬** |
| Webhook → Active | 켬 |
| **Webhook URL** | `<SITE_URL>/api/integrations/github/webhook` |
| Webhook secret | 아무 긴 문자열. `python -c "import secrets;print(secrets.token_urlsafe(32))"` |
| SSL verification | Enable |

### Permissions

**Repository permissions**

| 권한 | 값 | 쓰는 기능 |
|---|---|---|
| Contents | Read and write | 브랜치 만들기, 릴리스 → 결과 선반 |
| Issues | Read and write | 이슈 ↔ 태스크, 마일스톤 동기화 |
| Pull requests | Read | PR 상태·리뷰·검토 독촉·주간 지표 |
| **Checks** | **Read** | CI 배지·CI 실패 알림(라운드 8) |
| **Commit statuses** | **Read** | 외부 CI의 commit status(라운드 8) |
| **Webhooks** | **Read and write** | GitHub 알림 → Discord 채널 웹훅 자동 설정(§7, 라운드 8) |
| Metadata | Read (자동으로 켜져 있다) | |
| Administration | **No access** (기본값 그대로 둔다) | |
| Actions·Pull requests Write | **No access** | 쓰지 않는다 |

**Organization permissions**

| 권한 | 값 |
|---|---|
| Members | Read and write |

나머지는 전부 No access.

### Subscribe to events

Push · Create · Pull request · Issues · Membership · Team ·
**Pull request review** · **Check suite** · **Status** · **Milestone** · **Release**

(권한을 고른 뒤에야 체크할 수 있는 항목이 나타난다. Check suite는 Checks, Status는 Commit statuses 권한을
고른 뒤에 보인다. 라운드 8 이벤트 다섯 개는 `pull_request_review`·`check_suite`·`status`·`milestone`·`release`다.)

**이미 만든 앱을 라운드 8로 올릴 때**: 이벤트 구독을 먼저 켜고, Checks·Commit statuses·Webhooks 권한을 추가한다.
권한 추가는 설치 계정(조직·개인)마다 **재승인**이 필요하다 — 조직 관리자(개인 계정은 그 사람)에게 GitHub 알림이 가고,
승인 전에는 새 권한을 쓰는 기능만 꺼진 채 나머지는 그대로 돈다(§6). 승인하면 PM이 `new_permissions_accepted`
이벤트를 받아 점검 결과를 새로 묻는다. 확인은 PM **조직 → GitHub 탭의 "앱 권한 · 이벤트 점검" 표**에서 한다:
CI·리뷰·마일스톤·릴리스·Discord 웹훅 줄이 전부 켜짐이면 끝이고, 꺼진 줄에는 빠진 권한·구독이 적혀 있다.

`installation`과 `installation_repositories`는 **목록에 없다. 찾지 말 것.** 모든 GitHub App에 자동으로
전달되는 이벤트라 구독 항목이 아니다(목록의 "Installation target"은 설치 대상 개명으로 다른 이벤트다).
PM은 이 둘을 받아 설치와 저장소 추가·삭제를 반영한다.

### Where can this GitHub App be installed?

**Any account**

---

## 2. 만든 뒤 확보할 것

| 값 | 어디서 | `.env` 키 |
|---|---|---|
| App ID | 앱 General 페이지 상단 | `GITHUB_APP_ID` |
| 앱 슬러그 | Public link의 마지막 조각 `github.com/apps/<slug>` | `GITHUB_APP_SLUG` |
| Client ID | General 페이지 | `GITHUB_CLIENT_ID` |
| Client secret | General → "Generate a new client secret". **그때 한 번만 보인다** | `GITHUB_CLIENT_SECRET` |
| Private key | General 맨 아래 → "Generate a private key" → `.pem` 내려받음 | `GITHUB_APP_PRIVATE_KEY` |
| Webhook secret | 위에서 만든 값 | `GITHUB_WEBHOOK_SECRET` |
| 암호화 키 | 아래 명령으로 만든다 | `CREDENTIAL_KEY` |

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`.pem` 파일은 여러 줄이다. `.env`에는 한 줄로 넣되 줄바꿈 자리에 `\n`을 쓴다.

```bash
# 한 줄로 바꾸기
awk 'BEGIN{ORS="\\n"} 1' sandol-pm.private-key.pem
```

```
GITHUB_APP_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----\n
```

`.pem`·client secret·webhook secret은 `.env` 밖 어디에도 두지 않는다. 채팅·이슈·커밋에 붙여 넣지 않는다.

---

## 3. 조직에 설치 (조직 관리자)

앱 등록이 끝나고 PM이 떠 있으면, **PM 화면에서** 한다. GitHub 앱 페이지의 Install 버튼을 직접 누르지 않는다(그러면 PM이 어느 조직에 붙일지 모른다).

1. PM → 조직 → GitHub 탭 → [GitHub 앱 설치]
2. GitHub로 넘어가면 설치할 조직을 고르고 저장소 범위를 **All repositories**로 둔다(연결 안 한 저장소는 PM에 보이지 않으니 전체로 두어도 된다)
3. Install을 누르면 PM으로 돌아오며 "GitHub 앱을 설치했습니다"가 뜬다

각 사용자는 그 뒤 **프로필 → [GitHub 연결]**로 자기 계정을 잇는다. 연결하기 전에는 GitHub 정보가 보이지 않는다.

---

## 4. 개발 서버와 리버스 프록시

개발 서버도 공개 도메인 뒤에 둔다. 예: `https://project.dorm.sio2.kr`. 주소만 다를 뿐 §1의 입력값은 운영용과 같다. `<SITE_URL>`에 그 도메인을 넣으면 Callback·Setup·Webhook 주소가 모두 정해진다.

`localhost`로 두면 GitHub가 웹훅을 보낼 수 없어 브랜치·PR 자동 전환을 눈으로 확인할 수 없다. 공개 주소를 아직 못 붙였다면 웹훅만 빼고 시험한다. Webhook을 Active로 두되 주소는 아무 값이나 넣고, 이벤트 처리는 서명을 만들어 보내는 테스트 픽스처로만 확인한다(`GUIDE-V2-07` §12).

### 서버 쪽

`compose.yml`의 `web`은 `8000:8000`으로 열려 있다. 프록시가 다른 장비에 있어서 루프백으로는 닿지 않기 때문이다. **방화벽에서 프록시 장비 IP만 8000번을 열어 둔다.** 직접 오는 요청은 평문 HTTP이고 TLS를 거치지 않는다.

`.env`의 도메인 셋을 맞춘다. 안 맞추면 웹훅이 400으로 떨어지고, 더 찾기 어려운 쪽은 OAuth 콜백 주소를 `SITE_URL`로 만들기 때문에 계정 연결이 엉뚱한 데로 가는 것이다.

```
ALLOWED_HOSTS=project.dorm.sio2.kr,web
CSRF_TRUSTED_ORIGINS=https://project.dorm.sio2.kr
SITE_URL=https://project.dorm.sio2.kr
DEBUG=0
```

`web`을 빼면 안 된다. `mcp`·`discord` 컨테이너가 `http://web:8000`으로 직접 부른다. `DEBUG`는 외부에 열리는 순간 `0`이어야 한다. `1`이면 오류 화면에 설정값과 소스가 그대로 나온다.

### NginxProxyManager 쪽

| 항목 | 값 |
|---|---|
| Domain Names | `project.dorm.sio2.kr` |
| Forward Hostname / IP | Docker 호스트의 IP |
| Forward Port | `8000` |
| Websockets Support | 꺼도 된다 |
| SSL | Let's Encrypt 발급 + **Force SSL** 켬 |

NginxProxyManager는 `Host`를 원래 도메인 그대로 넘기고 `X-Forwarded-Proto`를 세워 준다. Django의 `SECURE_PROXY_SSL_HEADER`가 그것을 읽으므로 추가 설정이 없다. 커밋이 많은 push에서 413이 나면 Advanced에 `client_max_body_size 10m;`을 넣는다.

개발용 앱은 개발자 개인 계정 아래 만들고, 설치도 개인 계정이나 시험용 조직에 한다.

---

## 5. 확인

1. `.env`를 채우고 PM을 다시 띄운다. 조직 → GitHub 탭에 [GitHub 앱 설치] 버튼이 보이면 설정이 읽힌 것이다(값이 비어 있으면 탭 자체가 없다).
2. §3대로 설치한다. GitHub 조직 이름과 저장소 범위가 화면에 뜬다.
3. 프로필에서 [GitHub 연결]을 한다. "접근 가능 저장소 N개"가 뜬다.
4. 프로젝트 → 저장소 연결에 `https://github.com/<org>/<repo>.git`을 넣는다. "연결됨"이 뜨고 열린 이슈가 보인다.
5. 그 저장소에 `feat/TASK-<번호>-test` 브랜치를 만든다. 몇 초 안에 그 태스크가 진행 중으로 바뀌면 웹훅까지 통한 것이다. GitHub 앱 설정의 Advanced → Recent Deliveries에서 응답 코드를 볼 수 있다. 200이 아니면 그 화면에서 Redeliver로 다시 보낼 수 있다.

---

## 6. 나중에 바꿀 때

- **권한을 추가하면** 설치한 조직마다 승인을 다시 받아야 한다. 조직 관리자에게 GitHub 알림이 가고, 승인 전까지 새 권한은 동작하지 않는다.
- **Private key를 갈면** 옛 키는 즉시 무효다. `.env`를 바꾸고 PM을 다시 띄운다.
- **Webhook secret을 갈면** `.env`와 앱 설정을 같이 바꾼다. 어긋난 동안의 웹훅은 401로 버려지고, Recent Deliveries에서 다시 보낼 수 있다.
- **앱을 지우면** 모든 설치와 사용자 연결이 무효가 된다. PM 쪽 데이터는 남지만 GitHub 정보가 갱신되지 않는다.

---

## 7. GitHub 알림을 Discord 채널로 받기(선택, IMPL-PLAN-8 §10-2)

프로젝트 → 저장소 탭의 [GitHub 알림을 Discord 채널로 받기]는 봇이 프로젝트 Discord 채널에 웹훅을 만들고,
그 주소의 GitHub 호환 엔드포인트(`…/github`)를 **누른 사람의 GitHub 계정으로** 저장소 웹훅에 등록한다.
저장소 Settings → Webhooks에 손으로 넣던 일을 대신한다. 해제하면 양쪽 웹훅을 모두 지운다.

| 필요한 것 | 값 | 없으면 |
|---|---|---|
| GitHub 앱 Repository permissions → **Webhooks** | **Read and write** | 버튼 대신 이유가 보인다 |
| 누른 사람의 저장소 역할 | **Admin**(개인 계정 저장소는 소유자) | 누를 때 거절하고 이유를 보여 준다 |
| Discord 봇 권한 | **웹후크 관리(Manage Webhooks)**(채널 권한 덮어쓰기에서 막히지 않아야 함) | 버튼 대신 이유가 보인다 |
| 누른 사람의 Discord 서버 권한 | 웹후크 관리 | 웹에서 거절된다 |
| 프로젝트 | 저장소 연결 + Discord 프로젝트 채널(`/프로젝트채널`) | 버튼 대신 이유가 보인다 |

- Webhooks 권한은 **추가 권한이라 설치 계정(조직·개인)마다 재승인**이 필요하다(§6). 승인 전에는 이 기능만 꺼지고 나머지는 그대로 돈다.
- 사용자 토큰은 앱 권한 범위로 제한되므로, 사람이 저장소 Admin이어도 앱에 Webhooks 쓰기가 없으면 GitHub가 404·403으로 거부한다.
- 봇 권한은 봇을 다시 초대하거나 Discord 서버 설정 → 역할에서 봇 역할에 웹후크 관리를 준다.
- Discord 웹훅 주소는 토큰을 품으므로 PM은 저장하지 않는다. 화면에는 `…/webhooks/<id>/****/github`로만 보이고 로그에서도 가린다.
