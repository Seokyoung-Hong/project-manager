"""Read current templates and generate an auditable control inventory (no app mutations).

Run from repository root. Output files are created exclusively; existing reports are preserved.
This lists template control sites, not rendered repetitions or every possible DOM instance.
"""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
CONTEXT = json.loads((OUT / "button-purpose-context.json").read_text(encoding="utf-8"))
TAG = re.compile(r'''<(?:[^>"']|"[^"]*"|'[^']*')*>''')
ATTR = re.compile(r'''([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))''')
VOID = set("input img br hr meta link area base col embed param source track wbr".split())
URL = re.compile(r'''\{%\s*url\s+['"]([^'"]+)['"]''')


def attributes(tag):
    raw = re.sub(r"^</?[\w-]+", "", tag)
    return {m[1]: next(v for v in m.groups()[1:] if v is not None) for m in ATTR.finditer(raw)}


def plain(text):
    text = re.sub(r"\{%[\s\S]*?%\}|\{#[\s\S]*?#\}", " ", text)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", text)).strip()


def extract():
    result = []
    files = sorted((ROOT / "core/web/templates").rglob("*.html"))
    for file in files:
        source = file.read_text(encoding="utf-8")
        stack = []
        for match in TAG.finditer(source):
            tag = match[0]
            opening = re.match(r"</?([\w-]+)", tag)
            if not opening:
                continue
            name = opening[1].lower()
            if tag.startswith("</"):
                indexes = [i for i, item in enumerate(stack) if item["tag"] == name]
                if indexes:
                    i = indexes[-1]
                    if stack[i].get("control") is not None:
                        stack[i]["control"]["label"] = plain(source[stack[i]["end"]:match.start()])
                    stack = stack[:i]
                continue
            attrs = attributes(tag)
            form = next((item for item in reversed(stack) if item["tag"] == "form"), None)
            label = next((item for item in reversed(stack) if item["tag"] == "label"), None)
            included = (
                name in {"button", "a", "summary"}
                or (name == "label" and attrs.get("for") and f'id="{attrs["for"]}"' in source
                    and 'type="file"' in source)
                or (name in {"input", "select", "textarea"} and
                    (attrs.get("hx-post") or attrs.get("hx-get") or attrs.get("onchange")
                     or attrs.get("type") in {"submit", "file", "button"}))
            )
            line = source[:match.start()].count("\n") + 1
            control = None
            if included:
                control = {
                    "file": file.relative_to(ROOT).as_posix(), "line": line, "tag": name,
                    "attrs": attrs, "form": form["attrs"] if form else {},
                    "formLine": form["line"] if form else None,
                    "openingTag": tag,
                    "label": attrs.get("value") or attrs.get("aria-label") or attrs.get("title")
                             or attrs.get("name") or "",
                    "contextLabel": plain(source[label["end"]:match.start()]) if label else "",
                }
                result.append(control)
            if name not in VOID and not tag.endswith("/>"):
                stack.append({"tag": name, "attrs": attrs, "line": line,
                              "end": match.end(), "control": control})
    for i, c in enumerate(result, 1):
        c["id"] = f"B{i:03d}"
        c["visibleLabel"] = c["label"] or c["attrs"].get("aria-label") or c["attrs"].get("title") or "(문구 없음)"
        c["accessibleLabel"] = c["attrs"].get("aria-label") or c["attrs"].get("title") or c["contextLabel"] or c["visibleLabel"]
        c["destination"] = next((v for v in (
            c["attrs"].get("hx-post"), c["attrs"].get("hx-get"), c["attrs"].get("href"),
            c["form"].get("hx-post"), c["form"].get("hx-get"), c["form"].get("action")) if v), "(현재 화면)")
        c["routes"] = URL.findall(c["destination"])
    return files, result


def route_index():
    source = (ROOT / "core/web/urls.py").read_text(encoding="utf-8")
    index = {}
    pattern = r'path\(\s*"([^"]*)",\s*(\w+)\.(\w+),\s*name="([^"]+)"'
    for m in re.finditer(pattern, source):
        path, module, fn, name = m.groups()
        view = ROOT / f"core/web/views/{module}.py"
        lines = view.read_text(encoding="utf-8").splitlines()
        line = next(i for i, s in enumerate(lines, 1) if s.startswith(f"def {fn}("))
        index.setdefault(name, []).append({"path": path, "module": module, "fn": fn,
                                           "evidence": f"core/web/views/{module}.py:{line}"})
    index["login"] = [{"path": "login", "evidence": "core/web/urls.py:39"}]
    index["logout"] = [{"path": "logout", "evidence": "core/web/urls.py:47"}]
    return index


# Parent-reviewed route semantics. Requirements and failure behavior remain server-controlled.
SEMANTICS = {}


def register(names, purpose, effect, recommendation="유지"):
    for name in names.split():
        SEMANTICS[name] = dict(purpose=purpose, effect=effect, recommendation=recommendation)


for name, goal, effect in [
    ("today", "오늘 할 일 확인", "오늘 목록; cal/day/quick 파라미터에 따라 달력·빠른 추가 표시"),
    ("me", "담당 태스크 확인", "담당자·묶음·정렬·필터 조건에 맞는 태스크 목록 표시"),
    ("project_index", "작업할 프로젝트 열기", "최근 또는 조직 첫 프로젝트 상세로 이동; 없으면 빈 화면"),
    ("org", "현재 조직 업무 확인", "현재 조직 상세로 이동; 없으면 조직 목록"),
    ("org_detail", "조직 업무 확인", "선택 조직의 개요 표시"),
    ("org_teams", "멤버·팀·초대 관리", "조직 멤버·초대·팀 관리 화면"),
    ("org_capacity", "조직 업무 부하 확인", "부하 지표와 팀·기술 태그 필터 화면"),
    ("org_roadmap", "프로젝트 일정·의존성 확인", "마일스톤·프로젝트 의존성 화면"),
    ("org_governance", "조직 합의 확인·편집", "거버넌스 본문·편집 화면"),
    ("org_settings", "조직 규칙 관리", "조직 설정·잠금 화면"),
    ("org_notes", "회의 기록 확인", "조직 회의록 목록 또는 지정 회의록 표시"),
    ("org_issues", "조직 저장소 이슈 확인", "조직 GitHub 이슈 목록"),
    ("org_github", "조직 GitHub 연동 관리", "GitHub App 설치·조직 저장소 연결 상태"),
    ("org_discord", "조직 Discord 연동 관리", "Discord 서버 연결 화면"),
    ("team_detail", "팀 구성·프로젝트 확인", "선택 팀 상세·GitHub 팀 연결 화면"),
    ("project_detail", "프로젝트 태스크 확인", "선택 프로젝트 목록 또는 보드"),
    ("project_docs", "프로젝트 문서 읽기·편집", "문서 목록 또는 doc 파라미터의 문서 표시"),
    ("project_api", "API 정의 확인", "OpenAPI 문서·엔드포인트 화면"),
    ("project_issues", "프로젝트 이슈 확인", "프로젝트 GitHub 이슈 목록"),
    ("project_repo", "프로젝트 저장소 연동 관리", "저장소 연결·규칙·이슈·이벤트 화면; 조건부 이슈 동기화 가능"),
    ("project_settings", "프로젝트 규칙·수명주기 관리", "설정·보관·삭제·거버넌스 화면"),
    ("task_detail", "태스크 내용 확인", "태스크 상세 페이지"),
    ("task_panel", "태스크 내용 읽기·편집", "HTMX 패널 표시; focus=notes 메모 포커스, block=1 막힘 사유"),
    ("profile", "개인 정보·연동 관리", "프로필·개인 GitHub/Discord 연결 화면"),
    ("tokens", "API·AI 연결 자격 관리", "토큰 관리·연결 안내 화면"),
    ("preferences", "개인 환경설정 관리", "개인 설정 화면"),
    ("portfolio", "내 기록으로 초안 준비·확인", "출처 선택 또는 draft 파라미터의 저장된 초안 표시"),
    ("ops", "운영 상태 확인", "staff 전용 실행 상태 화면"),
    ("search", "태스크 찾기", "태스크 번호·제목·프로젝트 이름 검색 화면"),
    ("signup", "새 계정 만들기", "가입 화면; 유효 POST 계정 생성·로그인·next/조직 목록 이동"),
    ("login", "로그인", "로그인 화면; POST 세션 로그인"),
    ("logout", "로그인 종료", "POST 세션 로그아웃"),
]:
    register(name, goal, effect)

register("org_new", "새 조직 생성", "GET 생성 폼; 유효 POST 조직 생성", "조직 만들기")
register("project_new", "새 프로젝트 생성", "GET 생성 다이얼로그; 유효 POST 프로젝트 생성", "새 프로젝트 / 프로젝트 만들기")
register("project_edit", "프로젝트 정보 수정", "GET 편집 다이얼로그; 유효 POST 변경 저장", "프로젝트 수정 / 변경 내용 저장")
register("project_task_create", "프로젝트 태스크 등록", "POST 새 태스크 생성", "태스크 만들기")
register("project_link_add", "프로젝트 참고 주소 등록", "POST Link 등록", "프로젝트 링크 추가")
register("project_archive", "프로젝트를 활성 업무에서 보관", "POST 보관; cancel_open=1이면 미완료 태스크 취소도 수행", "프로젝트 보관 / 미완료 태스크를 취소하고 프로젝트 보관")
register("project_restore", "보관 프로젝트 다시 사용", "POST 보관 해제", "프로젝트 보관 해제")
register("project_delete", "보관 프로젝트 영구 제거", "POST 관리자·보관 조건 검사 후 삭제", "프로젝트 삭제")
register("doc_new", "새 문서 바로 작성", "POST 빈 문서 생성 후 해당 문서 이동", "새 문서 만들기")
register("doc_upload", "Markdown을 문서로 등록", "파일 선택 후 POST 업로드·생성", "Markdown 문서 올리기; 선택 즉시 제출 안내")
register("doc_save", "문서 변경 저장", "POST 제목·본문 저장; JS 본문은 800ms 지연 자동 저장", "자동 저장 상태 안내; fallback 문서 저장")
register("doc_delete", "문서 본문까지 제거", "POST 문서 삭제", "문서 삭제")
register("task_doc_link", "기존 문서를 참고로 연결", "POST 태스크·문서 참조 추가", "문서 연결")
register("task_doc_unlink", "문서 참조만 해제", "POST 연결 해제; 문서 유지", "문서 연결 해제")
register("note_new", "새 회의록 바로 작성", "POST 빈 회의록 생성 후 해당 회의록 이동", "새 회의록 만들기")
register("note_upload", "Markdown을 회의록으로 등록", "파일 선택 후 POST 업로드·생성", "Markdown 회의록 올리기; 선택 즉시 제출 안내")
register("note_save", "회의록 변경 저장", "POST 제목·본문 저장; JS 본문은 800ms 지연 자동 저장", "자동 저장 상태 안내; fallback 회의록 저장")
register("note_delete", "회의록 본문까지 제거", "POST 회의록 삭제", "회의록 삭제")
register("task_note_link", "기존 회의록을 참고로 연결", "POST 태스크·회의록 참조 추가", "회의록 연결")
register("task_note_unlink", "회의록 참조만 해제", "POST 연결 해제; 회의록 유지", "회의록 연결 해제")
register("today_quick", "태스크 생성 후 오늘 계획에 등록", "POST 태스크 생성·today_add", "태스크 만들고 오늘에 추가")
register("today_add", "기존 태스크를 오늘 계획에 등록", "POST 본인 오늘 목록 추가", "오늘 목록에 추가")
register("today_exclude", "오늘 계획에서만 제외", "POST 오늘 목록 제외; 태스크 삭제·취소 아님", "오늘 목록에서 빼기")
register("today_restore", "제외했던 오늘 계획 복원", "POST 본인 제외 항목 복원", "오늘 목록에 복원")
register("today_move", "오늘 순서 조정", "POST 해당 태스크를 up/down 이동", "오늘 목록에서 위로 / 아래로")
register("today_settings", "목표일 기준 자동 추가 조정", "change POST auto_pull_days 저장", "목표일 기준 자동 추가 · N일 이내")
register("task_delete", "태스크 영구 제거", "POST 태스크 삭제", "태스크 삭제")
register("task_text", "태스크 내용 편집", "POST 지정 field 저장; change, 메모는 keyup 600ms도 적용", "필드 이름 유지 + 자동 저장 시점 안내")
register("task_meta", "담당자·프로젝트·기한 미정 사유 변경", "change POST 메타 정보 저장", "필드 이름 유지 + 저장 시점 안내")
register("task_status", "태스크 상태 전환", "POST 상태 변경; 막힘은 사유 입력 먼저; 서버 규칙 적용", "태스크 전체 상태임을 명시; 상태 선택은 유지")
register("task_priority", "태스크 중요도 조정", "change POST 중요도 저장", "중요도 라벨 유지")
register("task_extend", "목표일 최초 지정 또는 연장", "POST 날짜·사유 저장; 같은 연장 폼 사용", "목표일 저장 / 목표일 연장")
register("task_stop_reason", "일시정지·막힘 사유 기록", "POST 사유 저장; block_pending이면 막힘으로 전환", "막힘으로 변경 / 사유 저장")
register("checklist_add", "체크 항목 등록", "POST 체크리스트 생성", "체크 항목 추가")
register("checklist_action", "체크 항목 완료·순서·삭제 관리", "POST action=toggle/up/down/delete", "항목 완료/위로/아래로/삭제; 대상 접근성 이름")
register("task_link_add", "태스크 참고 주소 등록", "POST Link 등록", "외부 링크 추가")
register("link_delete", "참고 링크만 제거", "POST Link 레코드 삭제; 외부 사이트 유지", "링크 삭제")
register("decision_confirm", "수집된 내 의사결정이 맞다고 확인", "POST 본인 user_input confirmed 전환; AI 판단 승인 아님", "내 의사결정으로 확인")
register("decision_reject", "내 입력 기록 제외", "POST rejected 전환; 원본 감사 기록 보존", "기록 제외")
register("decision_supersede", "의사결정 기록을 이력으로 정정", "POST 원본과 연결된 새 정정 기록 생성", "정정 기록 저장")
register("team_new", "새 PM 팀 생성", "GET 다이얼로그; POST 팀 생성", "새 팀 / 팀 만들기")
register("team_edit", "PM 팀 정보 수정", "GET 폼; POST 변경 저장·조건부 GitHub 반영", "팀 수정 / 변경 내용 저장")
register("team_delete", "PM 팀 제거", "POST 팀 삭제; 멤버·프로젝트·GitHub 팀 유지", "팀 삭제")
register("team_member_add", "PM 팀에 멤버 등록", "POST PM 추가·조건부 GitHub 팀 추가 요청", "팀 멤버 추가")
register("team_member_remove", "PM 팀에서 멤버 제외", "POST PM 제거·조건부 GitHub 팀 제거 요청", "팀에서 제거")
register("team_github_link", "기존 GitHub 팀 연결", "POST PM 연결 생성; 멤버 반영은 별도", "선택한 GitHub 팀 연결")
register("team_github_create", "외부 팀 생성 및 연결", "POST GitHub 새 팀 생성 후 PM 연결", "GitHub 팀 만들고 연결")
register("team_github_unlink", "팀 연결만 해제", "POST PM 연결 삭제; 외부 팀 유지", "GitHub 팀 연결 해제")
register("team_github_reconcile", "PM 멤버를 GitHub에도 등록", "POST 활성 PM 멤버 추가 요청; 외부에만 있는 멤버 제거 안함", "GitHub에 멤버 추가")
register("member_role", "조직 멤버 역할 변경", "select change POST 조직 역할 저장", "조직 역할 라벨 유지")
register("member_tags", "멤버 기술 등록", "POST 기술 태그 저장", "기술 태그 저장")
register("member_remove", "조직에서 멤버 제외", "POST 조직 제거·조건부 GitHub 조직 제거 요청; 태스크 담당 유지", "조직에서 제거")
register("invite_create", "참여 초대 발급", "POST 초대 링크 생성; gh_invite면 조건부 외부 초대 요청; 기간 검증 fallback 별도 문제", "초대 링크 만들기")
register("invite_revoke", "초대 사용 중단", "POST 초대 폐기", "초대 링크 폐기")
register("milestone_new", "마일스톤 생성", "GET 폼; POST 생성", "새 마일스톤 / 마일스톤 만들기")
register("milestone_edit", "마일스톤 수정", "GET 폼; POST 저장", "마일스톤 수정 / 변경 내용 저장")
register("dependency_add", "프로젝트 의존 관계 등록", "POST from_project→to_project 데이터 생성; 착수 자동 차단 보장 아님", "프로젝트 의존 관계 추가")
register("dependency_delete", "의존 관계만 제거", "POST 관계 레코드 삭제; 프로젝트 유지", "의존 관계 삭제")
register("discord_link", "개인 Discord 계정 연결 준비", "POST 연결 코드 발급; 연결 완료는 봇 DM 후속 단계", "Discord 연결 코드 받기")
register("discord_unlink", "Discord 연결 중단", "개인 화면은 계정 연결, 조직 화면은 서버 연결 해제; 동일 URL 이름의 인자 구분", "Discord 계정/서버 연결 해제")
register("discord_connect", "조직 Discord 서버 연결 시작", "GET Discord 설치·권한 선택 단계", "Discord 서버 연결")
register("github_connect", "개인 GitHub 연동 시작", "GET 외부 OAuth 권한 확인 단계", "GitHub 계정 연결")
register("github_refresh", "접근 가능한 저장소 갱신", "POST 개인 저장소 캐시 갱신 후 프로필 이동", "접근 가능한 저장소 다시 확인")
register("github_unlink", "개인 GitHub 인증 연결 중단", "POST GitHubIdentity 삭제; 외부 계정 유지", "GitHub 계정 연결 해제")
register("github_install", "조직 GitHub App 설치 시작", "GET 외부 앱 설치·권한 선택 화면", "GitHub 앱 설치")
register("repo_disconnect", "프로젝트와 저장소 연결 해제", "POST RepoConnection 해제; 외부 저장소 유지", "저장소 연결 해제")
register("repo_settings", "저장소 연동 규칙 저장", "POST 기본 담당·자동 가져오기 등 규칙 저장", "저장소 규칙 저장")
register("repo_issues_sync", "최신 저장소 이슈 확인", "POST GitHub 열린 이슈 갱신; 자동 가져오기 규칙 영향 별도", "GitHub 이슈 새로 확인")
register("project_issues_sync org_issues_sync", "GitHub 이슈 갱신", "POST 해당 프로젝트/조직 이슈 캐시 갱신; 일부 실패 가능", "GitHub에서 새로 고침")
register("repo_issue_import project_issue_import org_issue_import", "이슈를 내가 맡을 태스크로 등록", "POST actor 담당 태스크 생성·이슈 연결; 이미 가져왔으면 기존 태스크 반환", "내 태스크로 가져오기")
register("repo_event_link", "GitHub 이벤트를 태스크 증거로 연결", "POST 이벤트의 task 참조 저장; 태스크 생성·상태 변경 아님", "태스크에 이벤트 연결")
register("git_issue", "기존 이슈 연결", "POST GitHub 이슈 번호 연결", "이슈 연결")
register("git_issue_create", "외부 이슈 생성", "POST GitHub 이슈 생성 후 태스크 연결", "GitHub 이슈 만들기")
register("git_issue_close", "완료 태스크의 외부 이슈 닫기", "POST 완료·열린 이슈 조건 확인 후 외부 닫기 요청", "이슈 #N 닫기")
register("git_branch", "기존 브랜치 연결", "POST 브랜치 참조 연결", "브랜치 연결")
register("git_branch_create", "외부 브랜치 생성", "POST GitHub 브랜치 생성 후 연결", "GitHub 브랜치 만들기")
register("git_unlink", "태스크 외부 참조만 해제", "POST what=issue/branch/pr/all 참조 해제; 외부 객체 삭제 아님", "대상 연결 해제 / 이 태스크의 GitHub 연결 모두 해제")
register("token_revoke", "API 인증 수단 사용 중단", "POST 본인 토큰 revoke", "토큰 폐기")
register("portfolio_prompt", "외부 AI에 작성 요청 준비", "POST 선택 출처로 프롬프트 생성; 앱 내 초안 자동 생성 아님", "선택한 출처로 AI 프롬프트 만들기 유지(Astra)")
register("portfolio_create", "AI 결과를 개인 초안으로 보관", "POST 붙여 넣은 Markdown·출처로 비공개 초안 생성", "비공개 초안 저장")
register("portfolio_save", "편집한 초안 저장", "POST 제목·Markdown 저장; 버전 충돌 검사", "초안 저장")
register("portfolio_export", "저장된 초안 파일 확보", "GET 서버 저장 Markdown 다운로드; 미저장 본문 제출 안함", "Markdown 다운로드 유지 + 저장된 내용만 내보낸다는 안내 후보")
register("export_json", "운영 데이터 파일 확보", "GET 지정 모델 전체 레코드 JSON; 문서·회의록 등 제외되어 완전 백업 아님", "운영 데이터 JSON 내보내기")


def evaluate(c, routes):
    attrs = c["attrs"]
    if c["id"] in CONTEXT["perControl"]:
        return dict(CONTEXT["perControl"][c["id"]], status="개별 검토")
    if attrs.get("data-action"):
        return dict(CONTEXT["jsInfo"][attrs["data-action"]], status="JS 동작 대조")
    if "data-copy" in attrs or "data-copy-text" in attrs:
        return dict(purpose="해당 주소·텍스트 전달", effect="JS clipboard 복사; 실패 수동 prompt 취소에도 성공 안내 가능",
                    recommendation="대상을 포함한 복사 문구; 성공 분기 수정", evidence="core/web/static/app.js:131",
                    status="동작 수정 필요")
    if c["tag"] == "summary":
        return dict(purpose="해당 묶음·상세 내용 확인", effect="HTML details 접힘/펼침; 데이터 변경 없음",
                    recommendation="문맥이 드러나는 현재 제목 유지", evidence=f'{c["file"]}:{c["line"]}', status="소스 대응")
    if c["id"] in CONTEXT["selfInfo"]:
        return dict(CONTEXT["selfInfo"][c["id"]], status="소스 동작 대조")
    if c["routes"]:
        definitions = [SEMANTICS[r] for r in c["routes"]]
        method = "POST" if attrs.get("hx-post") else "GET" if attrs.get("hx-get") or attrs.get("href") else (
            "POST" if c["form"].get("hx-post") else "GET" if c["form"].get("hx-get") else c["form"].get("method", "get").upper())
        evidence = "; ".join(item["evidence"] for r in c["routes"] for item in routes[r])
        return dict(purpose=" / ".join(d["purpose"] for d in definitions),
                    effect=method + " · " + " / ".join(d["effect"] for d in definitions),
                    recommendation=" / ".join(d["recommendation"] for d in definitions), evidence=evidence,
                    status="소스 동작 대조")
    if attrs.get("href"):
        return dict(purpose="관련 자료·설정 열기", effect="GET " + attrs["href"] + (" 새 탭" if attrs.get("target") == "_blank" else ""),
                    recommendation="대상 제목 유지; 변수 URL의 실제 값은 데이터별 확인 필요",
                    evidence=f'{c["file"]}:{c["line"]}', status="동적 URL/외부 화면 미검증")
    return dict(purpose="확인 불가", effect="독립 동작 근거 추가 확인 필요", recommendation="확정 문구 없음",
                evidence=f'{c["file"]}:{c["line"]}', status="확인 불가")


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", "")


def main():
    files, controls = extract()
    routes = route_index()
    used = {r for c in controls for r in c["routes"]}
    missing = used - SEMANTICS.keys()
    if missing:
        raise RuntimeError(f"Missing route semantics: {missing}")
    for c in controls:
        c["review"] = evaluate(c, routes)
    unresolved = [c["id"] for c in controls if c["review"]["status"] == "확인 불가"]
    if unresolved:
        raise RuntimeError(f"Unresolved control sites: {unresolved}")
    payload = {"date": "2026-10-04", "head": "134ae90320d01dcb64131a0dc33df78cc44a8e7a",
               "template_count": len(files), "control_count": len(controls),
               "tags": dict(Counter(c["tag"] for c in controls)), "used_route_names": len(used),
               "templates": [f.relative_to(ROOT).as_posix() for f in files], "controls": controls,
               "routes": routes, "route_semantics": {r: SEMANTICS[r] for r in sorted(used)}}
    with (OUT / "button-purpose-inventory.json").open("x", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    lines = ["# UI-UX 전체 버튼·링크 목적성 인벤토리", "", "2026-10-04 · 현재 UI-UX 소스 기준. 앱 수정 없음.", "",
             f"템플릿 {len(files)}개 전체에서 컨트롤 위치 {len(controls)}곳, URL 이름 {len(used)}개를 대조했다.", "",
             "한 행은 템플릿의 컨트롤 위치다. 반복 데이터 개수와 조건 분기를 펼친 실제 DOM 개수가 아니다. 조건부 문구는 병기한다.",
             "입력 컨트롤의 현재 값·선택지, 아이콘과 접근성 이름도 함께 기록한다. JS가 숨기는 fallback 저장 버튼은 별도 판정한다.",
             "GET/POST는 클릭·폼 제출을 구분한다. 펼치기·취소·복사 등 JS 동작은 상위 폼의 POST보다 우선하여 대조했다.",
             "소스 대응 판정은 실제 동작 성공·모든 권한 분기의 브라우저 통과를 의미하지 않는다. 외부 URL 값과 데이터별 제목은 미확정이다.", "",
             "[최종 검토·범위·Astra 화면 검증](UX_BUTTON_PURPOSE_REVIEW.md) · [원시 속성·라우트 JSON](button-purpose-inventory.json)", ""]
    previous = None
    for c in controls:
        if c["file"] != previous:
            previous = c["file"]
            lines += ["", f'## {previous.removeprefix("core/web/templates/")}', "",
                      "| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |",
                      "| --- | --- | --- | --- | --- | --- |"]
        r = c["review"]
        label = c["visibleLabel"]
        if c["accessibleLabel"] != label:
            label += " / 접근성: " + c["accessibleLabel"]
        source = f'{c["id"]} · `{c["file"]}:{c["line"]}`'
        lines.append("| " + " | ".join(map(cell, (source, label, r["purpose"], r["effect"], r["recommendation"],
                                                       r["evidence"] + " · " + r["status"]))) + " |")
    lines += ["", "## 컨트롤이 없는 템플릿도 조사 범위에 포함", ""]
    present = {c["file"] for c in controls}
    lines += [f'- `{f.relative_to(ROOT).as_posix()}`' for f in files if f.relative_to(ROOT).as_posix() not in present]
    with (OUT / "UX_BUTTON_PURPOSE_INVENTORY.md").open("x", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(json.dumps({"templates": len(files), "controls": len(controls), "route_names": len(used),
                      "unresolved": unresolved, "tags": payload["tags"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
