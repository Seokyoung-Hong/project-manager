from datetime import timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm

from accounts.models import User
from common.dates import today_kst
from orgs import settings as S
from orgs.models import Team
from projects.models import Project
from tasks.models import Link

PRIORITY_CHOICES = [(n, str(n)) for n in range(10, 0, -1)]


def _business_days_from(start, n):
    """start + n영업일(월~금, 공휴일 없음).
    # ponytail: 공휴일 표가 필요해지면 여기만 바꾼다.
    """
    d = start
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "display_name")
        labels = {"username": "아이디", "display_name": "표시 이름"}


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


class TaskForm(forms.Form):
    """전체 수정 화면(/tasks/{id}/edit). 담당자·프로젝트·기한 미정 사유는 여기서만 바꾼다."""

    project = forms.ModelChoiceField(label="프로젝트", queryset=Project.objects.none())
    title = forms.CharField(label="제목", max_length=200)
    assignee = forms.ModelChoiceField(label="담당자", queryset=User.objects.none())
    priority = forms.TypedChoiceField(
        label="중요도", choices=PRIORITY_CHOICES, coerce=int, initial=5
    )
    due_date = forms.DateField(
        label="목표 기한", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    no_due_reason = forms.CharField(label="기한 미정 사유", max_length=200, required=False)
    description = forms.CharField(
        label="설명", required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    done_when = forms.CharField(label="완료 조건", max_length=300, required=False)
    next_action = forms.CharField(label="다음 행동", max_length=200, required=False)
    version = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(self, *args, org, reason_required=False, **kwargs):
        super().__init__(*args, **kwargs)
        if reason_required:
            # task.assignee_change_reason·task.due_change_reason이 켜져 있을 때만 보인다.
            self.fields["reason"] = forms.CharField(
                label="변경 사유",
                max_length=300,
                required=False,
                widget=forms.TextInput(attrs={"placeholder": "변경 사유"}),
            )
        self.fields["project"].queryset = Project.objects.filter(
            org=org, is_archived=False
        ).order_by("name")
        self.fields["assignee"].queryset = org.members.filter(is_active=True).order_by(
            "display_name"
        )


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
        if project is not None and not self.is_bound:
            self.fields["priority"].initial = S.effective("task.default_priority", project=project)
            days = S.effective("task.default_due_days", project=project)
            if days > 0:
                self.fields["due_date"].initial = _business_days_from(today_kst(), days)


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
