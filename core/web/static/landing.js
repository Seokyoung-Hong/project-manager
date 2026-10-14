// teams 탭: ARIA tabs(자동 활성화, 화살표·Home·End)
(() => {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const pick = (t) => {
    tabs.forEach((x) => {
      const on = x === t;
      x.setAttribute('aria-selected', on);
      x.tabIndex = on ? 0 : -1;
      document.getElementById(x.getAttribute('aria-controls')).hidden = !on;
    });
    t.focus();
  };
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => pick(t));
    t.addEventListener('keydown', (e) => {
      const n = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
      if (n === undefined) return;
      e.preventDefault();
      pick(tabs[(n + tabs.length) % tabs.length]);
    });
  });
})();

// 소개 화면의 메모 카드: 앱과 같이 평소엔 반듯하게, 처음 열 때 한 번만 흔든다(기울기·흔들기 규칙은 app.css .memo)
if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  document.querySelectorAll(".memo").forEach(function (memo) {
    memo.classList.add("memo-wiggle");
    memo.addEventListener("animationend", function () { memo.classList.remove("memo-wiggle"); }, { once: true });
  });
}
