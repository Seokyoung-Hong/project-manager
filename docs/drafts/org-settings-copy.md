# 조직 설정 개편 — 사용자 노출 문구 최종본

기준: HEAD da73091, 변경 범위 bcbe63c..da73091의 core. 기존 임시 키 99개와 설명 보완용 제안 키 7개, 총 106개입니다. 아래 ‘추가 키’ 절에서 HEAD e2bf160 기준 신규 COPY 키 7개를 확정하여, 최종 문구는 총 113개입니다. 코드 수정·커밋 없이 문구만 확정한 문서이며, 화면 반영은 별도 작업입니다.

기획 근거: docs/IMPL-PLAN-14-org-settings-ia.md:53(탭·섹션), :162(내 정보), :189(구성원 패널), :208(이름 표시·항목 정의), :306(문구); docs/drafts/org-settings-ia-brief.md:8(사용자 요구), :35(관리자 권한).

## 용어와 반영 규칙

- ‘실명’과 ‘계정 표시 이름’은 계정 공통 정보입니다. ‘조직 표시 이름’과 ‘구성원 정보’는 이 조직에서 사용하는 정보입니다. 관리자는 조직 표시 이름·구성원 정보 값만 수정할 수 있습니다.
- ‘이름 표시 방식’은 조직 안에서 어떤 이름을 표시할지 정하는 설정이고, ‘요청할 정보 항목’은 구성원에게 받을 질문을 만드는 설정입니다. 두 섹션은 각각 저장합니다.
- ‘구성원이 정한 조직 표시 이름’은 관리자의 수정 권한을 가리므로 ‘조직 표시 이름’으로 통일합니다. 실명 표시를 끄면 보관된 조직 표시 이름을 다시 사용하며, 값이 없으면 계정 표시 이름을 사용합니다.
- 관리자의 수정 기록은 관리자만 보는 정책 변경 이력에 남습니다. 본인에게 기록이 표시되지 않는다는 뜻이며, 수정된 값 자체를 본인이 볼 수 없다는 뜻은 아닙니다.
- 설명은 격식체, 요청은 ‘…해 주세요’, 버튼과 제목은 명사형입니다. 확인창은 ‘…하시겠습니까?’로 끝납니다.
- 중괄호는 현재 템플릿·뷰의 동적 값입니다. 문구 내 ‘ / ’는 제목·설명·예시 또는 확인창 본문·확인 버튼의 경계이며 화면에 슬래시를 추가하라는 뜻이 아닙니다. 실제 줄바꿈과 요소 배치는 기존 화면을 따릅니다.
- 위치는 da73091 기준입니다. 하나의 키가 복수 요소를 가리키면 해당 요소 전체의 최종 문구를 함께 적었습니다. me.no_fields는 미리보기뿐 아니라 내 정보의 같은 빈 상태 문구에도 적용합니다.
- 신규 COPY 표기 55종 중 와일드카드 org_settings.section.members.*는 아래 실제 섹션 키 6개로, members.fields.kind_help.text/long/choice는 형식별 키 3개로 풀었습니다. COPY_DRAFT의 탭·섹션 42개와 변경 서비스에 남은 nickname.real_name_org도 포함했습니다.

## 코드에 있는 임시 키·문구

| 키 | 위치(파일:줄) | 현재 임시 문구 | 최종 문구 |
|---|---|---|---|
| org_settings.tab.me | core/orgs/settings.py:1157 | 내 정보 | 내 정보 |
| org_settings.tab.members | core/orgs/settings.py:1158 | 구성원 관리 | 구성원 관리 |
| org_settings.tab.work | core/orgs/settings.py:1159 | 태스크·프로젝트 | 태스크·프로젝트 |
| org_settings.tab.notify | core/orgs/settings.py:1160 | 알림 | 알림 |
| org_settings.tab.ai | core/orgs/settings.py:1161 | AI | AI |
| org_settings.tab.meeting | core/orgs/settings.py:1162 | 회의·전사 | 회의·전사 |
| org_settings.tab.integrations | core/orgs/settings.py:1163 | 연동 | 연동 |
| org_settings.tab.org | core/orgs/settings.py:1164 | 조직 관리 | 조직 관리 |
| org_settings.section.me.name | core/orgs/settings.py:1165 | 실명·조직 표시 이름 | 이름 |
| org_settings.section.me.info | core/orgs/settings.py:1166 | 구성원 정보 | 구성원 정보 |
| org_settings.section.me.links | core/orgs/settings.py:1167 | 다른 설정 | 다른 설정 |
| org_settings.section.members.list | core/orgs/settings.py:1168 | 구성원 목록 | 구성원 목록 |
| org_settings.section.members.pending | core/orgs/settings.py:1169 | 가입 전 구성원 | 가입 전 구성원 |
| org_settings.section.members.invites | core/orgs/settings.py:1170 | 초대 링크·정책 | 초대 링크·정책 |
| org_settings.section.members.names | core/orgs/settings.py:1171 | 이름 표시 방식 | 이름 표시 방식 |
| org_settings.section.members.fields | core/orgs/settings.py:1172 | 요청할 정보 항목 | 요청할 정보 항목 |
| org_settings.section.members.teams_tags | core/orgs/settings.py:1173 | 팀·기술 태그 정책 | 팀·기술 태그 정책 |
| org_settings.section.work.create | core/orgs/settings.py:1174 | 생성 기본값 | 생성 기본값 |
| org_settings.section.work.flow | core/orgs/settings.py:1175 | 진행·검토 | 진행·검토 |
| org_settings.section.work.reasons | core/orgs/settings.py:1176 | 변경 사유 | 변경 사유 |
| org_settings.section.work.due | core/orgs/settings.py:1177 | 기한 | 기한 |
| org_settings.section.work.project_perm | core/orgs/settings.py:1178 | 프로젝트 권한 | 프로젝트 권한 |
| org_settings.section.work.project_default | core/orgs/settings.py:1179 | 프로젝트 기본값 | 프로젝트 기본값 |
| org_settings.section.notify.deadline | core/orgs/settings.py:1180 | 기한 알림 | 기한 알림 |
| org_settings.section.notify.nudge | core/orgs/settings.py:1181 | 막힘·검토 알림 | 막힘·검토 알림 |
| org_settings.section.notify.weekly | core/orgs/settings.py:1182 | 주간 보고 | 주간 보고 |
| org_settings.section.notify.channel | core/orgs/settings.py:1183 | 채널 게시 | 채널 게시 |
| org_settings.section.notify.github | core/orgs/settings.py:1184 | GitHub 알림 | GitHub 알림 |
| org_settings.section.ai.assist | core/orgs/settings.py:1185 | AI 자동완성·이용 권한 | AI 자동완성·이용 권한 |
| org_settings.section.ai.org_ai | core/orgs/settings.py:1186 | 조직 AI 연결·한도 | 조직 AI 연결·한도 |
| org_settings.section.ai.ai_write | core/orgs/settings.py:1187 | 외부 AI 쓰기 허용 | 외부 AI 쓰기 허용 |
| org_settings.section.ai.ai_task | core/orgs/settings.py:1188 | 태스크 작업 권한 | 태스크 작업 권한 |
| org_settings.section.ai.ai_org | core/orgs/settings.py:1189 | 조직·요청 관리 권한 | 조직·요청 관리 권한 |
| org_settings.section.meeting.recording | core/orgs/settings.py:1190 | 녹음 운영 | 녹음 운영 |
| org_settings.section.meeting.visibility | core/orgs/settings.py:1191 | 공개·보관 | 공개·보관 |
| org_settings.section.meeting.glossary | core/orgs/settings.py:1192 | 전사 용어 | 전사 용어 |
| org_settings.section.meeting.stt | core/orgs/settings.py:1193 | 전사 | 전사 수단·이용 권한 |
| org_settings.section.integrations.github | core/orgs/settings.py:1194 | GitHub | GitHub |
| org_settings.section.integrations.discord | core/orgs/settings.py:1195 | Discord | Discord |
| org_settings.section.org.storage | core/orgs/settings.py:1196 | 저장 공간 | 저장 공간 |
| org_settings.section.org.history | core/orgs/settings.py:1197 | 정책 변경 이력 | 정책 변경 이력 |
| org_settings.section.org.danger | core/orgs/settings.py:1198 | 위험 구역 | 위험 구역 |
| org_settings.back | core/web/templates/orgs/settings.html:16 | ‹ 설정 | ‹ 설정 |
| github_self_link | core/web/templates/orgs/settings/_github.html:55 | 본인 GitHub 계정 연결은 프로필에서 합니다. | 개인 GitHub 계정은 프로필에서 연결할 수 있습니다. |
| me.preview | core/web/templates/orgs/settings/_me.html:3 | 이 조직에서는 {이름}(으)로 보입니다. | 이 조직에서 표시되는 이름: {이름} |
| me.real_name_help | core/web/templates/orgs/settings/_me.html:9 | 모든 조직에 반영됩니다. 조직 관리자는 열람만 할 수 있습니다. | 실명은 모든 조직에서 공통으로 사용하는 계정 정보입니다. 변경하면 실명으로 표시하는 모든 조직에 반영됩니다. 조직 관리자는 실명을 열람할 수 있으며, 수정은 본인만 할 수 있습니다. |
| nickname.readonly_reason | core/web/templates/orgs/settings/_me.html:13 | 이 조직은 구성원 이름을 실명으로 표시합니다. 조직 표시 이름은 쓰지 않습니다. | 이 조직은 구성원 이름을 실명으로 표시합니다. 조직 표시 이름은 사용하지 않으며, 본인과 관리자 모두 변경할 수 없습니다. |
| nickname.help | core/web/templates/orgs/settings/_me.html:18 | 이 조직에서만 사용하는 이름입니다. 비워 두면 계정의 표시 이름({계정 표시 이름})이 표시됩니다. | 이 조직에서 표시되는 이름입니다. 조직 관리자도 변경할 수 있습니다. 비워 두면 계정 표시 이름({계정 표시 이름})이 표시됩니다. |
| me.links | core/web/templates/orgs/settings/_me.html:29 | 업무 규칙 보기 / 알림·첫 화면 설정 / 계정 표시 이름·비밀번호 | 업무 규칙 보기 / 알림·첫 화면 설정 / 계정 표시 이름·비밀번호 |
| members.fields.intro | core/web/templates/orgs/settings/_member_fields_editor.html:2 | 구성원에게 받을 질문을 만드는 곳입니다. 답은 구성원이 내 정보에서 쓰고, 관리자는 구성원 패널에서 고칩니다. | 이 조직에서 구성원에게 요청할 정보 항목을 만드는 곳입니다. 예를 들어 항목 이름을 ‘학번’으로 정하면 내 정보에 ‘학번’ 입력칸이 생깁니다. 구성원은 내 정보에서 값을 입력하며, 관리자는 구성원 목록에서 이름을 눌러 값을 수정할 수 있습니다. 이름 표시 방식은 별도 설정입니다. |
| members.fields.required_confirm | core/web/templates/orgs/settings/_member_fields_editor.html:6 | 필수 항목을 비워 둔 구성원은 입력할 때까지 이 조직을 쓸 수 없습니다(관리자 포함). 저장하시겠습니까? / 필수로 저장 | 필수로 저장하면 이 항목을 입력하지 않은 구성원은 값을 입력할 때까지 이 조직을 사용할 수 없습니다. 관리자에게도 적용됩니다. 필수 항목으로 저장하시겠습니까? / 필수로 저장 |
| members.fields.help_help | core/web/templates/orgs/settings/_member_fields_editor.html:21 | 도움말 / 예: 숫자 8자리로 적어 주세요. / 입력칸 아래에 회색 글로 보입니다. | 도움말 / 예: 숫자 8자리로 입력해 주세요. / 구성원이 값을 입력할 때 참고할 설명입니다. 내 정보의 입력칸 아래에 표시됩니다. |
| members.fields.required_impact | core/web/templates/orgs/settings/_member_fields_editor.html:24 | 지금 {n}명이 비워 두었습니다. 필수로 저장하면 입력할 때까지 조직을 쓸 수 없습니다(관리자 포함). | 현재 이 항목을 입력하지 않은 구성원은 {n}명입니다. 필수로 저장하면 이 구성원들은 값을 입력할 때까지 이 조직을 사용할 수 없습니다. 관리자에게도 적용됩니다. |
| members.fields.add | core/web/templates/orgs/settings/_member_fields_editor.html:31 | ＋ 항목 추가 | ＋ 항목 추가 |
| members.fields.save | core/web/templates/orgs/settings/_member_fields_editor.html:44 | 정보 항목 저장 / 저장 전까지 구성원 화면과 오른쪽 미리보기는 바뀌지 않습니다. | 정보 항목 저장 / 저장 안내는 추가 키 members.fields.save_hint의 최종 문구로 분리합니다. |
| members.fields.preview_title | core/web/templates/orgs/settings/_member_fields_editor.html:47 | 구성원에게 보이는 모습 / 내 정보 탭 | 구성원에게 보이는 입력 항목 / 내 정보 탭 |
| me.no_fields | core/web/templates/orgs/settings/_member_fields_editor.html:49 | 이 조직은 구성원 정보를 받지 않습니다. | 이 조직에서 요청하는 구성원 정보 항목이 없습니다. |
| members.panel.back | core/web/templates/orgs/settings/_member_panel.html:4 | ‹ 구성원 목록 | ‹ 구성원 목록 |
| members.panel.blocked | core/web/templates/orgs/settings/_member_panel.html:10 | 필수 항목 {n}개가 비어 있어 이 구성원은 조직을 쓸 수 없습니다. | 필수 항목 {n}개가 입력되지 않아 이 구성원은 이 조직을 사용할 수 없습니다. |
| members.panel.account | core/web/templates/orgs/settings/_member_panel.html:13 | 계정 공통 / 열람만 | 계정 공통 정보 / 열람만 가능 |
| members.panel.account_note | core/web/templates/orgs/settings/_member_panel.html:18 | 실명과 계정 표시 이름은 본인만 바꿀 수 있는 계정 정보입니다. | 실명·계정 표시 이름·아이디는 모든 조직에서 공통으로 사용하는 계정 정보입니다. 조직 관리자는 이곳에서 열람만 할 수 있습니다. 실명과 계정 표시 이름은 본인만 수정할 수 있습니다. |
| members.panel.org_info | core/web/templates/orgs/settings/_member_panel.html:22 | 이 조직에 제공한 정보 | 이 조직에 제공한 정보 |
| members.panel.real_name_org | core/web/templates/orgs/settings/_member_panel.html:25 | 이 조직은 실명으로 표시하므로 조직 표시 이름 칸이 없습니다. | 이 조직은 구성원 이름을 실명으로 표시합니다. 조직 표시 이름은 사용하지 않으며, 본인과 관리자 모두 변경할 수 없습니다. 아래 구성원 정보는 수정할 수 있습니다. |
| members.panel.admin_note | core/web/templates/orgs/settings/_member_panel.html:28 | 관리자는 필수 항목을 비워 둔 채로도 저장할 수 있습니다. 고친 기록은 조직 관리 → 정책 변경 이력에 남습니다. | 관리자는 필수 항목이 비어 있어도 저장할 수 있습니다. 필수 항목이 비어 있으면 이 구성원은 이 조직을 사용할 수 없습니다. 수정 기록은 조직 관리 → 정책 변경 이력에 남으며 관리자만 볼 수 있습니다. 구성원 본인에게 수정 기록은 표시되지 않습니다. |
| members.panel.save | core/web/templates/orgs/settings/_member_panel.html:29 | 구성원 정보 저장 | 구성원 정보 저장 |
| members.list.hint | core/web/templates/orgs/settings/_members.html:8 | {n}명 · 이름을 누르면 구성원 패널이 열립니다 | {n}명 · 이름을 누르면 이 조직에 제공한 정보를 확인하고 수정할 수 있습니다. |
| members.real_name_missing | core/web/templates/orgs/settings/_members.html:18 | 실명 미입력 | 실명 미입력 |
| members.list.discord_note | core/web/templates/orgs/settings/_members.html:28 | Discord가 ‘연결 안 됨’인 구성원은 기한 알림 DM을 받지 못합니다. 본인이 프로필 → [Discord 연결]에서 연결합니다. | Discord가 ‘연결 안 됨’인 구성원은 기한 알림 DM을 받을 수 없습니다. 구성원 본인이 프로필 → Discord 연결에서 연결할 수 있습니다. |
| members.pending.help | core/web/templates/orgs/settings/_members.html:37 | 아직 계정이 없는 사람을 먼저 담당자로 넣어 둡니다. 구성원 패널의 [초대 링크 만들기]로 받은 1회용 링크(7일)를 본인에게 보내 주세요. 그 링크로 가입하면 맡은 태스크와 팀을 그대로 이어받습니다. | 아직 계정이 없는 사람도 가입 전 구성원으로 추가해 태스크를 배정할 수 있습니다. 구성원 패널에서 초대 링크를 만들어 본인에게 보내 주세요. 링크는 1회만 사용할 수 있으며 유효기간은 7일입니다. 이 링크로 가입하면 배정된 태스크와 소속 팀을 이어받습니다. |
| members.invites.save | core/web/templates/orgs/settings/_members.html:79 | 초대 정책 저장 | 초대 정책 저장 |
| members.names.help | core/web/templates/orgs/settings/_members.html:87 | 목록·담당자 칸·회의록 참석자처럼 이 조직 안에서 사람 이름이 나오는 모든 곳에 적용됩니다. | 이 조직의 구성원 목록·태스크 담당자·회의록 참석자 등에 표시할 이름을 정하는 설정입니다. 구성원에게 요청할 정보 항목은 아래에서 별도로 설정합니다. |
| members.names.confirm | core/web/templates/orgs/settings/_members.html:89 | 켜면 이 조직의 모든 구성원에게 실명이 표시됩니다. 본인과 관리자 모두 조직 표시 이름을 변경할 수 없습니다. 실명으로 표시하시겠습니까? / 실명으로 표시 | 이 조직의 구성원 이름이 실명으로 표시됩니다. 본인과 관리자 모두 조직 표시 이름을 변경할 수 없습니다. 기존 조직 표시 이름은 보관되며, 실명 표시를 끄면 다시 사용됩니다. 실명으로 표시하시겠습니까? / 실명으로 표시 |
| members.names.nickname | core/web/templates/orgs/settings/_members.html:92 | 구성원이 정한 조직 표시 이름 / 구성원이 내 정보에서 정한 이름을 씁니다. 비어 있으면 계정 표시 이름을 씁니다. | 조직 표시 이름 / 실명 표시가 꺼집니다. 저장된 조직 표시 이름을 사용하며, 비어 있으면 계정 표시 이름이 표시됩니다. 구성원은 내 정보에서, 관리자는 구성원 패널에서 조직 표시 이름을 수정할 수 있습니다. |
| members.names.real | core/web/templates/orgs/settings/_members.html:93 | 실명 / 모든 구성원을 계정 실명으로 표시합니다. 조직 표시 이름 칸이 사라지고, 저장된 값은 지우지 않습니다. | 실명 / 실명 표시가 켜집니다. 구성원 이름을 계정의 실명으로 표시합니다. 내 정보와 구성원 패널의 조직 표시 이름 입력칸이 숨겨지며, 본인과 관리자 모두 변경할 수 없습니다. 기존 조직 표시 이름은 보관됩니다. |
| members.names.preview | core/web/templates/orgs/settings/_members.html:95 | 목록·담당자 칸에 이렇게 보입니다: {조직 표시 이름} / 실명으로 표시하면 {실명} (관리자 본인 기준) | 관리자 본인의 이름 예시: 조직 표시 이름 사용 시 {조직 표시 이름} / 실명 사용 시 {실명} |
| members.names.save | core/web/templates/orgs/settings/_members.html:96 | 이름 표시 방식 저장 | 이름 표시 방식 저장 |
| members.fields.limits | core/web/templates/orgs/settings/_members.html:102 | 항목 {최대 항목 수}개 · 이름 50자 · 선택지 50자×30개까지 | 항목은 최대 {최대 항목 수}개, 항목 이름은 50자까지입니다. 선택지는 항목당 최대 30개이며, 각 선택지는 50자까지입니다. |
| members.teams_tags.save | core/web/templates/orgs/settings/_members.html:111 | 팀·기술 태그 정책 저장 | 팀·기술 태그 정책 저장 |
| members.teams_tags.teams_link | core/web/templates/orgs/settings/_members.html:113 | 팀을 만들고 구성원을 넣는 일은 팀 메뉴에서 합니다. | 팀 생성과 구성원 추가는 팀 메뉴에서 할 수 있습니다. |
| server_view_intro | core/web/templates/orgs/settings/_stt.html:4 | 회의가 끝나면 연결된 진행자의 PC로 전사합니다. 사용할 수 없으면 조직에 등록한 전사 서버와 모델을 사용하며, 전사 서버가 없으면 조직의 OpenAI 키로 전사합니다. | 회의가 끝나면 연결된 진행자의 PC로 전사합니다. 진행자의 PC를 사용할 수 없으면 조직에 등록한 전사 서버와 모델을 사용합니다. 전사 서버가 없으면 조직의 OpenAI 키로 전사합니다. |
| pc_online_count | core/web/templates/orgs/settings/_stt.html:5 | 구성원 PC / 연결된 PC {n}대 | 구성원 PC / 현재 연결된 PC: {n}대 |
| server_advanced | core/web/templates/orgs/settings/_stt.html:9 | 고급 설정 · 조직 전사 서버 주소 직접 입력 | 고급 설정 · 조직 전사 서버 주소 직접 입력 |
| teams.members_moved | core/web/templates/orgs/teams.html:4 | 구성원·초대는 설정 → 구성원 관리에서 관리합니다. 실명으로 표시도 이름 표시 방식에서 바꿉니다. | 구성원과 초대 링크는 설정 → 구성원 관리에서 관리할 수 있습니다. 실명 표시 켜기·끄기는 같은 탭의 이름 표시 방식에서 설정할 수 있습니다. |
| transcribe_settings_link | core/web/templates/orgs/transcribe.html:4 | 전사 서버·이용 권한은 설정 → 회의·전사에서 바꿉니다. | 전사 서버와 전사 이용 권한은 설정 → 회의·전사에서 설정할 수 있습니다. |
| members.fields.kind_help.text | core/web/views/org_members.py:24 | 짧은 글 / 한 줄 입력, 200자 / 예: 학번 | 짧은 글 / 구성원이 한 줄로 입력하는 형식입니다. 최대 200자입니다. / 예: 항목 이름 ‘학번’ → 입력값 ‘20260001’ |
| members.fields.kind_help.long | core/web/views/org_members.py:25 | 긴 글 / 여러 줄, 2000자 / 예: 가능한 시간 | 긴 글 / 구성원이 여러 줄로 입력하는 형식입니다. 최대 2,000자입니다. / 예: 항목 이름 ‘참여 가능한 시간’ → 입력값 ‘월요일 오후 2시부터 4시까지’ |
| members.fields.kind_help.choice | core/web/views/org_members.py:26 | 선택지 / 목록에서 하나 고름 / 예: 학년(1·2·3·4) | 선택지 / 관리자가 등록한 선택지 중 구성원이 하나를 고르는 형식입니다. / 예: 항목 이름 ‘학년’, 선택지 ‘1학년·2학년·3학년·4학년’ → 선택값 ‘2학년’ |
| members.panel.unblocked | core/web/views/org_members.py:149 | 이제 이 구성원은 조직을 쓸 수 있습니다. | 구성원 정보를 저장했습니다. 필수 항목이 모두 입력되어 이 구성원은 이제 이 조직을 사용할 수 있습니다. |
| members.panel.still_missing | core/web/views/org_members.py:153 | 필수 항목 {n}개가 아직 비었습니다. | 구성원 정보를 저장했습니다. 필수 항목 {n}개가 아직 입력되지 않아 이 구성원은 이 조직을 사용할 수 없습니다. |
| members.panel.saved | core/web/views/org_members.py:155 | 저장했습니다. | 구성원 정보를 저장했습니다. |
| org_history.member_info | core/web/views/orgs.py:552 | 구성원 정보 수정 | 구성원 정보 수정 |
| org_settings.group.me | core/web/views/orgs.py:622 | 나 | 나 |
| org_settings.group.admin | core/web/views/orgs.py:623 | 조직 관리 | 조직 관리 |
| org_settings.forbidden | core/web/views/orgs.py:741 | 조직 관리자만 볼 수 있는 탭입니다. 내 정보로 이동했습니다. | 조직 관리자만 볼 수 있는 설정입니다. 내 정보로 이동했습니다. |
| org_settings.integrations_blocked | core/web/views/orgs.py:748 | 내 정보의 필수 항목을 먼저 입력해 주세요. | 연동 설정을 사용하려면 내 정보의 필수 구성원 정보를 먼저 입력해 주세요. |
| org_settings.saved_tab | core/web/views/orgs.py:781 | {탭} 설정을 저장했습니다. | {탭} 설정을 저장했습니다. |
| me.unblocked | core/web/views/orgs.py:870 | 이제 {조직}을(를) 쓸 수 있습니다. | 필수 구성원 정보가 모두 입력되었습니다. 이제 {조직} 조직을 사용할 수 있습니다. |
| me.saved | core/web/views/orgs.py:872 | 내 정보를 저장했습니다. | 내 정보를 저장했습니다. |
| nickname.real_name_org | core/orgs/member_info.py:195 | 이 조직은 구성원 이름을 실명으로 표시하므로 조직 표시 이름을 변경할 수 없습니다. | 이 조직은 구성원 이름을 실명으로 표시합니다. 본인과 관리자 모두 조직 표시 이름을 변경할 수 없습니다. |

## 설명 누락 보완 문구

아래 7개 키는 해당 변경 화면에 문장은 있으나 COPY 표기는 없습니다. 사용자 요구인 ‘무엇을 채우면 어떻게 동작하는지’를 설명하기 위해 반영용 키를 제안합니다. 위 기존 키 수에는 포함하지 않으며, 전체 최종 문구 수에는 포함합니다.

| 키 | 위치(파일:줄) | 현재 임시 문구 | 최종 문구 |
|---|---|---|---|
| me.blocked | core/web/templates/orgs/settings/_me.html:2 | 필수 항목을 입력해야 {조직} 조직을 쓸 수 있습니다. 다른 조직은 그대로 쓸 수 있습니다. | 이 조직을 사용하려면 필수 구성원 정보를 입력해 주세요. 다른 조직은 계속 사용할 수 있습니다. |
| me.info_help | core/web/templates/orgs/settings/_me.html:24 | 이 조직에만 제출하는 정보입니다. {조직} 조직이 정한 목적에 따라 처리되며 조직 관리자가 열람하고 고칠 수 있습니다. | 이 조직에서 요청하는 정보입니다. {조직} 조직이 정한 목적에 따라 처리되며, 조직 관리자가 값을 열람하고 수정할 수 있습니다. 다른 조직과는 공유되지 않습니다. |
| me.save | core/web/templates/orgs/settings/_me.html:27 | 내 정보 저장 / 이름과 구성원 정보를 함께 저장합니다. | 내 정보 저장 / 이름과 구성원 정보를 함께 저장합니다. |
| members.fields.label_help | core/web/templates/orgs/settings/_member_fields_editor.html:14 | 항목 이름 / 구성원에게 보이는 질문 제목 | 항목 이름 / 내 정보에 표시할 입력 항목의 제목입니다. 예: 학번 |
| members.fields.choices_help | core/web/templates/orgs/settings/_member_fields_editor.html:19<br>core/web/templates/orgs/settings/_member_fields_editor.html:38 | 선택지 / 한 줄에 하나, 50자·30개까지. 형식이 ‘선택지’일 때만 씁니다. / 한 줄에 하나 | 선택지 / ‘선택지’ 형식에서 구성원이 고를 값입니다. 한 줄에 하나씩 입력해 주세요. 최대 30개이며 각 선택지는 50자까지입니다. 예: 1학년, 2학년을 각각 한 줄에 입력 |
| members.fields.required_help | core/web/templates/orgs/settings/_member_fields_editor.html:23<br>core/web/templates/orgs/settings/_member_fields_editor.html:40 | 필수 / 비워 두면 조직을 쓸 수 없습니다(관리자 포함). | 필수 / 값을 입력해야 이 조직을 사용할 수 있습니다. 관리자에게도 적용됩니다. |
| members.fields.order_help | core/web/templates/orgs/settings/_member_fields_editor.html:13 | 순서 | 순서 / 내 정보에서 항목이 표시되는 순서입니다. 작은 숫자부터 표시됩니다. |

## 추가 키

HEAD e2bf160에서 추가된 COPY 키 7개입니다. 미리보기는 편집 즉시 저장 전 초안을 표시하며, 구성원의 내 정보 화면에는 저장 후 반영됩니다. 기존 members.fields.save의 ‘마지막으로 저장한 항목 기준’ 설명은 사용하지 않고, 버튼은 ‘정보 항목 저장’으로 유지하며 아래 save_hint 문구로 대체합니다.

| 키 | 위치(파일:줄) | 현재 임시 문구 | 최종 문구 |
|---|---|---|---|
| members.fields.empty_info | core/web/templates/orgs/settings/_member_fields_editor.html:26 | 지금 {n}명이 비워 두었습니다. 필수가 아니라 조직 사용에는 영향이 없습니다. | 현재 이 항목을 입력하지 않은 구성원은 {n}명입니다. 필수 항목이 아니므로 입력하지 않아도 이 조직을 사용할 수 있습니다. |
| members.fields.filled | core/web/templates/orgs/settings/_member_fields_editor.html:29 | 지금 {n}명이 입력했습니다. | 현재 이 항목을 입력한 구성원은 {n}명입니다. |
| members.fields.save_hint | core/web/templates/orgs/settings/_member_fields_editor.html:52 | 미리보기는 바로 바뀌고, 구성원 화면은 저장해야 바뀝니다. | 미리보기에는 편집 중인 내용이 즉시 표시됩니다. 구성원의 내 정보 화면에는 정보 항목을 저장한 후 반영됩니다. |
| members.fields.preview_jump | core/web/templates/orgs/settings/_member_fields_editor.html:53 | 미리보기 보기 | 미리보기로 이동 |
| members.names.effect_on | core/web/templates/orgs/settings/_members.html:99 | 내 정보·구성원 패널에서 조직 표시 이름 칸이 사라집니다. 저장된 조직 표시 이름은 지우지 않으며, 다시 끄면 그대로 돌아옵니다. | 실명 표시를 켜고 저장하면 내 정보와 구성원 패널의 조직 표시 이름 입력칸이 숨겨집니다. 기존 조직 표시 이름은 보관되며, 실명 표시를 끄고 저장하면 다시 사용됩니다. |
| members.names.effect_off | core/web/templates/orgs/settings/_members.html:97 | 구성원은 내 정보에서, 관리자는 구성원 패널에서 조직 표시 이름을 바꿀 수 있습니다. | 실명 표시를 끄고 저장하면 구성원은 내 정보에서, 관리자는 구성원 패널에서 조직 표시 이름을 수정할 수 있습니다. |
| member_fields.summary_show_real_name | core/orgs/member_info.py:150 | 실명으로 표시 켬 / 실명으로 표시 끔 | 실명 표시: 켜짐 / 실명 표시: 꺼짐 |

## 적용 시 확인할 사항

- 필수 영향 인원 {n}은 가입 전 구성원을 제외한 실제 미입력 인원입니다(core/orgs/member_info.py:284). 0명과 계산 실패는 구분해야 합니다. 현재 화면은 0명이면 영향 문구를 표시하지 않습니다(core/web/templates/orgs/settings/_member_fields_editor.html:24). 본 문서로 노출 조건을 바꾸지는 않습니다.
- 필수 항목으로 바꾸어도 관리자는 항목 정의를 고칠 수 있도록 일부 관리 탭에 접근할 수 있습니다(docs/IMPL-PLAN-14-org-settings-ia.md:150). ‘이 조직을 사용할 수 없습니다’는 구성원 업무 이용 제한을 설명하는 기존 관문 용어입니다.
- org_settings.forbidden은 관리자 탭 GET을 내 정보로 돌린 뒤 보여 주는 안내입니다. 비관리자 POST와 구성원 패널의 권한 거절은 현재 PermissionDenied로 처리되며 별도 COPY 문구가 없습니다(core/web/views/orgs.py:740, core/web/views/org_members.py:135). 공통 403 화면의 개편은 이 문서의 범위 밖입니다.
- me.no_fields의 추가 적용 위치: core/web/templates/orgs/settings/_me.html:26. org_settings.section.me.name의 임시 사전 문구는 ‘실명·조직 표시 이름’이지만 실제 본문 제목은 이미 ‘이름’입니다(core/web/templates/orgs/settings/_me.html:5). 실명 표시 켜짐 상태에서도 제목이 맞도록 ‘이름’으로 통일합니다.
- members.fields.kind_help의 예시는 항목 이름과 입력값을 구분합니다. 선택지 예시의 가운데점은 문서에서 값을 나누는 표시입니다. 실제 선택지 입력은 한 줄에 하나씩입니다.
- members.fields.order_help는 설명 추가 제안입니다. 현재 화면에는 ‘순서’ 제목만 있으며 저장 시 숫자 순으로 정렬합니다(core/web/views/orgs.py:789).
- 연동·전사 문구는 실제 코드 키 github_self_link, transcribe_settings_link를 따릅니다. 계획서의 integrations.github.own_link, transcribe.server_moved는 같은 문구의 기획상 이름이므로 중복 키를 만들지 않습니다.
- 약관 제6조 링크와 민감정보 금지 경고는 유지합니다(core/web/templates/orgs/settings/_member_fields_editor.html:3). 약관·개인정보 처리방침은 수정하지 않습니다.
- 실명 표시 켜기 확인창은 기존 구현대로 끄기→켜기 전환 때만 사용합니다. 끄기 동작은 라디오 설명에 명시했으며 새 확인창을 요구하지 않습니다.
