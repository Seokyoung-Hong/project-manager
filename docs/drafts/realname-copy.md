# 계정 실명·조직 표시 이름 화면 문구 최종본

## 용어표와 금지어

| 표준 용어 | 뜻·사용 기준 | 금지어·피할 표현 |
| --- | --- | --- |
| 실명 | 계정에 하나 저장하는 본인의 실제 이름 | 본명, 조직 실명, 실명을 뜻하는 모호한 ‘이름’ |
| 표시 이름 | 계정의 기본 표시 이름. 조직 표시 이름을 비워 두면 사용합니다. 문장에서는 조직 표시 이름과 구분할 때 ‘계정의 표시 이름’이라고 씁니다. | 계정 이름, 프로필 이름 |
| 조직 표시 이름 | 해당 조직에서만 사용하는 이름 | 닉네임, 별명, 서버 별명, 조직 닉네임 |
| 실명으로 표시 | 조직에서 구성원 이름을 실명으로 표시하는 옵션 | 옵션을 뜻하는 ‘실명 필수’, ‘실명 입력’, ‘실명 받지 않음·선택·필수’ |
| 구성원 정보 | 조직이 정한 추가 정보 항목. 계정 실명은 포함하지 않습니다. | 실명을 구성원 정보 항목으로 설명하는 표현 |

설명·알림은 격식체로, 요청은 ‘…해 주세요’로 통일합니다. 버튼·탭·배지는 짧은 명사형을 사용합니다. Discord에도 같은 기준을 적용합니다. 키·명령 이름·변수 이름은 용어 금지 대상이 아닙니다.

근거: `docs/IMPL-PLAN-13-realname-org-nickname.md:267–277`(용어표), 같은 계획서 `:296–306`(공개 범위·화면 글), `:251–255`(Discord 동작), `core/accounts/services.py:28–47`(검증). 아래 위치는 COPY 주석 또는 해당 문자열 줄입니다. 동일 키의 여러 위치는 한 행에 모았습니다. 총 **30개 키**입니다.

## COPY 문구

| 키 | 위치 | 현재 임시 문구 | 최종 문구 |
| --- | --- | --- | --- |
| `real_name.required` | `core/accounts/services.py:40`; `core/web/forms.py:35` | 실명을 입력해 주세요. | 실명을 입력해 주세요. |
| `real_name.too_long` | `core/accounts/services.py:43` | 50자까지 입력할 수 있습니다. | 50자 이내로 입력해 주세요. |
| `real_name.invalid_chars` | `core/accounts/services.py:46–47` | 글자로만 입력해 주세요. 숫자와 기호는 쓸 수 없습니다. | 글자를 포함해 입력해 주세요. 공백·마침표(.)·하이픈(-)·작은따옴표(')·가운뎃점(·) 외의 기호와 숫자는 사용할 수 없습니다. |
| `real_name.gate_api` | `core/accounts/services.py:56–57` | 실명을 먼저 입력해 주세요: {url} | 유달리를 이용하려면 먼저 실명을 입력해 주세요: {url} |
| `real_name.gate_notice` | `core/web/templates/settings/profile.html:7–8` | 실명을 입력해야 유달리를 이용할 수 있습니다. 저장하면 보던 화면으로 돌아갑니다. | 유달리를 이용하려면 실명을 입력해 주세요. 저장하면 이전 화면으로 이동합니다. |
| `real_name.candidates` | `core/web/templates/settings/profile.html:12–16` | 조직마다 다른 실명이 입력되어 있었습니다. 맞는 이름을 고르거나 위 칸에 직접 입력해 주세요.<br>버튼: {{ c }}(으)로 저장 | 조직별로 입력한 실명이 서로 다릅니다. 본인의 실명을 선택하거나 위 입력란에 직접 입력해 주세요.<br>버튼: {{ c }} 저장 |
| `signup.real_name_help` | `core/web/forms.py:90–91` | 본인의 실제 이름을 입력해 주세요. 소속 조직의 관리자가 볼 수 있고, 실명으로 표시하는 조직에서는 구성원에게 이 이름이 보입니다. | 본인의 실명을 입력해 주세요. 소속 조직의 관리자는 이 실명을 볼 수 있습니다. 구성원 이름을 실명으로 표시하는 조직에서는 모든 구성원에게 이 실명이 표시됩니다. |
| `profile.real_name_help` | `core/web/forms.py:234–235` | 소속 조직의 관리자가 볼 수 있고, 실명으로 표시하는 조직에서는 구성원에게 이 이름이 보입니다. | 소속 조직의 관리자는 이 실명을 볼 수 있습니다. 구성원 이름을 실명으로 표시하는 조직에서는 모든 구성원에게 이 실명이 표시됩니다. 실명을 변경하면 해당 조직에 바로 반영됩니다. |
| `claim.real_name_admin` | `core/web/templates/auth/claim.html:5` | 입력한 실명은 {{ invite.org.name }} 조직 관리자에게 보입니다. | 가입하면 {{ invite.org.name }} 조직 관리자가 입력한 실명을 볼 수 있습니다. |
| `member_fields.show_real_name` | `core/web/templates/orgs/settings.html:35–36` | 구성원 이름을 실명으로 표시 | 구성원 이름을 실명으로 표시 |
| `member_fields.show_real_name_help` | `core/web/templates/orgs/settings.html:35–37` | 켜면 이 조직에서 모든 구성원의 조직 표시 이름이 계정 실명으로 바뀌고, 본인과 관리자 모두 조직 표시 이름을 바꿀 수 없습니다. 끄면 원래 조직 표시 이름으로 돌아갑니다. | 켜면 이 조직의 모든 구성원 이름이 실명으로 표시됩니다. 본인과 관리자 모두 조직 표시 이름을 변경할 수 없습니다. 끄면 저장된 조직 표시 이름이 다시 표시되며, 비어 있으면 계정의 표시 이름이 표시됩니다. |
| `member_fields.summary_show_real_name` | `core/orgs/member_info.py:116–117` | 실명으로 표시 켬 / 실명으로 표시 끔 | 실명으로 표시 켬 / 실명으로 표시 끔 |
| `members.real_name_missing` | `core/web/templates/orgs/teams.html:19` | 실명 미입력 | 실명 미입력 |
| `members.real_name_locked` | `core/web/templates/orgs/teams.html:20` | 배지: 실명으로 표시 중<br>도움말: 조직 설정에서 실명으로 표시를 켜 두어 조직 표시 이름을 바꿀 수 없습니다. | 배지: 실명으로 표시 중<br>도움말: 이 조직은 구성원 이름을 실명으로 표시하므로 조직 표시 이름을 변경할 수 없습니다. |
| `nickname.forbidden` | `core/orgs/services.py:366–367` | 본인 또는 조직 관리자만 조직 표시 이름을 바꿀 수 있습니다. | 본인 또는 조직 관리자만 조직 표시 이름을 변경할 수 있습니다. |
| `nickname.real_name_org` | `core/orgs/services.py:369–371` | 이 조직은 실명으로 표시하므로 조직 표시 이름을 바꿀 수 없습니다. | 이 조직은 구성원 이름을 실명으로 표시하므로 조직 표시 이름을 변경할 수 없습니다. |
| `nickname.saved` | `core/web/views/orgs.py:286` | 조직 표시 이름을 저장했습니다. | 조직 표시 이름을 저장했습니다. |
| `nickname.readonly_reason` | `core/web/templates/orgs/member_info.html:7–9` | 이 조직은 구성원 이름을 실명으로 표시합니다. 조직 표시 이름은 바꿀 수 없고, 실명은 설정 → 프로필에서 바꿉니다. | 이 조직은 구성원 이름을 실명으로 표시하므로 조직 표시 이름을 변경할 수 없습니다. 실명을 변경하려면 설정 → 프로필에서 수정해 주세요. |
| `nickname.help` | `core/web/templates/orgs/member_info.html:10–13` | 이 조직에서만 쓰는 이름입니다. 비워 두면 계정 표시 이름({{ user.display_name }})이 보입니다. | 이 조직에서만 사용하는 이름입니다. 비워 두면 계정의 표시 이름({{ user.display_name }})이 표시됩니다. |
| `org_tabs.member_info` | `core/web/templates/orgs/_tabs.html:15–16` | 구성원 정보 | 구성원 정보 |
| `org_history.nickname` | `core/web/views/orgs.py:546` | 조직 표시 이름 | 조직 표시 이름 |
| `ops_real_name` | `core/web/templates/ops/users.html:16`; `core/web/templates/ops/user.html:9` | 실명<br>상세 화면 빈 값: 입력 안 함 / 목록 빈 값: — | 실명<br>빈 값: 실명 미입력 |
| `nickname.dc_description` | `discord_service/discord_service/slash.py:620–621` | 이 서버 조직에서 쓰는 내 조직 표시 이름을 바꿉니다 (비우면 계정 표시 이름) | 이 서버에 연결된 조직에서 내 조직 표시 이름을 변경합니다. 비우면 계정의 표시 이름을 사용합니다. |
| `nickname.dc_param` | `discord_service/discord_service/slash.py:626–627` | 새 조직 표시 이름 (비우면 계정 표시 이름으로 돌아갑니다) | 새 조직 표시 이름을 입력해 주세요. 비우면 계정의 표시 이름을 사용합니다. |
| `nickname.dc_done` | `discord_service/discord_service/commands.py:167–168` | {org_name} 조직에서 쓰는 조직 표시 이름을 ‘{display_name}’(으)로 바꿨습니다. | {org_name} 조직의 표시 이름을 변경했습니다. 새 조직 표시 이름은 ‘{display_name}’입니다. |
| `nickname.dc_cleared` | `discord_service/discord_service/commands.py:170–171` | {org_name} 조직 표시 이름을 지웠습니다. 이제 계정 표시 이름 ‘{display_name}’(으)로 보입니다. | {org_name} 조직의 표시 이름을 삭제했습니다. 이제 계정의 표시 이름 ‘{display_name}’이 표시됩니다. |
| `nickname.dc_delay` | `discord_service/discord_service/commands.py:172–173` | 자동완성 목록에는 잠시 뒤 반영될 수 있습니다. | 변경한 이름은 잠시 후 반영될 수 있습니다. |
| `nickname.dc_help` | `discord_service/discord_service/messages.py:21,27` | • `/표시이름` — 이 서버 조직에서 쓰는 내 조직 표시 이름 바꾸기 | • `/표시이름` — 이 서버에 연결된 조직에서 내 조직 표시 이름을 변경합니다. |
| `nickname.dc_unbound` | `core/api/routers/discord.py:297–300` | Discord 서버가 조직에 연결되지 않았습니다. 조직 설정에서 서버를 연결해 주세요. | 이 Discord 서버에 연결된 조직이 없습니다. 조직 관리자에게 서버 연결을 요청해 주세요. |
| `nickname.dc_not_member` | `core/api/routers/discord.py:305–307` | 이 조직의 구성원이 아닙니다. 조직 초대를 받은 뒤 다시 시도해 주세요. | 이 서버에 연결된 조직의 구성원이 아닙니다. 조직 초대를 수락한 뒤 다시 시도해 주세요. |

## 적용 참고

- `{url}`, `{org_name}`, `{display_name}`은 기존 런타임 값의 문서 표기입니다. Django 템플릿 변수는 그대로 유지합니다.
- `real_name.too_long`과 `real_name.invalid_chars`는 조직 표시 이름 검증에도 쓰이므로 최종 문구에 ‘실명’을 넣지 않았습니다(`core/orgs/services.py:373`). 허용 기호 안내는 실제 검증과 일치합니다.
- `nickname.dc_delay`는 계획서의 반영 지연 안내를 유지하되 자동완성 목록을 특정하지 않습니다. `/members` 자동완성은 계정의 표시 이름을 사용하며 조직 표시 이름 변경 대상이 아닙니다(계획서 `:185,255`).
- `real_name.gate_notice`는 `next`가 없는 직접 프로필 방문에도 표시될 수 있으므로, 적용 시 저장 후 이동 문장을 `next`가 있는 경우에만 표시해야 정확합니다(`core/web/templates/settings/profile.html:7–8`; 계획서 `:222`). 이 문서는 코드 변경을 포함하지 않습니다.
- 검색 범위는 `core`, `discord_service`, `skills`, `mcp_server`입니다. `skills`와 `mcp_server`에는 이번 기능의 COPY 키가 없었습니다. COPY 키가 없는 인접 버튼·입력 제목·법률 문서 문구는 이번 표 범위에 포함하지 않았습니다.

## 추가 키 2

디자인 검토 후 추가된 4개 키입니다. 아래 위치는 `705c0e2` 기준이며, 이 절을 포함한 문구 목록은 총 **34개 키**입니다.

| 키 | 위치 | 현재 임시 문구 | 최종 문구 |
| --- | --- | --- | --- |
| `members.real_name_locked_link` | `core/web/templates/orgs/teams.html:10` | 조직 설정 → 구성원 정보에서 바꿉니다. | 실명으로 표시 설정을 변경하려면 조직 설정 → 구성원 정보로 이동해 주세요. |
| `member_fields.nav` | `core/web/templates/orgs/settings.html:13` | 구성원 정보·실명으로 표시 | 구성원 정보·실명으로 표시 |
| `member_fields.show_real_name_confirm` | `core/web/templates/orgs/settings.html:36` | 켜면 이 조직의 모든 구성원 이름이 실명으로 표시되고, 본인과 관리자 모두 조직 표시 이름을 바꿀 수 없습니다.<br>확인 버튼: 실명으로 표시 켜기 | 켜면 이 조직의 모든 구성원에게 실명이 표시됩니다. 본인과 관리자 모두 조직 표시 이름을 변경할 수 없습니다. 실명으로 표시를 켜시겠습니까?<br>확인 버튼: 실명으로 표시 켜기 |
| `member_fields.save` | `core/web/templates/orgs/settings.html:72` | 실명으로 표시·구성원 정보 항목 저장 | 실명으로 표시·구성원 정보 항목 저장 |

- `members.real_name_locked_link`는 앞 문장의 변경 제한 안내와 이어서 사용합니다. ‘조직 설정 → 구성원 정보’에 기존 링크를 유지하며, 변경 대상이 실명이 아니라 조직의 표시 설정임을 명시합니다.
- `member_fields.show_real_name_confirm`는 옵션을 끔에서 켬으로 저장할 때만 표시하는 확인 문구입니다. 공개 범위와 조직 표시 이름 변경 제한을 함께 안내합니다.
