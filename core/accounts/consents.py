"""연결할 때 받는 개인정보 국외 이전(제3자 제공) 동의의 고지 내용.

개인정보 보호법 제17조, 제28조의8①1호에 따른 별도 동의다. 고지 항목은 제28조의8②를 따른다.
처리방침 제4조·제6조와 대조하기 쉽게 대상별 문구를 이 파일 한 곳에 둔다. 문구를 바꾸면
POLICY_VERSION을 올린다 — 동의 기록은 어느 판에 동의했는지를 이 값으로 남긴다.
`value`는 법정 고지가 아니라 동의 화면 맨 위에 두는 "연결하면 얻는 것" 한 줄이다. 바꿔도 판을 올리지 않는다.
"""

# 처리방침 판. 시행일이 정해지면 그 날짜로 바꾼다.
POLICY_VERSION = "v1"

# 로그인 화면 고지로 받는 이용약관·처리방침 동의의 현재 판(content/terms.md·privacy.md 머리의 버전).
# 판을 올리면 다음 로그인 때 그 판의 동의 행이 새로 생긴다(accounts.services.agree_terms).
DOC_VERSIONS = {"terms": "v2", "privacy": "v3"}

TARGETS = [("github", "GitHub"), ("discord", "Discord"), ("ai", "AI 도구")]

NOTICES = {
    "github": {
        "value": "GitHub를 연결하면 이슈·브랜치·PR이 태스크와 이어지고, PR이 병합되면 태스크 상태가 저절로 바뀝니다.",
        "rows": [
            {
                "recipient": "GitHub, Inc.",
                "contact": "https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement",
                "country": "미국",
                "items": "GitHub 인증 토큰, 연동하는 태스크·이슈·마일스톤의 제목·본문·담당자",
                "purpose": "GitHub 계정 인증, 저장소 업무 연동",
                "when": "GitHub 로그인·연결·동기화 때 HTTPS(OAuth·API)로 전송",
                "retention": "GitHub 계정 이용 기간과 GitHub가 법적 의무·분쟁 해결에 필요하다고 정한 기간",
            }
        ],
        "refusal": "동의하지 않으면 GitHub 로그인과 저장소 연동만 쓸 수 없습니다. "
        "아이디로 가입하면 다른 기능은 그대로 쓸 수 있습니다.",
    },
    "discord": {
        "value": "Discord를 연결하면 기한 알림을 개인 DM으로 받고, 봇에게 DM으로 태스크를 처리할 수 있습니다.",
        "rows": [
            {
                "recipient": "Discord Inc.",
                "contact": "https://discord.com/privacy",
                "country": "미국",
                "items": "Discord 사용자 ID, DM으로 보내는 알림·봇 답장 내용(태스크 제목·기한·담당자)",
                "purpose": "개인 DM 알림, 봇 명령 처리",
                "when": "알림 발송·봇 명령 때 HTTPS(Discord API)로 전송",
                "retention": "Discord가 처리 목적과 법적 의무에 따라 정한 기간",
            }
        ],
        "refusal": "동의하지 않으면 Discord 개인 연결(DM 알림·봇 명령)만 쓸 수 없습니다.",
    },
    "ai": {
        "value": "AI 도구를 연결하면 Claude·Codex에서 내 태스크를 묻고 상태를 바꿀 수 있습니다.",
        "rows": [
            {
                "recipient": "OpenAI, L.L.C.",  # 확인 필요: 계약 법인(OpenAI OpCo, LLC 등)
                "contact": "https://privacy.openai.com/",
                "country": "미국",
                "items": "허용한 범위의 조직·프로젝트·태스크·문서, 구성원 ID·표시 이름·Discord ID, "
                "결정 기록(원문 제외)",
                "purpose": "연결한 AI 도구(Codex 등)의 업무 조회·변경 요청 처리",
                "when": "AI 도구가 요청할 때 HTTPS(MCP·API)로 전송",
                "retention": "OpenAI 정책과 사용자의 대화 삭제 설정에 따른 기간",
            },
            {
                "recipient": "Anthropic, PBC",
                "contact": "https://privacy.claude.com/",
                "country": "미국",
                "items": "허용한 범위의 조직·프로젝트·태스크·문서, 구성원 ID·표시 이름·Discord ID, "
                "결정 기록(원문 제외)",
                "purpose": "연결한 AI 도구(Claude 등)의 업무 조회·변경 요청 처리",
                "when": "AI 도구가 요청할 때 HTTPS(MCP·API)로 전송",
                "retention": "Anthropic 정책과 사용자의 대화 삭제 설정에 따른 기간",
            },
        ],
        "refusal": "동의하지 않으면 AI용 토큰 발급과 AI 커넥터 연결만 쓸 수 없습니다.",
    },
}
