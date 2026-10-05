# 구현 지시서 V2-06: 프로젝트 API 문서 (6단계)

목표: 프로젝트에 OpenAPI 문서를 붙이고 Swagger 방식으로 그린다. 스펙은 **주소에서 서버가 받아 오거나 파일로 올린다.** 브라우저가 직접 받아 오는 경로는 만들지 않는다.

목업에는 브라우저 `fetch` 갈래가 있지만 쓰지 않는다. 두 경로를 두면 CORS 오류 문구 같은 분기가 두 벌이 되고, README 자신이 서버 프록시를 권했다. 로컬 개발 서버의 스펙은 서버가 볼 수 없으므로 **파일로 올린다.**

---

## 1. Step 1. 모델

`projects/models.py`:

```python
class ApiSpec(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="api_spec")
    source_url = models.CharField("출처", max_length=500, blank=True)
    spec = models.JSONField()
    fetched_at = models.DateTimeField(auto_now=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    def __str__(self):
        return f"{self.project.name} API"
```

`$ref`는 풀지 않는다. 받은 JSON을 그대로 저장하고 화면에는 문자 그대로 보여 준다.

---

## 2. Step 2. 서비스

`projects/services.py`에 더한다.

```python
import json
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

SPEC_MAX = 5 * 1024 * 1024
SPEC_TIMEOUT = 10
METHOD_COLOR = {
    "get": "#1F6F82", "post": "#12793F", "patch": "#A85B00",
    "put": "#2F6FBF", "delete": "#C92A37",
}


def parse_spec(raw: bytes, *, source: str) -> dict:
    if len(raw) > SPEC_MAX:
        raise ServiceError({"spec": "스펙이 너무 큽니다 (5MB 상한)."})
    try:
        spec = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ServiceError({"spec": f"{source}를 JSON으로 읽지 못했습니다."}) from None
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise ServiceError({"spec": "OpenAPI 문서가 아닙니다 (paths 없음)."})
    return spec


def fetch_spec(url: str) -> dict:
    """주소에서 OpenAPI JSON을 받는다. 브라우저가 아니라 서버가 받는다.

    # ponytail: 로그인한 조직 멤버만 부를 수 있고 스킴·크기·시간만 막는다.
    # 사내 주소까지 막아야 하면 여기에 호스트 검사를 더한다.
    """
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ServiceError({"spec": "http:// 또는 https:// 주소를 입력하세요."})
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "udally"})
    try:
        with urlopen(req, timeout=SPEC_TIMEOUT) as r:  # noqa: S310 — 스킴을 위에서 검사했다
            raw = r.read(SPEC_MAX + 1)
    except URLError as e:
        raise ServiceError({"spec": f"주소를 읽지 못했습니다: {e.reason}"}) from None
    except OSError as e:
        raise ServiceError({"spec": f"주소를 읽지 못했습니다: {e}"}) from None
    return parse_spec(raw, source=url)


def set_api_spec(project, spec: dict, *, source_url: str, actor) -> ApiSpec:
    if not is_member(actor, project.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    obj, _ = ApiSpec.objects.update_or_create(
        project=project,
        defaults={"spec": spec, "source_url": source_url[:500], "uploaded_by": actor},
    )
    return obj
```

화면용 변환. 목업 `renderVals().api`가 하던 일이다.

```python
def spec_view(spec: dict, q: str = "") -> dict:
    """OpenAPI 문서를 태그별 그룹으로 바꾼다. 화면에 필요한 것만 뽑는다."""
    q = (q or "").strip().lower()
    info = spec.get("info") or {}
    tag_desc = {
        t.get("name"): t.get("description", "")
        for t in (spec.get("tags") or [])
        if isinstance(t, dict)
    }
    groups, order = {}, []
    for path, ops in (spec.get("paths") or {}).items():
        if not isinstance(ops, dict):
            continue
        for method, op in ops.items():
            m = method.lower()
            if m not in METHOD_COLOR or not isinstance(op, dict):
                continue
            summary = op.get("summary") or ""
            if q and q not in f"{path} {summary} {m}".lower():
                continue
            tag = ((op.get("tags") or ["기타"]) or ["기타"])[0]
            if tag not in groups:
                groups[tag] = {"tag": tag, "desc": tag_desc.get(tag, ""), "ops": []}
                order.append(tag)
            body = None
            content = ((op.get("requestBody") or {}).get("content") or {})
            for ctype, c in content.items():
                example = (c or {}).get("example")
                body = {
                    "type": ctype,
                    "example": json.dumps(example, ensure_ascii=False, indent=2) if example else "",
                }
                break
            params = []
            for pa in op.get("parameters") or []:
                if not isinstance(pa, dict):
                    continue
                sc = pa.get("schema") or {}
                bits = [pa.get("in", ""), sc.get("type", "string")]
                if pa.get("required"):
                    bits.append("필수")
                if sc.get("enum"):
                    bits.append(" | ".join(str(x) for x in sc["enum"]))
                if sc.get("default") is not None:
                    bits.append(f"기본 {sc['default']}")
                params.append(
                    {"name": pa.get("name", ""), "meta": " · ".join(b for b in bits if b),
                     "desc": pa.get("description", "")}
                )
            responses = []
            for code, r in (op.get("responses") or {}).items():
                code = str(code)
                responses.append({
                    "code": code,
                    "desc": (r or {}).get("description", ""),
                    "bg": "#B9E6CB" if code.startswith("2") else "#F6C9C4" if code.startswith("4") else "#F0F4F6",
                    "color": "#0B3D22" if code.startswith("2") else "#6B1410" if code.startswith("4") else "#636D7A",
                })
            groups[tag]["ops"].append({
                "method": m.upper(),
                "color": METHOD_COLOR[m],
                "path": path,
                "summary": summary,
                "desc": op.get("description", ""),
                "auth": bool(op.get("security")),
                "params": params,
                "body": body,
                "responses": responses,
            })
    out = [groups[t] for t in order]
    return {
        "title": info.get("title") or "제목 없는 API",
        "version": f"v{info['version']}" if info.get("version") else "버전 없음",
        "openapi": spec.get("openapi") or spec.get("swagger") or "—",
        "server": ((spec.get("servers") or [{}])[0] or {}).get("url") or "서버 정보 없음",
        "desc": info.get("description", ""),
        "groups": out,
        "count": sum(len(g["ops"]) for g in out),
    }
```

---

## 3. Step 3. 뷰와 URL

```
projects/<int:project_id>/api          project_api      GET(?q=&part=endpoints) · POST
```

```python
@login_required
def project_api(request, project_id):
    project = project_or_404(request.user, project_id)
    error = None
    if request.method == "POST":
        try:
            upload = request.FILES.get("file")
            if upload:
                if not upload.name.lower().endswith(".json"):
                    raise ServiceError({"spec": ".json 파일만 올릴 수 있습니다."})
                spec = parse_spec(upload.read(SPEC_MAX + 1), source=upload.name)
                source = upload.name
            else:
                source = request.POST.get("url", "")
                spec = fetch_spec(source)
            set_api_spec(project, spec, source_url=source, actor=request.user)
            return redirect("project_api", project_id=project.pk)
        except ServiceError as e:
            error = " ".join(e.errors.values())

    obj = getattr(project, "api_spec", None)
    q = request.GET.get("q", "")
    ctx = {
        "project": project, "tab": "api", "q": q, "error": error,
        "spec_obj": obj,
        "api": spec_view(obj.spec, q) if obj else None,
    }
    if request.GET.get("part") == "endpoints":
        return render(request, "projects/_endpoints.html", ctx)
    return render(request, "projects/api.html", ctx)
```

`projects/_tabs.html`에 한 줄 더한다.

```html
  <a href="{% url 'project_api' project.pk %}" {% if tab == "api" %}aria-current="page"{% endif %}>API 문서</a>
```

### HTTP API

`api/routers/projects.py`에 둘을 더한다. CI가 `openapi.json`을 밀어 넣는 용도다(쓰기 토큰 필요).

```python
@router.get("/{project_id}/api-spec", response=dict)
def get_api_spec(request, project_id: int):
    p = _project_or_404(request, project_id)
    obj = getattr(p, "api_spec", None)
    if obj is None:
        raise HttpError(404, "등록된 API 문서가 없습니다.")
    return {"source_url": obj.source_url, "fetched_at": obj.fetched_at, "spec": obj.spec}


@router.put("/{project_id}/api-spec", response={200: dict, 400: ErrorOut})
def put_api_spec(request, project_id: int, payload: ApiSpecIn):
    p = _project_or_404(request, project_id)
    spec = parse_spec(json.dumps(payload.spec).encode(), source=payload.source_url or "요청 본문")
    obj = set_api_spec(p, spec, source_url=payload.source_url, actor=request.auth)
    return {"ok": True, "fetched_at": obj.fetched_at}
```

```python
class ApiSpecIn(Schema):
    spec: dict
    source_url: str = ""
```

---

## 4. Step 4. 화면

`projects/api.html` 카드 둘이다.

**스펙 헤더**

- 왼쪽: 제목(20/28, 700) · 버전 배지 · 서버 URL(monospace) · `OpenAPI 3.0.3` · 설명
- 오른쪽: 주소 입력 + [주소에서 불러오기] + [파일]. 아래 한 줄에 출처와 시각

```html
<form method="post" enctype="multipart/form-data" class="row">{% csrf_token %}
  <input class="input" name="url" value="{{ spec_obj.source_url }}" placeholder="https://example.com/openapi.json" style="flex:1 1 200px">
  <button class="btn sm primary">주소에서 불러오기</button>
  <label class="btn sm">파일<input type="file" name="file" accept=".json,application/json" hidden onchange="this.form.requestSubmit()"></label>
</form>
<span class="t12 muted">{% if spec_obj %}{{ spec_obj.source_url }} · {{ spec_obj.fetched_at|date:"n/j H:i" }} 저장됨{% else %}아직 등록된 문서가 없습니다.{% endif %}</span>
```

입력칸에서 Enter를 누르면 폼이 그대로 제출된다(버튼이 하나뿐이라 따로 처리하지 않는다).

오류는 카드 안에 붉은 문단으로 띄운다. 로컬 주소를 넣어 실패했을 때를 위해 안내 한 줄을 함께 둔다: "서버가 읽을 수 없는 주소(예: `localhost`)라면 파일로 올리세요."

**엔드포인트** (`projects/_endpoints.html`)

```html
<div id="endpoints" class="stack">
  {% for g in api.groups %}
  <div class="stack">
    <div class="row" style="border-bottom:1px solid var(--border);padding-bottom:4px">
      <span class="t15" style="font-weight:700">{{ g.tag }}</span>
      <span class="t12 muted">{{ g.desc }}</span>
    </div>
    {% for op in g.ops %}
    <details class="op">
      <summary>
        <span class="method" style="background:{{ op.color }}">{{ op.method }}</span>
        <code class="path">{{ op.path }}</code>
        <span class="t13 muted grow">{{ op.summary }}</span>
        {% if op.auth %}<span class="badge">인증</span>{% endif %}
      </summary>
      ...파라미터·요청 본문·응답...
    </details>
    {% endfor %}
  </div>
  {% empty %}<p class="muted">조건에 맞는 엔드포인트가 없습니다.</p>{% endfor %}
</div>
```

검색은 카드 머리의 입력칸이 부분 렌더를 부른다.

```html
<input class="input auto" name="q" value="{{ q }}" placeholder="경로·요약 검색" aria-label="엔드포인트 검색"
       hx-get="{% url 'project_api' project.pk %}?part=endpoints" hx-target="#endpoints" hx-swap="outerHTML"
       hx-trigger="keyup changed delay:300ms">
```

```css
.op > summary { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; min-height: 48px; padding: 8px 12px; }
.op { border: 1px solid var(--border); border-radius: 8px; }
.op[open] { border-color: var(--primary); background: var(--bg-secondary); }
.op .method { min-width: 64px; padding: 0 8px; border-radius: 4px; color: #fff; font-size: 12px; line-height: 24px; font-weight: 700; text-align: center; }
.op .path { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; font-weight: 600; }
.op .grow { flex: 1 1 160px; min-width: 0; }
.op pre { margin: 0; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); overflow-x: auto; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; line-height: 18px; }
```

스펙이 없으면 카드 하나만 보여 준다: "이 프로젝트에 등록된 API 문서가 없습니다. 주소를 넣거나 `openapi.json`을 올리세요."

---

## 5. 테스트

| 이름 | 확인 |
|---|---|
| `test_spec_rejects_without_paths` | `paths` 없는 JSON은 400 |
| `test_spec_rejects_non_json` | 깨진 JSON은 400 |
| `test_spec_rejects_bad_scheme` | `file://`·`ftp://`는 거부 |
| `test_spec_rejects_oversize` | 5MB 초과 거부 |
| `test_spec_upload_json_only` | `.txt` 거부 |
| `test_spec_saved_and_replaced` | 두 번 올리면 덮어쓴다(프로젝트당 하나) |
| `test_spec_view_groups_by_tag` | 태그별 묶음과 개수 |
| `test_spec_view_search_filters` | `?q=`가 경로·요약으로 거른다 |
| `test_spec_view_method_colors` | 다섯 메서드 색이 표대로 |
| `test_spec_view_handles_missing_fields` | `info`·`tags`·`responses`가 없어도 안 터진다 |
| `test_api_spec_put_endpoint` | 쓰기 토큰으로 `PUT`이 되고 읽기 토큰은 403 |
| `test_api_tab_requires_membership` | 다른 조직 사람은 404 |

`fetch_spec`은 네트워크를 타므로 단위 테스트에서 `urlopen`을 `monkeypatch`한다. 실제 호출 테스트는 만들지 않는다.

## 6. 검증

이 프로젝트 자신의 문서로 확인한다.

```bash
cd core && uv run python manage.py runserver
# 다른 창에서
curl -s http://127.0.0.1:8000/api/openapi.json -o /tmp/openapi.json
```

프로젝트 → API 문서에서 그 파일을 올리면 태그별로 엔드포인트가 그려지고, 검색창에 `tasks`를 치면 태스크 것만 남는다.

## 7. 완료 체크

- [ ] 브라우저가 직접 스펙을 받아 오는 코드가 없다
- [ ] 스킴·크기·시간 제한과 `paths` 검사가 있다
- [ ] 프로젝트당 스펙 하나(`OneToOne`)
- [ ] 검색이 부분 렌더로 동작한다
- [ ] `PUT /api/projects/{id}/api-spec`이 쓰기 토큰에서만 된다
