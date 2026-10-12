// 회의 상태기·내부 HTTP. 가짜 Discord 어댑터(가짜 receiver)·가짜 core fetch로 돌린다.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { Readable } from 'node:stream';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createCore } from '../src/core.mjs';
import { Meetings, HttpErr } from '../src/meetings.mjs';
import { createControl } from '../src/control.mjs';
import * as texts from '../src/texts.mjs';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });

function fakeReceiver() {
  return { speaking: new EventEmitter(), subscribe: () => new Readable({ objectMode: true, read() {} }) };
}

function fakeDiscord({ voice = { h: 'vc', a: 'vc' }, members = [{ id: 'h', name: '진행', bot: false }, { id: 'a', name: '참여', bot: false }, { id: 'bot', name: '유달리', bot: true }], joinFails = false } = {}) {
  const d = {
    sent: [], nicks: [], destroyed: 0, lost: null,
    voiceChannelOf: (_g, u) => voice[u] ?? null,
    membersIn: () => members,
    getNick: () => '원래',
    setNick: async (_g, n) => { d.nicks.push(n); },
    send: async (ch, text) => { d.sent.push([ch, text]); },
    join: async (_g, _ch, { onLost }) => {
      if (joinFails) throw new Error('timeout');
      d.lost = onLost;
      return { receiver: fakeReceiver(), destroy: () => { d.destroyed++; } };
    },
  };
  return d;
}

// handler(method, path, body) → [status, data] | undefined(기본 응답)
function fakeCore(handler = () => undefined) {
  const calls = [];
  const fetch = async (url, opts) => {
    const path = new URL(url).pathname.replace('/api/integrations/discord', '');
    const body = opts.body ? JSON.parse(opts.body) : undefined;
    calls.push({ method: opts.method, path, body, auth: opts.headers.Authorization });
    const r = handler(opts.method, path, body);
    if (r) return json(r[1], r[0]);
    if (opts.method === 'POST' && path === '/meetings') {
      return json({ id: 7, note_id: 3, status: 'recording', host: { id: 1, discord_user_id: 'h' }, max_minutes: 180, leave_grace_s: 0.05, audio_expires_at: null, stt: {}, glossary: '' });
    }
    if (opts.method === 'PATCH') {
      return json({ id: 7, status: body.status ?? 'recording', audio_expires_at: body.status ? '2026-10-19T00:00:00Z' : null,
        channel_notice: body.end_reason === 'host_left' ? '회의 진행자가 나가서 회의를 종료하였습니다.' : '' });
    }
    if (path.endsWith('/names')) return json({ names: [{ discord_user_id: 'h', display_name: '홍길동' }], stt: {}, glossary: '' });
    return json({ detail: 'nope' }, 404);
  };
  return { core: createCore({ url: 'http://web:8000/', token: 'tok', fetch }), calls };
}

function setup({ handler, discord, env = {}, minuteMs = 60000 } = {}) {
  const dataDir = mkdtempSync(join(tmpdir(), 'voice-'));
  const { core, calls } = fakeCore(handler);
  const d = discord ?? fakeDiscord();
  const m = new Meetings({ core, discord: d, dataDir, env, minuteMs, debounceMs: 10, retryDelayMs: 1, convert: async () => Buffer.from('a') });
  return { m, d, calls, dataDir };
}
const startBody = { guild_id: '1', discord_user_id: 'h', project_id: 5, team_id: null, title: '주간' };
const patches = (calls) => calls.filter((c) => c.method === 'PATCH').map((c) => c.body);

test('시작: core에 음성 채널을 보내고 접속·닉네임·고지·참여자(봇 제외) PATCH, 응답은 {meeting, recording}', async () => {
  const { m, d, calls } = setup();
  const out = await m.start(startBody);
  assert.equal(calls[0].auth, 'Bearer tok');
  assert.deepEqual(calls[0].body, { ...startBody, voice_channel_id: 'vc' });
  assert.equal(out.recording.id, 7);
  assert.deepEqual(Object.keys(out.meeting).sort(), ['host_discord_user_id', 'note_id', 'participants', 'recording_id', 'started_at', 'voice_channel_id']);
  assert.deepEqual(out.meeting.participants.map((p) => p.discord_user_id), ['h', 'a']);
  assert.deepEqual(d.nicks, [texts.NICK_RECORDING]);
  await sleep(5);
  assert.match(d.sent[0][1], /회의 녹음을 시작했습니다\(진행자: <@h>\)/);
  assert.equal(patches(calls)[0].participants.length, 2);
  await assert.rejects(m.start(startBody), (e) => e.status === 409 && e.detail === texts.alreadyRunning());
  await assert.rejects(m.start({ ...startBody, guild_id: '2', discord_user_id: 'x' }), (e) => e.status === 409 && e.detail === texts.notInVoice());
  m.end(m.byGuild.get('1'), 'empty');
  await m.idle();
});

test('시작 실패: core 거절 detail을 펼쳐 그대로, 음성 접속 실패면 core failed 후 502', async () => {
  const { m } = setup({ handler: (me, p) => (p === '/meetings' ? [403, { detail: { meeting: '이 조직(프로젝트)은 회의 녹음을 켜지 않았습니다.' } }] : undefined) });
  await assert.rejects(m.start(startBody), (e) => e.status === 403 && e.detail === '이 조직(프로젝트)은 회의 녹음을 켜지 않았습니다.');
  const s2 = setup({ discord: fakeDiscord({ joinFails: true }) });
  await assert.rejects(s2.m.start(startBody), (e) => e.status === 502 && e.detail === texts.joinFailed());
  assert.deepEqual(patches(s2.calls), [{ status: 'failed', end_reason: 'failed' }]);
  assert.equal(s2.m.count, 0);
});

test('진행자 퇴장 뒤 유예 안에 돌아오면 종료하지 않는다, 입장 고지는 1인 1회', async () => {
  const { m, d, calls } = setup();
  await m.start(startBody);
  m.onVoiceState({ guildId: '1', userId: 'h', from: 'vc', to: null });
  await sleep(10);
  m.onVoiceState({ guildId: '1', userId: 'h', from: null, to: 'vc' }); // 시작 때 있던 사람 → 고지 없음
  m.onVoiceState({ guildId: '1', userId: 'n', name: '새', from: null, to: 'vc' });
  m.onVoiceState({ guildId: '1', userId: 'n', from: 'vc', to: null });
  m.onVoiceState({ guildId: '1', userId: 'n', from: null, to: 'vc' });
  await sleep(100);
  assert.ok(!patches(calls).some((b) => b.status));
  assert.equal(d.sent.filter(([, t]) => t.includes('<@n> 님')).length, 1);
  assert.equal(m.view('1').participants.length, 3);
  m.end(m.byGuild.get('1'), 'empty');
  await m.idle();
});

test('진행자 퇴장 유예가 지나 core가 400(지금 진행자 아님)이면 회의 계속', async () => {
  const { m, calls } = setup({ handler: (me, p, b) => (b?.end_reason === 'host_left' ? [400, { detail: { meeting: '나간 사람이 지금 진행자가 아니므로 회의를 계속합니다.' } }] : undefined) });
  await m.start(startBody);
  m.onVoiceState({ guildId: '1', userId: 'h', from: 'vc', to: null });
  await sleep(100);
  assert.deepEqual(patches(calls).filter((b) => b.status).map((b) => [b.end_reason, b.discord_user_id]), [['host_left', 'h']]);
  assert.equal(m.count, 1);
  assert.equal(m.byGuild.get('1').ending, false);
  m.end(m.byGuild.get('1'), 'empty');
  await m.idle();
});

test('진행자 퇴장 유예가 지나 200이면 종료: channel_notice·종료 고지·닉네임 복구·전사 → draft', async () => {
  const { m, d, calls } = setup();
  await m.start(startBody);
  m.onVoiceState({ guildId: '1', userId: 'h', from: 'vc', to: null });
  await sleep(100);
  await m.idle();
  assert.equal(m.count, 0);
  assert.equal(d.destroyed, 1);
  assert.deepEqual(d.nicks, [texts.NICK_RECORDING, '원래']);
  const sent = d.sent.map(([, t]) => t);
  assert.ok(sent.includes('회의 진행자가 나가서 회의를 종료하였습니다.'));
  assert.ok(sent.some((t) => t.startsWith('회의 녹음을 마쳤습니다')));
  const ps = patches(calls).filter((b) => b.status);
  assert.equal(ps[0].status, 'transcribing');
  assert.ok(ps[0].participants.every((p) => p.left_at));
  assert.equal(ps[1].status, 'draft'); // 말한 구간이 없어 빈 전사문
  assert.equal(ps[1].transcript_md, '');
});

test('진행자를 넘기면 이전 진행자의 퇴장은 유예를 걸지 않고, 모두 나가면 empty(discord_user_id 비움)', async () => {
  const { m, calls } = setup();
  await m.start(startBody);
  assert.deepEqual(m.setHost(7, 'a'), { ok: true });
  m.onVoiceState({ guildId: '1', userId: 'h', from: 'vc', to: null });
  await sleep(100);
  assert.equal(m.count, 1);
  m.onVoiceState({ guildId: '1', userId: 'a', from: 'vc', to: 'other' });
  await m.idle();
  const ps = patches(calls).filter((b) => b.status);
  assert.deepEqual([ps[0].end_reason, ps[0].discord_user_id], ['empty', '']);
  assert.throws(() => m.setHost(99, 'a'), (e) => e instanceof HttpErr && e.status === 404);
});

test('최대 길이: 5분 전 고지, 도달하면 max_length', async () => {
  const { m, d, calls } = setup({ minuteMs: 20, handler: (me, p) => (p === '/meetings' && me === 'POST' ? [200, { id: 7, note_id: 3, host: { discord_user_id: 'h' }, max_minutes: 6, leave_grace_s: 10 }] : undefined) });
  await m.start(startBody);
  await sleep(60);
  assert.ok(d.sent.some(([, t]) => t === texts.maxWarning({ maxMinutes: 6 })));
  await sleep(150);
  await m.idle();
  assert.equal(patches(calls).find((b) => b.status).end_reason, 'max_length');
});

test('stop: core 403 detail 그대로 돌려주고 회의 계속, 성공하면 {recording}', async () => {
  let deny = true;
  const { m, calls } = setup({ handler: (me, p, b) => (deny && b?.end_reason === 'command' ? [403, { detail: { meeting: '진행자나 조직 관리자만 회의를 종료할 수 있습니다.' } }] : undefined) });
  await m.start(startBody);
  await assert.rejects(m.stop(7, 'a'), (e) => e.status === 403 && e.detail === '진행자나 조직 관리자만 회의를 종료할 수 있습니다.');
  assert.equal(m.count, 1);
  deny = false;
  const out = await m.stop(7, 'h');
  assert.equal(out.recording.status, 'transcribing');
  assert.deepEqual(patches(calls).filter((b) => b.status)[1].discord_user_id, 'h');
  await assert.rejects(m.stop(7, 'h'), (e) => e.status === 404);
  await m.idle();
});

test('봇 연결이 끊겨 재접속 못 하면 end_reason=failed로 마감하고 전사한다', async () => {
  const { m, d, calls } = setup();
  await m.start(startBody);
  d.lost();
  await sleep(5);
  await m.idle();
  const ps = patches(calls).filter((b) => b.status);
  assert.deepEqual(ps.map((b) => [b.status, b.end_reason]), [['transcribing', 'failed'], ['draft', undefined]]);
  assert.ok(d.sent.some(([, t]) => t === texts.lost()));
});

test('재시작 복구: recording은 restart로 마감 후 남은 구간 전사, transcribing은 결과 이어서', async () => {
  const dataDir = mkdtempSync(join(tmpdir(), 'voice-'));
  const st = (id, phase) => {
    const dir = join(dataDir, 'meetings', String(id));
    mkdirSync(join(dir, 'seg'), { recursive: true });
    writeFileSync(join(dir, 'state.json'), JSON.stringify({ recording_id: id, guild_id: 'g' + id, voice_channel_id: 'vc', phase,
      host_discord_user_id: 'h', started_at: '2026-10-12T00:00:00Z', ended_at: phase === 'recording' ? null : '2026-10-12T00:10:00Z',
      prev_nick: null, participants: [{ discord_user_id: 'h', discord_name: 'H', joined_at: '2026-10-12T00:00:00Z', left_at: null }], noticed: ['h'] }));
    writeFileSync(join(dir, 'segments.jsonl'), [1, 2].map((seq) => JSON.stringify({ seq, user_id: 'h', start_ms: seq * 5000, duration_ms: 3000, file: `seg/${seq}.ogg` })).join('\n') + '\n');
    return dir;
  };
  st(11, 'recording');
  const dir12 = st(12, 'transcribing');
  writeFileSync(join(dir12, 'results.jsonl'), JSON.stringify({ seq: 1, user_id: 'h', start_ms: 5000, text: '저장된', engine: 'openai' }) + '\n');
  st(13, 'done');
  const calls = [];
  const fetch = async (url, opts) => {
    if (url.includes('openai')) { calls.push({ openai: true }); return json({ text: '새 전사' }); }
    const path = new URL(url).pathname.replace('/api/integrations/discord', '');
    const body = opts.body ? JSON.parse(opts.body) : undefined;
    calls.push({ method: opts.method, path, body });
    if (path.endsWith('/names')) return json({ names: [], stt: {}, glossary: '' });
    return json({ status: body?.status, audio_expires_at: '2026-10-19T00:00:00Z' });
  };
  const d = fakeDiscord();
  const m = new Meetings({ core: createCore({ url: 'http://web:8000', token: 't', fetch }), discord: d, dataDir,
    env: { OPENAI_API_KEY: 'sk' }, fetch, convert: async () => Buffer.from('a'), retryDelayMs: 1 });
  await m.recover();
  await m.idle();
  const p = calls.filter((c) => c.method === 'PATCH');
  assert.deepEqual(p.map((c) => [c.path, c.body.status, c.body.end_reason]), [
    ['/meetings/11', 'transcribing', 'restart'], ['/meetings/11', 'draft', undefined], ['/meetings/12', 'draft', undefined]]);
  assert.equal(p[1].body.transcript_md, '[00:00:05] H: 새 전사\n[00:00:10] H: 새 전사');
  assert.equal(p[2].body.transcript_md, '[00:00:05] H: 저장된\n[00:00:10] H: 새 전사');
  assert.equal(calls.filter((c) => c.openai).length, 3);
  assert.ok(d.sent.some(([, t]) => t === texts.restarted()));
  assert.equal(JSON.parse(readFileSync(join(dataDir, 'meetings', '11', 'state.json'))).phase, 'done');
  // 정리: 만료 지난 끝난 회의만 지운다
  m.now = () => Date.parse('2026-10-20T00:00:00Z');
  m.cleanup();
  assert.ok(!existsSync(join(dataDir, 'meetings', '11')));
  assert.ok(!existsSync(join(dataDir, 'meetings', '13'))); // audio_expires_at 없음 → ended_at + 7일
});

test('control: healthz는 인증 없음, 나머지는 Bearer 아니면 401, 형식 오류 400, 오류는 {detail}', async () => {
  const { m, d } = setup();
  const server = createControl({ meetings: m, discord: d, secret: 's3cret' });
  await new Promise((r) => server.listen(0, r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const call = (method, path, body, auth = 'Bearer s3cret') => fetch(base + path, {
    method, headers: auth ? { Authorization: auth } : {}, body: body === undefined ? undefined : (typeof body === 'string' ? body : JSON.stringify(body)),
  }).then(async (r) => [r.status, await r.json()]);
  try {
    assert.deepEqual(await call('GET', '/healthz', undefined, null), [200, { ok: true, ready: true, meetings: 0 }]);
    assert.deepEqual(await call('GET', '/guilds/1/meeting', undefined, null), [401, { detail: texts.unauthorized() }]);
    assert.deepEqual(await call('GET', '/guilds/1/meeting', undefined, 'Bearer wrong'), [401, { detail: texts.unauthorized() }]);
    assert.deepEqual(await call('GET', '/guilds/1/meeting'), [200, { meeting: null }]);
    assert.deepEqual(await call('GET', '/guilds/1/members/9/voice'), [200, { channel_id: null }]);
    assert.deepEqual(await call('POST', '/meetings', '{bad'), [400, { detail: texts.badRequest() }]);
    const [s, out] = await call('POST', '/meetings', { ...startBody, guild_id: '1' });
    assert.equal(s, 201);
    assert.equal(out.meeting.recording_id, 7);
    assert.equal((await call('GET', '/guilds/1/meeting'))[1].meeting.host_discord_user_id, 'h');
    assert.deepEqual(await call('POST', '/meetings/7/host', { discord_user_id: 'a' }), [200, { ok: true }]);
    assert.deepEqual(await call('POST', '/meetings/8/stop', { discord_user_id: 'a' }), [404, { detail: texts.noMeeting() }]);
    const [s2, stop] = await call('POST', '/meetings/7/stop', { discord_user_id: 'a' });
    assert.equal(s2, 200);
    assert.equal(stop.recording.status, 'transcribing');
    await m.idle();
    const none = createControl({ meetings: m, discord: d, secret: '' });
    await new Promise((r) => none.listen(0, r));
    const r = await fetch(`http://127.0.0.1:${none.address().port}/guilds/1/meeting`, { headers: { Authorization: 'Bearer ' } });
    assert.equal(r.status, 401); // 비밀값이 없으면 전부 거절
    none.close();
  } finally {
    server.close();
  }
});
