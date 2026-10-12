// 실제 포인터 끌기(mouse down → 단계적 move → up): 목록 항목(중첩 자식 포함)·표·코드·블록 HTML → 자동 저장 → 실행 취소 → 저장.
const { chromium } = require('C:/Users/tjrdu/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright');
const assert = require('assert/strict');
const SHOTS = process.argv[2];
const B = 'http://127.0.0.1:8931';
const DOC = 7;
const ORIG = '시작 문단\n\n- 가\n  - 가의 자식\n- 나\n\n| 이름 | 수 |\n| --- | --- |\n| 갑 | 1 |\n\n```\n~x <b>\n```\n\n<aside>보존 HTML</aside>\n\n끝 문단';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const p = await ctx.newPage();
  p.on('pageerror', (e) => errors.push('pageerror ' + e.message));
  p.on('console', (m) => { if (m.type() === 'error') errors.push('console ' + m.text()); });
  await p.goto(B + '/login');
  await p.fill('#id_username', 'demo');
  await p.fill('#id_password', 'DemoPass123!');
  await Promise.all([p.waitForNavigation(), p.click('form button')]);

  // 표 칸 맞춤 공백·빈 줄 수는 직렬화 정규화(내용 아님)라 비교에서 접는다
  const norm = (s) => s.replace(/^\|.*\|$/gm, (row) => row.replace(/ +/g, ' ')).replace(/\n{3,}/g, '\n\n').trim();
  const md = () => p.evaluate(() => window.udallyEditor.getMarkdown()).then(norm);
  const version = async () => Number(await p.getAttribute('#doc-body', 'data-version'));
  const savedBody = async () => {
    const html = await (await p.request.get(`${B}/projects/1/docs?doc=${DOC}`)).text();
    const m = html.match(/<textarea class="md-src textarea"[^>]*>([\s\S]*?)<\/textarea>/);
    return norm(m[1].replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&'));
  };
  async function waitSaved(v0) {
    await p.waitForFunction((v0) => Number(document.querySelector('#doc-body').dataset.version) > v0 && /저장됨/.test(document.querySelector('#note-status')?.textContent || ''), v0, { timeout: 8000 });
  }

  // source: 끌 블록(호버할 요소), target: 놓을 블록(그 오른쪽 아래에 놓는다 → 그 블록 뒤)
  async function drag(name, source, expect) {
    await p.goto(`${B}/projects/1/docs?doc=${DOC}`);
    await p.waitForSelector('#doc-body[data-ready="1"]', { state: 'attached' });
    assert.equal(await md(), ORIG, name + ': 시작 상태');
    await p.click('#doc-body .ProseMirror > p >> nth=0'); // 편집 시작
    await p.waitForTimeout(150);
    const sb = await p.locator(source).first().boundingBox();
    await p.mouse.move(sb.x + 30, sb.y + Math.min(10, sb.height / 2), { steps: 4 });
    await p.waitForTimeout(250);
    const hb = await p.locator('.drag-handle').boundingBox();
    assert.ok(hb && Math.abs(hb.y - sb.y) < 16, name + ': 손잡이가 블록 옆 ' + JSON.stringify({ hb, sb }));
    const tb = await p.locator('#doc-body .ProseMirror > p').last().boundingBox();
    const v0 = await version();
    await p.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2, { steps: 3 });
    await p.mouse.down();
    for (let i = 1; i <= 12; i++) {
      await p.mouse.move(hb.x + (tb.x + tb.width - 6 - hb.x) * (i / 12), hb.y + (tb.y + tb.height - 3 - hb.y) * (i / 12));
      await p.waitForTimeout(20);
    }
    await p.mouse.up();
    await waitSaved(v0);
    const moved = await md();
    assert.equal(moved, expect, name + ': 옮긴 결과');
    assert.equal(await savedBody(), expect, name + ': 서버 저장본');
    await p.screenshot({ path: `${SHOTS}/1440-pointer-drag-${name}.png` });
    // 실행 취소 → 원래 순서로 저장
    const v1 = await version();
    await p.click('#doc-body .ProseMirror > p >> nth=0');
    await p.keyboard.press('Control+z');
    await waitSaved(v1);
    assert.equal(await md(), ORIG, name + ': 실행 취소');
    assert.equal(await savedBody(), ORIG, name + ': 실행 취소 저장본');
    console.log('OK', name, '끌기 → 저장 → 실행 취소 → 저장');
  }

  const LIST = '- 가\n  - 가의 자식\n- 나';
  const TABLE = '| 이름 | 수 |\n| --- | --- |\n| 갑 | 1 |';
  const CODE = '```\n~x <b>\n```';
  const HTML = '<aside>보존 HTML</aside>';
  const join = (...b) => b.join('\n\n');
  // 목록 항목 "가"(중첩 자식 포함)를 "나" 아래로 — 놓는 곳: "나" 항목 오른쪽 아래
  {
    await p.goto(`${B}/projects/1/docs?doc=${DOC}`);
  }
  await dragListItem();
  await drag('table', '#doc-body .ProseMirror > .tableWrapper', join('시작 문단', LIST, CODE, HTML, '끝 문단', TABLE));
  await drag('code', '#doc-body .ProseMirror > pre:not(.tt-html)', join('시작 문단', LIST, TABLE, HTML, '끝 문단', CODE));
  await drag('html', '#doc-body .ProseMirror > pre.tt-html', join('시작 문단', LIST, TABLE, CODE, '끝 문단', HTML));

  async function dragListItem() {
    await p.waitForSelector('#doc-body[data-ready="1"]', { state: 'attached' });
    await p.click('#doc-body .ProseMirror > p >> nth=0');
    await p.waitForTimeout(150);
    const li = p.locator('#doc-body .ProseMirror > ul > li').first();
    const lb = await li.locator('p').first().boundingBox();
    await p.mouse.move(lb.x + 20, lb.y + lb.height / 2, { steps: 4 });
    await p.waitForTimeout(250);
    const hb = await p.locator('.drag-handle').boundingBox();
    assert.ok(Math.abs(hb.y - lb.y) < 16, 'list: 손잡이가 "가" 옆');
    const nb = await p.locator('#doc-body .ProseMirror > ul > li').nth(1).boundingBox();
    const v0 = await version();
    await p.mouse.move(hb.x + 10, hb.y + 10, { steps: 3 });
    await p.mouse.down();
    for (let i = 1; i <= 12; i++) {
      await p.mouse.move(hb.x + (nb.x + nb.width - 6 - hb.x) * (i / 12), hb.y + (nb.y + nb.height - 3 - hb.y) * (i / 12));
      await p.waitForTimeout(20);
    }
    await p.mouse.up();
    await waitSaved(v0);
    const expect = join('시작 문단', '- 나\n- 가\n  - 가의 자식', TABLE, CODE, HTML, '끝 문단');
    assert.equal(await md(), expect, 'list: 옮긴 결과');
    assert.equal(await savedBody(), expect, 'list: 서버 저장본');
    await p.screenshot({ path: `${SHOTS}/1440-pointer-drag-list.png` });
    const v1 = await version();
    await p.keyboard.press('Control+z');
    await waitSaved(v1);
    assert.equal(await md(), ORIG, 'list: 실행 취소');
    assert.equal(await savedBody(), ORIG, 'list: 실행 취소 저장본');
    console.log('OK list(중첩 자식 포함) 끌기 → 저장 → 실행 취소 → 저장');
  }

  await browser.close();
  console.log(errors.length ? 'ERRORS\n' + errors.join('\n') : 'console errors 0');
})().catch((e) => { console.error('FAIL', e); process.exit(1); });
