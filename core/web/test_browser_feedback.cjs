// Run with: node core/web/test_browser_feedback.cjs
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const app = fs.readFileSync(__dirname + '/static/app.js', 'utf8');
const notes = fs.readFileSync(__dirname + '/static/notes.js', 'utf8');
const alerts = [], flashes = [], prompts = [];
const context = {
  window: {}, navigator: {}, Promise, JSON,
  flash: text => flashes.push(text),
  prompt: (...args) => { prompts.push(args); return null; },
  alert: text => alerts.push(text),
};
vm.createContext(context);
vm.runInContext(app.slice(app.indexOf('  window.copyText ='), app.indexOf('  function updateDueSuggestion')), context);
vm.runInContext(app.slice(app.indexOf('  function requestError('), app.indexOf('  function openPanel')), context);

(async () => {
  assert.equal(await context.window.copyText('text'), false);
  assert.equal(prompts.length, 1);
  assert.equal(flashes.length, 0);
  context.navigator.clipboard = { writeText: () => Promise.reject(Error()) };
  assert.equal(await context.window.copyText('text'), false);
  assert.equal(flashes.length, 0);
  context.navigator.clipboard = { writeText: () => Promise.resolve() };
  assert.equal(await context.window.copyText('text', '복사 성공'), true);
  assert.equal(flashes.at(-1), '복사 성공');
  context.requestError({ detail: { requestConfig: { verb: 'get' }, xhr: { responseText: '<html>private</html>' } } }, false);
  assert.match(alerts.at(-1), /불러오지/);
  assert.doesNotMatch(alerts.at(-1), /html|private/);
  context.requestError({ detail: { requestConfig: { verb: 'post' }, xhr: { responseText: '{"error":"권한 부족"}' } } }, false);
  assert.match(alerts.at(-1), /변경 요청.*권한 부족/);
  context.requestError({ detail: { requestConfig: { verb: 'get' } } }, true);
  assert.match(alerts.at(-1), /네트워크/);

  const editor = {
    FormData: class { append() {} }, Promise, Number, String,
    doc: { dataset: { url: '/notes/1', version: '2' } }, csrf: '', version: 2,
    dead: false, conflictEl: { hidden: true }, savedFields: {},
    flash: text => flashes.push(text),
  };
  vm.createContext(editor);
  vm.runInContext(notes.slice(notes.indexOf('    function requestSave('), notes.indexOf('    function nextPending()')), editor);
  editor.fetch = () => Promise.resolve({ ok: false, status: 400, json: () => Promise.resolve({ error: '길이 제한 초과' }) });
  assert.equal(await editor.requestSave('title', '작성내용'), false);
  assert.match(flashes.at(-1), /길이 제한 초과.*복사/);
  assert.equal(editor.doc.dataset.version, '2');
  editor.fetch = () => Promise.resolve({ ok: false, status: 409, json: () => Promise.resolve({ detail: '충돌' }) });
  assert.equal(await editor.requestSave('body_md', '보존내용'), false);
  assert.equal(editor.dead, true);
  assert.equal(editor.conflictEl.hidden, false);
  assert.match(flashes.at(-1), /복사한 뒤 새로고침/);
  editor.fetch = () => Promise.resolve({ ok: true, status: 200, redirected: true, headers: { get: () => null } });
  assert.equal(await editor.requestSave('body_md', '미저장'), false);
  assert.match(flashes.at(-1), /로그인.*이 화면/);
  assert.equal(editor.doc.dataset.version, '2');
  editor.fetch = () => Promise.resolve({ ok: true, status: 204, headers: { get: () => null } });
  assert.equal(await editor.requestSave('body_md', '미저장'), false);
  editor.fetch = () => Promise.resolve({ ok: true, status: 204, headers: { get: () => '3' } });
  assert.equal(await editor.requestSave('body_md', '저장본문'), true);
  assert.equal(editor.version, 3);
  assert.equal(editor.savedFields.body_md, '저장본문');
  console.log('PASS: copy cancel/success, GET/POST/network errors, save reason/conflict/login redirect/version acknowledgement');
})().catch(error => { console.error(error); process.exitCode = 1; });
