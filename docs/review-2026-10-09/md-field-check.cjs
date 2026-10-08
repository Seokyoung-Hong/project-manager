const { chromium } = require('C:/Users/tjrdu/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright');
const assert = require('assert/strict');
const SHOTS = process.argv[2];
const B = 'http://127.0.0.1:8931';
const log = (...a) => console.log('OK', ...a);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  async function page(width, height = 900) {
    const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, colorScheme: 'light' });
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errors.push(`${width} pageerror ${e.message}`));
    p.on('console', (m) => { if (m.type() === 'error') errors.push(`${width} console ${m.text()}`); });
    p.on('dialog', (d) => d.accept(d.type() === 'prompt' ? 'https://example.com/a' : undefined));
    await p.goto(B + '/login');
    await p.fill('#id_username', 'demo');
    await p.fill('#id_password', 'DemoPass123!');
    await Promise.all([p.waitForNavigation(), p.click('button[type=submit], form button')]);
    return p;
  }
  const ready = (p, n = 1) => p.waitForFunction((n) => document.querySelectorAll('.mdf .ProseMirror').length >= n, n);

  // ---------- 1440 ----------
  let p = await page(1440);
  await p.goto(B + '/tasks/1');
  await ready(p, 3);
  const panelMd = await p.$$eval('textarea[data-md]', (t) => t.map((x) => [x.name, x.hidden, x.dataset.ready]));
  assert.ok(panelMd.length >= 3 && panelMd.every((x) => x[1] && x[2] === '1'));
  // 열기만으로 저장하지 않는다: 초점을 넣었다 빼도 요청이 없다
  let posts = 0;
  p.on('request', (r) => { if (r.method() === 'POST' && /\/text\//.test(r.url())) posts++; });
  const desc = p.locator('#task-desc-1 + .mdf .ProseMirror');
  await desc.click();
  await p.evaluate(() => document.activeElement.blur());
  await p.waitForTimeout(1200);
  assert.equal(posts, 0, 'open-only must not save');
  log('열기만으로 저장 안 함');
  // 자동 저장: 입력 → change → 서버 저장
  await desc.click();
  await p.keyboard.press('Control+End');
  await p.keyboard.press('Enter');
  const saved = p.waitForResponse((r) => /\/tasks\/1\/text\/description/.test(r.url()) && r.request().method() === 'POST');
  await p.keyboard.insertText('자동 저장 확인 문장');
  await p.keyboard.press('Control+b');
  await p.keyboard.insertText(' 굵게');
  assert.equal(await p.locator('#task-desc-1 + .mdf .mdf-bar').isVisible(), true);
  const bar = await p.$eval('#task-desc-1 + .mdf', (box) => {
    const bar = box.querySelector('.mdf-bar'), r = bar.getBoundingClientRect(), body = box.querySelector('.mdf-body').getBoundingClientRect();
    return { below: r.top >= body.bottom - 1, text: [...bar.querySelectorAll('button')].some((b) => b.textContent.trim()), svg: bar.querySelectorAll('button:not([hidden]) svg').length };
  });
  assert.ok(bar.below && !bar.text && bar.svg > 0, JSON.stringify(bar));
  await p.screenshot({ path: SHOTS + '/1440-task-desc-focus.png' });
  await saved;
  const html = await (await p.request.get(B + '/tasks/1/panel')).text();
  assert.ok(html.includes('자동 저장 확인 문장 **굵게**'), 'server has markdown');
  log('태스크 설명 자동 저장', '자동 저장 확인 문장 **굵게**');

  // 폭을 줄이면 [더보기]로 넘긴다
  const count = () => p.$eval('#task-desc-1 + .mdf .mdf-bar', (b) => ({ shown: b.querySelectorAll('[data-k]:not([hidden])').length, more: !b.querySelector('.more').hidden }));
  const wide = await count();
  await p.evaluate(() => { document.querySelector('#task-desc-1 + .mdf').style.width = '300px'; });
  await p.waitForTimeout(300);
  const narrow = await count();
  assert.ok(narrow.more && narrow.shown < wide.shown, JSON.stringify({ wide, narrow }));
  await p.click('#task-desc-1 + .mdf .more');
  const menu = await p.$eval('#task-desc-1 + .mdf .mdf-menu', (m) => ({ n: m.querySelectorAll('button').length, svg: m.querySelectorAll('button svg').length, txt: m.textContent }));
  assert.ok(menu.n > 0 && menu.svg === menu.n && /그림|구분선/.test(menu.txt));
  await p.screenshot({ path: SHOTS + '/1440-narrow-more-menu.png' });
  await p.keyboard.press('Escape');
  await p.evaluate(() => { document.querySelector('#task-desc-1 + .mdf').style.width = ''; });
  await p.waitForTimeout(300);
  const back = await count();
  assert.equal(back.shown, wide.shown);
  log('폭 넘김', JSON.stringify({ wide, narrow, back }));

  // 사유: 막힘 → 빈 사유 Ctrl+Enter → 오류, HTMX 재초기화, 사유 입력 Ctrl+Enter → 저장
  await p.evaluate(() => htmx.ajax('GET', '/tasks/1/panel?block=1', { target: '#panel', swap: 'innerHTML' }));
  await p.waitForSelector('#stop-reason-1[data-ready="1"]', { state: 'attached' });
  await p.waitForFunction(() => document.activeElement?.closest('.mdf')?.previousElementSibling?.id === 'stop-reason-1');
  log('data-focus → 사유 칸 초점');
  await p.keyboard.press('Control+Enter');
  await p.waitForSelector('.stop-box .error');
  assert.equal(await p.$$eval('textarea[data-md]', (t) => t.filter((x) => x.nextElementSibling?.classList.contains('mdf')).length), await p.$$eval('textarea[data-md]', (t) => t.length));
  assert.equal(await p.$$eval('.mdf', (b) => b.length), await p.$$eval('textarea[data-md]', (t) => t.length), 'no duplicate editors after HTMX swap');
  await p.screenshot({ path: SHOTS + '/1440-stop-required-error.png' });
  log('사유 필수 오류(서버)', await p.textContent('.stop-box .error'));
  await p.locator('#stop-reason-1 + .mdf .ProseMirror').click();
  await p.keyboard.insertText('외부 API 응답 대기');
  await p.keyboard.press('Control+Enter');
  await p.waitForFunction(() => !document.querySelector('#stop-reason-1') || document.body.textContent.includes('외부 API 응답 대기'));
  await p.waitForTimeout(500);
  const st = await (await p.request.get(B + '/tasks/1/panel')).text();
  assert.ok(st.includes('외부 API 응답 대기'));
  log('Ctrl+Enter 사유 제출');

  // 결정 기록 정정의 required(숨은 textarea) → 칸 오류
  // (사용자 입력 기록이 있어야 보이므로 여기서는 생략 가능) — 요청 화면으로
  await p.goto(B + '/requests/new');
  await ready(p, 1);
  await p.fill('input[name=title]', '영상 촬영 지원');
  await p.check('input[name=target][value=team]');
  await p.selectOption('select[name=team]', { index: 1 });
  await p.locator('#req-body + .mdf .ProseMirror').click();
  await p.keyboard.press('Control+b');
  await p.keyboard.insertText('금요일까지');
  await p.keyboard.press('Control+b');
  await p.keyboard.insertText(' 필요합니다.');
  await p.screenshot({ path: SHOTS + '/1440-request-new.png' });
  await Promise.all([p.waitForNavigation(), p.click('button:has-text("요청 보내기")')]);
  await p.waitForSelector('.md-view[data-ready="1"] strong');
  assert.equal(await p.textContent('.md-view strong'), '금요일까지');
  await p.screenshot({ path: SHOTS + '/1440-request-detail-render.png' });
  log('요청 제출·보기 렌더', p.url());

  // 거버넌스(위 서식 줄, sticky)
  await p.goto(B + '/orgs/1/governance');
  await ready(p, 1);
  const gov = p.locator('textarea[name=text] + .mdf .ProseMirror');
  assert.equal(await p.isVisible('textarea[name=text] + .mdf .mdf-cue'), true);
  await gov.click();
  await p.keyboard.press('Control+Home');
  await p.keyboard.insertText('거버넌스 시험 문장 ');
  const g = await p.$eval('textarea[name=text] + .mdf', (box) => { const bar = box.querySelector('.mdf-bar'); return Boolean(bar.compareDocumentPosition(box.querySelector('.mdf-body')) & 4) && getComputedStyle(bar).position === 'sticky' && bar.getBoundingClientRect().top >= 0; });
  assert.ok(g, 'top bar above body');
  await p.screenshot({ path: SHOTS + '/1440-governance-top-bar.png' });
  await Promise.all([p.waitForNavigation(), p.click('button:has-text("거버넌스 저장")')]);
  await ready(p, 1);
  assert.ok((await p.inputValue('textarea[name=text]')).slice(0, 80).includes('거버넌스 시험 문장'));
  log('거버넌스 저장');

  // 문서(version 저장 큐 + 공용 서식 줄)
  await p.goto(B + '/projects/1/docs?doc=3');
  await p.waitForSelector('#doc-body[data-ready="1"]', { state: 'attached' });
  const v0 = Number(await p.getAttribute('#doc-body', 'data-version'));
  await p.click('#doc-body .ProseMirror');
  await p.waitForTimeout(150);
  await p.keyboard.press('Control+End');
  await p.keyboard.press('Enter');
  await p.keyboard.insertText('문서 저장 시험');
  assert.equal(await p.isVisible('.mdf[data-toolbar=top] .mdf-bar'), true);
  assert.equal(await p.$$eval('.tt-bar, [data-cmd]', (x) => x.length), 0);
  await p.waitForFunction((v0) => Number(document.querySelector('#doc-body').dataset.version) > v0, v0, { timeout: 5000 });
  await p.screenshot({ path: SHOTS + '/1440-doc-editor.png' });
  await p.keyboard.press('Escape');
  await p.waitForTimeout(200);
  assert.equal(await p.isVisible('.mdf[data-toolbar=top] .mdf-bar'), false, 'Esc ends editing, bar hidden');
  log('문서 저장 version', v0, '→', await p.getAttribute('#doc-body', 'data-version'));
  await p.context().close();

  // ---------- 390 ----------
  p = await page(390, 844);
  await p.goto(B + '/tasks/1');
  await ready(p, 3);
  await p.locator('#task-notes-1 + .mdf .ProseMirror').click();
  // 화면 키보드 흉내: visualViewport 높이를 336px 줄이고 resize를 쏜다
  await p.evaluate(() => {
    const h = innerHeight - 336;
    Object.defineProperty(visualViewport, 'height', { get: () => h, configurable: true });
    visualViewport.dispatchEvent(new Event('resize'));
  });
  await p.waitForTimeout(200);
  const m = await p.$eval('#task-notes-1 + .mdf .mdf-bar', (bar) => {
    const r = bar.getBoundingClientRect(), b = bar.querySelector('[data-k]:not([hidden])').getBoundingClientRect();
    return { bottom: Math.round(r.bottom), top: Math.round(r.top), h: Math.round(r.height), w: Math.round(r.width), sw: bar.scrollWidth, cw: bar.clientWidth, btnW: Math.round(b.width), ih: innerHeight, more: !bar.querySelector('.more').hidden };
  });
  assert.equal(m.bottom, m.ih - 336, JSON.stringify(m));
  assert.equal(m.h, 40);
  assert.equal(m.w, 390);
  assert.ok(m.sw <= m.cw + 1, 'no horizontal scroll');
  assert.ok(m.btnW >= 44);
  await p.keyboard.insertText('모바일 메모');
  await p.screenshot({ path: SHOTS + '/390-keyboard-bar.png' });
  await p.click('#task-notes-1 + .mdf .more');
  const mm = await p.$eval('#task-notes-1 + .mdf .mdf-menu', (x) => Math.round(x.getBoundingClientRect().bottom));
  assert.ok(mm <= m.top, 'menu opens upward above keyboard bar');
  await p.screenshot({ path: SHOTS + '/390-more-up.png' });
  log('모바일 키보드 위 서식 줄', JSON.stringify(m), 'menu bottom', mm);
  await p.context().close();

  await browser.close();
  console.log(errors.length ? 'ERRORS\n' + errors.join('\n') : 'console errors 0');
})().catch((e) => { console.error('FAIL', e); process.exit(1); });
