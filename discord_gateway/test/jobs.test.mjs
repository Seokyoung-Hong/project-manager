// 전사 작업(IMPL-PLAN-10-transcribe-menu): 진행 보고·취소 신호·다시 전사(트랙 구간 자르기). 가짜 core·가짜 변환기.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createCore } from '../src/core.mjs';
import { Meetings } from '../src/meetings.mjs';
import { transcribeMeeting, speechRanges, splitBySilence } from '../src/transcribe.mjs';
import { execFileSync } from 'node:child_process';

const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const seg = (seq, user_id, start_ms, duration_ms = 3000) => ({ seq, user_id, start_ms, duration_ms, file: `seg/${seq}.ogg` });

test('transcribeMeeting: 구간마다 진행을 알리고, 취소되면 새 구간을 꺼내지 않고 cancelled', async () => {
  const ctl = new AbortController();
  const progress = [];
  let sent = 0;
  const fetch = async (url) => {
    if (url.endsWith('/v1/models')) return json({ data: [] });
    sent++;
    return json({ text: `말${sent}` });
  };
  const segments = Array.from({ length: 9 }, (_, i) => seg(i + 1, 'u1', i * 4000));
  const out = await transcribeMeeting({
    dir: '/x', segments, names: { u1: '홍' }, stt: { url: 'http://stt:8000', model: 'm' }, fetch, env: {},
    convert: async () => Buffer.from('a'), retryDelayMs: 1, signal: ctl.signal,
    onProgress: (p) => { progress.push(p); if (p.segments_done === 2) ctl.abort(); },
  });
  assert.equal(out.cancelled, true);
  assert.equal(out.transcript_md, '');
  assert.ok(sent < 9, `보낸 구간 ${sent}`);
  assert.deepEqual(progress[0], { done_ms: 3000, audio_ms: 27000, segments_total: 9, segments_done: 1, segments_failed: 0 });
});

test('transcribeMeeting: 변환기에 구간을 넘긴다(다시 전사는 cut 구간을 트랙에서 자른다)', async () => {
  const seen = [];
  const fetch = async (url) => json(url.endsWith('/v1/models') ? { data: [] } : { text: 't' });
  await transcribeMeeting({
    dir: '/r', segments: [{ ...seg(1, 'u1', 61000), file: 'track-u1.ogg', cut: true }], names: {},
    stt: { url: 'http://stt:8000' }, fetch, env: {}, retryDelayMs: 1,
    convert: async (path, fmt, g) => { seen.push([path, fmt, g.cut, g.start_ms]); return Buffer.from('a'); },
  });
  assert.deepEqual(seen, [[join('/r', 'track-u1.ogg'), 'webm', true, 61000]]);
});

function fakeCore(handler) {
  const calls = [];
  const fetch = async (url, opts = {}) => {
    if (!url.includes('/api/integrations/discord')) return handler.stt(url, opts);
    const path = new URL(url).pathname.replace('/api/integrations/discord', '');
    const body = typeof opts.body === 'string' ? JSON.parse(opts.body) : undefined;
    calls.push({ method: opts.method ?? 'GET', path, body });
    return handler.core(opts.method ?? 'GET', path, body);
  };
  return { core: createCore({ url: 'http://web:8000', token: 't', fetch }), fetch, calls };
}

test('다시 전사: 큐가 비었을 때 가져가 트랙을 받고 구간 경계로 잘라 전사, done 보고 뒤 임시 폴더 삭제', async () => {
  const dataDir = mkdtempSync(join(tmpdir(), 'voice-'));
  const cuts = [];
  const { core, fetch, calls } = fakeCore({
    stt: async (url) => json(url.endsWith('/v1/models') ? { data: [] } : { text: '다시' }),
    core: async (method, path) => {
      if (path === '/transcriptions/claim') {
        return json({ job: { id: 5, recording_id: 7, engine: 'local', model: 'big' }, tracks: ['h'],
          segments: [{ seq: 1, user_id: 'h', start_ms: 2000, duration_ms: 3000 }, { seq: 2, user_id: 'x', start_ms: 0, duration_ms: 3000 }],
          participants: [{ discord_user_id: 'h', discord_name: 'H닉' }], names: [], stt: { url: 'http://stt:8000', model: 'big' }, glossary: '' });
      }
      if (method === 'GET' && path === '/meetings/7/tracks/h') return new Response('ogg', { status: 200 });
      return json({ status: 'running', cancel: false });
    },
  });
  const m = new Meetings({ core, discord: {}, dataDir, fetch, retryDelayMs: 1,
    convert: async (path, _fmt, g) => { cuts.push([existsSync(path), g.cut, g.start_ms]); return Buffer.from('a'); } });
  await m.pollJobs();
  await m.idle();
  assert.deepEqual(cuts, [[true, true, 2000]]); // 트랙이 없는 x 구간은 뺀다
  const done = calls.find((c) => c.method === 'PATCH' && c.body.status);
  assert.equal(done.path, '/transcriptions/5');
  assert.equal(done.body.status, 'done');
  assert.equal(done.body.transcript_md, '[00:00:02] H닉: 다시');
  assert.ok(!existsSync(join(dataDir, 'retry', '5')));
});

test('다시 전사: 후처리 큐가 바쁘면 가져가지 않는다, 대기열이 비면 아무 일도 없다', async () => {
  const dataDir = mkdtempSync(join(tmpdir(), 'voice-'));
  const { core, calls } = fakeCore({ stt: async () => json({}), core: async () => json({ job: null }) });
  const m = new Meetings({ core, discord: {}, dataDir });
  m.pending = 1;
  assert.equal(await m.pollJobs(), null);
  assert.equal(calls.length, 0);
  m.pending = 0;
  assert.equal(await m.pollJobs(), null);
  assert.deepEqual(calls.map((c) => c.path), ['/transcriptions/claim']);
});

test('다시 전사: 진행 보고 응답이 cancel이면 멈추고 cancelled 보고', async () => {
  const dataDir = mkdtempSync(join(tmpdir(), 'voice-'));
  let t = 0;
  const { core, fetch, calls } = fakeCore({
    stt: async (url) => json(url.endsWith('/v1/models') ? { data: [] } : { text: 'x' }),
    core: async (method, path, body) => {
      if (path === '/transcriptions/claim') {
        return json({ job: { id: 6, recording_id: 7, engine: 'openai', model: 'whisper-1' }, tracks: ['h'],
          segments: Array.from({ length: 12 }, (_, i) => ({ seq: i, user_id: 'h', start_ms: i * 4000, duration_ms: 3000 })),
          names: [], stt: { url: '', openai_api_key: 'sk' }, glossary: '' });
      }
      if (method === 'GET') return new Response('ogg');
      return json({ status: body.status ?? 'cancelling', cancel: !body.status });
    },
  });
  const m = new Meetings({ core, discord: {}, dataDir, fetch, retryDelayMs: 1, now: () => (t += 10000),
    convert: async () => Buffer.from('a') });
  await m.pollJobs();
  await m.idle();
  const reports = calls.filter((c) => c.method === 'PATCH');
  assert.equal(reports.at(-1).body.status, 'cancelled');
  assert.ok(reports.length < 12);
});

// ---------- 올린 녹음(IMPL-PLAN-10-transcribe-menu §12) ----------

test('speechRanges: 무음 사이를 말한 구간으로, 끝까지 무음이면 마지막은 비우고, 긴 구간은 30초로 자른다', () => {
  const err = '  Duration: 00:01:10.50, start: 0\n[silencedetect] silence_start: 2.0\n[silencedetect] silence_end: 3.5 | silence_duration: 1.5\n'
    + '[silencedetect] silence_start: 69.0\n';
  assert.deepEqual(speechRanges(err), [
    { start_ms: 0, duration_ms: 2000 }, { start_ms: 3500, duration_ms: 30000 }, { start_ms: 33500, duration_ms: 30000 },
    { start_ms: 63500, duration_ms: 5500 }]);
  assert.deepEqual(speechRanges('Duration: 00:00:04.00\n'), [{ start_ms: 0, duration_ms: 4000 }]); // 무음 없음
  assert.deepEqual(speechRanges('no duration'), []);
});

test('splitBySilence: 실제 ffmpeg로 소리 2초·무음 2초 반복 파일을 두 구간으로', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'split-'));
  const wav = join(dir, 'a.wav');
  execFileSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', "aevalsrc='if(lt(mod(t,4),2),0.5*sin(440*2*PI*t),0)':d=8:s=16000", wav]);
  const r = await splitBySilence(wav);
  assert.equal(r.length, 2);
  assert.ok(Math.abs(r[0].start_ms) < 100 && Math.abs(r[0].duration_ms - 2000) < 200, JSON.stringify(r));
  assert.ok(Math.abs(r[1].start_ms - 4000) < 200, JSON.stringify(r));
});

test('올린 녹음 전사: 파일 하나를 받아 구간을 나누고 wav로 보내 화자 하나의 전사문을 done 보고', async () => {
  const dataDir = mkdtempSync(join(tmpdir(), 'voice-'));
  const sent = [];
  const { core, fetch, calls } = fakeCore({
    stt: async (url, opts) => {
      if (url.endsWith('/v1/models')) return json({ data: [] });
      sent.push(opts.body.get('file').name);
      return json({ text: '안녕하세요' });
    },
    core: async (method, path) => {
      if (path === '/transcriptions/claim') {
        return json({ job: { id: 9, recording_id: 8, engine: 'local', model: 'm' }, source: 'upload', speaker: '올린 녹음',
          segments: [], tracks: [], names: [], stt: { url: 'http://stt:8000', model: 'm' }, glossary: '' });
      }
      if (method === 'GET' && path === '/meetings/8/audio') return new Response('mp3', { status: 200 });
      return json({ status: 'running', cancel: false });
    },
  });
  const cuts = [];
  const m = new Meetings({ core, discord: {}, dataDir, fetch, retryDelayMs: 1,
    split: async (path) => { assert.ok(existsSync(path)); return [{ start_ms: 0, duration_ms: 2000 }, { start_ms: 65000, duration_ms: 3000 }]; },
    convert: async (path, fmt, g) => { cuts.push([path.endsWith('upload.audio'), fmt, g.cut, g.start_ms]); return Buffer.from('a'); } });
  await m.pollJobs();
  await m.idle();
  assert.deepEqual(cuts, [[true, 'wav', true, 0], [true, 'wav', true, 65000]]);
  assert.deepEqual(sent, ['audio.wav', 'audio.wav']);
  const done = calls.find((c) => c.method === 'PATCH' && c.body.status);
  assert.equal(done.body.status, 'done');
  assert.equal(done.body.transcript_md, '[00:00:00] 올린 녹음: 안녕하세요\n[00:01:05] 올린 녹음: 안녕하세요');
  assert.equal(done.body.done_ms, 5000);
  assert.ok(!existsSync(join(dataDir, 'retry', '9')));
});
