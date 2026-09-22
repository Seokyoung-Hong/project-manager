// 마크다운 인라인 편집기. 서버는 마크다운을 텍스트로만 다루고, 문서를 그리는 것은 여기뿐이다.
// innerHTML을 쓰지 않는다 — 이것이 XSS를 막는 유일한 장치다. 링크·임베드 주소는 safeUrl을
// 반드시 지나간다(javascript:·data: 따위를 여기서 버린다).
//
// 편집 창이 곧 뷰어다. 줄을 누르면 그 줄만 입력창이 되고, 나머지는 렌더된 상태로 남는다.
// 따로 미리보기 칸을 두지 않는다.
//
// 이 파일은 `.doc` 하나마다 독립으로 붙는다(전에는 페이지당 `#doc` 하나만 붙었다).
// 그래서 (1) HTMX로 나중에 끼워 넣은 본문도 편집기가 되고 — 전에는 원문 textarea가 그대로
// 보였다 —, (2) 한 화면에 문서가 둘인 거버넌스 화면도 둘 다 살아난다.
(function () {
  // ---------- 주소 ----------
  // 링크·이미지·영상이 모두 여기를 지난다. 통과하지 못하면 그냥 글자로 남는다.
  function safeUrl(u) {
    u = (u || "").trim();
    if (/^(https?:\/\/|mailto:)/i.test(u)) return u;
    if (/^\/[^/]/.test(u)) return u; // 같은 사이트 경로. //evil.com은 걸러진다
    return null;
  }

  var YT = /(?:youtube\.com\/(?:watch\?(?:.*&)?v=|shorts\/|embed\/)|youtu\.be\/)([A-Za-z0-9_-]{6,20})/;
  var VIMEO = /vimeo\.com\/(?:video\/)?(\d{6,12})/;
  var IMG_EXT = /\.(png|jpe?g|gif|webp|svg|avif|bmp)([?#]|$)/i;
  var VID_EXT = /\.(mp4|webm|ogv|ogg|mov|m4v)([?#]|$)/i;

  function frame(src, title) {
    var f = document.createElement("iframe");
    f.src = src;
    f.title = title || "임베드";
    f.loading = "lazy";
    f.setAttribute("allowfullscreen", "");
    // no-referrer로 두면 YouTube가 오류 153으로 재생을 거부한다. 오리진만 보내고 경로는 감춘다.
    f.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
    // 임베드가 이쪽 페이지를 건드리지 못하게 막는다. 영상 재생에 필요한 것만 연다.
    f.setAttribute("sandbox", "allow-scripts allow-same-origin allow-presentation");
    return f;
  }

  // 주소 하나를 무엇으로 볼지 정한다. 아무것도 아니면 null — 부르는 쪽이 글자로 되돌린다.
  // force는 `![]()` 문법으로 쓴 경우다. 확장자가 없어도 그림으로 본다.
  function media(url, alt, force) {
    var safe = safeUrl(url);
    if (!safe) return null;
    var m;
    if ((m = YT.exec(safe))) {
      return frame("https://www.youtube-nocookie.com/embed/" + m[1], alt || "YouTube");
    }
    if ((m = VIMEO.exec(safe))) {
      return frame("https://player.vimeo.com/video/" + m[1], alt || "Vimeo");
    }
    if (VID_EXT.test(safe)) {
      var v = document.createElement("video");
      v.src = safe;
      v.controls = true;
      v.preload = "metadata";
      // 재생 단추를 누르는 것이 편집으로 들어가는 것이 되면 안 된다.
      v.addEventListener("click", function (e) { e.stopPropagation(); });
      return v;
    }
    if (force || IMG_EXT.test(safe)) {
      var img = document.createElement("img");
      img.src = safe;
      img.alt = alt || "";
      img.loading = "lazy";
      return img;
    }
    return null;
  }

  function link(url, text) {
    var safe = safeUrl(url);
    if (!safe) return null;
    var a = document.createElement("a");
    a.href = safe;
    a.textContent = text;
    if (/^https?:/i.test(safe)) {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    }
    // 링크를 누르면 링크로 간다. 편집으로 들어가지 않는다.
    a.addEventListener("click", function (e) { e.stopPropagation(); });
    return a;
  }

  // ---------- / 메뉴 ----------
  // 마크다운을 외우지 않아도 되게 하는 지름길이다. 넣는 결과는 전부 위 렌더가 이미 아는
  // 문법이라, 직접 쳐 넣던 방식과 결과가 똑같다 — 대체가 아니라 보조다.
  // keys는 찾기용 별칭이다(한글·영문 둘 다 친다).
  var MENU = [
    { label: "제목 1", hint: "#", keys: "제목1 heading h1 title", ins: "# " },
    { label: "제목 2", hint: "##", keys: "제목2 heading h2", ins: "## " },
    { label: "제목 3", hint: "###", keys: "제목3 heading h3", ins: "### " },
    { label: "글머리 목록", hint: "-", keys: "글머리 불릿 목록 bullet list", ins: "- " },
    { label: "번호 목록", hint: "1.", keys: "번호 순서 목록 number ordered list", ins: "1. " },
    { label: "할 일", hint: "- [ ]", keys: "할일 체크 todo task checkbox", ins: "- [ ] " },
    { label: "인용", hint: ">", keys: "인용 인용문 quote blockquote", ins: "> " },
    { label: "구분선", hint: "---", keys: "구분선 구분 divider rule hr", ins: "---", done: true },
    { label: "코드 블록", hint: "```", keys: "코드 코드블록 code snippet", block: ["```", "", "```"], caret: 4 },
    { label: "이미지", hint: "![](…)", keys: "이미지 그림 사진 image img picture", ins: "![]()", caret: 4 },
    { label: "영상", hint: "![](…)", keys: "영상 동영상 비디오 유튜브 video youtube vimeo", ins: "![]()", caret: 4 },
    { label: "링크", hint: "[](…)", keys: "링크 주소 link url", ins: "[]()", caret: 1 },
  ];

  function menuMatches(q) {
    if (!q) return MENU.slice();
    var t = q.toLowerCase();
    return MENU.filter(function (it) {
      return (it.label + " " + it.keys).toLowerCase().indexOf(t) >= 0;
    });
  }

  var uidSeq = 0;

  function setup(doc) {
    if (doc.dataset.ready === "1") return;
    doc.dataset.ready = "1";

    // id는 페이지 안에서 겹칠 수 있다(거버넌스 화면). 항상 그 문서 안에서만 찾는다.
    var bodyEl = doc.querySelector("#doc-body, .doc-body");
    var src = doc.querySelector("#doc-src, .doc-src");
    if (!bodyEl || !src) return;
    var scope = doc.closest(".card") || document;
    var editorForm = doc.closest("form");
    var editStart = editorForm && editorForm.querySelector(".doc-edit-start");
    var submit = scope.querySelector("#doc-submit, .doc-submit");
    var statusEl = scope.querySelector("#note-status, .note-status");
    var conflictEl = scope.querySelector("#note-conflict, .note-conflict");
    var form = scope.querySelector("[name=csrfmiddlewaretoken]");
    var csrf = form ? form.value : "";

    var lines = src.value.replace(/\r\n/g, "\n").split("\n");
    var version = Number(doc.dataset.version);
    var editing = -1,
      caret = null,
      timer = null,
      dead = false;
    var bodyDirty = false,
      pendingFields = Object.create(null),
      pendingSeq = 0,
      worker = null,
      returning = false,
      navigating = false;
    // 읽기 전용(거버넌스 보기 등): 같은 파서로 그리기만 하고 편집·저장은 하지 않는다.
    var readonly = doc.dataset.readonly === "1";
    // / 메뉴 상태. 한 화면에 문서가 둘일 수 있으므로 id 앞머리를 문서마다 따로 만든다.
    var uid = "slash" + ++uidSeq;
    var menu = null, menuItems = [], menuIdx = 0, menuSig = "";

    src.hidden = true;
    if (submit) submit.hidden = true;

    // ---------- 파싱 ----------
    var EMBED_IMG = /^!\[([^\]\n]*)\]\(([^)\s]+)\)$/;
    var EMBED_URL = /^<?(https?:\/\/[^\s<>]+)>?$/;

    function parse(raw) {
      // 들여쓰기는 버리지 않는다 — 중첩 목록이 화면에서 한 단으로 뭉개지던 원인이다.
      var ind = /^[ \t]*/.exec(raw)[0].replace(/\t/g, "  ").length;
      var t = raw.trim(), m;
      if ((m = /^(#{1,3})\s+(.*)$/.exec(t))) return { type: "h", level: m[1].length, text: m[2], indent: ind };
      if ((m = /^[-*]\s+\[([ xX])\]\s*(.*)$/.exec(t))) return { type: "todo", checked: m[1] !== " ", text: m[2], indent: ind };
      if ((m = /^(\d+)\.\s+(.*)$/.exec(t))) return { type: "li", marker: m[1] + ".", text: m[2], indent: ind };
      if (/^[-*]\s+/.test(t)) return { type: "li", marker: "•", text: t.replace(/^[-*]\s+/, ""), indent: ind };
      if (/^>\s?/.test(t)) return { type: "quote", text: t.replace(/^>\s?/, ""), indent: ind };
      if (/^(---|\*\*\*)$/.test(t)) return { type: "rule", text: "", indent: 0 };
      // 줄 전체가 그림·영상 하나면 블록으로 키워 그린다. 글 사이에 낀 것은 inline이 맡는다.
      if ((m = EMBED_IMG.exec(t))) return { type: "embed", alt: m[1], url: m[2], force: true, text: t, indent: ind };
      if ((m = EMBED_URL.exec(t))) return { type: "embed", alt: "", url: m[1], force: false, text: t, indent: ind };
      return { type: "p", text: t, indent: ind };
    }

    // 이미지 → 링크 → 강조 → 코드 → 맨 URL 순서로 본다.
    var INLINE = /(!\[[^\]\n]*\]\([^)\s]+\)|\[[^\]\n]*\]\([^)\s]+\)|\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|~~[^~]+~~|https?:\/\/[^\s<>()]+)/g;
    var MD_LINK = /^!?\[([^\]\n]*)\]\(([^)\s]+)\)$/;

    function inline(text, parent) {
      var last = 0, m;
      INLINE.lastIndex = 0;
      while ((m = INLINE.exec(text))) {
        if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
        var tok = m[0], el = null, mm;
        if (tok.charAt(0) === "!" && (mm = MD_LINK.exec(tok))) el = media(mm[2], mm[1], true);
        else if (tok.charAt(0) === "[" && (mm = MD_LINK.exec(tok))) el = link(mm[2], mm[1] || mm[2]);
        else if (tok.slice(0, 2) === "**") { el = document.createElement("strong"); el.textContent = tok.slice(2, -2); }
        else if (tok.slice(0, 2) === "~~") { el = document.createElement("s"); el.textContent = tok.slice(2, -2); }
        else if (tok.charAt(0) === "`") { el = document.createElement("code"); el.textContent = tok.slice(1, -1); }
        else if (/^https?:/i.test(tok)) el = link(tok, tok);
        else { el = document.createElement("em"); el.textContent = tok.slice(1, -1); }
        // 주소가 막히면(javascript: 등) 만들지 않는다 — 그대로 글자로 남긴다.
        parent.appendChild(el || document.createTextNode(tok));
        last = m.index + tok.length;
      }
      if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
    }

    // ---------- 묶음 ----------
    // "줄 하나가 블록 하나"의 유일한 예외가 ``` 코드 블록이다. 여는 줄부터 닫는 줄까지를
    // 한 묶음으로 그리고, 편집도 그 범위를 통째로 연다.
    var FENCE_OPEN = /^\s*```(.*)$/;
    var FENCE_CLOSE = /^\s*```\s*$/;

    function units() {
      var out = [], i = 0, m, j;
      while (i < lines.length) {
        m = FENCE_OPEN.exec(lines[i]);
        if (m) {
          j = i + 1;
          while (j < lines.length && !FENCE_CLOSE.test(lines[j])) j++;
          if (j >= lines.length) j = lines.length - 1; // 닫히지 않은 펜스는 끝까지
          out.push({ start: i, end: j, code: true, lang: m[1].trim() });
          i = j + 1;
        } else {
          out.push({ start: i, end: i, code: false });
          i++;
        }
      }
      return out;
    }

    // ---------- 렌더 ----------
    function autosize(ta) { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; }

    function openAt(i) {
      return function (e) {
        if (readonly) return;
        if (e.target && e.target.type === "checkbox") return;
        editing = i; caret = null; render();
      };
    }

    function codeBlock(u) {
      var wrap = document.createElement("div");
      wrap.className = "blk blk-code";
      var pre = document.createElement("pre");
      var code = document.createElement("code");
      if (u.lang) code.className = "lang-" + u.lang.replace(/[^\w.+-]/g, "");
      // 울타리 줄은 빼고 안쪽만 보여 준다. 닫히지 않았으면 끝까지가 내용이다.
      var tail = FENCE_CLOSE.test(lines[u.end]) && u.end > u.start ? u.end : u.end + 1;
      code.textContent = lines.slice(u.start + 1, tail).join("\n");
      pre.appendChild(code);
      wrap.appendChild(pre);
      if (u.lang) {
        var tag = document.createElement("span");
        tag.className = "lang";
        tag.textContent = u.lang;
        wrap.appendChild(tag);
      }
      wrap.addEventListener("click", openAt(u.start));
      return wrap;
    }

    function block(raw, i) {
      var b = parse(raw);
      var wrap = document.createElement("div");
      wrap.className = "blk blk-" + b.type + (b.type === "h" ? " h" + b.level : "");
      // 2칸 = 한 단. .blk의 padding-left 6px를 기준으로 민다.
      if (b.indent) wrap.style.paddingLeft = 6 + b.indent * 10 + "px";
      if (b.type === "rule") {
        wrap.appendChild(document.createElement("hr"));
      } else if (b.type === "embed") {
        var el = media(b.url, b.alt, b.force);
        if (el) {
          wrap.appendChild(el);
        } else {
          // 그림도 영상도 아니면 평범한 문단으로 되돌린다(맨 URL은 inline이 링크로 만든다).
          wrap.className = "blk blk-p";
          var fb = document.createElement("div");
          fb.className = "txt";
          inline(b.text, fb);
          wrap.appendChild(fb);
        }
      } else if (b.type === "todo") {
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = b.checked;
        cb.setAttribute("aria-label", b.text);
        cb.addEventListener("change", function (e) { e.stopPropagation(); toggle(i); });
        wrap.appendChild(cb);
        var sp = document.createElement("span");
        sp.className = "txt" + (b.checked ? " done" : "");
        inline(b.text, sp);
        wrap.appendChild(sp);
      } else {
        if (b.type === "li") {
          var mk = document.createElement("span");
          mk.className = "mk";
          mk.textContent = b.marker;
          wrap.appendChild(mk);
        }
        var box = document.createElement(
          b.type === "h" ? "h" + b.level : b.type === "quote" ? "blockquote" : "div"
        );
        box.className = "txt";
        inline(b.text, box);
        if (!b.text) box.appendChild(document.createTextNode(" "));
        wrap.appendChild(box);
      }
      wrap.addEventListener("click", openAt(i));
      return wrap;
    }

    // ---------- / 메뉴 ----------
    // 여는 조건: 그 줄이 `/`로 시작하고, 뒤에 띄어쓰기가 없고, 커서가 맨 뒤에 있을 때.
    // 띄어쓰기가 나오면 "/etc 경로를 보세요" 같은 평범한 글이므로 조용히 닫는다.
    function slashQuery(ta) {
      var v = ta.value;
      if (v.charAt(0) !== "/" || v.indexOf("\n") >= 0) return null;
      if (ta.selectionStart !== v.length) return null;
      var q = v.slice(1);
      return /\s/.test(q) ? null : q;
    }

    function closeMenu(ta) {
      if (menu && menu.parentNode) menu.parentNode.removeChild(menu);
      menu = null; menuItems = []; menuIdx = 0; menuSig = "";
      if (ta) {
        ta.removeAttribute("aria-activedescendant");
        ta.setAttribute("aria-expanded", "false");
      }
    }

    function highlight(ta) {
      for (var k = 0; k < menu.children.length; k++) {
        menu.children[k].setAttribute("aria-selected", k === menuIdx ? "true" : "false");
      }
      var cur = menu.children[menuIdx];
      if (cur) {
        ta.setAttribute("aria-activedescendant", cur.id);
        if (cur.scrollIntoView) cur.scrollIntoView({ block: "nearest" });
      }
    }

    function syncMenu(ta, u) {
      var q = slashQuery(ta);
      var hits = q == null ? [] : menuMatches(q);
      if (!hits.length) return closeMenu(ta);

      var sig = hits.map(function (it) { return it.label; }).join("|");
      menuItems = hits;
      if (!menu) {
        menu = document.createElement("div");
        menu.className = "slash";
        menu.id = uid;
        menu.setAttribute("role", "listbox");
        menu.setAttribute("aria-label", "블록 넣기");
        bodyEl.appendChild(menu);
        ta.setAttribute("aria-controls", uid);
        ta.setAttribute("aria-expanded", "true");
      }
      if (sig !== menuSig) {
        menuSig = sig;
        menuIdx = 0;
        while (menu.firstChild) menu.removeChild(menu.firstChild);
        hits.forEach(function (it, k) {
          var opt = document.createElement("div");
          opt.className = "opt";
          opt.id = uid + "-" + k;
          opt.setAttribute("role", "option");
          var name = document.createElement("span");
          name.textContent = it.label;
          var hint = document.createElement("span");
          hint.className = "hint";
          hint.textContent = it.hint;
          opt.appendChild(name);
          opt.appendChild(hint);
          // mousedown으로 잡아야 textarea가 포커스를 잃기 전에 고를 수 있다.
          opt.addEventListener("mousedown", function (e) {
            e.preventDefault(); e.stopPropagation(); choose(it, u, ta);
          });
          menu.appendChild(opt);
        });
      }
      menu.style.top = ta.offsetTop + ta.offsetHeight + 4 + "px";
      menu.style.left = ta.offsetLeft + 6 + "px";
      highlight(ta);
    }

    function choose(it, u, ta) {
      var i = u.start;
      closeMenu(ta);
      if (it.block) {
        Array.prototype.splice.apply(lines, [i, 1].concat(it.block));
        editing = i;
      } else if (it.done) {
        // 구분선처럼 더 쓸 것이 없는 블록은 바로 다음 줄로 내려 준다.
        lines.splice(i, 1, it.ins, "");
        editing = i + 1;
      } else {
        lines[i] = it.ins;
        editing = i;
      }
      caret = it.done ? 0 : it.caret == null ? it.ins.length : it.caret;
      changed();
    }

    function editor(u) {
      var ta = document.createElement("textarea");
      ta.className = "blk-edit";
      ta.rows = 1;
      ta.value = lines.slice(u.start, u.end + 1).join("\n");
      ta.setAttribute("aria-label", "본문 입력");
      ta.addEventListener("input", function () {
        // 코드 블록은 여러 줄이라 통째로 갈아 끼운다. 한 줄짜리도 같은 길로 간다.
        var parts = ta.value.split("\n");
        Array.prototype.splice.apply(lines, [u.start, u.end - u.start + 1].concat(parts));
        u.end = u.start + parts.length - 1;
        editing = u.start;
        autosize(ta);
        if (!u.code) syncMenu(ta, u);
        save();
      });
      ta.addEventListener("blur", function () { closeMenu(ta); });
      ta.addEventListener("keydown", function (e) { keys(e, ta, u); });
      return ta;
    }

    function render() {
      // 메뉴는 bodyEl의 자식이다. 먼저 떼지 않으면 상태 변수만 남고 노드는 지워진다.
      closeMenu();
      while (bodyEl.firstChild) bodyEl.removeChild(bodyEl.firstChild);
      var us = units();
      for (var k = 0; k < us.length; k++) {
        var u = us[k];
        var open = !readonly && editing >= u.start && editing <= u.end;
        bodyEl.appendChild(open ? editor(u) : u.code ? codeBlock(u) : block(lines[u.start], u.start));
      }
      var ta = bodyEl.querySelector("textarea");
      if (ta) {
        autosize(ta);
        ta.focus();
        var p = caret == null ? ta.value.length : Math.min(caret, ta.value.length);
        ta.setSelectionRange(p, p);
      }
    }

    function beginEditing() {
      if (readonly) return;
      editing = 0;
      caret = null;
      render();
    }

    function exitEditing() {
      editing = -1;
      caret = null;
      render();
      if (editStart) editStart.focus();
    }

    if (editStart) editStart.addEventListener("click", beginEditing);

    function changed() { render(); save(); }

    function toggle(i) {
      lines[i] = /\[[xX]\]/.test(lines[i])
        ? lines[i].replace(/\[[xX]\]/, "[ ]")
        : lines[i].replace(/\[ \]/, "[x]");
      changed();
    }

    // ---------- 키 ----------
    // 목록을 이어 쓸 때 넣을 접두어. 번호 목록은 **하나 올린다** — 앞 줄을 그대로 복사하면
    // 1. 1. 1.이 된다. 사람이 번호를 직접 고쳐 적으면 그 값이 다음 줄의 기준이 되고,
    // 화면은 원문을 그대로 보여 준다(재번호 매기기를 하지 않는다).
    function nextPrefix(p) {
      var m = /^(\s*)(\d+)\.(\s)$/.exec(p);
      return m ? m[1] + (parseInt(m[2], 10) + 1) + "." + m[3] : p;
    }

    function keys(e, ta, u) {
      var at = ta.selectionStart, i = u.start;
      // / 메뉴가 떠 있으면 방향키·Enter·Tab·Escape를 메뉴가 먼저 가져간다.
      // 글자 키는 그냥 흘려 보낸다 — input이 뒤따라 돌며 목록을 좁힌다.
      if (menu) {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          menuIdx = (menuIdx + (e.key === "ArrowDown" ? 1 : -1) + menuItems.length) % menuItems.length;
          highlight(ta);
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          e.preventDefault();
          choose(menuItems[menuIdx], u, ta);
          return;
        }
        if (e.key === "Escape") {
          // 메뉴만 닫는다. 편집까지 빠져나가지 않는다.
          e.preventDefault();
          closeMenu(ta);
          return;
        }
      }
      // 코드 블록 안에서는 Enter가 줄바꿈이고 Backspace가 글자 지우기다. 블록을 쪼개지 않는다.
      if (u.code) {
        // 맨 앞·뒤에서만 이웃 블록으로 건너간다. 코드 안쪽의 화살표는 native 이동을 유지한다.
        var plainArrow = !e.shiftKey && !e.altKey && !e.metaKey && !e.ctrlKey;
        var collapsed = ta.selectionStart === ta.selectionEnd;
        if (plainArrow && collapsed && e.key === "ArrowUp" && at === 0 && u.start > 0) {
          e.preventDefault(); editing = u.start - 1; caret = null; render();
        } else if (plainArrow && collapsed && e.key === "ArrowDown" && at === ta.value.length && u.end < lines.length - 1) {
          e.preventDefault(); editing = u.end + 1; caret = 0; render();
        } else if (e.key === "Escape") {
          e.preventDefault(); exitEditing();
        }
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        var head = ta.value.slice(0, at), tail = ta.value.slice(at);
        var cont = /^(\s*(?:[-*]\s\[[ xX]\]|[-*]|\d+\.)\s)/.exec(head);
        // 접두어만 남은 줄에서 Enter를 치면 목록을 끝낸다.
        var prefix = cont && tail === "" && head.trim() !== cont[1].trim() ? nextPrefix(cont[1]) : "";
        lines.splice(i, 1, head, prefix + tail);
        editing = i + 1; caret = prefix.length;
        changed();
      } else if (e.key === "Backspace" && at === 0 && i > 0) {
        e.preventDefault();
        var prev = lines[i - 1];
        lines.splice(i - 1, 2, prev + ta.value);
        editing = i - 1; caret = prev.length;
        changed();
      } else if (e.key === "ArrowUp" && at === 0 && i > 0) {
        e.preventDefault(); editing = i - 1; caret = null; render();
      } else if (e.key === "ArrowDown" && at === ta.value.length && i < lines.length - 1) {
        e.preventDefault(); editing = i + 1; caret = 0; render();
      } else if (e.key === "Escape") {
        e.preventDefault(); exitEditing();
      }
    }

    doc.addEventListener("click", function (e) {
      if (readonly) return;
      if (e.target !== doc && e.target !== bodyEl) return; // 빈 영역만
      if (lines.length && lines[lines.length - 1].trim() === "") {
        editing = lines.length - 1;
      } else {
        lines.push("");
        editing = lines.length - 1;
      }
      caret = 0;
      changed();
    });

    // ---------- 저장 ----------
    function flash(text, state) {
      if (!statusEl) return;
      statusEl.textContent = text;
      statusEl.dataset.state = state || "saved";
    }

    function pendingCount() { return Object.keys(pendingFields).length; }

    function hasUnsaved() {
      return Boolean(timer || bodyDirty || worker || pendingCount());
    }

    function maybeShowSaved() {
      if (!dead && !hasUnsaved()) {
        flash("저장됨 · v" + version, "saved");
      }
    }

    function requestSave(field, value) {
      var data = new FormData();
      data.append("field", field);
      data.append("value", value);
      data.append("version", String(version));
      flash("저장 중…", "saving");
      return fetch(doc.dataset.url, {
        method: "POST", headers: { "X-CSRFToken": csrf }, body: data, credentials: "same-origin",
      }).then(function (r) {
        if (r.status === 409) {
          dead = true;
          if (conflictEl) conflictEl.hidden = false;
          flash("저장하지 못했습니다", "error");
          return false;
        }
        if (!r.ok) throw new Error(String(r.status));
        version = Number(r.headers.get("X-Note-Version")) || version + 1;
        doc.dataset.version = String(version);
        return true;
      }).catch(function () {
        flash("저장 실패 · 새로고침하세요", "error");
        return false;
      });
    }

    function nextPending() {
      var next = null;
      Object.keys(pendingFields).forEach(function (field) {
        var item = pendingFields[field];
        if (!next || item.seq < next.seq) next = item;
      });
      return next;
    }

    // 필드별 최신 값을 outbox에 남긴다. 실패한 항목은 지우지 않으므로 다른 필드가
    // 나중에 성공해도 전체가 저장됐다고 거짓 표시하지 않는다.
    function stage(field, value) {
      if (dead || !doc.dataset.url) return Promise.resolve(false);
      pendingFields[field] = { field: field, value: value, seq: ++pendingSeq };
      flash("저장 대기…", "pending");
      return runQueue();
    }

    // 요청은 하나씩 보낸다. 성공 응답의 version을 다음 항목이 이어 받고, 전송 중 같은
    // 필드가 다시 바뀌면 캡처했던 항목만 지우고 최신 항목은 다음 차례에 보낸다.
    function runQueue() {
      if (worker) return worker;
      if (!nextPending()) { maybeShowSaved(); return Promise.resolve(true); }
      worker = new Promise(function (resolve) {
        function step() {
          var item = nextPending();
          if (!item) {
            worker = null;
            maybeShowSaved();
            resolve(true);
            return;
          }
          requestSave(item.field, item.value).then(function (ok) {
            if (!ok) {
              worker = null;
              resolve(false);
              return;
            }
            if (pendingFields[item.field] === item) delete pendingFields[item.field];
            step();
          });
        }
        step();
      });
      return worker;
    }

    function stageBody() {
      clearTimeout(timer);
      timer = null;
      if (readonly || !bodyDirty) return runQueue();
      src.value = lines.join("\n");
      bodyDirty = false;
      return stage("body_md", src.value);
    }

    // 복귀 중 새 입력이 생겨도 outbox와 debounce가 모두 빌 때까지 반복한다.
    function flushAll() {
      clearTimeout(timer);
      timer = null;
      var current = bodyDirty ? stageBody() : runQueue();
      return current.then(function (ok) {
        if (!ok || dead) return false;
        return (timer || bodyDirty || pendingCount() || worker) ? flushAll() : true;
      });
    }

    function save() {
      if (readonly) return;
      bodyDirty = true;
      clearTimeout(timer);
      flash("저장 대기…", "pending");
      timer = setTimeout(stageBody, 800);
    }

    Array.prototype.forEach.call(scope.querySelectorAll("[data-note-field]"), function (el) {
      if (el.dataset.bound === "1") return;
      el.dataset.bound = "1";
      el.addEventListener("change", function () { stage(el.dataset.noteField, el.value); });
    });

    var frozenControls = [];
    function freezeEditor() {
      frozenControls = [];
      Array.prototype.forEach.call(scope.querySelectorAll("[data-note-field]"), function (el) {
        frozenControls.push({ el: el, disabled: el.disabled });
        el.disabled = true;
      });
      doc.setAttribute("inert", "");
      scope.classList.add("note-returning");
    }
    function unfreezeEditor() {
      frozenControls.forEach(function (item) { item.el.disabled = item.disabled; });
      frozenControls = [];
      doc.removeAttribute("inert");
      scope.classList.remove("note-returning");
    }

    var back = scope.querySelector(".note-back");
    if (back) back.addEventListener("click", function (e) {
      if (returning) { e.preventDefault(); return; }
      // programmatic click처럼 포커스 이동이 생략된 경우에도 현재 메타데이터의 change를
      // 먼저 발생시켜 outbox에 넣는다.
      var active = document.activeElement;
      if (active && scope.contains(active) && active.matches("[data-note-field]")) active.blur();
      if (!hasUnsaved()) return;
      e.preventDefault();
      returning = true;
      back.setAttribute("aria-disabled", "true");
      scope.setAttribute("aria-busy", "true");
      freezeEditor();
      flushAll().then(function (ok) {
        if (ok) {
          navigating = true;
          window.location.assign(back.href);
        } else {
          returning = false;
          unfreezeEditor();
          back.removeAttribute("aria-disabled");
          scope.removeAttribute("aria-busy");
        }
      });
    });

    // 브라우저 뒤로 가기·탭 닫기도 조용히 최신 입력을 버리면 안 된다.
    window.addEventListener("beforeunload", function (e) {
      if (readonly || navigating || !hasUnsaved()) return;
      e.preventDefault();
      e.returnValue = "";
    });

    render();
  }

  function init(root) {
    var where = root && root.querySelectorAll ? root : document;
    Array.prototype.forEach.call(where.querySelectorAll(".doc"), setup);
    // 바뀐 조각 자신이 `.doc`인 경우(HTMX가 그 요소를 통째로 갈아 끼울 때)도 붙인다.
    if (root && root.classList && root.classList.contains("doc")) setup(root);
  }

  init(document);
  // HTMX가 나중에 끼워 넣은 본문에도 붙여야 한다 — 이것이 없으면 회의록을 눌러도
  // 원문 textarea만 보인다(편집기가 붙지 않은 상태).
  document.addEventListener("htmx:load", function (e) { init(e.target); });
  document.addEventListener("htmx:afterSwap", function (e) { init(e.target); });
})();
