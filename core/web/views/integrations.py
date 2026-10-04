"""연동 문제의 해결 절차와 비밀값 없는 질문 자료."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from github.client import GitHubError

TOPICS = [
    {
        "key": "oauth",
        "title": "GitHub 계정 연결·접근 목록",
        "steps": [
            "연결을 취소했거나 시간이 지났다면 프로필에서 GitHub 연결을 다시 시작하세요. 돌아오기 전의 콜백 URL을 재사용하지 마세요.",
            "계정 연결 성공과 저장소 목록 조회 성공은 별개입니다. 연결됐지만 목록 조회가 실패했다면 계정 연결을 해제하지 말고 접근 가능한 저장소 다시 확인을 실행하세요.",
            "목록에 저장소가 없다면 GitHub 계정의 접근 권한과 조직 앱의 설치 대상 저장소를 관리자에게 확인해 달라고 요청하세요.",
            "운영자는 GitHub 앱의 Client ID·비밀값 설정과 콜백 주소를 확인하세요. 상태 검증 실패는 다른 탭에서 연결했거나 세션이 만료된 경우도 있으므로 권한 오류로 단정하지 마세요.",
        ],
        "url": "https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app",
    },
    {
        "key": "repositories",
        "title": "앱 설치·저장소 후보·접근 팀",
        "steps": [
            "앱 미설치, 조회 실패, 정상 조회 후 저장소 0개는 서로 다른 상태입니다. 조직 관리자는 조직 GitHub 화면에서 설치 상태와 저장소 선택 범위를 확인하세요.",
            "선택한 저장소에만 설치했다면 대상 저장소가 포함됐는지 확인하세요. 변경된 앱 권한은 설치 관리자가 승인해야 적용됩니다.",
            "접근 팀 조회에는 Repository Administration: Read-only가 필요합니다. Organization Members 읽기와 다릅니다. 기존 앱 가이드는 Administration을 요청하지 않습니다.",
            "권한을 유지하면 GitHub 저장소의 접근 관리 화면에서 직접 확인할 수 있습니다. 웹 조회가 필요하면 앱 관리자와 읽기 권한 추가를 검토하세요. 쓰기 권한은 필요하지 않습니다.",
            "빈 접근 팀 목록은 호출자에게 보이는 팀이 없다는 뜻이며, 모든 개인 접근 권한이 없다는 뜻은 아닙니다.",
        ],
        "url": "https://docs.github.com/en/rest/repos/repos#list-repository-teams",
    },
    {
        "key": "issues",
        "title": "이슈 동기화 실패·부분 성공",
        "steps": [
            "실패한 저장소와 마지막 동기화 시각을 확인하고 해당 프로젝트 이슈 화면에서 GitHub에서 새로 고침을 실행하세요. 기존 태스크를 다시 가져올 필요는 없습니다.",
            "조직 새로 고침은 저장소별로 처리하므로 일부만 성공할 수 있습니다. 성공한 건수와 실패한 저장소를 구분해 확인하세요.",
            "조직 관리자는 앱 설치·대상 저장소 선택·Issues 읽기 권한과 변경 승인 여부를 확인하세요. 운영자는 네트워크·GitHub 서비스 상태를 확인하세요.",
            "HTTP 401·403·404만으로 원인을 단정할 수 없습니다. 인증, 선택 범위, 조직 정책, 호출 제한 등을 함께 확인하세요.",
        ],
        "url": "https://docs.github.com/en/rest/issues/issues#list-repository-issues",
    },
    {
        "key": "writes",
        "title": "PM 적용 성공·GitHub 반영 실패",
        "steps": [
            "PM 변경은 이미 적용됐습니다. 같은 초대나 PM 멤버 변경을 반복하지 마세요. 아래 실패 작업의 GitHub만 다시 반영을 사용하세요.",
            "재시도는 현재 로그인한 조직 관리자의 GitHub 사용자 권한으로 실행됩니다. 프로필에서 GitHub 연결과 접근 목록을 확인하세요.",
            "팀·계정·앱 연결 또는 PM 멤버 상태가 바뀌면 오래된 작업은 취소합니다. 최신 상태를 확인한 후 필요한 작업을 새로 실행하세요.",
            "재시도 목록은 현재 로그인 세션에서 최대 20개 보관합니다. 로그아웃하거나 세션이 만료되면 목록이 사라집니다. 이 경우 GitHub에서 실제 반영 상태를 먼저 확인하고 수동으로 복구하세요.",
            "새 팀·이슈·브랜치 생성은 응답만 유실돼 이미 생성됐을 수 있습니다. 생성 버튼을 반복하기 전에 GitHub에서 대상을 확인하세요.",
        ],
        "url": "https://docs.github.com/en/rest/teams/members#add-or-update-team-membership-for-a-user",
    },
    {
        "key": "discord",
        "title": "Discord 연결·알림 채널·DM",
        "steps": [
            "PM 조직 관리자는 조직 Discord 화면에서 서버 연결을 확인하세요. Discord 서버 선택에는 해당 서버의 관리 권한도 필요합니다.",
            "연결한 서버의 원하는 채널에서 /알림채널을 실행하세요. 실행자는 PM 계정을 Discord에 연결한 조직 관리자여야 합니다.",
            "명령이 보이지 않으면 봇의 서버 참여와 명령 등록 상태를 운영자에게 확인해 달라고 요청하세요. 채널의 봇 View Channel·Send Messages 권한은 Discord 관리자에게 확인하세요.",
            "개인 마감 DM은 조직 알림 채널과 별개입니다. 개인 Discord 계정 연결, 봇과 같은 서버 참여, DM 수신 허용을 확인하세요.",
            "명령 결과와 서버·채널 ID를 질문에 적으면 진단에 도움이 됩니다. 연결 코드·봇 토큰은 공유하지 마세요.",
        ],
        "url": "https://docs.discord.com/developers/topics/permissions",
    },
]


def record_problem(request, topic, stage, error=None, *, target=""):
    status = (
        (f"HTTP {error.status}" if error.status else "네트워크 연결 실패")
        if isinstance(error, GitHubError)
        else "설정 또는 처리 상태 확인 필요"
    )
    records = dict(request.session.get("integration_problems", {}))
    records[topic] = {
        "stage": stage,
        "status": status,
        "target": target,
        "at": timezone.now().isoformat(),
    }
    request.session["integration_problems"] = records


def clear_problem(request, topic):
    records = dict(request.session.get("integration_problems", {}))
    records.pop(topic, None)
    request.session["integration_problems"] = records


@login_required
def integration_help(request):
    from .github_retries import visible_retries

    diagnostics = request.session.get("integration_problems", {})
    topics = []
    for item in TOPICS:
        topic = dict(item)
        diagnostic = diagnostics.get(topic["key"])
        context = (
            f"최근 실패 단계: {diagnostic['stage']}. 상태: {diagnostic['status']}. "
            f"대상: {diagnostic['target'] or '기록 없음'}. 발생 시각: {diagnostic['at']}. "
            if diagnostic
            else "실패 단계·대상·발생 시각·화면에 보이는 상태를 추가하겠습니다. "
        )
        topic["diagnostic"] = diagnostic
        topic["prompt"] = (
            f"ProjectManager의 {topic['title']} 문제를 해결하고 싶습니다. {context}"
            "사용자가 할 일과 앱·조직 관리자 또는 운영자가 할 일을 구분해 설명해 주세요. "
            "확인된 상태만으로 원인을 단정하지 말고 점검 순서와 안전한 복구 방법을 알려 주세요. "
            "토큰·개인키·OAuth code/state·연결 코드·초대 링크는 공유하지 않겠습니다."
        )
        topics.append(topic)
    return render(
        request, "integrations/help.html", {"topics": topics, "retries": visible_retries(request)}
    )
