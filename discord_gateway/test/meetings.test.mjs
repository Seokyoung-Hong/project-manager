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
import { mix } from '../src/mix.mjs';
import { OggOpusWriter } from '../src/ogg.mjs';
import { execFileSync } from 'node:child_process';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });

function fakeReceiver() {
  return { speaking: new EventEmitter(), subscribe: () => new Readable({ objectMode: true, read() {} }) };
}

function fakeDiscord({ voice = { h: 'vc', a: 'vc' }, members = [{ id: 'h', name: '진행', bot: false }, { id: 'a', name: '참여', bot: false }, { id: 'bot', name: '유달리', bot: true }], joinFails = false, joinHangs = false } = {}) {
  const d = {
    sent: [], nicks: [], destroyed: 0, lost: null,
    voiceChannelOf: (_g, u) => voice[u] ?? null,
    membersIn: () => members,
    getNick: () => '원래',
    setNick: async (_g, n) => { d.nicks.push(n); },
    send: async (ch, text) => { d.sent.push([ch, text]); },
    join: async (_g, _ch, { onLost }) => {
      if (joinFails) throw new Error('timeout');
      if (joinHangs) return new Promise(() => {});
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
    const body = typeof opts.body === 'string' ? JSON.parse(opts.body) : opts.body;
    calls.push({ method: opts.method, path, body, auth: opts.headers.Authorization });
    const r = await handler(opts.method, path, body);
    if (r) return json(r[1], r[0]);
    if (opts.method === 'POST' && path === '/meetings') {
      return json({ id: 7, note_id: 3, status: 'recording', host: { id: 1, discord_user_id: 'h' }, max_minutes: 180, leave_grace_s: 0.05, audio_expires_at: null, stt: {}, glossary: '' });
    }
    if (opts.method === 'PATCH') {
      return json({ id: 7, status: body.status ?? 'recording', audio_expires_at: body.status ? '2026-10-19T00:00:00Z' : null,
        channel_notice: body.end_reason === 'host_left' ? '회의 진행자가 나가서 회의를 종료하였습니다.' : '' });
    }
    if (opts.method === 'PUT' && path.endsWith('/audio')) return json({ ok: true });
    if (path.endsWith('/names')) return json({ names: [{ discord_user_id: 'h', display_name: '홍길동' }], stt: {}, glossary: '' });
    return json({ detail: 'nope' }, 404);
  };
  return { core: createCore({ url: 'http://web:8000/', token: 'tok', fetch }), calls };
}

function setup({ handler, discord, env = {}, minuteMs = 60000, ffmpeg } = {}) {
  const dataDir = mkdtempSync(join(tmpdir(), 'voice-'));
  const { core, calls } = fakeCore(handler);
  const d = discord ?? fakeDiscord();
  const m = new Meetings({ core, discord: d, dataDir, env, minuteMs, debounceMs: 10, retryDelayMs: 1, convert: async () => Buffer.from('a'),
    backoff: () => 5, hostBackoff: () => 10, ...(ffmpeg ? { ffmpeg } : {}), log: process.env.DBG ? (...a) => console.log(...a) : undefined });
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
  assert.match(d.sent[0][1], /회의 녹음 중입니다\(진행자: <@h>\)/);
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
  await s2.m.idle();
  assert.deepEqual(patches(s2.calls).map((b) => [b.status, b.end_reason]), [['failed', 'failed']]);
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
  assert.ok(sent.some((t) => t.startsWith('회의 녹음이 끝난 상태입니다')));
  const ps = patches(calls).filter((b) => b.status);
  assert.equal(ps[0].status, 'transcribing');
  assert.ok(ps[0].participants.every((p) => p.left_at));
  assert.equal(ps[1].status, 'draft'); // 말한 구간이 없어 빈 전사문
  assert.equal(ps[1].transcript_md, '');
});

test('모두 나가면 empty(discord_user_id 비움), /host 알림은 진행자 표시만 바꾼다', async () => {
  const { m, calls } = setup({ handler: (me, p, b) => (b?.end_reason === 'host_left' ? [400, { detail: { meeting: '진행자 아님' } }] : undefined) });
  await m.start(startBody);
  assert.deepEqual(m.setHost(7, 'a'), { ok: true });
  assert.equal(m.view('1').host_discord_user_id, 'a');
  m.onVoiceState({ guildId: '1', userId: 'h', from: 'vc', to: null });
  await sleep(100);
  assert.equal(m.count, 1);
  m.onVoiceState({ guildId: '1', userId: 'a', from: 'vc', to: 'other' });
  await m.idle();
  const ps = patches(calls).filter((b) => b.status);
  assert.deepEqual(ps.filter((b) => b.status === 'transcribing').map((b) => [b.end_reason, b.discord_user_id]), [['host_left', 'h'], ['empty', '']]);
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
    if (path.endsWith('/names')) return json({ names: [], stt: { openai_api_key: 'sk' }, glossary: '' });
    return json({ status: body?.status, audio_expires_at: '2026-10-19T00:00:00Z' });
  };
  const d = fakeDiscord();
  const m = new Meetings({ core: createCore({ url: 'http://web:8000', token: 't', fetch }), discord: d, dataDir,
    fetch, convert: async () => Buffer.from('a'), retryDelayMs: 1 });
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

// 가짜 ffmpeg: 마지막 인자(출력 경로)에 파일을 만들고 인자를 기록한다
const fakeFfmpeg = (runs = []) => Object.assign(async (args) => { runs.push(args); writeFileSync(args.at(-1), 'ogg'); }, { runs });
const inputsOf = (args) => args.filter((_, i) => args[i - 1] === '-i');

test('혼합: 40개 넘으면 묶음별 중간 트랙(시작 기준 지연) 뒤 다시 섞고, 결과만 32kbps', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'mix-'));
  const run = fakeFfmpeg();
  const inputs = Array.from({ length: 85 }, (_, i) => ({ path: `s${i}.ogg`, delay_ms: i * 1000 }));
  await mix(inputs, join(dir, 'meeting.ogg'), { run });
  assert.equal(run.runs.length, 4);
  assert.deepEqual(run.runs.slice(0, 3).map((a) => inputsOf(a).length), [40, 40, 5]);
  assert.match(run.runs[1].join(' '), /\[0:a\]adelay=40000:all=1/); // 두 번째 묶음 첫 입력 = 40초
  assert.deepEqual(run.runs.slice(0, 3).map((a) => a[a.indexOf('-b:a') + 1]), ['64k', '64k', '64k']);
  const last = run.runs[3];
  assert.equal(inputsOf(last).length, 3);
  assert.match(last.join(' '), /adelay=0:all=1.*amix=inputs=3/);
  assert.equal(last[last.indexOf('-b:a') + 1], '32k');
  assert.ok(existsSync(join(dir, 'meeting.ogg')));
  assert.ok(!existsSync(join(dir, 'mix-0-0.ogg'))); // 중간 파일은 지운다
});

test('혼합: 실제 ffmpeg로 지연을 반영한 모노 Opus 하나', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'mix-'));
  const seg = (name) => { const w = new OggOpusWriter(join(dir, name)); for (let i = 0; i < 50; i++) w.write(Buffer.from([0xf8, 0xff, 0xfe])); w.end(); return join(dir, name); };
  await mix([{ path: seg('a.ogg'), delay_ms: 0 }, { path: seg('b.ogg'), delay_ms: 3000 }, { path: seg('c.ogg'), delay_ms: 1000 }], join(dir, 'meeting.ogg'), { batch: 2 }); // 묶음 2개 → 다시 섞기
  const info = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', join(dir, 'meeting.ogg')]));
  assert.equal(info.streams[0].codec_name, 'opus');
  assert.equal(info.streams[0].channels, 1);
  assert.ok(Math.abs(Number(info.format.duration) - 4) < 0.2, info.format.duration);
});

// 말한 구간이 있는 회의를 시작·종료한다(패킷 0인 구간 하나 포함)
async function endedWithSegments(opts) {
  const s = setup(opts);
  await s.m.start(startBody);
  const dir = join(s.dataDir, 'meetings', '7');
  writeFileSync(join(dir, 'seg', 'a.ogg'), 'x');
  writeFileSync(join(dir, 'segments.jsonl'), [{ seq: 1, user_id: 'h', start_ms: 1000, duration_ms: 3000, packets: 150, file: 'seg/a.ogg' },
    { seq: 2, user_id: 'a', start_ms: 0, duration_ms: 0, packets: 0, file: 'seg/b.ogg' }].map((x) => JSON.stringify(x)).join('\n') + '\n');
  await s.m.stop(7, 'h');
  await s.m.idle();
  return { ...s, dir };
}

test('녹음만: 올리기 → 빈 전사문 draft(engine none) → 로컬 구간·혼합 파일 삭제', async () => {
  const run = fakeFfmpeg();
  const { calls, dir } = await endedWithSegments({ ffmpeg: run });
  assert.equal(inputsOf(run.runs[0]).length, 1); // 패킷 0인 구간은 섞지 않는다
  assert.match(run.runs[0].join(' '), /adelay=1000:all=1/);
  const seq = calls.filter((c) => c.method !== 'PATCH' || c.body.status).map((c) => c.method + ' ' + c.path);
  assert.deepEqual(seq.slice(1), ['PATCH /meetings/7', 'PUT /meetings/7/audio', 'GET /meetings/7/names', 'PATCH /meetings/7']);
  const put = calls.find((c) => c.method === 'PUT');
  assert.equal(put.auth, 'Bearer tok');
  assert.equal(put.body.get('file').name, 'meeting.ogg');
  const draft = patches(calls).at(-1);
  assert.equal(draft.status, 'draft');
  assert.equal(draft.transcript_md, '');
  assert.equal(draft.stats.engine, 'none');
  assert.equal(draft.participants.length, 2);
  assert.ok(!existsSync(join(dir, 'seg')));
  assert.ok(!existsSync(join(dir, 'meeting.ogg')));
  assert.equal(JSON.parse(readFileSync(join(dir, 'state.json'))).uploaded, true);
});

test('올리기 실패: 전사·PATCH는 진행하고 백오프 재시도, 성공하면 그때 정리', async () => {
  let fails = 2;
  const { m, calls, dir } = await endedWithSegments({ ffmpeg: fakeFfmpeg(), handler: (me) => (me === 'PUT' && fails-- > 0 ? [503, { detail: 'busy' }] : undefined) });
  assert.equal(patches(calls).at(-1).status, 'draft'); // 올리기 실패와 무관하게 회의록 PATCH
  assert.ok(existsSync(join(dir, 'seg', 'a.ogg'))); // 아직 못 올렸으니 남긴다
  await sleep(40);
  await m.idle();
  assert.equal(calls.filter((c) => c.method === 'PUT').length, 3);
  assert.equal(patches(calls).filter((b) => b.status === 'draft').length, 1);
  assert.ok(!existsSync(join(dir, 'seg')));
  const st = JSON.parse(readFileSync(join(dir, 'state.json')));
  assert.deepEqual([st.uploaded, st.retries], [true, 0]);
});

test('자동 종료 PATCH가 실패하면 재시도 큐로 다시 보내 recording으로 남지 않는다', async () => {
  let down = true;
  const { m, calls } = setup({ ffmpeg: fakeFfmpeg(), handler: (me, p, b) => (down && b?.end_reason === 'empty' ? [502, {}] : undefined) });
  await m.start(startBody);
  m.onVoiceState({ guildId: '1', userId: 'h', from: 'vc', to: null });
  m.onVoiceState({ guildId: '1', userId: 'a', from: 'vc', to: null });
  await sleep(5);
  await m.idle();
  assert.equal(m.count, 0); // 로컬 회의는 끝났다
  down = false;
  await sleep(40);
  await m.idle();
  const ps = patches(calls).filter((b) => b.status);
  assert.ok(ps.length >= 3); // 실패 1회 이상 뒤 재전송 성공, 그다음 draft
  assert.ok(ps.slice(0, -1).every((b) => b.status === 'transcribing' && b.end_reason === 'empty'));
  assert.equal(ps.at(-1).status, 'draft');
});

// ---- Sol 교차 검토(2026-10-12) 재현 ----
const gate = () => { let open; const p = new Promise((r) => { open = r; }); return { p, open }; };

test('Sol 1: 종료 PATCH가 지연·거절되는 동안의 퇴장을 버리지 않고 거절 뒤 실제 상태로 다시 판단한다', async () => {
  const g = gate();
  const { m, calls } = setup({ handler: async (me, p, b) => {
    if (b?.end_reason === 'command') { await g.p; return [403, { detail: { meeting: '진행자나 조직 관리자만 회의를 종료할 수 있습니다.' } }]; }
  } });
  await m.start(startBody);
  const stop = m.stop(7, 'a');
  await sleep(5);
  m.onVoiceState({ guildId: '1', userId: 'h', from: 'vc', to: null });
  m.onVoiceState({ guildId: '1', userId: 'a', from: 'vc', to: null });
  assert.equal(m.present(m.byGuild.get('1').state).length, 0); // 기다리는 중에도 퇴장 반영
  g.open();
  await assert.rejects(stop, (e) => e.status === 403);
  await sleep(5);
  await m.idle();
  assert.equal(m.count, 0);
  assert.deepEqual(patches(calls).filter((b) => b.status === 'transcribing').map((b) => b.end_reason), ['command', 'empty']);
});

test('Sol 1: 기다리는 중 유예가 끝난 진행자 퇴장·최대 길이도 거절 뒤 처리한다', async () => {
  const g = gate();
  const { m, calls } = setup({ minuteMs: 10, handler: async (me, p, b) => {
    if (p === '/meetings' && me === 'POST') return [200, { id: 7, note_id: 3, host: { discord_user_id: 'h' }, max_minutes: 6, leave_grace_s: 0.01 }];
    if (b?.end_reason === 'command') { await g.p; return [403, { detail: '거절' }]; }
  } });
  await m.start(startBody);
  const stop = m.stop(7, 'a');
  m.onVoiceState({ guildId: '1', userId: 'h', from: 'vc', to: null }); // a는 남아 있다
  await sleep(30); // 유예(10ms) 지남 — PATCH 대기 중
  g.open();
  await assert.rejects(stop);
  await sleep(5);
  await m.idle();
  assert.deepEqual(patches(calls).filter((b) => b.status === 'transcribing').map((b) => [b.end_reason, b.discord_user_id]), [['command', 'a'], ['host_left', 'h']]);
});

test('Sol 2: 같은 길드 동시 시작은 core 호출 전에 자리를 잡아 두 번째를 409로 돌려보낸다', async () => {
  const g = gate();
  const { m, calls } = setup({ handler: async (me, p) => { if (me === 'POST' && p === '/meetings') await g.p; } });
  const first = m.start(startBody);
  await assert.rejects(m.start(startBody), (e) => e.status === 409 && e.detail === texts.alreadyRunning());
  assert.equal(m.view('1'), null); // 시작 중에는 회의 없음으로 보인다
  g.open();
  await first;
  assert.equal(calls.filter((c) => c.method === 'POST' && c.path === '/meetings').length, 1);
  // core가 거절하면 자리를 비운다
  const s2 = setup({ handler: (me, p) => (me === 'POST' && p === '/meetings' ? [403, { detail: '꺼짐' }] : undefined) });
  await assert.rejects(s2.m.start(startBody), (e) => e.status === 403);
  assert.equal(s2.m.count, 0);
  m.end(m.byGuild.get('1'), 'empty');
  await m.idle();
});

test('Sol 3: 음성 접속 대기 중에 멈추면 state.json이 이미 있어 재시작 복구가 failed로 마감한다', async () => {
  const { m, dataDir } = setup({ discord: fakeDiscord({ joinHangs: true }) });
  m.start(startBody);
  await sleep(5);
  const st = JSON.parse(readFileSync(join(dataDir, 'meetings', '7', 'state.json')));
  assert.deepEqual([st.phase, st.started_at], ['recording', null]);
  // 프로세스 재시작
  const { core, calls } = fakeCore();
  const m2 = new Meetings({ core, discord: fakeDiscord(), dataDir, backoff: () => 5, ffmpeg: fakeFfmpeg() });
  await m2.recover();
  await m2.idle();
  assert.deepEqual(patches(calls).map((b) => [b.status, b.end_reason]), [['failed', 'failed']]);
  assert.equal(JSON.parse(readFileSync(join(dataDir, 'meetings', '7', 'state.json'))).phase, 'failed');
});

test('Sol 4: /host 알림이 빠져도 새 진행자의 퇴장을 잡는다 — 사람마다 유예, 진행자 아니면 400으로 계속', async () => {
  // core만 진행자가 a로 바뀐 것을 안다(Python→Node 알림 유실)
  const { m, calls } = setup({ handler: (me, p, b) => (b?.end_reason === 'host_left' && b.discord_user_id !== 'a' ? [400, { detail: { meeting: '진행자 아님' } }] : undefined) });
  await m.start(startBody);
  m.onVoiceState({ guildId: '1', userId: 'n', name: '새', from: null, to: 'vc' });
  m.onVoiceState({ guildId: '1', userId: 'h', from: 'vc', to: null }); // Node가 아는 진행자 h
  m.onVoiceState({ guildId: '1', userId: 'a', from: 'vc', to: null }); // 실제 진행자 a
  m.onVoiceState({ guildId: '1', userId: 'h', from: null, to: 'vc' }); // h는 유예 안에 복귀 → h 타이머만 취소
  await sleep(100);
  await m.idle();
  assert.equal(m.count, 0);
  const ends = patches(calls).filter((b) => b.status === 'transcribing').map((b) => [b.end_reason, b.discord_user_id]);
  assert.deepEqual(ends, [['host_left', 'a']]);
});

test('Sol 재검증: host_left가 5xx·연결 실패면 백오프로 다시 보내 종료, 돌아오면 재시도 취소', async () => {
  let fails = 2;
  const { m, calls } = setup({ handler: (me, p, b) => (b?.end_reason === 'host_left' && fails-- > 0 ? [503, {}] : undefined) });
  await m.start(startBody);
  m.onVoiceState({ guildId: '1', userId: 'h', from: 'vc', to: null }); // a는 남아 있다
  await sleep(150);
  await m.idle();
  assert.equal(m.count, 0);
  assert.deepEqual(patches(calls).filter((b) => b.status === 'transcribing').map((b) => [b.end_reason, b.discord_user_id]),
    [['host_left', 'h'], ['host_left', 'h'], ['host_left', 'h']]);
  // 실패 뒤 돌아오면 다시 보내지 않는다
  const s2 = setup({ handler: (me, p, b) => (b?.end_reason === 'host_left' ? [503, {}] : undefined) });
  await s2.m.start(startBody);
  s2.m.onVoiceState({ guildId: '1', userId: 'h', from: 'vc', to: null });
  await sleep(60); // 유예(50ms) → 503
  s2.m.onVoiceState({ guildId: '1', userId: 'h', from: null, to: 'vc' });
  await sleep(50);
  assert.equal(patches(s2.calls).filter((b) => b.end_reason === 'host_left').length, 1);
  assert.equal(s2.m.byGuild.get('1').graces.size, 0);
  s2.m.end(s2.m.byGuild.get('1'), 'empty');
  await s2.m.idle();
});

test('Sol 재검증: empty·max_length의 5xx는 로컬 종료 뒤 재시도 큐로 같은 PATCH를 다시 보낸다', async () => {
  let fails = 1;
  const { m, calls } = setup({ minuteMs: 10, ffmpeg: fakeFfmpeg(), handler: (me, p, b) => {
    if (p === '/meetings' && me === 'POST') return [200, { id: 7, note_id: 3, host: { discord_user_id: 'h' }, max_minutes: 1, leave_grace_s: 10 }];
    if (b?.end_reason === 'max_length' && fails-- > 0) return [503, {}];
  } });
  await m.start(startBody);
  await sleep(20);
  assert.equal(m.count, 0); // 최대 길이에서 로컬 종료
  await sleep(30);
  await m.idle();
  const ps = patches(calls).filter((b) => b.status);
  assert.deepEqual(ps.map((b) => [b.status, b.end_reason]), [['transcribing', 'max_length'], ['transcribing', 'max_length'], ['draft', undefined]]);
});
