// 실시간 반영 클라이언트(설계: design-concepts/realtime/DESIGN-v2.md 3·4절).
// 서버(/rt/*)는 "무엇이(키) 바뀌었다"만 알린다. 화면은 이미 듣고 있는 HTMX 이벤트로 다시 받는다.
//   T:<태스크> → task-changed·task-updated, P:<프로젝트> → project-changed, U:<나> → today-changed
// 탭 공유: Web Locks를 잡은 탭 하나(리더)만 서버에 붙고, 다른 탭은 BroadcastChannel로 구독을 보내고 이벤트를 받는다.
// 사다리: WebSocket → SSE → 폴링. 내려간 단계는 sessionStorage에 두고 5분마다 한 단계 위를 몰래 시도한다.
(function () {
  "use strict";
  var body = document.body;
  if (!body || !body.dataset.live || !window.htmx) return;

  var panel = document.getElementById("panel");
  var PANEL = /^\/tasks\/(\d+)\/panel$/;
  var tab = Math.random().toString(36).slice(2);
  var share = window.BroadcastChannel && navigator.locks;
  var bc = share ? new BroadcastChannel("udally-rt") : null;
  var rows = new Set();      // 화면에 보이는 행(app.js 패널 미리 받기의 IntersectionObserver가 rt-row로 알린다)
  var mine = {};             // 내가 방금 바꾼 것: 되돌아온 메아리는 무시한다
  var held = {};             // 패널에 타이핑 중이면 덮어쓰지 않고 쥐고 있는다
  var folded = { id: null, s: {} };   // 접힌 섹션에 온 변경: 펼 때 패널을 다시 받는다
  var lastSeq = null;        // 마지막으로 본 seq(리더가 바뀌면 이어받는다)

  // ---------- 이 탭의 보기 상태 → 키 ----------
  function panelId() {
    var p = panel && panel.firstElementChild;
    var m = p && PANEL.exec(p.getAttribute("hx-get") || "");
    return m ? m[1] : null;
  }
  function myKeys() {
    if (document.hidden) return [];   // 숨은 탭은 구독하지 않는다
    var k = {};
    (body.dataset.rtKeys || "").split(/\s+/).forEach(function (x) { if (x) k[x] = 1; });
    var p = panelId();
    if (p) k["T:" + p] = 1;
    rows.forEach(function (el) {
      var url = el.getAttribute("data-panel") || el.getAttribute("hx-get") || "";
      if (!el.isConnected) {
        // 행만 다시 그려졌다(outerHTML): 관찰자가 새 행을 알릴 때까지 구독이 빠지지 않게 새 행으로 갈아 끼운다
        rows.delete(el);
        el = url && document.querySelector('[data-panel="' + url + '"], [hx-get="' + url + '"]');
        if (!el || panel && panel.contains(el)) return;
        rows.add(el);
      }
      var m = PANEL.exec(url);
      if (m) k["T:" + m[1]] = 1;
    });
    return Object.keys(k);
  }
  var announceTimer = 0;
  function changed() { clearTimeout(announceTimer); announceTimer = setTimeout(announce, 50); }
  function announce() {
    var m = { t: "subs", tab: tab, keys: myKeys(), panel: !document.hidden && !!panelId() };
    if (L) L.tab(m); else bc.postMessage(m);
  }
  body.addEventListener("rt-row", function (e) {
    var d = e.detail || {};
    if (d.on) rows.add(d.el); else rows.delete(d.el);
    changed();
  });
  body.addEventListener("htmx:afterSettle", changed);
  if (panel) new MutationObserver(changed).observe(panel, { childList: true });
  document.addEventListener("visibilitychange", function () {
    changed();
    if (!document.hidden) resync();   // 숨어 있던 사이 놓친 것은 다시 받는다
  });

  // ---------- 이벤트 → 화면 ----------
  function typingInPanel() {
    var el = document.activeElement;
    return panel && el && panel.contains(el) && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName);
  }
  function apply(id) {
    htmx.trigger(body, "task-changed", { id: id, rt: true });
    htmx.trigger(body, "task-updated", { id: id, rt: true });
  }
  function refresh(key, section, force) {
    var m = /^([TPU]):(\d+)$/.exec(key || "");
    if (!m) return;
    if (m[1] === "P") { htmx.trigger(body, "project-changed", { id: m[2], rt: true }); return; }
    if (m[1] === "U") { htmx.trigger(body, "today-changed", { id: m[2], rt: true }); return; }
    var id = m[2];
    htmx.trigger(body, "rt-stale", { id: id });   // 패널 미리 받기 캐시를 낡음으로
    if (!force && mine[id] && Date.now() - mine[id] < 5000) return;   // 내가 낸 변경이 돌아온 것
    if (section && panel && id === panelId()) {
      var d = panel.querySelector('details[data-section="' + section + '"]');
      if (d && !d.open) {   // 접힌 섹션: 패널은 두고 행만 다시 받는다
        if (folded.id !== id) folded = { id: id, s: {} };
        folded.s[section] = true;
        htmx.trigger(body, "task-changed", { id: id, rt: true });
        return;
      }
    }
    if (typingInPanel()) { held[id] = true; return; }
    apply(id);
  }
  function resync() {
    htmx.trigger(body, "rt-stale", {});
    myKeys().forEach(function (k) { refresh(k, null, true); });
  }
  function handle(m) {
    if (m.seq != null) lastSeq = m.seq;
    if (m.op === "logout") { location.replace("/login"); return; }
    if (m.op === "resync") { resync(); return; }
    var keys = myKeys();
    if (m.op === "denied") {   // 볼 수 없게 됐다: 기존 화면 코드가 권한대로 다시 그린다
      (m.keys || []).forEach(function (k) { if (keys.indexOf(k) >= 0) refresh(k, null, true); });
      return;
    }
    if (m.key && keys.indexOf(m.key) >= 0) refresh(m.key, m.section || null, false);
  }

  // 내가 보낸 쓰기(GET 제외)는 잠시 메아리를 무시한다
  body.addEventListener("htmx:afterRequest", function (e) {
    var d = e.detail || {}, cfg = d.requestConfig || {};
    if (cfg.verb === "get") return;
    var m = /\/tasks\/(\d+)\//.exec((d.pathInfo && d.pathInfo.requestPath) || "");
    if (m) mine[m[1]] = Date.now();
  });
  body.addEventListener("focusout", function () {
    setTimeout(function () {
      if (typingInPanel()) return;
      Object.keys(held).forEach(function (id) { apply(id); delete held[id]; });
    }, 0);
  });
  // 이 화면에서 낸 변경(서버 HX-Trigger task-changed)은 보드에도 바로 반영한다. 실시간으로 온 것은 P 키가 맡는다.
  body.addEventListener("task-changed", function (e) {
    if (e.detail && e.detail.rt) return;
    (body.dataset.rtKeys || "").split(/\s+/).forEach(function (k) {
      if (k.indexOf("P:") === 0) htmx.trigger(body, "project-changed", { id: k.slice(2) });
    });
  });
  if (panel) {
    // 접힌 채 바뀐 섹션을 펴면 그때 패널을 다시 받는다(ETag)
    panel.addEventListener("toggle", function (e) {
      var d = e.target, id = panelId();
      if (!d.open || !d.dataset || !d.dataset.section || folded.id !== id || !folded.s[d.dataset.section]) return;
      folded.s = {};
      // source를 패널로 두어 미리 받기(app.js)가 낡은 캐시로 가로채지 않게 한다
      htmx.ajax("GET", "/tasks/" + id + "/panel", { source: panel, target: panel, swap: "innerHTML" });
    }, true);
    // 같은 태스크 패널을 다시 받을 때는 펼쳐 둔 섹션을 그대로 편다
    var keepOpen = null;
    body.addEventListener("htmx:beforeSwap", function (e) {
      var d = e.detail || {}, cur = panel.firstElementChild;
      if (d.target !== panel) return;
      keepOpen = cur && d.pathInfo && d.pathInfo.requestPath === cur.getAttribute("hx-get")
        ? [].map.call(panel.querySelectorAll("details[data-section][open]"), function (x) { return x.dataset.section; })
        : null;
    });
    body.addEventListener("htmx:afterSwap", function (e) {
      if (e.detail.target !== panel) return;
      folded = { id: panelId(), s: {} };
      (keepOpen || []).forEach(function (s) {
        var d = panel.querySelector('details[data-section="' + s + '"]');
        if (d) d.open = true;
      });
      keepOpen = null;
    });
  }

  // ---------- 탭 공유 ----------
  var L = null;   // 이 탭이 리더면 리더 상태
  if (bc) {
    bc.onmessage = function (e) {
      var m = e.data || {};
      if (m.t === "msg") handle(m.m);
      else if (m.t === "level") body.dataset.rt = m.v;
      else if (L) L.tab(m);
      else if (m.t === "hello") announce();
    };
    window.addEventListener("pagehide", function () { if (!L) bc.postMessage({ t: "bye", tab: tab }); });
    navigator.locks.request("udally-rt", function () { lead(); return new Promise(function () {}); });
  } else {
    lead();   // Web Locks·BroadcastChannel이 없으면 탭마다 직접 붙는다
  }

  // ---------- 리더: 서버 연결 ----------
  function lead() {
    var LEVELS = ["ws", "sse", "poll"];
    var tabs = {}, server = {}, denied = {}, cur = null, drops = [], fails = 0, lost = false, stopped = false, retry = 0;
    var level = 0;
    try { level = Math.min(2, Math.max(0, +sessionStorage.getItem("udally-rt-level") || 0)); } catch (err) { level = 0; }

    function setLevel(v) {
      level = v;
      try { sessionStorage.setItem("udally-rt-level", String(v)); } catch (err) { /* 저장 못 해도 동작은 같다 */ }
      mark(LEVELS[v]);
    }
    function mark(v) { body.dataset.rt = v; if (bc) bc.postMessage({ t: "level", v: v }); }
    function broadcast(m) { if (bc) bc.postMessage({ t: "msg", m: m }); handle(m); }
    function since() { return lastSeq == null ? "" : "since=" + encodeURIComponent(lastSeq); }
    function csrf() {
      try { return JSON.parse(body.getAttribute("hx-headers") || "{}")["X-CSRFToken"]; } catch (err) { return ""; }
    }

    // 모든 탭의 키를 합쳐 서버 구독과 맞춘다
    function sync() {
      if (!cur || !cur.ok) return;
      var want = {};
      Object.keys(tabs).forEach(function (t) {
        tabs[t].keys.forEach(function (k) { if (!denied[k]) want[k] = 1; });
      });
      var add = Object.keys(want).filter(function (k) { return !server[k]; });
      var del = Object.keys(server).filter(function (k) { return !want[k]; });
      if (!add.length && !del.length) return;
      add.forEach(function (k) { server[k] = 1; });
      del.forEach(function (k) { delete server[k]; });
      cur.sub(add, del);
    }

    function ready(t) {
      if (t.ok || stopped) return;
      t.ok = true;
      if (t !== cur) {   // 한 단계 위 탐색이 붙었다: 갈아 끼운다
        var old = cur;
        cur = t;
        if (old) old.close();
        clearTimeout(retry);
      }
      setLevel(t.v);
      server = {};
      fails = 0;
      sync();
      if (lost) { lost = false; broadcast({ op: "resync" }); }   // 전면 실패에서 돌아왔다
    }
    function msg(t, m) {
      if (t !== cur || !m) return;
      if (m.op === "pong" || m.op === "ping" || m.op === "stream") return;
      if (m.op === "denied") (m.keys || []).forEach(function (k) { denied[k] = 1; delete server[k]; });
      if (m.op === "logout") { stopped = true; cur = null; t.close(); }
      broadcast(m);
    }
    // SSE·폴링: 서버가 stream id를 주면 그 stream에 구독을 다시 건다
    function stream(t, id) {
      if (t.stream === id) return;
      t.stream = id;
      if (!t.ok) { ready(t); return; }
      if (t === cur) { server = {}; sync(); }
    }
    function end(t, wasOk, lower) {
      if (t !== cur) return;   // 실패한 탐색, 이미 갈아 끼운 연결
      cur = null;
      server = {};
      if (stopped) return;
      var now = Date.now();
      if (wasOk && !lower) {   // 붙어 있다 끊겼다: 1분 안에 두 번이 아니면 같은 단계로 다시
        drops = drops.filter(function (x) { return now - x < 60000; });
        drops.push(now);
        if (drops.length < 2) { connect(); return; }
      }
      drops = [];
      if (level < 2) { setLevel(level + 1); connect(); return; }
      // 세 단계 모두 실패(/rt/가 죽음): 5초~60초 지수 백오프(지터 포함) 뒤 맨 위부터 다시
      lost = true;
      mark("off");
      var d = Math.min(60000, 5000 * Math.pow(2, fails++));
      retry = setTimeout(function () { setLevel(0); connect(); }, d / 2 + Math.random() * d / 2);
    }
    function connect() { cur = open(level); }
    function open(v) {
      var t = { v: v, ok: false, stream: null };
      [openWS, openSSE, openPoll][v](t);
      return t;
    }

    function openWS(t) {
      var ws, last = Date.now(), pinger = 0, timer;
      try {
        ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/rt/ws" + (since() ? "?" + since() : ""));
      } catch (err) { setTimeout(function () { end(t, false, false); }, 0); t.sub = t.close = function () {}; return; }
      function send(o) { if (ws.readyState === 1) ws.send(JSON.stringify(o)); }
      timer = setTimeout(function () { if (!t.ok) ws.close(); }, 5000);   // 5초 안에 열리지 않으면 내려간다
      ws.onopen = function () {
        clearTimeout(timer);
        ready(t);
        pinger = setInterval(function () {
          if (Date.now() - last > 60000) ws.close(); else send({ op: "ping" });
        }, 25000);
      };
      ws.onmessage = function (e) {
        last = Date.now();
        try { msg(t, JSON.parse(e.data)); } catch (err) { /* 형식이 아니면 무시 */ }
      };
      ws.onclose = function () { clearTimeout(timer); clearInterval(pinger); end(t, t.ok, false); };
      t.sub = function (add, del) {
        if (add.length) send({ op: "sub", keys: add });
        if (del.length) send({ op: "unsub", keys: del });
      };
      t.close = function () { ws.onclose = ws.onmessage = null; clearTimeout(timer); clearInterval(pinger); ws.close(); };
    }

    function subscribe(t, add, del) {
      if (!t.stream) return;
      fetch("/rt/subscribe", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ stream: t.stream, keys: add, unsub: del }),
      }).then(function (r) { if (!r.ok) throw r; }).catch(function () {
        if (t !== cur) return;   // 실패하면 다음 맞추기에서 다시 보낸다
        server = {};
        setTimeout(sync, 5000);
      });
    }

    function openSSE(t) {
      var q = [since()].filter(Boolean).join("&");
      var es = new EventSource("/rt/sse" + (q ? "?" + q : "")), watch = 0;
      // 처음엔 5초, 붙은 뒤엔 30초 동안 아무것도 없으면 내려간다(스트리밍을 모았다 넘기는 프록시 대비)
      function arm() {
        clearTimeout(watch);
        watch = setTimeout(function () { t.close(); end(t, t.ok, true); }, t.ok ? 30000 : 5000);
      }
      arm();
      es.onmessage = function (e) {
        var m;
        try { m = JSON.parse(e.data); } catch (err) { arm(); return; }
        if (m.stream) stream(t, m.stream);
        msg(t, m);
        arm();   // 첫 메시지(stream)로 붙은 뒤에 걸어야 5초가 아니라 30초 감시가 된다
      };
      es.onerror = function () {
        if (es.readyState === 2) { t.close(); end(t, t.ok, false); }   // 닫혔다(브라우저가 다시 붙지 않는다)
      };
      t.sub = function (add, del) { subscribe(t, add, del); };
      t.close = function () { clearTimeout(watch); es.onmessage = es.onerror = null; es.close(); };
    }

    function openPoll(t) {
      var timer = 0, dead = false;
      function tick() {
        var q = [t.stream ? "stream=" + encodeURIComponent(t.stream) : "", since()].filter(Boolean).join("&");
        fetch("/rt/poll" + (q ? "?" + q : ""), { credentials: "same-origin", headers: { Accept: "application/json" } })
          .then(function (r) { if (!r.ok || r.redirected) throw r; return r.json(); })
          .then(function (d) {
            if (dead) return;
            if (d.stream) stream(t, d.stream); else ready(t);
            if (d.op) msg(t, d);
            (d.events || []).forEach(function (m) { msg(t, m); });
            if (d.seq != null && t === cur) lastSeq = d.seq;
            if (dead || stopped) return;
            var open = Object.keys(tabs).some(function (k) { return tabs[k].panel; });
            timer = setTimeout(tick, open ? 5000 : 15000);
          })
          .catch(function () { if (!dead) { dead = true; end(t, t.ok, false); } });
      }
      tick();
      t.sub = function (add, del) { subscribe(t, add, del); };
      t.close = function () { dead = true; clearTimeout(timer); };
    }

    // 5분마다 한 단계 위를 몰래 시도한다. 붙으면 ready가 갈아 끼운다.
    setInterval(function () { if (cur && cur.ok && level > 0 && !stopped) open(level - 1); }, 300000);

    L = {
      tab: function (m) {
        if (m.t === "subs") { tabs[m.tab] = m; if (m.tab !== tab && body.dataset.rt) bc.postMessage({ t: "level", v: body.dataset.rt }); }
        else if (m.t === "bye") delete tabs[m.tab];
        else return;
        sync();
      },
    };
    connect();
    announce();
    if (bc) bc.postMessage({ t: "hello" });   // 다른 탭은 자기 구독을 다시 보낸다
  }
})();
