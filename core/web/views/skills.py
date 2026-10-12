"""Claude Code 스킬(저장소 skills/pm, pm-*)과 한 줄 설치 스크립트. 로그인 없이 받는 공개 파일이다(비밀값 없음)."""

import io
import zipfile

from django.conf import settings
from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET

SCRIPTS = settings.BASE_DIR / "web" / "skills_install"
TYPES = {"ps1": "text/plain; charset=utf-8", "sh": "text/x-shellscript; charset=utf-8"}


@require_GET
def install(request, ext):
    if ext not in TYPES:
        raise Http404
    # 요청한 주소로 설치해야 토큰도 그 주소로 받는다
    base = request.build_absolute_uri("/").rstrip("/")
    body = (SCRIPTS / f"install.{ext}").read_text(encoding="utf-8").replace("\r\n", "\n")
    return HttpResponse(body.replace("__BASE__", base), content_type=TYPES[ext])


@require_GET
def bundle(request):
    # ponytail: 요청마다 새로 묶는다(파일 10여 개, 수 KB). 요청이 많아지면 빌드 때 한 번 만든다.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for d in sorted(settings.SKILLS_DIR.glob("pm*")):
            for f in sorted(d.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    z.write(f, f.relative_to(settings.SKILLS_DIR).as_posix())
    resp = HttpResponse(buf.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = 'attachment; filename="udally-skills.zip"'
    return resp
