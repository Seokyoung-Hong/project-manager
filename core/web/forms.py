from datetime import timedelta

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from accounts.models import User
from orgs.models import Team
from projects.models import Project
from tasks.models import Link

PRIORITY_CHOICES = [(n, str(n)) for n in range(10, 0, -1)]


def suggested_due_date(*, org, project=None):
    """설정의 영업일은 월~금이다. 날짜를 강제하지 않고 생성 폼에 제안만 한다."""
    from common.dates import today_kst
    from orgs.settings import effective

    remaining = effective("task.default_due_days", org=org, project=project)
    if not remaining:
        return ""
    day = today_kst()
    while remaining:
        day += timedelta(days=1)
        if day.weekday() < 5:
            remaining -= 1
    return day.isoformat()


class LoginForm(AuthenticationForm):
    """기본 폼의 라벨은 '사용자 이름'이다 — 가입 화면과 같은 말로 부른다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "아이디"


class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "display_name")
        labels = {"username": "아이디", "display_name": "표시 이름"}
        help_texts = {"username": "영문·숫자와 @ . + - _ 만, 150자 이하"}


class OrgForm(forms.Form):
    name = forms.CharField(label="조직 이름", max_length=100)
    purpose = forms.CharField(label="목적 한 줄", max_length=200, required=False)


class InviteForm(forms.Form):
    days = forms.IntegerField(label="만료(일)", min_value=1, max_value=90, initial=7)
    gh_invite = forms.BooleanField(label="GitHub 조직에도 초대", required=False)
    gh_login = forms.CharField(label="GitHub 로그인", max_length=100, required=False)


class TeamForm(forms.Form):
    # 빈 이름 검사는 services.create_team/update_team이 한다(업무 규칙은 services에만).
    name = forms.CharField(label="이름", max_length=100, required=False)
    purpose = forms.CharField(label="목적", max_length=200, required=False)


class ProjectForm(forms.Form):
    """프로젝트 모달. 관리자는 체크 칩, 상태는 카드형 라디오로 템플릿이 직접 그린다."""

    # 빈 이름 검사는 services.create_project/update_project가 한다(업무 규칙은 services에만).
    name = forms.CharField(label="이름", max_length=100, required=False)
    purpose = forms.CharField(
        label="목적", max_length=200, required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    owners = forms.ModelMultipleChoiceField(
        label="관리자", queryset=User.objects.none(), required=False
    )
    teams = forms.ModelMultipleChoiceField(
        label="담당 팀", queryset=Team.objects.none(), required=False
    )
    status = forms.ChoiceField(label="상태", choices=Project.STATUSES, initial="preparing")
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, org, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owners"].queryset = org.members.filter(is_active=True).order_by("display_name")
        self.fields["teams"].queryset = org.teams.all()


class TaskInlineForm(forms.Form):
    """프로젝트 화면의 태스크 만들기 인라인 폼."""

    title = forms.CharField(max_length=200)
    assignee = forms.ModelChoiceField(queryset=User.objects.none())
    priority = forms.TypedChoiceField(choices=PRIORITY_CHOICES, coerce=int, initial=5)
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    no_due_reason = forms.CharField(max_length=200, required=False)
    # IdempotencyKey.key는 varchar(100)이다. 클라이언트가 보내는 값이므로 폼에서 막는다.
    idem = forms.CharField(widget=forms.HiddenInput, required=False, max_length=100)

    def __init__(self, *args, org, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = org.members.filter(is_active=True).order_by(
            "display_name"
        )
        self.suggested_due_date = suggested_due_date(org=org, project=project)


class QuickTaskForm(forms.Form):
    """오늘 화면의 빠른 추가: 제목·프로젝트·중요도·기한(없으면 사유). 담당자는 본인."""

    title = forms.CharField(max_length=200)
    project = forms.ModelChoiceField(queryset=Project.objects.none())
    priority = forms.TypedChoiceField(choices=PRIORITY_CHOICES, coerce=int, initial=5)
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    no_due_reason = forms.CharField(max_length=200, required=False)
    # IdempotencyKey.key는 varchar(100)이다. 클라이언트가 보내는 값이므로 폼에서 막는다.
    idem = forms.CharField(widget=forms.HiddenInput, required=False, max_length=100)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        from orgs.services import orgs_of

        self.fields["project"].queryset = (
            Project.objects.filter(org__in=orgs_of(user), is_archived=False)
            .select_related("org")
            .order_by("org__name", "name")
        )
        # 선택한 프로젝트의 설정에 맞는 제안을 제공한다. 날짜 입력은 사용자가 결정한다.
        for project in self.fields["project"].queryset:
            project.suggested_due_date = suggested_due_date(org=project.org, project=project)


class LinkForm(forms.Form):
    title = forms.CharField(label="제목", max_length=100)
    url = forms.URLField(label="URL", max_length=500)
    kind = forms.ChoiceField(
        label="종류",
        choices=[(c, label) for c, label in Link.KINDS if c in ("doc", "issue", "dash", "other")],
        initial="doc",
    )


class ProfileForm(forms.Form):
    """Discord 사용자 ID 입력칸은 없다 — 연결은 코드 교환으로만 이뤄진다(GUIDE-00 §3)."""

    display_name = forms.CharField(label="표시 이름", max_length=50)


class TokenForm(forms.Form):
    name = forms.CharField(label="이름", max_length=50)
    scope = forms.ChoiceField(
        label="범위", choices=[("read", "읽기"), ("write", "읽기·쓰기")], initial="read"
    )
    # 조직의 AI 정책(ai.*)이 걸리는지를 정한다. 발급 뒤에는 바꿀 수 없다.
    purpose = forms.ChoiceField(
        label="용도",
        choices=[("ai", "AI 도구(Claude·Codex 등)"), ("person", "사람이 쓰는 스크립트·자동화")],
        initial="ai",
    )
    person_ack = forms.BooleanField(
        label="이 토큰을 AI 도구에 넣지 않겠습니다", required=False
    )

    def clean(self):
        data = super().clean()
        # 사람용 토큰을 AI에 주면 조직의 AI 정책(ai.*)이 전부 풀린다. 실수로 고르지 않게 한 번 더 받는다.
        if data.get("purpose") == "person" and not data.get("person_ack"):
            self.add_error(
                "person_ack", "사람용 토큰은 AI 도구에 넣지 않겠다는 확인이 필요합니다."
            )
        return data
