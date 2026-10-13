// 설정 → 구성원 관리 → 요청할 정보 항목: 편집 중 초안을 "구성원에게 보이는 모습"에 바로 그린다(IMPL-PLAN-14 §8.4, 시안 A).
// 마크업은 orgs/_member_info_fields.html과 같게(disabled). 저장 전 미리보기일 뿐 서버 값은 바꾸지 않는다.
(function () {
  "use strict";
  function draft(form) {
    var out = [];
    form.querySelectorAll(".field-card").forEach(function (card, n) {
      var q = function (suffix) { return card.querySelector('[name$="-' + suffix + '"]'); };
      var label = q("label"), del = q("delete"), order = q("order");
      if (!label || !label.value.trim() || (del && del.checked)) return;
      var kind = card.querySelector('[name$="-kind"]:checked');
      var req = q("required"), help = q("help"), choices = q("choices");
      out.push({
        order: parseInt(order && order.value, 10) || 0, n: n,
        label: label.value.trim(), kind: kind ? kind.value : "text",
        required: !!(req && req.checked), help: help ? help.value.trim() : "",
        choices: choices ? choices.value.split("\n").map(function (c) { return c.trim(); }).filter(Boolean) : [],
      });
    });
    return out.sort(function (a, b) { return a.order - b.order || a.n - b.n; });
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }
  function render(box, fields) {
    box.replaceChildren();
    if (!fields.length) { box.append(el("p", "muted t13", "이 조직에서 요청하는 구성원 정보 항목이 없습니다.")); return; } // COPY:me.no_fields
    fields.forEach(function (f) {
      var lab = el("label", "field", f.label + (f.required ? " (필수)" : "")), input;
      if (f.kind === "long") { input = el("textarea", "textarea"); input.rows = 4; }
      else if (f.kind === "choice") {
        input = el("select", "select");
        input.append(el("option", "", "고르기"));
        f.choices.forEach(function (c) { input.append(el("option", "", c)); });
      } else { input = el("input", "input"); }
      input.disabled = true;
      lab.append(input);
      if (f.help) lab.append(el("span", "helptext", f.help));
      box.append(lab);
    });
  }
  function init() {
    var form = document.querySelector("[data-field-editor]"), box = document.querySelector("[data-field-preview]");
    if (!form || !box) return;
    var update = function () { render(box, draft(form)); };
    form.addEventListener("input", update);
    form.addEventListener("change", update);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
