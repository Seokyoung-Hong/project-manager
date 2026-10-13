# IMPL-PLAN-14 — 조직 설정 정보 구조 개편(내 정보 · 구성원 관리 · 탭별 저장)

> **판 v2: Fable 조건부 승인·사용자 결정 반영**(2026-10-14)
> - 사용자 결정: 약관은 바꾸지 않는다(판 올림 없음). 관리자가 고친 기록을 구성원 본인에게 보일 필요 없음 → **본인 통지 전부 v1 제외**.
> - Fable 필수 조건: ① 숨김 키 `notify.team_channel_weekly`는 탭 저장 키에서 뺀다(§3·§9) ② `member_info.url()` 변경과 `set_definition` 호출부(`orgs.py:690`)·관련 시험은 B 갈래로(§11) ③ 본인 통지 관련 항목 삭제, 관리자 감사 이력은 기존 `set_nickname` 방식(`target_type="org"`)으로 → **마이그레이션 0건**(§10).
> - Fable 권고 반영: `only=` 반환값 계약·트랜잭션 창·AI 요청 승인 경쟁(§9.1), 연동 탭은 필수 정보 관문 적용(§6), A0는 `member_info.html` 복사만(§11), nav 매핑·`#member-info` 앵커 갱신(§11), 영향 인원 계산 실패 시 문구 생략(§8.4), 시안 선택 단계(§14).

작성 2026-10-14. 승인: Fable. 입력: `docs/drafts/org-settings-ia-brief.md`(요구 1~5, 5는 정정본), 두 안(`org-settings-ia-claude.md`, `org-settings-ia-sol.md`), 상호 검토(`org-settings-ia-claude-review.md` §4, `org-settings-ia-sol-review.md` §5), 인벤토리 `docs/drafts/settings-inventory.json`(84개, 아래 번호는 이 파일 순서).
이 계획은 코드를 고치지 않았다. 줄번호는 작성 시점 `31e6165` 기준.

## 0. 요구와 결정

| # | 요구·결정 | 설계 한 줄 |
|---|---|---|
| R1 | 구성원 정보 카드가 이해 안 됨 → "구성원 관리" 그룹 | 구성원 관리 탭: 목록·패널·가입 전·초대·이름 표시 방식·요청할 정보 항목·팀/태그 정책 |
| R2 | 디스코드 서버 프로필처럼 "내 정보" 탭, 모든 구성원, 별도 페이지 없음 | 설정을 모든 구성원에게 연다. 기본 탭 = 내 정보. 옛 `member-info` 페이지 폐지 |
| R3 | 실명 표시 켜짐이면 조직 표시 이름 입력 없음 | 본인·관리자 화면 모두 칸 미출력 + 서버 거절(`set_nickname` 기존 검사), 값은 보존 |
| R4 | 저장 뒤 열린 섹션·스크롤 유지 | 이미 커밋(`3e2a7d8`, app.js). 저장 키에 탭(`location.search`)을 넣는 한 줄만 고침 |
| R5 | 관리자는 구성원이 이 조직에 낸 정보(nickname·info)만 수정. 실명·로그인 ID·계정 표시 이름·비밀번호 수정 불가 | 구성원 패널 폼은 `nickname`·`v-*`만 받는다. 실명은 열람만 |
| U1 | GitHub·Discord = "연동" 탭 하나(관리자, 기능 켜졌을 때만) | `?tab=integrations`, 섹션은 `github_enabled`·`discord_enabled`로 |
| U2 | 계정 실명 미입력자는 지금처럼 프로필로 | 실명 관문(`common/middleware.py:93-95`) 변경 없음. 내 정보 예외 없음 |
| U3 | 구성원용 업무 규칙 읽기 탭 없음 | 내 정보에 업무 규칙 메뉴 링크만 |
| U4 | `task.doing_limit*`는 태스크·프로젝트 | 태스크·프로젝트 / 진행·검토 |
| U5 | (v2) 관리자 대리 수정을 본인에게 알리지 않음 | 관리자 감사 이력만 남긴다(조직 관리 → 정책 변경 이력). 본인 화면·안내 없음 |
| U6 | 약관 변경 없음(v2) | 약관·처리방침 판 올림 없음 |
| D1 | 내 정보에서 본인 계정 실명 편집 | 두 검토 합의(Sol 안 채택). 라벨 "실명(계정 공통)", 다른 조직에도 반영 안내 |
| D2 | URL = `orgs/<id>/settings?tab=<코드>`(+`&member=<membership id>`) | Claude 검토 §3-4 채택. 뷰·URL 이름이 `org_settings` 하나라 `_OPEN_VIEWS`·관문 링크가 거의 안 바뀐다. Sol 검토가 요구한 조건(설정 셸 유지, 옛 GET/POST 구분 호환, 안전한 `next`)은 모두 충족 |

### 0.1 v1 제외(만들지 않는다)

- 동시 수정 충돌 감지(버전 필드·재확인 화면) — 마지막 저장 우선, 이력으로 추적.
- 선택지 삭제·형식 변경 시 "재입력 필요" 상태와 관문 확장 — `missing()` 의미 그대로. 저장 화면에 "비어 있는 사람 N명"만 안내.
- **관리자 대리 수정의 본인 통지 일체**(v2): 내 정보 기록·다음 접속 안내·Discord DM·확인 시각 필드.
- 약관·처리방침 변경(v2).
- 항목 정의 실시간(JS) 미리보기 — 미리보기는 저장된 정의를 서버가 그린다. 끌어 놓기 순서 변경도 없음(순서 숫자 칸 유지).
- 업무 규칙 화면의 "기본값 포함 전체 규칙" 표·허용 목록 — `enforced()` 그대로. 단 서버 주소 2개만 뺀다(§9.4).
- 탭 이동 시 미저장 경고(`beforeunload`).
- 구성원 정보 수정 API·MCP. 본인 수정 이력.
- 옛 `OrgMembership.real_name` 열 삭제(IMPL-PLAN-13 후속, 예정대로 orgs 0015).

## 1. 현재 상태(근거)

- 조직 메뉴 `orgs/_tabs.html:3-17`: 개요·팀·사람별 할 일 양·로드맵·업무 규칙·문서·회의록·전사·이슈·GitHub(관리자)·Discord(관리자)·구성원 정보(모두)·설정(관리자에게만 링크).
- 설정 뷰 `web/views/orgs.py:592-649`: 비관리자도 URL로 읽기 전용 열람 가능, POST는 비관리자면 조용히 무시. 한 폼이 전사 7개 빼고 전부 저장(`:599-614`).
- `orgs/services.py:88-119` `set_org_settings`는 설정을 **통째로 교체**, `:122-150` `set_locks`는 잠금 목록 **전체 교체**. 전사 서버 저장(`views/transcribe.py:132-147`)은 "나머지 키 유지" 방식으로 부분 저장을 이미 한다 — 이 방식을 일반화한다.
- `settings.clean()`(`orgs/settings.py:1209-1222`)은 `specs_for(scope)`(숨김 제외, `:1098-1103`)에 없는 키를 거절한다.
- 구성원 정보: 정의·실명 표시 한 폼(`settings.html:31-74`, 7열 표) → `org_member_fields`(`orgs.py:684-699`, `set_definition` 호출 `:690`) → `member_info.set_definition`(둘을 함께 교체, `member_info.py:78-114`). 본인 입력은 별도 페이지 `org_member_info`(`orgs.py:703-733`, `member_info.html`), 표시 이름은 따로 `member_nickname`.
- 구성원 목록·역할·태그·조직 표시 이름·가입 전 구성원·초대 링크: 조직 메뉴 "팀"의 관리자 분기(`orgs.py:201-260`, `teams.html:4-99`). 액션 뒤 `_member_redirect`(`orgs.py:293-297`)가 팀 화면으로 보낸다.
- 관문: 계정 실명 → 프로필(`middleware.py:93-95`), 조직 필수 정보 → `member_info.url()`(`member_info.py:203-204`)이 가리키는 곳. `_OPEN_VIEWS`(`middleware.py:48-51`)에 `org_settings`·`org_member_info`·`org_member_fields`·`member_nickname`.
- 변경 이력: `set_nickname`(`services.py:380-388`)이 `ChangeLog(target_type="org", field="nickname", 값="이름(user pk)")`을 남기고, 설정 화면 이력(`orgs.py:540-569`, `extra_labels` `:543-547`)이 보여 준다.
- 실명은 계정 공통(`accounts/models.py:17`). 프로필 저장은 `views/settings.py:48-56`(후보 정리·`forget_all`).

## 2. 탭·섹션 최종표

`?tab=` 코드 | 보는 사람 | 섹션 순서(섹션 id). 설정 셸 왼쪽(≤1100px는 위 칩 줄)에 "나" / "조직 관리" 두 묶음.

| 탭 | 코드 | 권한 | 섹션 |
|---|---|---|---|
| 내 정보 | `me`(기본) | 모든 구성원(관리자 포함) | 보이는 이름 미리보기 → 실명·조직 표시 이름 → 구성원 정보 → 링크(업무 규칙·환경설정·프로필) |
| 구성원 관리 | `members` | 관리자 | 구성원 목록(+패널 `&member=`) `list` → 가입 전 구성원 `pending` → 초대 링크·정책 `invites` → 이름 표시 방식 `names` → 요청할 정보 항목 `fields` → 팀·기술 태그 정책 `teams_tags` |
| 태스크·프로젝트 | `work` | 관리자 | 생성 기본값 `create` → 진행·검토 `flow` → 변경 사유 `reasons` → 기한 `due` → 프로젝트 권한 `project_perm` → 프로젝트 기본값 `project_default` |
| 알림 | `notify` | 관리자 | 기한 알림 `deadline` → 막힘·검토 알림 `nudge` → 주간 보고 `weekly` → 채널 게시 `channel` → GitHub 알림 `github` |
| AI | `ai` | 관리자 | AI 자동완성·이용 권한 `assist` → 조직 AI 연결·한도·시험 `org_ai` → 외부 AI 쓰기 허용 `ai_write` → 태스크 작업 권한 `ai_task` → 조직·요청 관리 권한 `ai_org` |
| 회의·전사 | `meeting` | 관리자 | 녹음 운영 `recording` → 공개·보관 `visibility` → 전사 용어 `glossary` → 전사 수단·이용 권한·전사 서버·연결 점검 `stt`(독립 폼) |
| 연동 | `integrations` | 관리자, 둘 중 하나라도 켜졌을 때 | GitHub `github`(앱 설치·상태 → 권한·이벤트 점검 → 저장소 연결 현황) → Discord `discord`(서버 → 팀·프로젝트 채널 → 알림 채널) |
| 조직 관리 | `org` | 관리자 | 저장 공간 `storage` → 정책 변경 이력 `history`(관리자 대리 수정 기록 포함) → 위험 구역 `danger` |

- AI 변경 요청 대기 카드(`_pending_requests.html`)와 "조직 기본값과 잠금" 안내(`settings.html:5-7`)는 관리자 탭 셸 위에 그대로.
- 탭 순서는 사용자가 정한 순서.

## 3. 설정 항목 84개 매핑

이 표가 `ORG_TABS` 계약(§10.1)의 원본이다. 키 이름·scope·overridable·hidden은 바꾸지 않는다.

| 번호 | 키 | 새 위치(탭 / 섹션) |
|---|---|---|
| 1~3 | `task.default_priority`, `task.priority_cap`, `task.require_done_when` | 태스크·프로젝트 / 생성 기본값 |
| 6~9 | `task.doing_limit`, `task.doing_limit_mode`, `task.review_required`, `task.self_review` | 태스크·프로젝트 / 진행·검토 (U4) |
| 10~13, 15 | `task.reopen_reason_required`, `task.cancel_reason_required`, `task.assignee_change_reason`, `task.due_change_reason`, `task.reject_reason_required` | 태스크·프로젝트 / 변경 사유 |
| 4, 5, 14 | `task.due_required`, `task.default_due_days`, `task.overdue_grace_days` | 태스크·프로젝트 / 기한 |
| 16~22 | `project.create_by`, `edit_by`, `status_by`, `archive_by`, `settings_by`, `roadmap_by`, `owner_required` | 태스크·프로젝트 / 프로젝트 권한 |
| 23~24 | `project.default_view`, `project.dev_tools` | 태스크·프로젝트 / 프로젝트 기본값 |
| 25~26 | `org.invite_days`, `org.invite_max_uses` | 구성원 관리 / 초대 링크·정책 (링크 목록 바로 아래 작은 폼) |
| 27~28 | `org.tags_by`, `org.team_join_self` | 구성원 관리 / 팀·기술 태그 정책 |
| 29 | `org.attachment_quota_mb` | 조직 관리 / 저장 공간 |
| 30 | `ai.enabled` | AI / 외부 AI 쓰기 허용 |
| 31~40 | `ai.create_task`, `edit_text`, `record_work`, `change_assignee`, `change_due`, `change_priority`, `priority_cap`, `transition_open`, `close_task`, `reopen_task` | AI / 태스크 작업 권한 |
| 41~45 | `ai.delete`, `manage_repo`, `manage_teams`, `create_request`, `answer_request` | AI / 조직·요청 관리 권한 |
| 46~49 | `notify.deadline_kinds`, `send_hour`, `overdue_repeat`, `quiet_weekend` | 알림 / 기한 알림 |
| 53~54 | `notify.blocked_escalate_days`, `notify.review_nudge_days` | 알림 / 막힘·검토 알림 |
| 50~52 | `notify.weekly_enabled`, `weekly_weekday`, `weekly_hour` | 알림 / 주간 보고 |
| 56 | `notify.team_channel_weekly`(**hidden**) | 알림 / 주간 보고에 **자리만 예약**. 화면·저장 키에 넣지 않는다(§9.2) |
| 55 | `notify.project_channel_events` | 알림 / 채널 게시 |
| 57~58 | `notify.github_channel_events`, `notify.github_dm` | 알림 / GitHub 알림 (연동 탭 GitHub 섹션에 이리로 오는 링크) |
| 59, 61, 62 | `meeting.recording_enabled`, `max_minutes`, `leave_grace_s` | 회의·전사 / 녹음 운영 |
| 60, 63 | `meeting.audio_keep_days`, `meeting.default_visibility` | 회의·전사 / 공개·보관 |
| 64 | `meeting.glossary` | 회의·전사 / 전사 용어 |
| 70~71 | `meeting.member_pc`, `meeting.transcribe_level` | 회의·전사 / 전사(위쪽 정책 행, 현 `POLICY_KEYS`) |
| 65~69 | `meeting.stt_url`, `stt_model`, `stt_timeout_s`, `stt_api_key`, `openai_api_key` | 회의·전사 / 전사(고급 접기 + 연결 시험·적용) |
| 72, 76 | `assist.enabled`, `assist.org_level` | AI / AI 자동완성·이용 권한 |
| 73~75, 77 | `assist.org_url`, `org_model`, `org_api_key`, `org_daily_limit` | AI / 조직 AI 연결·한도·시험(`_assist_test.html` 포함) |
| 78~84 | `user.*` 7개 | 조직 설정 밖 — 계정 설정 → 환경설정 그대로. 내 정보에 링크만 |

검산: 24 + 4 + 1 + 16 + 13 + 13 + 6 + 7 = 84. org scope 77개 = **화면·저장 키 76개 + 숨김 1개(56)**. `ORG_TABS`에는 77개가 정확히 한 번씩 있고, `tab_keys()`는 숨김을 걸러 76개만 돌려준다 — 둘 다 시험으로 고정(§12).

## 4. 설정 정의 밖 항목 매핑

| 대상 | 현재 | 새 위치 |
|---|---|---|
| 본인 실명(`User.real_name`, 계정 공통) | 프로필 | 내 정보에서도 본인 편집(D1). 프로필도 같은 원본. 관리자는 패널에서 열람만 |
| 계정 표시 이름·로그인 ID·비밀번호 | 프로필·계정 | 그대로. 패널에 표시 이름·아이디 보조 줄(읽기) |
| 실명으로 표시(`member_fields.show_real_name`) | 설정 하단 카드(정의와 한 폼) | 구성원 관리 / 이름 표시 방식 — 독립 폼 |
| 구성원 정보 항목 정의(`member_fields.fields`) | 같은 카드 7열 표 | 구성원 관리 / 요청할 정보 항목 — 카드+미리보기(§8.4), 독립 폼 |
| 본인 nickname·info | `member-info` 별도 페이지 | 내 정보, 한 폼 원자 저장 |
| 관리자 nickname·info | 팀 화면 표(nickname 인라인, info 읽기) | 구성원 패널에서 편집(신규) |
| 구성원 목록·역할·스킬 태그·Discord 연결·제거 | 팀 화면 관리자 표 | 구성원 관리 / 목록 + 패널. 업무량은 패널에 "사람별 할 일 양" 링크만(목록에서 미완료 열 제거) |
| 가입 전 구성원 추가·개인 초대 링크 | 팀 화면 | 구성원 관리 / 가입 전 구성원(개인 초대 버튼은 패널에도) |
| 조직 초대 링크(만들기·폐기) | 팀 화면 "초대 링크" 카드 | 구성원 관리 / 초대 링크·정책(25~26과 함께) |
| 팀 목록·새 팀·팀 관리, 구성원용 팀 화면 | 팀 메뉴 | 그대로. 관리자 팀 화면 위에 "구성원·초대는 설정 → 구성원 관리" 한 줄 |
| 정책 변경 이력 | 설정 하단(비관리자도 열람) | 조직 관리 / 정책 변경 이력(관리자만). 관리자 대리 수정 기록도 여기 |
| 위험 구역(조직 삭제) | 설정 하단 | 조직 관리 / 위험 구역 |
| 조직 GitHub(`org_github`) | 조직 메뉴 탭 | 연동 / GitHub. "내 GitHub 연결" 카드(`github.html:57-68`)는 삭제하고 "본인 연결은 프로필에서" 한 줄(프로필에 이미 있음, `settings/profile.html:45-55`) |
| 이슈(`org_issues`) | 조직 메뉴 | 그대로 |
| 조직 Discord(`org_discord`) | 조직 메뉴 탭 | 연동 / Discord |
| 전사 서버(`transcribe?view=server`) | 전사 메뉴 관리자 보기 | 회의·전사 / 전사 |
| 전사 작업 목록·재시도·취소·적용 | 전사 메뉴 | 그대로(관리자 "전사 서버" 전환 버튼 제거, 설정 링크 한 줄) |
| 업무 규칙 문서(`org_governance`) | 조직 메뉴 | 그대로. "설정에서 바꾸기"는 `?tab=work` |

## 5. URL·옛 주소·조직 메뉴

| 주소 | 처리 |
|---|---|
| `GET orgs/<id>/settings?tab=X[&member=M]` | 설정 셸 + 그 탭만 서버 렌더. 탭 값이 없거나 모르는 값 → `me`. 관리자 탭을 비관리자가 요청 → 302 `?tab=me`(데이터 안 그림) |
| `POST orgs/<id>/settings?tab=X[&section=S]` | 설정 키 탭의 부분 저장(§9). 비관리자 → 403(지금은 조용히 무시). 성공·실패 모두 303 `?tab=X` |
| `GET orgs/<id>/member-info` (`org_member_info`) | `org_or_404` 확인 뒤 302 `settings?tab=me` |
| `POST orgs/<id>/member-info` | **내 정보 저장 엔드포인트**(새 폼도 여기로). 옛 폼(`v-*`만)도 같은 처리로 호환 — 안 보낸 키는 그대로 둔다. 303 `?tab=me` |
| `POST orgs/<id>/member-fields` | `part=names` / `part=fields` / 없음(옛 폼, 둘 다). 303 `?tab=members#settings-members-<part>` |
| `POST orgs/memberships/<m>/profile` (신규 `member_profile`) | 관리자 패널 저장(nickname·info) |
| `POST orgs/memberships/<m>/nickname` (`member_nickname`) | 남겨 둔다(옛 폼 호환). 돌아가는 곳만 바뀜 |
| 역할·태그·제거·개인 초대·가입 전 추가·초대 만들기/폐기 | URL 그대로. `_member_redirect` → `settings?tab=members&member=<m>`(구성원 단위) 또는 `?tab=members`. 비관리자는 지금처럼 개요로 |
| `GET orgs/<id>/github`, `GET orgs/<id>/discord` | 302 `settings?tab=integrations#settings-integrations-github` / `…-discord`. 설치 콜백·연결·해제·채널·알림 POST의 `redirect("org_github"/"org_discord")`는 새 주소로 직접 |
| `GET orgs/<id>/transcribe?view=server` | 관리자면 302 `settings?tab=meeting#settings-meeting-stt`, 아니면 작업 목록 |
| `POST orgs/<id>/transcribe/server`, `settings/stt-test`, `settings/stt-apply` | 그대로(이미 부분 저장). 저장 뒤 303 `settings?tab=meeting#settings-meeting-stt` |
| 개요 "시작하기" 링크(`orgs.py:114,123`) | `?tab=integrations` |
| `member_info.url(org_id)` | `reverse("org_settings")+"?tab=me"` — 웹 관문·API 403 `profile_required`·`X-Blocked-Orgs`·Discord 안내 문구가 함께 바뀐다(**B 갈래**, §11) |
| `next` | 기존 `_safe_next`만 사용(내부 경로) |

조직 메뉴(`_tabs.html`) 최종: 개요 · 팀 · 사람별 할 일 양 · 로드맵 · 업무 규칙 · 문서 · 회의록 · 전사 · 이슈(GitHub 연결 시) · 설정(**모든 구성원**). GitHub·Discord·구성원 정보 탭 삭제.

## 6. 권한·관문

| 대상 | 규칙 |
|---|---|
| 설정 진입 | 모든 구성원. 셸은 관리자에게만 관리자 탭 링크를 그린다 — 그러나 **권한은 뷰가 매 요청 `can_admin`으로 검사**(GET은 `?tab=me`로 돌림, POST는 403). 숨김에 의존하지 않는다 |
| 관리자 탭 응답 | 비관리자 응답에 관리자 탭 HTML·설정 값·이력·서버 주소가 없어야 한다(시험) |
| 내 정보 저장 | 대상은 항상 `request.user`의 그 조직 멤버십. 요청 본문의 대상 식별자는 받지 않는다 |
| 구성원 패널 | `member` 파라미터·`membership_id`는 이 조직 멤버십만(아니면 404). 관리자만 |
| 계정 실명 미입력 | 지금처럼 프로필(U2). 미들웨어 변경 없음 |
| 조직 필수 정보 미입력 | 관문이 `?tab=me`로 보낸다. `org_settings`가 `_OPEN_VIEWS`에 있으므로 미입력 관리자도 관리자 탭을 연다(현행 유지 — 항목 정의를 고칠 수 있어야 한다). **예외: `integrations` 탭은 관문 적용** — `org_settings` 뷰가 `tab=integrations`이고 `member_info.missing(본인)`이면 `?tab=me`로 돌린다(연동 설치·해제 POST 엔드포인트는 원래 `_OPEN_VIEWS` 밖이라 이미 막힌다). 패널 저장(`member_profile`)·역할 등 구성원 액션도 열지 않는다(멤버십 기준 관문) |
| 관리자 대리 수정 후 | 대상의 관문은 `missing()`으로 그대로 판정. 필수를 다 채우면 그 구성원은 풀린다(실명 관문은 별개) |

## 7. 내 정보 탭

```
① 이 조직에서 보이는 이름: [석영]   (display_for(user, org) — 저장 값 기준)
② 실명(계정 공통) [홍석영]  "모든 조직에 반영됩니다. 조직 관리자는 열람만 합니다."
   조직 표시 이름 [석영]    (실명으로 표시 켜짐이면 이 칸 자체를 그리지 않고
                              "이 조직은 구성원 이름을 실명으로 표시합니다" 한 줄)
③ 구성원 정보(조직이 정한 항목) — _member_info_fields.html
   필수 미입력이면 위에 경고: "필수 항목을 입력해야 ○○ 조직을 쓸 수 있습니다"
   항목이 없으면 "이 조직은 구성원 정보를 받지 않습니다."
   [내 정보 저장]   ← ②③ 한 폼, POST orgs/<id>/member-info
④ 업무 규칙 ↗ · 알림·첫 화면(환경설정) ↗ · 계정 표시 이름·비밀번호(프로필) ↗
```

- **원자 저장** `member_info.save_me(membership, *, real_name=None, nickname=None, values=None)`: 세 값을 모두 먼저 검증(실명 `clean_real_name` 필수, nickname `clean_real_name(required=False)`, info는 기존 `save` 규칙 — 필수 포함)하고 오류를 한꺼번에 모은다. 오류가 하나라도 있으면 아무것도 쓰지 않는다. 통과하면 한 트랜잭션에서 실명(`accounts.services.set_real_name`)·nickname(`set_nickname`)·info를 쓴다. `None` = 안 보냄 = 그대로(옛 폼 호환).
- 실명으로 표시 켜짐 + nickname이 현재 값과 다르게 오면 `set_nickname`이 거절(기존 문구 `COPY:nickname.real_name_org`). 폼에는 칸이 없으므로 정상 흐름에선 안 온다.
- 오류: 같은 탭을 다시 그리고 칸 옆에 표시(리다이렉트 없이 render — 입력 보존). 성공: 303 `?tab=me`. 저장 전 관문에 막혀 있다가 이번 저장으로 풀리면 303 `org_detail` + "이제 조직을 쓸 수 있습니다"(현행 흐름).
- 실명 변경은 이력 없음(IMPL-PLAN-13 결정 5). `forget_all()` 호출(프로필과 같은 함수 공유).
- `context.py:86`의 "막힌 조직 배너 숨김" 조건을 `org_settings`(tab=me)에도 적용.

## 8. 구성원 관리 탭

### 8.1 구성원 목록
- 열: 이름(이 조직 표시 + 가입 전 배지 + 입력 필요 배지) · 역할 · 소속 팀 · Discord 연결. 행 전체가 `?tab=members&member=<m>` 링크. 구성원 정보 값·미완료 수 열은 뺀다.
- 실명 보조 줄(관리자 열람, IMPL-PLAN-13 §6.2)은 목록에 유지.
- ≤700px: 사람 카드 목록, 패널은 목록 대신 전체 화면 + [← 구성원 목록].

### 8.2 구성원 패널(`&member=`)
| 영역 | 내용 | 편집 |
|---|---|---|
| 머리 | 보이는 이름, 계정 표시 이름·아이디, 가입 전 배지 | — |
| 계정 공통 | 실명(없으면 "실명 미입력") + "본인만 바꿀 수 있는 계정 정보입니다" | 불가 |
| 이 조직에 제공한 정보 | 조직 표시 이름(실명 표시 켜짐이면 미출력) + `_member_info_fields.html` | `POST member_profile` |
| 조직 안 역할 | 역할, 스킬 태그, 소속 팀(읽기) | 기존 `member_role`·`member_tags` |
| 초대·제거 | 가입 전이면 개인 초대 링크, 조직에서 제거(마지막 관리자 보호 유지) | 기존 엔드포인트 |
| 업무량 | "사람별 할 일 양에서 보기" 링크 | — |

- `member_info.admin_save(membership, actor, *, nickname=None, values=None)`: `require_admin`, 형식·길이·선택지 검사만(필수 비움 허용). nickname은 `set_nickname`(기존 org 이력 그대로). info가 바뀌면 `ChangeLog(target_type="org", target_id=org.pk, field="member_info", new_value="홍길동(12): 학번, 전화")` 1건 — `set_nickname`과 같은 "이름(user pk)" 방식, **값은 남기지 않고 항목 이름만**. 이 기록은 조직 관리 → 정책 변경 이력에 보인다(`_org_settings_history`의 `extra_labels`에 `"member_info": "구성원 정보 수정"` 한 줄). 본인 통지 없음(U5).
- 뷰는 `nickname`·`v-*`만 읽는다. `real_name`·`display_name`·`username`이 와도 무시(시험).
- 저장 뒤 관문이 풀렸으면 "이제 이 구성원은 조직을 쓸 수 있습니다", 아니면 "필수 항목 N개가 아직 비었습니다".

### 8.3 가입 전 구성원 · 초대 링크·정책
- 가입 전 추가 폼, 조직 초대 링크 표·만들기·폐기를 `teams.html`에서 그대로 옮긴다.
- 25~26은 초대 표 아래 작은 폼(`section=invites`, 부분 저장).
- 가입 전 구성원의 정보도 패널에서 같은 방식으로 고친다(인계 뒤 값은 같은 멤버십에 남음).

### 8.4 이름 표시 방식(`names`) · 요청할 정보 항목(`fields`)
- **이름 표시 방식** 독립 폼(`part=names`): 라디오 두 개 "구성원이 정한 조직 표시 이름"(기본) / "실명". 미리보기 한 줄 "목록·담당자 칸에 이렇게 보입니다: 석영 / 홍석영"(관리자 본인 기준). 켤 때만 확인창(기존 `data-confirm-if`).
- **요청할 정보 항목** 독립 폼(`part=fields`). 첫 문장: "구성원에게 받을 질문을 만드는 곳입니다. 답은 구성원이 내 정보에서 쓰고, 관리자는 구성원 패널에서 고칩니다."
  - 민감정보 금지 경고(약관 제6조 링크)는 머리에 그대로.
  - 항목 = 카드: 이름 · 형식(짧은 글 200자 / 긴 글 2000자 / 선택지 — 각 한 줄 설명과 예시) · 선택지 칸(형식이 선택지일 때만, CSS `:has()`로 표시 — JS 없음) · 도움말("입력칸 아래 회색 글로 보입니다") · 필수 스위치 · 순서 숫자 · 삭제.
  - 필수 스위치 옆: "지금 N명이 비워 두었습니다. 필수로 저장하면 입력할 때까지 조직을 쓸 수 없습니다(관리자 포함)." N = `member_info.empty_counts(org)`(항목 id → 빈 멤버십 수, 가입 전 제외). **계산이 실패하면(예외) 이 문구만 생략**하고 화면은 그린다. 꺼져 있던 필수를 켜고 저장하면 확인창(`data-confirm-if="[data-was-optional]:checked"`).
  - 새 항목: 끝의 접힌 "＋ 항목 추가" 카드(지금의 빈 줄 방식을 카드로 — JS 없음).
  - 제약 표시: 항목 30개, 이름 50자, 선택지 50자×30개.
  - 미리보기: 오른쪽(≤850px 아래) "구성원에게 보이는 모습" — 저장된 정의로 `_member_info_fields.html`을 `disabled`로 그린다.
- `set_definition(org, actor, *, show_real_name=None, fields=None)`로 바꾼다. `None` = 기존 값 유지, 행 잠금(`select_for_update`) 뒤 다시 읽어 합친다. 이력 `member_fields` 요약은 그대로.

### 8.5 팀·기술 태그 정책
- 27~28 작은 폼(`section=teams_tags`). 팀 실행 동선은 팀 메뉴에 남는다.

## 9. 탭별 부분 저장

### 9.1 서비스
- `set_org_settings(org, data, actor, *, only=None, …) -> Organization`: `only`(키 묶음)를 주면 `Organization`을 `select_for_update`로 다시 읽고, **`data` 중 `only` 안의 키만 `clean`**한 뒤 `old` 중 `only` 밖의 키(잠금 `_locked`, 숨김 키 값 포함)를 **검사 없이 그대로** 합친다(옛 숨김 키를 다시 `clean`하면 거절되므로). `only=None`은 지금과 같은 통째 교체(API `PUT /settings`·AI 요청 승인 계약 유지).
- **반환값 계약**: 잠금 뒤 다시 읽은 새 객체를 돌려준다. 호출자는 이어지는 `set_locks`에 반드시 **반환값**을 넘긴다(`org = set_org_settings(...); set_locks(org, ...)`). 들고 있던 옛 `org`를 넘기면 방금 쓴 값을 덮는다.
- `set_locks(org, keys, actor, *, only=None)`: `only`가 있으면 `old_locked - only ∪ (keys ∩ only)`. `set_locks`는 이미 행을 다시 읽는다(`services.py:126-127`).
- 감수하는 창: 뷰에서 두 함수는 **각자의 트랜잭션**이라 그 사이에 다른 저장이 끼어들 수 있다. 각 함수가 행을 다시 읽으므로 값은 잃지 않고, 최악은 잠금 한 칸이 마지막 저장 우선이 되는 정도 — v1 감수.
- 알려진 한계: AI 요청 승인(`orgs/requests.py:107`)은 `req.proposed`로 **통째 교체**한다. 요청 만든 뒤 관리자가 다른 탭을 저장했다면 승인이 그 값을 되돌릴 수 있다(지금도 같은 문제). v1은 기록만 하고 고치지 않는다.
- 전사 서버 저장(`views/transcribe.py:137-143`)은 `only=STT_KEYS`로 바꿔도 되고 그대로 둬도 된다 — D 갈래 재량.

### 9.2 뷰
- 저장 키 = 서버가 `tab_keys(tab, section)`으로 구한다. 클라이언트가 보낸 키 목록은 믿지 않는다. **`tab_keys()`는 숨김 키를 거른다**(56 `notify.team_channel_weekly`가 들어가면 `clean()`이 거절해 알림 탭 저장이 항상 실패한다). 화면 행 목록도 같은 함수로 만든다. `meeting` 탭 본 폼은 `stt` 섹션(별도 폼, 기존 엔드포인트)을 뺀 키만.
- 체크박스 끔 = 폼에 없음 문제는 `_settings_from_post(post, 그 탭 spec만)`이 해결(지금 코드 그대로).

### 9.3 R4(스크롤 유지)
- `app.js` 저장 키 `"udally.settingsView:" + location.pathname` → `+ location.search`. 섹션은 지금처럼 `details.settings-section[id]`, id는 `settings-<tab>-<section>`.

### 9.4 업무 규칙 화면
- `settings.enforced()`가 `meeting.stt_url`·`assist.org_url`을 건너뛰게 한 줄(구성원이 서버 주소를 보지 않게). 키는 이미 가려진다(`display`의 secret 처리). 나머지는 그대로(0.1).

## 10. 데이터 모델·마이그레이션·이력

- **마이그레이션 0건.** 모델 변경 없음. 리허설·되돌리기 마이그레이션 없음.
- 이력: 조직 정책·이름 표시·항목 정의·조직 표시 이름·관리자 대리 수정 모두 `ChangeLog(target_type="org")` 한 곳 → 조직 관리 → 정책 변경 이력(관리자만). 대리 수정은 "이름(user pk): 항목 이름들"만, 값 없음(§8.2).

### 10.1 A0 계약(선행 갈래가 만들고 이후 바꾸지 않는 이름)

```python
# core/orgs/settings.py
ORG_TABS: list[tuple[str, str, list[tuple[str, str, tuple[str, ...]]]]]
#   (탭 코드, 탭 라벨 COPY 키, [(섹션 코드, 섹션 라벨 COPY 키, 키들)]) — §3 표 그대로(숨김 56 포함 77개). 키 없는 섹션은 ()
ADMIN_TABS = ("members", "work", "notify", "ai", "meeting", "integrations", "org")
def tab_keys(tab: str, section: str | None = None) -> tuple[str, ...]   # 숨김 제외(76개 범위)

# core/orgs/services.py
set_org_settings(org, data, actor, *, only=None, note="", source="web", token=None) -> Organization  # 반환값을 set_locks에
set_locks(org, keys, actor, *, only=None)

# core/orgs/member_info.py   (url()은 B가 바꾼다 — §11)
save_me(membership, *, real_name=None, nickname=None, values=None)   # ServiceError(errors: {필드: 문구})
admin_save(membership, actor, *, nickname=None, values=None)
set_definition(org, actor, *, show_real_name=None, fields=None)      # A0가 바꿀 때 유일한 호출부 orgs.py:690은 B가 맞춘다(§11)
empty_counts(org) -> dict[str, int]

# core/accounts/services.py
set_real_name(user, value)   # clean + 후보 정리 + save + forget_all (프로필 뷰도 이걸 쓰게)

# 뷰 쪽 맥락 함수(A0가 빈 껍데기로 만들고 각 갈래가 채운다)
web/views/org_members.py: members_ctx(request, org, member_id) -> dict ; member_profile(request, membership_id)
web/views/github.py:      github_ctx(request, org) -> dict
web/views/discord.py:     discord_ctx(request, org) -> dict
web/views/transcribe.py:  stt_ctx(request, org) -> dict
# 템플릿
orgs/_member_info_fields.html   # 입력칸 반복(rows, errors, disabled) — member_info.html 루프를 복사(원본 삭제는 B)
# CSS 클래스(B가 app.css에 씀): .settings-shell .settings-tabs .member-split .member-panel .field-card
```

`set_definition` 시그니처 변경은 호출부와 짝이 맞아야 하므로 처리 방법을 하나로 정한다: **A0는 새 키워드 시그니처를 추가하되 옛 위치 인자 호출(`set_definition(org, flag, fields, actor)`)도 받는 한 판 호환**을 둔다(인자 개수로 분기 한 줄). B가 `orgs.py:690`을 새 형태로 바꾸고 호환 분기를 지운다. 이로써 A0 병합 시점에 core 전체 시험이 통과한다.

## 11. 구현 갈래

선행 **A0**가 병합된 뒤 B·C·D·F 병렬. 동시에 **디자인 시안**(§14)을 A0와 병렬로 만들어 사용자가 고른 뒤 B·C가 화면을 구현한다. 파일은 갈래끼리 겹치지 않는다.

| 갈래 | 모델 | 파일(독점) | 내용 |
|---|---|---|---|
| A0 계약·서비스 | Opus | `orgs/settings.py`, `orgs/services.py`, `orgs/member_info.py`(**`url()`은 건드리지 않음**), `accounts/services.py`, `web/views/settings.py`(프로필이 `set_real_name` 사용), 껍데기 `web/views/org_members.py`, `github.py`·`discord.py`·`transcribe.py`의 `*_ctx` 껍데기 함수 추가만, `orgs/_member_info_fields.html`(신규 — `member_info.html` 루프 복사), `orgs/test_settings_ia.py`(신규) | §9.1·§9.4·§7 저장·§8.2 서비스·§8.4 서비스. 서비스 시험. 병합 조건: core 전체 시험 통과 |
| B 셸·내 정보·설정 탭 | Opus | `web/views/orgs.py`(org_settings 탭·연동 탭 관문·org_member_info·org_member_fields part·**`:690` set_definition 새 형태**·`_member_redirect`·시작하기 링크·org_teams 관리자 표 제거·`extra_labels` 한 줄), `orgs/member_info.py`의 **`url()` 한 줄**(A0 병합 뒤 B 소유), `web/urls.py`, `web/context.py`(**`:36` nav 매핑**·`:86` 배너 조건), `common/middleware.py`(바뀔 것 없으면 손대지 않음), `orgs/settings.html`(셸, **`:13` `#member-info` 앵커 제거**), `orgs/settings/_me.html`·`_keys_tab.html`·`_org.html`(신규), `orgs/_tabs.html`, `orgs/member_info.html`(**삭제**), `orgs/governance.html`(링크), `static/app.js`, `static/app.css`, `web/test_org_settings_tabs.py`(신규), 기존 시험 **`orgs/test_member_profile.py:58,88,104,151,156,177,208,213`·`web/test_realname_screens.py:90,104-111`** 주소 갱신 | §2 셸·§5·§6·§7·§9.2·§9.3 |
| C 구성원 관리 | Opus | `web/views/org_members.py`, `orgs/settings/_members.html`·`_member_panel.html`·`_member_fields_editor.html`(신규), `orgs/teams.html`(구성원·초대 카드 제거, **`:10` 실명 안내의 `#member-info` 링크를 `?tab=members#settings-members-names`로**, 안내 한 줄), `web/test_org_members.py`(신규) | §8. CSS는 계약 클래스만 쓰고 B에 요청 |
| D 연동·전사 이동 | Sonnet | `web/views/github.py`, `web/views/discord.py`, `web/views/transcribe.py`, `orgs/github.html`·`orgs/discord.html`(→ `orgs/settings/_github.html`·`_discord.html`로 본문 이동 후 삭제), `orgs/transcribe.html`(전환 버튼 제거), `orgs/settings/_stt.html`(신규), `notes/test_transcription.py:268-277`·`orgs/test_stt_test.py:104` 갱신, GitHub·Discord 화면 시험 주소 갱신 | §4 연동·전사, §5 옛 주소 |
| F 문구 | Sol | `docs/COPY-14.md`(신규, 키→문구) | §13. 구현 갈래는 초안 문구로 넣고 F가 확정본으로 바꾼다(B·C·D 병합 뒤 한 번). 약관·처리방침은 손대지 않는다 |

- 겹침 규칙: `orgs.py`는 B만. C의 뷰는 새 파일 `org_members.py`. `app.css`는 B만(C·D는 필요한 CSS를 B에 요청). `urls.py`는 B만(C의 `member_profile` 경로도 B가 넣는다 — 계약 이름). `member_info.py`는 A0가 끝낸 뒤 `url()` 한 줄만 B.
- 의존: B의 셸은 C·D의 `*_ctx`를 부른다. A0 껍데기 덕에 병렬로 돌고, 통합 브랜치에서 전부 합친 뒤 전체 시험.

## 12. 시험 계획

`uv run pytest`(core). 로컬 python 직접 실행 금지.

- **A0** `orgs/test_settings_ia.py`: ① `ORG_TABS` 키 = org scope 77개 정확히 한 번씩, user 키 없음 ② `tab_keys()` 합집합 = 76개, `notify.team_channel_weekly` 없음, `tab_keys("notify")`로 저장 성공 ③ `only=` 저장이 다른 탭 값·잠금·`_locked`·**저장돼 있던 숨김 키 값**을 보존, 이력은 바뀐 키만, 반환값이 새 객체 ④ `only=None`은 기존 통째 교체(API 시험 그대로 통과) ⑤ `set_definition` 한쪽만 바꿔도 다른 쪽 보존, 옛 위치 인자 호출도 동작 ⑥ `save_me`: 실명 오류면 nickname·info도 안 바뀜, 세 오류 동시 반환, `None` 키 유지, 실명 표시 조직 nickname 변경 거절 ⑦ `admin_save`: 비관리자 거절, 다른 조직 멤버십 거절, 필수 비움 허용, 이력 1건(`target_type="org"`, `field="member_info"`)에 항목 이름은 있고 값 문자열은 없음, 필수 채우면 `missing()` False ⑧ `empty_counts` 가입 전 제외 ⑨ `enforced()`에 서버 주소 없음 ⑩ `set_real_name` 뒤 실명 표시 조직 이름 즉시 반영.
- **B** `web/test_org_settings_tabs.py`: 구성원 GET → 내 정보만, 관리자 탭 링크·이력·설정 값 없음 / `?tab=work` 구성원 → 302 `?tab=me` / 구성원 POST `?tab=work` → 403 / 관리자 `work` 저장이 `notify` 값·잠금 보존 / 관리자 `notify` 저장 성공(숨김 키 회귀) / 옛 `member-info` GET 302, POST(`v-*`) 저장 + 303 / 관문 리다이렉트·API `profile_required` url·`X-Blocked-Orgs` url이 `?tab=me` / 필수 미입력 관리자: `?tab=members` 열림, `?tab=integrations` → `?tab=me` / 실명 미입력 → 프로필(변경 없음 확인) / 실명 표시 켜짐이면 내 정보 HTML에 `name="nickname"` 없음 / 정책 변경 이력에 "구성원 정보 수정" 행 / 조직 메뉴에 GitHub·Discord·구성원 정보 탭 없음, 설정 링크는 구성원에게도.
- **C** `web/test_org_members.py`: `&member=`가 다른 조직 멤버십이면 404 / 패널 POST에 `real_name` 넣어도 `User.real_name` 불변 / 비관리자 패널 POST 403 / 실명 표시 켜짐이면 패널에 nickname 칸 없음·POST 거절 / 역할·태그·제거 뒤 `?tab=members&member=`로 복귀 / `part=names`·`part=fields` 각각 다른 쪽 보존, 옛 폼(part 없음) 호환 / 필수 영향 인원 문구 숫자, `empty_counts` 예외 시 문구 없이 렌더 / 팀 화면에 구성원 표·`#member-info` 없음.
- **D**: `org_github`·`org_discord` GET 302, 기능 꺼지면 연동 탭 없음·`?tab=integrations` → `me` / 연결·해제·채널 POST 뒤 새 주소 / `transcribe?view=server` 302, 비관리자는 작업 목록 / 전사 서버 저장이 다른 설정 보존 / 연동 탭에 "내 GitHub 연결" 카드 없음.
- **전체**: `uv run pytest`(core), `discord_service`, `mcp_server`, `skills/test_pm.py` — 관문 url 문자열이 바뀌므로 MCP·스킬·봇 시험의 `/member-info` 기대값 grep 후 갱신.

## 13. 문구(COPY 키 — 초안, 최종은 Sol)

용어는 IMPL-PLAN-13 §8(실명·표시 이름·조직 표시 이름·실명으로 표시·구성원 정보) 그대로. 금지어 grep: "구성원 정보 페이지", "member-info", "GitHub 탭", "Discord 탭".

| 키 | 초안 |
|---|---|
| `org_settings.tab.me` … `.org` | 내 정보 / 구성원 관리 / 태스크·프로젝트 / 알림 / AI / 회의·전사 / 연동 / 조직 관리 |
| `org_settings.group.me`, `.group.admin` | 나 / 조직 관리 |
| `org_settings.section.*` | §2 섹션 이름 |
| `org_settings.forbidden` | 조직 관리자만 볼 수 있는 탭입니다. 내 정보로 이동했습니다. |
| `org_settings.integrations_blocked` | 내 정보의 필수 항목을 먼저 입력해 주세요. |
| `org_settings.saved_tab` | {탭} 설정을 저장했습니다. |
| `org_history.member_info` | 구성원 정보 수정 |
| `me.preview` | 이 조직에서는 {이름}(으)로 보입니다. |
| `me.real_name_help` | 모든 조직에 반영됩니다. 조직 관리자는 열람만 할 수 있습니다. |
| `me.saved`, `me.unblocked` | 내 정보를 저장했습니다. / 이제 {조직}을(를) 쓸 수 있습니다. |
| `me.links` | 업무 규칙 보기 · 알림·첫 화면 설정 · 계정 표시 이름·비밀번호 |
| `members.panel.account_note` | 실명과 계정 표시 이름은 본인만 바꿀 수 있는 계정 정보입니다. |
| `members.panel.saved`, `.unblocked`, `.still_missing` | 저장했습니다. / 이제 이 구성원은 조직을 쓸 수 있습니다. / 필수 항목 {n}개가 아직 비었습니다. |
| `members.names.*` | 이름 표시 방식 / 구성원이 정한 조직 표시 이름 / 실명 / 미리보기 문장 / 켜기 확인 |
| `members.fields.intro` | 구성원에게 받을 질문을 만드는 곳입니다. 답은 구성원이 내 정보에서 쓰고, 관리자는 구성원 패널에서 고칩니다. |
| `members.fields.kind_help.text/long/choice` | 한 줄 입력, 200자(예: 학번) / 여러 줄, 2000자(예: 가능한 시간) / 목록에서 하나 고름 |
| `members.fields.required_impact` | 지금 {n}명이 비워 두었습니다. 필수로 저장하면 입력할 때까지 조직을 쓸 수 없습니다(관리자 포함). |
| `members.fields.preview_title`, `.add` | 구성원에게 보이는 모습 / 항목 추가 |
| `teams.members_moved` | 구성원·초대는 설정 → 구성원 관리에서 관리합니다. |
| `integrations.github.own_link` | 내 GitHub 계정 연결은 프로필에서 합니다. |
| `transcribe.server_moved` | 전사 서버 설정은 설정 → 회의·전사에 있습니다. |

## 14. 디자인 — 시안 선택 후 구현

- DESIGN.md 토큰·컴포넌트만(새 컴포넌트 없음: 탭은 기존 `.tabs`/칩, 카드·`details`·`notice`·`badge`). AI Slop 금지 규칙 준수.
- **시안(구현 전, 필수)**: 시안 2개를 단일 HTML로 만든다. 각 시안에 ① 내 정보 탭 ② 구성원 관리 목록 + 구성원 패널 ③ 항목 정의 카드 + 미리보기를 **데스크톱·모바일(390px)** 두 너비로 담는다. **A0와 병렬**로 만들고 사용자에게 보여 **사용자가 고른 뒤** B·C가 그 안으로 화면을 구현한다(메모 "디자인 시안은 사용자가 고른다" — 모델 검토보다 먼저). 보관: `design-concepts/org-settings/`.
- 구현 후: Astra(Sol 워커가 데스크톱·모바일 390px 화면을 찍음) + Claude 독립 검토. 대상: 설정 셸 두 너비, 내 정보(실명 표시 켬/끔·관문 상태), 구성원 패널(데스크톱 분할·모바일 전체 화면), 항목 카드·미리보기, 연동 탭. 의견이 갈리면 Astra 판단, 갈린 점은 보고.

## 15. 배포 순서

1. A0 ∥ 시안 2개 → 사용자 선택. A0 병합(core 전체 시험 통과).
2. B·C·D 병렬 → 통합 브랜치 → F 문구 확정 반영 → 전체 시험.
3. 코드 검토 Sol + Opus 독립, 디자인 검토 Astra + Claude. 수정 반복은 Claude.
4. Fable 승인.
5. 배포: DB 백업 → 배포(마이그레이션 없음) → 운영에서 화면 시험(운영 = 최종 시험 서버).
6. 되돌리기: 코드 이전 판만. 데이터 모양이 바뀌지 않으므로 DB 조치 없음.

## 16. 남은 미결정·확인 불가

- 미결정: 없음(약관은 사용자 결정으로 변경 없음, 본인 통지는 v1 제외).
- 확인 불가: 운영 데이터의 필수 항목 영향 인원, 실제 사용자 반응. 이번 계획에서 동작 검증은 하지 않았다.
