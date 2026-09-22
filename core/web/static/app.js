// 산돌이 태스크 — 표시 보조만. 상태와 규칙은 서버에 있다.
(function () {
  var body = document.body;
  var t1, t2;
  var panelReturnScroll = 0;

  function flash(text, after) {
    var el = document.getElementById("save-status");
    if (!el) return;
    clearTimeout(t1); clearTimeout(t2);
    el.textContent = text;
    if (after) t1 = setTimeout(function () { el.textContent = after; }, 400);
    t2 = setTimeout(function () { el.textContent = ""; }, 2500);
  }

  function openPanel(url, pushUrl) {
    htmx.ajax("GET", url, { target: "#panel", swap: "innerHTML" });
    if (pushUrl) history.pushState(null, "", pushUrl);
  }

  // 프로젝트 레일 접기. 닫으면 목록을 통째로 숨기고 여는 손잡이만 남긴다.
  // 사생활 모드 등에서 localStorage가 막혀도 페이지가 죽지 않도록 감싼다.
  function getRailClosed() {
    try { return localStorage.getItem("rail-collapsed") === "1"; } catch (e) { return false; }
  }
  function setRailClosed(off) {
    try { localStorage.setItem("rail-collapsed", off ? "1" : "0"); } catch (e) {}
  }
  function applyRail() {
    var rail = document.querySelector("[data-rail]");
    if (!rail) return;
    var off = getRailClosed();
    rail.classList.toggle("collapsed", off);
    var b = rail.querySelector("[data-action='toggle-rail']");
    if (b) {
      b.textContent = off ? "»" : "«";
      b.setAttribute("aria-expanded", off ? "false" : "true");
      b.setAttribute("aria-label", off ? "프로젝트 목록 펼치기" : "프로젝트 목록 접기");
    }
  }
  applyRail();

  // 조직 탭은 모바일에서 한 줄로 스크롤된다. 현재 탭이 뒤쪽이어도 첫 렌더부터 보이게 맞춘다.
  var orgTabs = document.querySelector(".org-tabs");
  if (orgTabs) {
    var mobileOrgTabs = window.matchMedia("(max-width: 700px)");
    function revealCurrentOrgTab(query) {
      if (!query.matches) { orgTabs.scrollLeft = 0; return; }
      var current = orgTabs.querySelector('[aria-current="page"]');
      if (!current) return;
      requestAnimationFrame(function () {
        var tabsRect = orgTabs.getBoundingClientRect();
        var currentRect = current.getBoundingClientRect();
        orgTabs.scrollLeft += currentRect.left - tabsRect.left - (tabsRect.width - currentRect.width) / 2;
      });
    }
    revealCurrentOrgTab(mobileOrgTabs);
    if (mobileOrgTabs.addEventListener) mobileOrgTabs.addEventListener("change", revealCurrentOrgTab);
    window.addEventListener("resize", function () { revealCurrentOrgTab(mobileOrgTabs); });
  }

  function syncBoardNavigation(board) {
    if (!board) return;
    var track = board.querySelector(".board-track");
    // 모바일 태스크 패널처럼 main이 잠시 display:none이면 폭이 0이다.
    // 그 순간 양쪽 버튼을 모두 비활성화하지 말고, 다시 보일 때 재계산한다.
    if (!track || !track.clientWidth) return;
    var max = Math.max(0, track.scrollWidth - track.clientWidth);
    Array.prototype.forEach.call(board.querySelectorAll('[data-action="scroll-board"]'), function (button) {
      var back = Number(button.dataset.direction) < 0;
      button.disabled = back ? track.scrollLeft <= 2 : track.scrollLeft >= max - 2;
    });
  }
  function syncAllBoardNavigation() {
    Array.prototype.forEach.call(document.querySelectorAll("#board"), syncBoardNavigation);
  }
  body.addEventListener("scroll", function (e) {
    if (e.target.classList && e.target.classList.contains("board-track")) {
      syncBoardNavigation(e.target.closest("#board"));
    }
  }, { passive: true, capture: true });
  window.addEventListener("resize", syncAllBoardNavigation);
  requestAnimationFrame(syncAllBoardNavigation);

  // 고급 필터는 넓은 화면에서 항상 보이고, 모바일 첫 진입에서만 접힌다.
  // 적용 중인 조건이 있으면 모바일에서도 열어 두어 현재 상태를 숨기지 않는다.
  var meFilters = document.querySelector(".me-filter-details");
  if (meFilters) {
    var mobileFilters = window.matchMedia("(max-width: 700px)");
    var mobileFilterOpen = meFilters.dataset.filterActive === "1";
    function syncMeFilters(query) {
      meFilters.open = query.matches ? mobileFilterOpen : true;
    }
    syncMeFilters(mobileFilters);
    meFilters.addEventListener("toggle", function () {
      if (mobileFilters.matches) mobileFilterOpen = meFilters.open;
    });
    if (mobileFilters.addEventListener) mobileFilters.addEventListener("change", syncMeFilters);
  }

  // 자동 저장 상태 표시
  body.addEventListener("htmx:beforeRequest", function (e) {
    if (e.detail && e.detail.target && e.detail.target.id === "panel" && !e.detail.target.children.length) {
      panelReturnScroll = window.scrollY;
    }
    if (e.target.hasAttribute && e.target.hasAttribute("data-autosave")) flash("저장 중…");
  });
  body.addEventListener("saved", function () { flash("자동 저장됨"); });
  body.addEventListener("htmx:responseError", function (e) {
    alert("저장하지 못했습니다. 페이지를 새로고침한 뒤 다시 시도하세요. (" + e.detail.xhr.status + ")");
  });

  // 행 전체 클릭 → 패널. 행 안의 컨트롤은 제외.
  body.addEventListener("click", function (e) {
    var row = e.target.closest(".task-row");
    if (!row || e.target.closest("button, select, a, input, textarea, form")) return;
    openPanel(row.dataset.panel, "/tasks/" + row.dataset.id);
  });
  body.addEventListener("keydown", function (e) {
    if (!e.target.classList || !e.target.classList.contains("task-row")) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.target.click(); }
  });

  // 안내 배너 닫기
  body.addEventListener("click", function (e) {
    var d = e.target.closest('[data-action="dismiss"]');
    if (d) d.closest(".notice").remove();
  });

  // 링크 복사. data-copy는 태스크 번호, data-copy-text는 아무 문자열(초대 링크·명령줄).
  body.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy], [data-copy-text]");
    if (!b) return;
    e.preventDefault(); e.stopPropagation();
    if (b.dataset.copyText !== undefined) {
      var text = b.dataset.copyText;
      var ok = function () { flash(b.dataset.copyLabel || "복사됨"); };
      (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject())
        .then(ok, function () { prompt("복사하세요", text); ok(); });
      return;
    }
    var id = b.dataset.copy, url = location.origin + "/tasks/" + id;
    var done = function () { flash("TASK-" + id + " 링크 복사됨"); };
    (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject())
      .then(done, function () { prompt("링크를 복사하세요", url); done(); });
  });

  // 상태 select에서 '막힘' 선택 → 보내지 않고 패널의 사유 박스를 연다. (HTMX는 hx-trigger 필터로 이미 막혀 있다)
  body.addEventListener("change", function (e) {
    var s = e.target;
    if (!s.matches || !s.matches("select[data-status]")) return;
    if (s.value === "blocked" && s.dataset.status !== "blocked") {
      openPanel(s.dataset.panel + "?block=1", "/tasks/" + s.dataset.id);
      s.value = s.dataset.status;
    }
  });

  // 패널·다이얼로그 스왑 후 처리
  body.addEventListener("htmx:afterSwap", function (e) {
    var layout = document.querySelector(".layout");
    if (e.target.id === "panel" && layout) {
      var open = e.target.children.length > 0;
      layout.classList.toggle("has-panel", open);
      layout.classList.toggle("wide", open && localStorage.getItem("panel-wide") === "1");
      var w = e.target.querySelector("[data-action='toggle-wide']");
      if (w) w.textContent = layout.classList.contains("wide") ? "작게 보기" : "크게 보기";
      var f = e.target.querySelector("[data-focus]");
      if (f) f.focus();
      else if (open && window.matchMedia("(max-width: 1150px)").matches) window.scrollTo(0, 0);
    }
    if (e.target.id === "dialog" && e.target.children.length) e.target.showModal();
    requestAnimationFrame(syncAllBoardNavigation);
  });

  // data-action 버튼
  body.addEventListener("click", function (e) {
    var b = e.target.closest("[data-action]");
    if (!b) return;
    var layout = document.querySelector(".layout"), panel = document.getElementById("panel"), dlg = document.getElementById("dialog");
    var a = b.dataset.action;
    if (a === "close-panel") {
      panel.innerHTML = ""; layout.classList.remove("has-panel", "wide");
      history.replaceState(null, "", body.dataset.pageUrl || "/today");
      requestAnimationFrame(function () {
        window.scrollTo(0, panelReturnScroll);
        syncAllBoardNavigation();
      });
    } else if (a === "toggle-wide") {
      var on = !layout.classList.contains("wide");
      layout.classList.toggle("wide", on); localStorage.setItem("panel-wide", on ? "1" : "0");
      b.textContent = on ? "작게 보기" : "크게 보기";
      requestAnimationFrame(syncAllBoardNavigation);
    } else if (a === "close-dialog") {
      dlg.close(); dlg.innerHTML = "";
    } else if (a === "open-settings-group") {
      e.preventDefault();
      var group = document.querySelector(b.dataset.target);
      if (!group) return;
      var settingsForm = group.closest(".settings-form");
      if (settingsForm) settingsForm.querySelectorAll("details.settings-section").forEach(function (item) {
        if (item !== group) item.open = false;
      });
      group.open = true;
      var summary = group.querySelector("summary");
      if (summary) summary.focus({ preventScroll: true });
      history.replaceState(null, "", b.getAttribute("href"));
      requestAnimationFrame(function () {
        group.scrollIntoView({
          block: "start",
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"
        });
      });
    } else if (a === "toggle") {
      var el = document.querySelector(b.dataset.target);
      el.hidden = !el.hidden;
      if (b.dataset.alt) { var t = b.textContent; b.textContent = b.dataset.alt; b.dataset.alt = t; }
      if (!el.hidden) { var i = el.querySelector("input:not([type=hidden]), textarea"); if (i) i.focus(); }
    } else if (a === "toggle-rail") {
      setRailClosed(!getRailClosed());
      applyRail();
      requestAnimationFrame(syncAllBoardNavigation);
    } else if (a === "scroll-board") {
      var board = b.closest("#board");
      var track = board && board.querySelector(".board-track");
      if (!track) return;
      var col = track.querySelector(".col");
      var gap = parseFloat(getComputedStyle(track).columnGap) || 12;
      var distance = col ? col.getBoundingClientRect().width + gap : track.clientWidth * .8;
      var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      track.scrollBy({ left: (Number(b.dataset.direction) || 1) * distance, behavior: reduce ? "auto" : "smooth" });
    }
  });
  var dlg = document.getElementById("dialog");
  if (dlg) dlg.addEventListener("click", function (e) { if (e.target === dlg) { dlg.close(); dlg.innerHTML = ""; } });
  document.addEventListener("keydown", function (e) {
    var panel = document.getElementById("panel");
    if (e.key === "Escape" && panel && panel.children.length && !(dlg && dlg.open)) {
      var close = panel.querySelector("[data-action='close-panel']");
      if (close) close.click();
    }
  });

  // #task-N 해시로 진입하면 패널을 연다 (생성 직후 리다이렉트, 공유 링크 호환)
  function openHash() {
    var m = /#task-(\d+)/.exec(location.hash);
    if (m) openPanel("/tasks/" + m[1] + "/panel", null);
  }
  openHash();
  window.addEventListener("hashchange", openHash);

  // 칸반 드래그. 드롭은 상태 전환이므로 기존 엔드포인트를 그대로 부른다.
  var dragId = null;
  function csrf() {
    try { return JSON.parse(body.getAttribute("hx-headers") || "{}")["X-CSRFToken"]; }
    catch (e) { return ""; }
  }
  function clearOver() {
    Array.prototype.forEach.call(document.querySelectorAll(".col.over"), function (c) {
      c.classList.remove("over");
    });
  }
  body.addEventListener("dragstart", function (e) {
    var card = e.target.closest && e.target.closest("li[draggable='true'][data-id]");
    if (!card) return;
    dragId = card.dataset.id;
    if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
    card.classList.add("dragging");
  });
  body.addEventListener("dragend", function (e) {
    dragId = null;
    if (e.target.classList) e.target.classList.remove("dragging");
    clearOver();
  });
  body.addEventListener("dragover", function (e) {
    var col = e.target.closest && e.target.closest(".col[data-status]");
    if (!col || !dragId) return;
    e.preventDefault();
    if (!col.classList.contains("over")) { clearOver(); col.classList.add("over"); }
  });
  body.addEventListener("drop", function (e) {
    var col = e.target.closest && e.target.closest(".col[data-status]");
    if (!col || !dragId) return;
    e.preventDefault();
    clearOver();
    var id = dragId, to = col.dataset.status;
    dragId = null;
    var card = document.getElementById("task-" + id);
    if (!card || card.dataset.status === to) return;
    // 막힘은 사유가 필수다. 보내지 않고 패널의 사유 박스를 연다(상태 select와 같은 규칙).
    if (to === "blocked") { openPanel("/tasks/" + id + "/panel?block=1", "/tasks/" + id); return; }
    var board = document.getElementById("board");
    htmx.ajax("POST", "/tasks/" + id + "/status", {
      target: "#board", swap: "outerHTML",
      headers: { "X-CSRFToken": csrf() },
      values: {
        status: to, version: card.dataset.version, from: "board",
        include_closed: board ? board.dataset.includeClosed : "",
      },
    });
  });

  // ---------- 실시간 반영 (SSE) ----------
  // 서버(/events)가 방금 바뀐 태스크 id를 흘려보내면, 이미 쓰고 있는 HTMX 이벤트로 바꿔 쏜다.
  // 행·패널·오늘 목록은 그 이벤트를 이미 듣고 있으므로 템플릿은 건드릴 것이 없다.
  (function () {
    if (!window.EventSource || !body.dataset.live) return;
    var mine = {};   // 내가 방금 바꾼 것: 되돌아온 메아리는 무시한다
    var held = {};   // 패널에 타이핑 중이면 덮어쓰지 않고 쥐고 있는다

    body.addEventListener("htmx:afterRequest", function (e) {
      var m = /\/tasks\/(\d+)\//.exec((e.detail && e.detail.pathInfo && e.detail.pathInfo.requestPath) || "");
      if (m) { mine[m[1]] = Date.now(); }
    });

    function typingInPanel() {
      var panel = document.getElementById("panel");
      var el = document.activeElement;
      return panel && el && panel.contains(el) && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName);
    }

    function apply(id) {
      htmx.trigger(body, "task-changed", { id: id });
      htmx.trigger(body, "task-updated", { id: id });
    }

    function onChange(id) {
      var t = mine[id];
      if (t && Date.now() - t < 5000) return;      // 내가 낸 변경이 SSE로 돌아온 것
      if (typingInPanel()) { held[id] = true; return; }
      apply(id);
    }

    body.addEventListener("focusout", function () {
      setTimeout(function () {
        if (typingInPanel()) return;
        Object.keys(held).forEach(function (id) { apply(id); delete held[id]; });
      }, 0);
    });

    var es = new EventSource("/events");
    es.onmessage = function (ev) {
      try { onChange(String(JSON.parse(ev.data).id)); } catch (err) { /* 형식이 아니면 무시 */ }
    };
  })();
})();
