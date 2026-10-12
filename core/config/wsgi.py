"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()


# 워커가 처음 받는 요청은 URLconf(API 스키마 생성 포함)와 템플릿 컴파일로 0.4초쯤 더 걸린다(로컬 기준).
# 워커 2개 중 아직 안 데워진 쪽으로 간 첫 클릭(태스크 패널 등)이 굼뜨지 않게 워커가 뜰 때 미리 해 둔다.
def _warm():
    from pathlib import Path

    from django.template import engines
    from django.urls import get_resolver

    get_resolver().url_patterns  # noqa: B018 — 불러오기 자체가 목적
    backend = engines["django"]
    for root in backend.template_dirs:
        for f in Path(root).rglob("*.html"):
            try:
                backend.get_template(f.relative_to(root).as_posix())
            except Exception:  # noqa: BLE001 — 미리 데우기일 뿐, 실패해도 첫 요청에서 다시 컴파일된다
                pass


_warm()
