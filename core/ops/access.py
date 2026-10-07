from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import Http404


def ops_required(view):
    """서비스 운영자. 아니면 404(존재를 숨긴다 — github_retries와 같은 규칙)."""

    @wraps(view)
    def inner(request, *a, **kw):
        if not request.user.is_staff:
            raise Http404
        return view(request, *a, **kw)

    return login_required(inner)


def superuser_required(view):
    """최고 운영자(서비스 운영자이면서 superuser)."""

    @wraps(view)
    def inner(request, *a, **kw):
        if not request.user.is_superuser:
            raise Http404
        return view(request, *a, **kw)

    return ops_required(inner)
