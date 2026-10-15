// 유달리 — 표시 보조만. 상태와 규칙은 서버에 있다.
(function () {
  var body = document.body;
  var t1, t2;
  // 패널은 흐름 밖(고정)에 뜬다. 연 요소를 기억해 닫을 때 초점만 돌려준다 — 스크롤은 건드리지 않는다.
  var panelOpener = null, panelOpening = false;

  // 저장 상태 칸(#save-status)은 태스크 패널에만 있다. 없는 화면에서는 화면 읽기용 알림 영역에만 알린다.
  function announce(text) {
    var live = document.getElementById("copy-live");
    if (!live) {
      live = document.createElement("span");
      live.id = "copy-live"; live.className = "sr-only"; live.setAttribute("aria-live", "polite");
      body.appendChild(live);
    }
    live.textContent = ""; setTimeout(function () { live.textContent = text; }, 50);
  }

  function flash(text, after) {
    var el = document.getElementById("save-status");
    if (!el) return announce(text);
    clearTimeout(t1); clearTimeout(t2);
    el.textContent = text;
    if (after) t1 = setTimeout(function () { el.textContent = after; }, 400);
    t2 = setTimeout(function () { el.textContent = el.dataset.idle || ""; }, 2500);
  }

  // 수동 복사 창을 열거나 취소한 것은 클립보드 복사 성공이 아니다.
  // btn을 주면 그 버튼 글자도 잠깐 성공 문구로 바꾼다(저장 상태 칸이 없는 화면에서도 눈에 보이게).
  window.copyText = function (text, successLabel, btn) {
    return Promise.resolve().then(function () {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      return navigator.clipboard.writeText(text);
    }).then(function () {
      var label = successLabel || "복사됨";
      flash(label);
      if (btn && !btn.dataset.copyOrig) {
        btn.dataset.copyOrig = btn.textContent;
        btn.textContent = label;
        setTimeout(function () { btn.textContent = btn.dataset.copyOrig; delete btn.dataset.copyOrig; }, 2000);
      }
      return true;
    }, function () {
      prompt("아래 내용을 선택해 직접 복사해 주세요.", text);
      return false;
    });
  };

  // 생성 폼 기본값(시스템화 D): 프로젝트를 바꾸면, 손대지 않은 기한을 그 프로젝트의 제안 기한으로 바꾼다.
  body.addEventListener("focusin", function (e) {
    if (e.target.matches("[data-due-suggestions]")) e.target.dataset.prev = (e.target.selectedOptions[0] || {}).value || "";
  });
  body.addEventListener("change", function (e) {
    var select = e.target;
    if (!select.matches("[data-due-suggestions]")) return;
    var due = select.form && select.form.querySelector("[data-due-input]");
    if (!due) return;
    var prev = select.querySelector('option[value="' + (select.dataset.prev || "") + '"]');
    var option = select.selectedOptions[0];
    if (!due.value || (prev && due.value === prev.dataset.dueSuggestion)) due.value = option ? option.dataset.dueSuggestion || "" : "";
    select.dataset.prev = option ? option.value : "";
  });

  // 버튼 모양 파일 입력: 고른 파일 이름을 옆에 보인다.
  body.addEventListener("change", function (e) {
    if (!e.target.matches("input[type=file][data-file-name]")) return;
    var label = e.target.closest("form").querySelector("[data-file-name-label]");
    if (label) label.textContent = e.target.files.length ? e.target.files[0].name : "선택한 파일 없음";
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
    alert(message + (network ? " 네트워크 연결을 확인하고 다시 시도해 주세요." :
      (reason ? " " + reason : " 다시 시도해 주세요.")));
  }

  // ---------- 공용 확인 창 (DESIGN.md 3절 "확인 창") ----------
  // data-confirm="결과 문장" data-confirm-ok="행동 버튼 문구"[, data-confirm-cancel]을 폼·제출 버튼·HTMX 요소에 단다.
  // 행동 버튼은 누른 버튼이 .danger(또는 data-confirm-danger)면 위험 스타일, 아니면 주 버튼. 초점은 [그대로 두기]에서 시작한다.
  var confirmDlg = document.getElementById("confirm");
  function askConfirm(el, styleFrom, then) {
    var msg = el.dataset.confirm;
    if (!confirmDlg || typeof confirmDlg.showModal !== "function") {
      if (window.confirm(msg)) then();  // ponytail: <dialog>를 못 쓰는 옛 브라우저만 기본 창
      return;
    }
    confirmDlg.querySelector("#confirm-text").textContent = msg;
    var ok = confirmDlg.querySelector("[value=ok]");
    ok.textContent = el.dataset.confirmOk || "계속하기";
    ok.className = "btn " + (styleFrom && styleFrom.matches(".danger, [data-confirm-danger]") ? "danger" : "primary");
    confirmDlg.querySelector("[value=cancel]").textContent = el.dataset.confirmCancel || "그대로 두기";
    confirmDlg.returnValue = "";
    confirmDlg.onclose = function () { if (confirmDlg.returnValue === "ok") then(); };
    confirmDlg.showModal();
  }
  // 바깥(배경)을 누르면 [그대로 두기]와 같다. 창에 안쪽 여백이 있어 target만으로는 안쪽 클릭과 구별되지 않으므로 좌표로 본다.
  if (confirmDlg) confirmDlg.addEventListener("click", function (e) {
    if (e.target !== confirmDlg) return;
    var r = confirmDlg.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) confirmDlg.close("cancel");
  });
  // 일반 폼: 캡처 단계에서 먼저 막아 htmx·편집기 저장보다 앞선다. 확인 뒤 같은 제출 버튼으로 다시 보낸다.
  window.addEventListener("submit", function (e) {
    var form = e.target, sub = e.submitter;
    var el = sub && sub.hasAttribute("data-confirm") ? sub : form.hasAttribute("data-confirm") ? form : null;
    // data-confirm-if="선택자": 폼 안에서 이 선택자가 맞을 때만 묻는다(예: 옵션을 켤 때만).
    if (el && el.dataset.confirmIf && !form.querySelector(el.dataset.confirmIf)) el = null;
    if (!el) return;
    if (form.dataset.confirmed) { delete form.dataset.confirmed; return; }
    e.preventDefault(); e.stopImmediatePropagation();
    askConfirm(el, sub || el, function () { form.dataset.confirmed = "1"; form.requestSubmit(sub || null); });
  }, true);
  // HTMX 요소(폼 밖 hx-post 버튼 등): 요청을 멈췄다가 확인하면 그대로 보낸다.
  body.addEventListener("htmx:confirm", function (e) {
    var el = e.detail.elt;
    if (!el.hasAttribute("data-confirm") || el.tagName === "FORM") return;
    e.preventDefault();
    askConfirm(el, el, function () { e.detail.issueRequest(true); });
  });

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

  // 자동 저장 상태 표시
  body.addEventListener("htmx:beforeRequest", function (e) {
    // 패널 밖에서 연 요청(행·버튼)만 연 요소로 기억한다. 패널 안 저장·상태 변경은 제외.
    var t = e.detail && e.detail.target, a = document.activeElement;
    if (t && t.id === "panel" && !(a && t.contains(a))) {
      panelOpener = a && a !== body ? a : null;
      panelOpening = true;
    }
    if (e.target.hasAttribute && e.target.hasAttribute("data-autosave")) flash("저장 중…");
  });
  // 저장 표시는 사라지지 않는다 — 저장한 뒤로는 "저장됨"이 남는다(b-workspace 중-12).
  body.addEventListener("saved", function () {
    var el = document.getElementById("save-status");
    if (el) el.dataset.idle = "저장됨";
    flash("저장됨 · 방금");
  });

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
  function celebrate(undo) {
    var old = document.querySelector(".toast");
    if (old) old.remove();
    var t = document.createElement("div");
    t.className = "toast"; t.setAttribute("role", "status");
    t.innerHTML = '<svg viewBox="0 0 40 40" aria-hidden="true"><ellipse class="art-pot" cx="20" cy="31" rx="9" ry="7"/>' +
      '<g class="leaf"><path class="art-leaf" d="M20 25Q8 25 7 13Q18 11 20 25"/><path class="art-leaf-2" d="M20 22Q22 9 33 10Q34 21 20 22"/></g></svg>' +
      "<span>완료했습니다. 화분이 한 뼘 자랐습니다.</span>";
    if (undo) {
      // 되돌리기: 완료 전 상태로 다시 보낸다. 오늘 화면 머리를 새로 그린다.
      var u = document.createElement("button");
      u.type = "button"; u.className = "btn sm"; u.textContent = "되돌리기";
      u.addEventListener("click", function () {
        t.remove();
        htmx.ajax("POST", undo.url, { target: "#today-head", swap: "outerHTML",
          values: { status: undo.undo_status, version: undo.version, from: "head" } });
      });
      t.appendChild(u);
    }
    body.appendChild(t);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.add("leaving"); setTimeout(function () { t.remove(); }, 250); }, undo ? 6000 : 3000);
  }
  body.addEventListener("htmx:afterRequest", function (e) {
    var d = e.detail || {}, cfg = d.requestConfig || {};
    if (!d.successful || !/\/tasks\/\d+\/status/.test((d.pathInfo && d.pathInfo.requestPath) || "")) return;
    var fd = cfg.formData, status = fd && fd.get ? fd.get("status") : (cfg.parameters || {}).status;
    var trig = (d.xhr && d.xhr.getResponseHeader("HX-Trigger")) || "";
    if (status === "done" && /task-(updated|changed)/.test(trig)) {
      var undo = null;
      try {
        var info = JSON.parse(trig)["task-updated"];
        if (info && info.undo_status) { undo = info; undo.url = d.pathInfo.requestPath; }
      } catch (err) { /* 이벤트 이름만 온 응답 */ }
      celebrate(undo);
    }
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
      window.copyText(b.dataset.copyText, b.dataset.copyLabel || "복사됨", b);
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
  function panelSwapped(panel) {
    var layout = document.querySelector(".layout");
    if (!layout) return;
    var open = panel.children.length > 0;
    layout.classList.toggle("has-panel", open);
    layout.classList.toggle("wide", open && localStorage.getItem("panel-wide") === "1");
    var w = panel.querySelector("[data-action='toggle-wide']");
    if (w) w.textContent = layout.classList.contains("wide") ? "패널 좁히기" : "패널 넓히기";
    var f = panel.querySelector("[data-focus]");
    if (!f && open && panelOpening) f = panel.querySelector("select, button, input:not([type=hidden]), textarea, a[href]");
    if (f) f.focus({ preventScroll: true });
    panelOpening = false;
  }
  body.addEventListener("htmx:afterSwap", function (e) {
    if (e.target.id === "panel") panelSwapped(e.target);
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
      // 목록이 다시 그려졌으면 같은 번호의 행을 찾는다
      var back = panelOpener && (panelOpener.isConnected ? panelOpener
        : panelOpener.id && document.getElementById(panelOpener.id));
      if (back) back.focus({ preventScroll: true });
      panelOpener = null;
      requestAnimationFrame(syncAllBoardNavigation);
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
      // 여는 버튼이 주 버튼이면 열린 동안 숨긴다 — 폼 안의 제출 버튼이 주 버튼 하나로 남는다(주 버튼 규칙).
      document.querySelectorAll('[data-hide-open][data-target="' + b.dataset.target + '"]').forEach(function (o) { o.hidden = !el.hidden; });
      if (el.hasAttribute("data-nodue")) {
        // [기한 없이 만들기]: 기한을 비우고 사유 칸을 연다. 다시 [기한 정하기]면 기한을 되살리고 사유를 비운다.
        var dueInput = el.closest("form").querySelector("[data-due-input]");
        if (!el.hidden) { dueInput.dataset.prev = dueInput.value; dueInput.value = ""; }
        else { dueInput.value = dueInput.dataset.prev || ""; el.querySelector("input").value = ""; }
      }
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
    if (e.key === "Escape" && panel && panel.children.length && !(dlg && dlg.open) && !(confirmDlg && confirmDlg.open)) {
      var close = panel.querySelector("[data-action='close-panel']");
      if (close) close.click();
    }
  });

  // #task-N 해시로 진입하면 패널을 연다 (생성 직후 리다이렉트, 공유 링크 호환)
  function openHash() {
    var m = /#task-(\d+)/.exec(location.hash);
    if (m) openPanel("/tasks/" + m[1] + "/panel", null);
    // 검색에서 고른 설정(#setting-…·#settings-…)이 접힌 섹션 안에 있으면 펼쳐서 보여 준다
    var target = location.hash.length > 1 && document.getElementById(decodeURIComponent(location.hash.slice(1)));
    var fold = target && target.closest("details");
    if (fold && !fold.open) { fold.open = true; target.scrollIntoView({ block: "center" }); }
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

  // ---------- 태스크 패널 미리 받기 ----------
  // 화면에 보이는(또는 마우스·초점이 간) 태스크의 패널을 미리 받아 두고, 열 때는 받아 둔 것을 바로 넣는다.
  // 넣은 직후 최신본인지 다시 묻고, 그사이 바뀌었고 아직 손대지 않았으면 갈아 끼운다.
  // 태스크가 바뀌었다는 이벤트(task-changed·task-updated·실시간 rt-stale)가 오면 그 태스크 것을 낡음으로 표시하고 다시 묻는다.
  // 물을 때는 가진 것의 해시(If-None-Match)를 보내, 같으면 서버가 본문 없이 304만 돌려준다.
  // ponytail: 캐시는 페이지 수명 동안 메모리에만 둔다. 화면에 나온 태스크 수만큼만 쌓인다.
  (function () {
    var panel = document.getElementById("panel");
    if (!panel || !window.fetch) return;
    var RE = /^\/tasks\/\d+\/panel$/;
    var cache = {}, tags = {}, stale = {}, gen = {}, queue = [], busy = 0, touched = false;
    // 폼마다 새로 섞이는 CSRF 값은 비교에서 뺀다
    function same(a, b) {
      var strip = function (h) { return h.replace(/name="csrfmiddlewaretoken" value="[^"]*"/g, ""); };
      return strip(a) === strip(b);
    }
    function urlOf(el) {
      var u = el.getAttribute && (el.getAttribute("data-panel") || el.getAttribute("hx-get"));
      return u && RE.test(u) ? u : null;
    }
    function fresh(url) { return cache[url] && !stale[url]; }
    function load(url) {
      var g = gen[url] || 0, headers = { "HX-Request": "true" };
      if (cache[url] && tags[url]) headers["If-None-Match"] = tags[url];
      return fetch(url, { headers: headers, credentials: "same-origin" }).then(function (r) {
        var mine = (gen[url] || 0) === g;   // 받는 사이 또 바뀌었으면 결과를 믿지 않는다
        if (r.status === 304) { if (mine) delete stale[url]; return cache[url]; }
        if (!r.ok || r.redirected) throw r;
        var tag = r.headers.get("ETag");
        return r.text().then(function (html) {
          if (mine) { cache[url] = html; tags[url] = tag; delete stale[url]; }
          return html;
        });
      });
    }
    function pump() {
      while (busy < 2 && queue.length) {
        var url = queue.shift();
        if (fresh(url)) continue;
        busy++;
        load(url).catch(function () {}).then(function () { busy--; pump(); });
      }
    }
    function want(url, first) {
      if (!url || fresh(url)) return;
      var i = queue.indexOf(url);
      if (i >= 0) { if (!first) return; queue.splice(i, 1); }
      if (first) queue.unshift(url); else queue.push(url);
      pump();
    }
    var seen = window.IntersectionObserver && new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) want(urlOf(en.target));
        // 실시간 구독(realtime.js)도 보이는 행을 이 관찰자로 안다
        body.dispatchEvent(new CustomEvent("rt-row", { detail: { el: en.target, on: en.isIntersecting } }));
      });
    }, { rootMargin: "200px 0px" });
    var ROW = "[data-panel], [hx-get$='/panel']";
    function scan(root) {
      if (!seen) return;
      root = root && root.isConnected ? root : document;
      var els = Array.prototype.slice.call(root.querySelectorAll(ROW));
      // 행 하나만 다시 그려졌으면(outerHTML) root가 곧 그 행이다 — querySelectorAll은 자기 자신을 안 본다
      if (root.matches && root.matches(ROW)) els.push(root);
      els.forEach(function (el) {
        if (!panel.contains(el) && urlOf(el)) { seen.unobserve(el); seen.observe(el); }
      });
    }
    var idle = window.requestIdleCallback || function (f) { setTimeout(f, 300); };
    idle(function () { scan(); });
    body.addEventListener("htmx:afterSettle", function (e) { if (e.target !== panel) scan(e.target); });
    // 누르기 직전(마우스 올림·초점)이면 줄 맨 앞으로
    ["pointerover", "focusin"].forEach(function (type) {
      body.addEventListener(type, function (e) {
        var el = e.target.closest && e.target.closest(ROW);
        if (el && !panel.contains(el)) want(urlOf(el), true);
      }, { passive: true });
    });
    function drop(e) {
      var id = e.detail && e.detail.id;
      if (id == null) { Object.keys(cache).forEach(function (u) { gen[u] = (gen[u] || 0) + 1; stale[u] = true; }); scan(); return; }
      var url = "/tasks/" + id + "/panel";
      gen[url] = (gen[url] || 0) + 1; stale[url] = true;
      if (document.querySelector('[data-panel="' + url + '"], [hx-get="' + url + '"]')) want(url);
    }
    body.addEventListener("task-changed", drop);
    body.addEventListener("task-updated", drop);
    body.addEventListener("rt-stale", drop);   // 실시간 T: 이벤트(접힌 섹션이라 다시 받지 않을 때도)
    ["input", "pointerdown", "keydown"].forEach(function (type) {
      panel.addEventListener(type, function () { touched = true; });
    });
    function shown(url) { return panel.firstElementChild && panel.firstElementChild.getAttribute("hx-get") === url; }
    function put(html) { panel.innerHTML = html; htmx.process(panel); panelSwapped(panel); requestAnimationFrame(syncAllBoardNavigation); }
    // 밖에서 패널을 여는 GET(행·버튼·달력·openPanel)만 가로챈다. 패널 안 새로고침과 ?block=1 같은 변형은 그대로 보낸다.
    body.addEventListener("htmx:beforeRequest", function (e) {
      var d = e.detail || {}, cfg = d.requestConfig || {}, url = d.pathInfo && d.pathInfo.requestPath;
      if (!d.target || d.target !== panel || cfg.verb !== "get" || !RE.test(url || "") || panel.contains(d.elt)) return;
      var html = cache[url];
      if (!html) return;
      e.preventDefault();
      var push = d.elt && d.elt.getAttribute && d.elt.getAttribute("hx-push-url");
      if (push && push !== "false") history.pushState(null, "", push);
      touched = false;
      put(html);
      load(url).then(function (latest) {
        if (touched || !shown(url) || same(latest, html)) return;
        var top = panel.scrollTop, focused = panel.contains(document.activeElement);
        panelOpening = focused;
        put(latest);
        panel.scrollTop = top;
      }).catch(function () {});
    });
    // 네트워크로 연 패널도 받아 둔다
    body.addEventListener("htmx:afterRequest", function (e) {
      var d = e.detail || {}, url = d.pathInfo && d.pathInfo.requestPath;
      if (!(d.successful && d.target === panel && RE.test(url || "") && d.xhr)) return;
      cache[url] = d.xhr.responseText; tags[url] = d.xhr.getResponseHeader("ETag"); delete stale[url];
    });
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

  // 오늘 화면의 메모 카드: 페이지를 처음 열 때만 한 번 흔든다(실시간으로 다시 그려질 때는 흔들지 않는다)
  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    var memo = document.querySelector(".memo");
    if (memo) {
      memo.classList.add("memo-wiggle");
      memo.addEventListener("animationend", function () { memo.classList.remove("memo-wiggle"); }, { once: true });
    }
  }

  // 설정 화면: 저장하면 서버가 같은 화면으로 다시 보내(redirect) 첫 섹션만 열린 채 맨 위로 돌아간다.
  // 저장 직전의 열린 섹션과 스크롤 위치를 이 탭에만 잠깐 적어 두었다가 돌아온 화면에서 되살린다.
  (function () {
    if (!document.querySelector("details.settings-section")) return;
    var KEY = "udally.settingsView:" + location.pathname + location.search; // 조직 설정은 탭(?tab=)마다 따로
    body.addEventListener("submit", function (e) {
      var f = e.target;
      // HTMX 폼은 화면을 다시 그리지 않으므로 기억하지 않는다(다음 방문에 엉뚱하게 되살아나지 않게)
      if (e.defaultPrevented || !f.closest("main") || f.matches("[hx-post],[hx-get],[hx-put],[data-hx-post]")) return;
      var open = [];
      document.querySelectorAll("details.settings-section[id]").forEach(function (d) { if (d.open) open.push(d.id); });
      try { sessionStorage.setItem(KEY, JSON.stringify({ open: open, y: window.scrollY })); } catch (err) { /* 저장소를 못 쓰면 기본 화면 */ }
    });
    var saved = null;
    try { saved = JSON.parse(sessionStorage.getItem(KEY) || "null"); sessionStorage.removeItem(KEY); } catch (err) { saved = null; }
    if (!saved || location.hash) return; // 주소에 섹션(#)을 지정해 온 경우는 그쪽을 따른다
    document.querySelectorAll("details.settings-section[id]").forEach(function (d) { d.open = saved.open.indexOf(d.id) >= 0; });
    requestAnimationFrame(function () { window.scrollTo(0, saved.y || 0); });
  })();

  // 헤더 통합 검색(combobox + listbox). 결과 조각은 htmx가 #hsearch-pop에 넣고, 여기서는 펼침·키보드·안내만 한다.
  (function () {
    var form = document.getElementById("hsearch-form");
    if (!form) return;
    var input = document.getElementById("hsearch-q"), pop = document.getElementById("hsearch-pop");
    var status = document.getElementById("hsearch-status"), toggle = document.querySelector(".hsearch-toggle");
    var header = form.closest(".header"), active = -1;
    function opts() { return pop.querySelectorAll("[role=option]"); }
    function setActive(i) {
      var o = opts();
      o.forEach(function (el, j) { el.setAttribute("aria-selected", j === i ? "true" : "false"); });
      active = o[i] ? i : -1;
      if (o[i]) { input.setAttribute("aria-activedescendant", o[i].id); o[i].scrollIntoView({ block: "nearest" }); }
      else input.removeAttribute("aria-activedescendant");
    }
    function show(on) {
      on = on && !!pop.firstElementChild;
      pop.hidden = !on;
      input.setAttribute("aria-expanded", on ? "true" : "false");
      if (!on) setActive(-1);
    }
    function isOverlay() { return toggle && getComputedStyle(toggle).display !== "none"; }
    function openSearch() {
      if (isOverlay()) { header.classList.add("hsearch-open"); toggle.setAttribute("aria-expanded", "true"); }
      input.focus(); input.select();
    }
    function closeOverlay() {
      show(false);
      if (!header.classList.contains("hsearch-open")) return;
      header.classList.remove("hsearch-open"); toggle.setAttribute("aria-expanded", "false"); toggle.focus();
    }
    pop.addEventListener("htmx:afterSwap", function () {
      var box = pop.firstElementChild;
      show(document.activeElement === input && input.value.trim() !== "");
      setActive(-1);
      status.textContent = box ? box.dataset.summary : "";
    });
    pop.addEventListener("mousedown", function (e) { e.preventDefault(); }); // 누르는 동안 입력칸 초점 유지
    input.addEventListener("focus", function () { if (input.value.trim()) show(true); });
    form.addEventListener("focusout", function (e) { if (!form.contains(e.relatedTarget)) show(false); });
    input.addEventListener("keydown", function (e) {
      var n = opts().length;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (pop.hidden) { show(true); return; }
        if (n) setActive(e.key === "ArrowDown" ? (active + 1) % n : (active <= 0 ? n - 1 : active - 1));
      } else if (e.key === "Enter" && active >= 0 && !pop.hidden) {
        e.preventDefault(); opts()[active].click();
      } else if (e.key === "Escape") {
        e.stopPropagation(); // 태스크 패널 닫기(문서 keydown)로 번지지 않게
        if (!pop.hidden) show(false);
        else if (header.classList.contains("hsearch-open")) closeOverlay();
        else if (input.value) input.value = "";
        else input.blur();
      }
    });
    if (toggle) toggle.addEventListener("click", function () {
      if (header.classList.contains("hsearch-open")) closeOverlay(); else openSearch();
    });
    form.querySelector(".hsearch-close").addEventListener("click", closeOverlay);
    // 단축키: / (글 입력 중이 아닐 때), Ctrl·⌘+K. 편집기 안 Ctrl+K(링크)는 md-field가 먼저 가져간다.
    document.addEventListener("keydown", function (e) {
      if (e.defaultPrevented || e.isComposing) return;
      var typing = e.target.closest && e.target.closest("input, textarea, select, [contenteditable]:not([contenteditable=false])");
      var slash = e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey;
      var ctrlK = (e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k";
      if (!slash && !ctrlK) return;
      if (document.querySelector("dialog[open]")) return;
      e.preventDefault(); openSearch();
    });
  })();
})();
