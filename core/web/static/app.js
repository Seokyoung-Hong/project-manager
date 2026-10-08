// 유달리 — 표시 보조만. 상태와 규칙은 서버에 있다.
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

  // 수동 복사 창을 열거나 취소한 것은 클립보드 복사 성공이 아니다.
  window.copyText = function (text, successLabel) {
    return Promise.resolve().then(function () {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      return navigator.clipboard.writeText(text);
    }).then(function () {
      flash(successLabel || "복사됨");
      return true;
    }, function () {
      prompt("아래 내용을 선택해 직접 복사하세요.", text);
      return false;
    });
  };

  function updateDueSuggestion() {
    var form = document.getElementById("quick-form");
    if (!form) return;
    var select = form.querySelector("[data-due-suggestions]");
    var box = form.querySelector("[data-quick-due-suggestion]");
    if (!select || !box) return;
    var option = select.options[select.selectedIndex];
    var date = option ? option.dataset.dueSuggestion : "";
    box.hidden = !date;
    box.dataset.date = date || "";
    box.querySelector("[data-due-suggestion-label]").textContent = date ? "설정에 따른 제안: " + date + " (월~금 기준)" : "";
  }
  updateDueSuggestion();
  body.addEventListener("htmx:afterSwap", updateDueSuggestion);
  body.addEventListener("change", function (e) {
    if (e.target.matches("[data-due-suggestions]")) updateDueSuggestion();
  });
  body.addEventListener("click", function (e) {
    var button = e.target.closest('[data-action="use-due-suggestion"]');
    if (!button) return;
    var form = button.closest("form"), box = button.closest("[data-quick-due-suggestion]");
    form.querySelector('[name="due_date"]').value = box.dataset.date;
  });

  function requestError(e, network) {
    var detail = e.detail || {}, config = detail.requestConfig || {};
    var verb = String(config.verb || "").toUpperCase();
    var message = verb === "GET" || verb === "HEAD" ? "불러오지 못했습니다." :
      verb ? "변경 요청을 완료하지 못했습니다." : "요청을 처리하지 못했습니다.";
    var xhr = detail.xhr, reason = "";
    if (xhr && !network) {
      try {
        var data = JSON.parse(xhr.responseText);
        reason = typeof data.detail === "string" ? data.detail : typeof data.error === "string" ? data.error : "";
      } catch (err) { /* HTML 오류 페이지는 표시하지 않는다. */ }
    }
    alert(message + (network ? " 네트워크 연결을 확인하고 다시 시도하세요." :
      (reason ? " " + reason : " 다시 시도하세요.")));
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

  // 설정 섹션 목차의 현재 위치 표시(스크롤 스파이). 화면 위쪽 3분의 1을 지난 마지막 섹션이 현재다.
  function markSettingsJump(link) {
    var nav = link && link.closest(".settings-jump");
    if (!nav) return;
    nav.querySelectorAll("a[aria-current]").forEach(function (a) { a.removeAttribute("aria-current"); });
    link.setAttribute("aria-current", "true");
  }
  var spyNav = document.querySelector(".settings-jump");
  if (spyNav) {
    var spyTick = false;
    var spy = function () {
      spyTick = false;
      var current = null, line = window.innerHeight / 3;
      spyNav.querySelectorAll('a[href^="#"]').forEach(function (a) {
        var target = document.querySelector(a.getAttribute("href"));
        if (target && target.getBoundingClientRect().top <= line) current = a;
      });
      markSettingsJump(current || spyNav.querySelector('a[href^="#"]'));
    };
    window.addEventListener("scroll", function () { if (!spyTick) { spyTick = true; requestAnimationFrame(spy); } }, { passive: true });
    spy();
  }

  // 완료 순간 피드백: '완료'로 바꾸는 요청이 성공하면 새싹 알림을 3초 띄운다.
  var toastTimer;
  function celebrate() {
    var old = document.querySelector(".toast");
    if (old) old.remove();
    var t = document.createElement("div");
    t.className = "toast"; t.setAttribute("role", "status");
    t.innerHTML = '<svg viewBox="0 0 40 40" aria-hidden="true"><ellipse class="art-pot" cx="20" cy="31" rx="9" ry="7"/>' +
      '<g class="leaf"><path class="art-leaf" d="M20 25Q8 25 7 13Q18 11 20 25"/><path class="art-leaf-2" d="M20 22Q22 9 33 10Q34 21 20 22"/></g></svg>' +
      "<span>완료했습니다. 화분이 한 뼘 자랐습니다.</span>";
    body.appendChild(t);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.add("leaving"); setTimeout(function () { t.remove(); }, 250); }, 3000);
  }
  body.addEventListener("htmx:afterRequest", function (e) {
    var d = e.detail || {}, cfg = d.requestConfig || {};
    if (!d.successful || !/\/tasks\/\d+\/status/.test((d.pathInfo && d.pathInfo.requestPath) || "")) return;
    var fd = cfg.formData, status = fd && fd.get ? fd.get("status") : (cfg.parameters || {}).status;
    var trig = (d.xhr && d.xhr.getResponseHeader("HX-Trigger")) || "";
    if (status === "done" && /task-(updated|changed)/.test(trig)) celebrate();
  });
  body.addEventListener("htmx:responseError", function (e) {
    requestError(e, false);
  });

  body.addEventListener("htmx:sendError", function (e) { requestError(e, true); });
  body.addEventListener("htmx:timeout", function (e) { requestError(e, true); });

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
      window.copyText(b.dataset.copyText, b.dataset.copyLabel || "복사됨");
      return;
    }
    var id = b.dataset.copy, url = location.origin + "/tasks/" + id;
    window.copyText(url, "TASK-" + id + " 링크 복사됨");
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
      if (w) w.textContent = layout.classList.contains("wide") ? "패널 좁히기" : "패널 넓히기";
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
      b.textContent = on ? "패널 좁히기" : "패널 넓히기";
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
      markSettingsJump(b);
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
    } else if (a === "toggle-subtasks") {
      // 프로젝트 목록 보기: 상위 행 "하위 n/m"이 그 아래 하위 행을 접고 편다. 상태는 저장하지 않는다.
      // ponytail: 접힘 기억은 필요해지면 localStorage.
      var open = b.getAttribute("aria-expanded") !== "true";
      b.setAttribute("aria-expanded", open ? "true" : "false");
      document.querySelectorAll('.task-row[data-group="' + b.dataset.group + '"]').forEach(function (r) { r.hidden = !open; });
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

  // 문서 트리: 서버는 현재 문서까지 가는 가지만 펴서 보낸다. 사용자가 펴고 접은 가지는 브라우저가 기억한다.
  (function () {
    var tree = document.querySelector(".doc-tree");
    if (!tree) return;
    var KEY = "udally.docTreeOpen";
    var open = {};
    try { open = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (err) { open = {}; }
    tree.querySelectorAll("details[data-doc]").forEach(function (d) {
      if (open[d.dataset.doc] === true) d.open = true;
    });
    // 사용자가 직접 펴고 접은 것만 기억한다(서버가 펴 준 조상 가지까지 쌓이지 않게).
    tree.addEventListener("click", function (e) {
      var s = e.target.closest("summary");
      if (!s || e.target.closest("a")) return;
      var d = s.parentElement;
      setTimeout(function () {
        if (d.open) open[d.dataset.doc] = true; else delete open[d.dataset.doc];
        try { localStorage.setItem(KEY, JSON.stringify(open)); } catch (err) { /* 저장소를 못 쓰면 이번 화면에서만 */ }
      }, 0);
    });
  })();
})();
