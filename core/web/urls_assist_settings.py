"""AI 자동완성 설정·운영 경로(IMPL-PLAN-12 §7.5). 이름은 A0가 고정했다 — 뷰는 B 갈래(경로 추가는 B가 해도 된다)."""

from django.urls import path

from .views import assist_settings as v

urlpatterns = [
    # 설정 AI 탭(사용자)
    path("settings/ai", v.ai_index, name="settings_ai"),
    path("settings/ai/new", v.ai_add, name="settings_ai_add"),
    path(
        "settings/ai/<int:source_id>", v.ai_row, name="settings_ai_row"
    ),  # GET 행·POST 고치기·끄기
    path(
        "settings/ai/<int:source_id>/move/<str:direction>", v.ai_move, name="settings_ai_move"
    ),  # up|down
    path("settings/ai/<int:source_id>/delete", v.ai_delete, name="settings_ai_delete"),
    path("settings/ai/<int:source_id>/test", v.ai_test, name="settings_ai_test"),
    path("settings/ai/<int:source_id>/models", v.ai_models, name="settings_ai_models"),
    path(
        "settings/ai/<int:source_id>/codex", v.ai_codex, name="settings_ai_codex"
    ),  # GET 로그인 상태·POST action=login|logout
    # 조직 AI [연결 시험]·[모델 불러오기](조직 관리자)
    path("orgs/<int:org_id>/settings/assist-test", v.org_assist_test, name="org_assist_test"),
    path("orgs/<int:org_id>/settings/assist-models", v.org_assist_models, name="org_assist_models"),
    # 운영 콘솔 허용 호스트(staff)
    path("ops/assist", v.ops_assist, name="ops_assist"),
    path("ops/assist/<int:host_id>/delete", v.ops_assist_delete, name="ops_assist_delete"),
]
