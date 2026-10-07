"""조직마다 깔아 두는 템플릿 2개(IMPL-PLAN-11 §4.2). 개발일지 템플릿은 두지 않는다(결정 5).

마이그레이션(역사 모델)과 orgs.services.create_org가 같이 쓰므로 모델 클래스를 인자로 받는다.
"""

TEMPLATES = [
    (
        "meeting",
        "회의록",
        "## 회의 주제\n\n\n## 내용\n\n\n## 결정\n\n\n## 할 일\n\n- [ ] \n",
    ),
    (
        "doc",
        "설계 문서",
        "## 배경\n\n\n## 결정\n\n\n## 대안\n\n\n## 영향\n\n",
    ),
]


def seed(doc_model, org_id: int, user_id: int):
    doc_model.objects.bulk_create(
        [
            doc_model(
                org_id=org_id,
                kind=kind,
                title=title,
                body_md=body,
                is_template=True,
                created_by_id=user_id,
                updated_by_id=user_id,
            )
            for kind, title, body in TEMPLATES
        ]
    )
