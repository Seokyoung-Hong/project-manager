// L3 마무리·인라인 HTML·블록 끌어 옮기기(손잡이, Alt+↑/↓)를 실제 서버에서 확인한다.
const { chromium } = require('C:/Users/tjrdu/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright');
const assert = require('assert/strict');
const SHOTS = process.argv[2];
const B = 'http://127.0.0.1:8931';
const log = (...a) => console.log('OK', ...a);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  async function page(width, height = 900, mobile = false) {
    const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, hasTouch: mobile, isMobile: mobile });
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errors.push(`${width} pageerror ${e.message}`));
    p.on('console', (m) => { if (m.type() === 'error') errors.push(`${width} console ${m.text()}`); });
    p.on('dialog', (d) => d.accept());
    await p.goto(B + '/login');
    await p.fill('#id_username', 'demo');
    await p.fill('#id_password', 'DemoPass123!');
    await Promise.all([p.waitForNavigation(), p.click('form button')]);
    return p;
  }
  const md = (p) => p.evaluate(() => window.udallyEditor.getMarkdown());

  // ---------- 1440: 문서 ----------
  let p = await page(1440);
  await p.goto(B + '/projects/1/docs?doc=6');
  await p.waitForSelector('#doc-body[data-ready="1"]', { state: 'attached' });
  // 인라인 HTML: 글자로 보이고(실행 안 함) 저장 시 원문 그대로
  assert.equal(await p.$$eval('#doc-body span[data-html-inline]', (s) => s.map((x) => x.textContent).join('|')), '<span>|</span>');
  let v = Number(await p.getAttribute('#doc-body', 'data-version'));
  await p.click('#doc-body p >> nth=0');
  await p.waitForTimeout(150);
  // 손잡이: 첫 문단 위에 올리면 칸 안 왼쪽 여백에 보인다
  const first = p.locator('#doc-body .ProseMirror > p').nth(0);
  await first.hover();
  await p.waitForTimeout(300);
  const h = await p.$eval('#doc-body', (root) => {
    const el = root.parentElement.querySelector('.drag-handle'), r = el.getBoundingClientRect(), box = root.closest('.mdf').getBoundingClientRect();
    return { vis: getComputedStyle(el).visibility, left: r.left, right: r.right, boxLeft: box.left, text: root.querySelector('.ProseMirror > p').getBoundingClientRect().left };
  });
  assert.ok(h.vis !== 'hidden' && h.left >= h.boxLeft && h.right <= h.text, '손잡이가 칸 안 왼쪽 여백에 ' + JSON.stringify(h));
  await p.screenshot({ path: SHOTS + '/1440-drag-handle-doc.png' });
  // 끌어서 첫 문단을 둘째 문단 아래로
  const handle = p.locator('#doc-body').locator('xpath=..').locator('.drag-handle');
  const target = p.locator('#doc-body .ProseMirror > p').nth(1);
  const tb = await target.boundingBox();
  await handle.dragTo(target, { targetPosition: { x: tb.width - 4, y: tb.height - 2 } });
  await p.waitForFunction((v) => Number(document.querySelector('#doc-body').dataset.version) > v, v, { timeout: 5000 });
  let saved = await md(p);
  assert.ok(saved.startsWith('둘째 문단\n\n첫째 문단'), '끌어 옮긴 순서 ' + JSON.stringify(saved));
  assert.ok(saved.includes('가격 <span>~3</span> 끝'), '인라인 HTML 보존 ' + JSON.stringify(saved));
  log('끌어 옮기기 → 저장 순서', JSON.stringify(saved.split('\n\n').slice(0, 2)), 'v', await p.getAttribute('#doc-body', 'data-version'));
  // Alt+↑로 되돌리기
  v = Number(await p.getAttribute('#doc-body', 'data-version'));
  await p.click('#doc-body .ProseMirror > p >> nth=1');
  await p.keyboard.press('Alt+ArrowUp');
  await p.waitForFunction((v) => Number(document.querySelector('#doc-body').dataset.version) > v, v, { timeout: 5000 });
  saved = await md(p);
  assert.ok(saved.startsWith('첫째 문단\n\n둘째 문단'), 'Alt+↑ ' + JSON.stringify(saved));
  log('Alt+↑ → 저장', JSON.stringify(saved.split('\n\n').slice(0, 2)));
  // 서버에 저장된 본문 확인
  const page6 = await (await p.request.get(B + '/projects/1/docs?doc=6')).text();
  assert.ok(page6.includes('첫째 문단\n\n둘째 문단\n\n가격 &lt;span&gt;~3&lt;/span&gt; 끝'), '서버 본문');
  log('서버 저장본: 순서·인라인 HTML 원문');

  // ---------- 1440: 작은 칸(완료 조건) ----------
  await p.goto(B + '/tasks/1');
  await p.waitForSelector('#task-done-1 + .mdf .ProseMirror');
  assert.ok(await p.$$eval('.mdf .drag-handle', (els) => els.every((e) => getComputedStyle(e).visibility === 'hidden')), '처음에는 손잡이 숨김');
  const before = await p.$eval('#task-done-1 + .mdf', (b) => b.getBoundingClientRect().width);
  await p.click('#task-done-1 + .mdf li >> nth=1');
  await p.locator('#task-done-1 + .mdf li').nth(0).hover();
  await p.waitForTimeout(100);
  await p.locator('#task-done-1 + .mdf li').nth(1).hover();
  await p.waitForTimeout(300);
  const s = await p.$eval('#task-done-1 + .mdf', (box) => {
    const el = box.querySelector('.drag-handle'), r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
    return { w: b.width, l: r.left, bl: b.left, vis: getComputedStyle(el).visibility, sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth };
  });
  assert.equal(s.w, before);
  assert.ok(s.vis !== 'hidden' && s.l >= s.bl && s.sw <= s.cw, '작은 칸 레이아웃 ' + JSON.stringify(s));
  await p.screenshot({ path: SHOTS + '/1440-drag-handle-small-field.png' });
  // 손잡이는 목록 항목(둘) 옆에 선다
  const at = await p.$eval('#task-done-1 + .mdf', (box) => {
    const h = box.querySelector('.drag-handle').getBoundingClientRect(), li = box.querySelectorAll('li')[1].getBoundingClientRect();
    return Math.abs(h.top - li.top) < 12;
  });
  assert.ok(at, '손잡이가 둘째 항목 옆');
  const saveReq = p.waitForResponse((r) => /\/tasks\/1\/text\/done_when/.test(r.url()));
  await p.keyboard.press('Alt+ArrowUp');
  await saveReq;
  const panel = await (await p.request.get(B + '/tasks/1/panel')).text();
  assert.ok(panel.includes('- [ ] 둘\n- [ ] 하나'), '완료 조건 Alt+↑ 저장');
  // 목록 항목 끌어 옮기기: 첫 항목(둘)을 둘째 항목(하나) 아래로
  await p.locator('#task-done-1 + .mdf li').nth(0).hover();
  await p.waitForTimeout(300);
  const li2 = await p.locator('#task-done-1 + .mdf li').nth(1).boundingBox();
  const save2 = p.waitForResponse((r) => /\/tasks\/1\/text\/done_when/.test(r.url()));
  await p.locator('#task-done-1 + .mdf .drag-handle').dragTo(p.locator('#task-done-1 + .mdf li').nth(1), { targetPosition: { x: li2.width - 4, y: li2.height - 2 } });
  await p.evaluate(() => document.activeElement.blur());
  await save2;
  const panelB = await (await p.request.get(B + '/tasks/1/panel')).text();
  assert.ok(panelB.includes('- [ ] 하나\n- [ ] 둘'), '목록 항목 끌어 옮기기 저장 ' + (panelB.match(/- \[ \][^<]*/g) || []).join('|'));
  log('목록 항목 끌어 옮기기 → 자동 저장');
  log('작은 칸: 손잡이 칸 안, 가로 넘침 없음, Alt+↑ 자동 저장');
  // 공용 칸(태스크 설명)에서 끌어 옮기기 → 자동 저장
  const desc = '#task-desc-1 + .mdf';
  await p.click(`${desc} p >> nth=0`);
  await p.locator(`${desc} .ProseMirror > p`).nth(0).hover();
  await p.waitForTimeout(300);
  const t2 = await p.locator(`${desc} .ProseMirror > p`).nth(1).boundingBox();
  const descSave = p.waitForResponse((r) => /\/tasks\/1\/text\/description/.test(r.url()));
  await p.locator(`${desc} .drag-handle`).dragTo(p.locator(`${desc} .ProseMirror > p`).nth(1), { targetPosition: { x: t2.width - 4, y: t2.height - 2 } });
  await p.locator('h1, .display, .number').first().click({ force: true }).catch(() => {});
  await p.evaluate(() => document.activeElement.blur());
  await descSave;
  const panel2 = await (await p.request.get(B + '/tasks/1/panel')).text();
  assert.ok(panel2.includes('아래 문단\n\n위 문단'), '설명 끌어 옮기기 저장');
  log('공용 칸 끌어 옮기기 → 자동 저장');
  await p.context().close();

  // ---------- 390(터치): L3 Tab→Enter→Esc→Tab→Enter, 손잡이 숨김 ----------
  p = await page(390, 844, true);
  await p.goto(B + '/projects/1/docs?doc=6');
  await p.waitForSelector('#doc-body[data-ready="1"]', { state: 'attached' });
  await p.focus('input[data-note-field="title"], #doc-body .ProseMirror');
  for (let i = 0; i < 40; i++) {
    if (await p.evaluate(() => document.activeElement?.classList.contains('ProseMirror'))) break;
    await p.keyboard.press('Tab');
  }
  assert.ok(await p.evaluate(() => document.activeElement.classList.contains('ProseMirror')), 'Tab으로 본문');
  await p.keyboard.press('Enter');
  assert.equal(await p.evaluate(() => window.udallyEditor.isEditable), true);
  await p.keyboard.press('Escape');
  const after = await p.evaluate(() => ({ editable: window.udallyEditor.isEditable, focus: document.activeElement.className, tab: document.querySelector('#doc-body .ProseMirror').getAttribute('tabindex') }));
  assert.ok(!after.editable && /ProseMirror/.test(after.focus) && after.tab === '0', 'Esc 뒤 본문에 초점 ' + JSON.stringify(after));
  await p.keyboard.press('Shift+Tab');
  await p.keyboard.press('Tab');
  assert.ok(await p.evaluate(() => document.activeElement.classList.contains('ProseMirror')), '다시 Tab으로 본문');
  await p.keyboard.press('Enter');
  assert.equal(await p.evaluate(() => window.udallyEditor.isEditable), true, '다시 Enter로 편집');
  const hd = await p.$$eval('.drag-handle', (els) => els.map((e) => getComputedStyle(e).display));
  assert.ok(hd.every((d) => d === 'none'), '터치에서 손잡이 숨김 ' + hd);
  await p.screenshot({ path: SHOTS + '/390-l3-reenter.png' });
  log('390: Tab→Enter→Esc→Tab→Enter, 손잡이 숨김');
  await p.context().close();

  await browser.close();
  console.log(errors.length ? 'ERRORS\n' + errors.join('\n') : 'console errors 0');
})().catch((e) => { console.error('FAIL', e); process.exit(1); });
