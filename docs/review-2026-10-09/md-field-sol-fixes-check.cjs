// Sol 반려(H1·M1·M2·M3·M4·L3) 재현 시나리오가 막히는지 실제 서버에서 확인한다.
const { chromium } = require('C:/Users/tjrdu/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright');
const assert = require('assert/strict');
const SHOTS = process.argv[2];
const B = 'http://127.0.0.1:8931';
const log = (...a) => console.log('OK', ...a);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  async function page(width, height = 900) {
    const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errors.push(`${width} pageerror ${e.message}`));
    p.on('console', (m) => { if (m.type() === 'error' && !/409|Failed to load resource/.test(m.text())) errors.push(`${width} console ${m.text()}`); });
    await p.goto(B + '/login');
    await p.fill('#id_username', 'demo');
    await p.fill('#id_password', 'DemoPass123!');
    await Promise.all([p.waitForNavigation(), p.click('form button')]);
    return p;
  }
  let p = await page(1440);

  // H1·M2·M3: 원문 보존 문서. 앞 문단만 고치고 저장된 md를 서버에서 읽는다.
  await p.goto(B + '/projects/1/docs?doc=4');
  await p.waitForSelector('#doc-body[data-ready="1"]', { state: 'attached' });
  const view = await p.$eval('#doc-body', (el) => ({
    evil: [...el.querySelectorAll('a')].filter((a) => /evil/.test(a.getAttribute('href') || '')).length,
    imgs: [...el.querySelectorAll('img[src]')].map((i) => i.getAttribute('src')),
    video: [...el.querySelectorAll('a.md-video')].map((a) => [a.getAttribute('href'), a.target, a.textContent]),
    blocked: el.querySelectorAll('.md-img-blocked').length,
  }));
  assert.equal(view.evil, 0, 'M2 역슬래시 링크 없음');
  assert.deepEqual(view.imgs, [], 'M2 위험 그림 src 없음');
  assert.deepEqual(view.video, [['https://youtu.be/dQw4w9WgXcQ', '_blank', '회의 영상']], 'M3 영상 링크');
  assert.equal(view.blocked, 1);
  await p.screenshot({ path: SHOTS + '/1440-h1-m2-m3-doc.png' });
  // 보기 상태에서 영상 링크를 누르면 새 탭, 이 화면은 그대로
  const [popup] = await Promise.all([p.context().waitForEvent('page'), p.click('a.md-video')]);
  assert.ok(popup.url().includes('youtu'), popup.url());
  await popup.close();
  assert.ok(p.url().includes('doc=4'));
  log('M2·M3 보기 렌더, 영상은 새 탭');
  const v0 = Number(await p.getAttribute('#doc-body', 'data-version'));
  await p.click('#doc-body p');
  await p.waitForTimeout(150);
  await p.keyboard.press('End');
  await p.keyboard.insertText('!');
  await p.waitForFunction((v0) => Number(document.querySelector('#doc-body').dataset.version) > v0, v0);
  const saved = await p.evaluate(() => window.udallyEditor.getMarkdown());
  for (const s of ['text\n~3000\n```', '\n~3000 들여쓴 코드\n', '<aside>~3000</aside>', '![회의 영상](https://youtu.be/dQw4w9WgXcQ)', '![x](javascript:alert(1))', '앞 문단!']) {
    assert.ok(saved.includes(s), 'H1 보존 ' + JSON.stringify(s) + '\n' + saved);
  }
  assert.ok(!saved.includes('\\~'), 'H1 역슬래시 추가 없음');
  log('H1 앞 문단만 고친 뒤 코드·HTML·영상 원문 그대로');

  // M1: 저장이 409면 목록으로 가지 않는다(모바일 ‘목록으로’)
  await p.setViewportSize({ width: 390, height: 844 });
  await p.goto(B + '/projects/1/docs?doc=4');
  await p.waitForSelector('#doc-body[data-ready="1"]', { state: 'attached' });
  await p.route('**/docs/4/save', (r) => r.fulfill({ status: 409, contentType: 'application/json', body: '{"error":"다른 사람이 먼저 수정했습니다."}' }));
  // L3: 키보드로 본문에 닿아 Enter로 편집 시작
  await p.focus('#doc-body .ProseMirror');
  await p.keyboard.press('Enter');
  assert.equal(await p.evaluate(() => window.udallyEditor.isEditable), true, 'L3 Enter로 편집');
  log('L3 키보드 편집 진입(390)');
  await p.keyboard.insertText('충돌 시험');
  p.on('dialog', (d) => d.accept());
  const back = p.locator('.note-back');
  if (await back.count()) {
    await back.click();
    await p.waitForTimeout(1500);
    assert.ok(p.url().includes('doc=4'), 'M1 머문다 ' + p.url());
    assert.match(await p.textContent('#note-status'), /먼저 수정/);
    await p.screenshot({ path: SHOTS + '/390-m1-409-stay.png' });
    log('M1 409 뒤 목록으로 가지 않음', await p.textContent('#note-status'));
  } else {
    errors.push('M1: .note-back 없음');
  }
  await p.unroute('**/docs/4/save');
  await p.setViewportSize({ width: 1440, height: 900 });

  const order = [];
  p.on('request', (r) => { if (r.method() === 'POST') order.push(new URL(r.url()).pathname); });
  // M4 실패: 본문 저장이 409면 확정 요청을 보내지 않는다
  await p.goto(B + '/orgs/1/notes?note=5');
  await p.waitForSelector('#doc-body[data-ready="1"]', { state: 'attached' });
  await p.route('**/notes/5/save', (r) => r.fulfill({ status: 409, contentType: 'application/json', body: '{"error":"충돌"}' }));
  await p.click('#doc-body p');
  await p.waitForTimeout(150);
  await p.keyboard.press('End');
  await p.keyboard.insertText(' 충돌');
  await p.click('form[data-flush-first] button');
  await p.waitForTimeout(1500);
  assert.ok(!order.includes('/notes/5/finalize') && p.url().includes('note=5'), 'M4 409면 확정 안 함 ' + order);
  await p.screenshot({ path: SHOTS + '/1440-m4-409-no-finalize.png' });
  log('M4 409 → 확정 막힘', await p.textContent('#note-status'));
  await p.unroute('**/notes/5/save');
  order.length = 0;

  // M4: 회의록 확정 — 본문을 고치고 0.8초 안에 확정을 눌러도 본문을 먼저 저장한 뒤 확정한다
  await p.goto(B + '/orgs/1/notes?note=5');
  await p.waitForSelector('#doc-body[data-ready="1"]', { state: 'attached' });
  await p.click('#doc-body p');
  await p.waitForTimeout(150);
  await p.keyboard.press('End');
  await p.keyboard.insertText(' 확정 전 마지막 문장');
  await Promise.all([p.waitForNavigation(), p.click('form[data-flush-first] button')]);
  assert.deepEqual(order.slice(0, 2), ['/notes/5/save', '/notes/5/finalize'], 'M4 순서 ' + order);
  const html = await (await p.request.get(B + '/orgs/1/notes?note=5')).text();
  assert.ok(html.includes('초안 본문 확정 전 마지막 문장'), 'M4 확정본에 최신 본문');
  log('M4 저장 → 확정 순서', order.join(' → '));

  // M4 실패: 409면 확정하지 않는다
  await browser.close();
  console.log(errors.length ? 'ERRORS\n' + errors.join('\n') : 'console errors 0');
})().catch((e) => { console.error('FAIL', e); process.exit(1); });
