// 전사 엔진 선택·대체·재시도·실패와 전사문 형식. 가짜 fetch·가짜 변환기(ffmpeg 없이).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { transcribeMeeting, formatTranscript, stamp } from '../src/transcribe.mjs';

const LOCAL = 'http://stt.local:8000';
const seg = (seq, user_id, start_ms, duration_ms = 3000) => ({ seq, user_id, start_ms, duration_ms, file: `seg/${seq}.ogg` });
const convert = async (_p, fmt) => Buffer.from(fmt);

// routes: (url, form) → Response | throw
function fakeFetch(route) {
  const calls = [];
  const fetch = async (url, opts = {}) => {
    const form = opts.body instanceof FormData ? opts.body : null;
    const call = { url, model: form?.get('model'), prompt: form?.get('prompt'), language: form?.get('language'),
      filename: form?.get('file')?.name, auth: opts.headers?.Authorization };
    calls.push(call);
    return route(url, call);
  };
  return { fetch, calls };
}
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const base = { dir: '/x', names: { u1: '홍길동', u2: '김철수 (계정 없음)' }, glossary: '유달리, 산돌이', convert, retryDelayMs: 1 };

test('로컬 헬스 통과면 로컬 전사, 1.5초 미만 생략, start_ms 순 [HH:MM:SS] 이름: 텍스트', async () => {
  const { fetch, calls } = fakeFetch((url, c) => {
    if (url === `${LOCAL}/v1/models`) return json({ data: [] });
    return json({ text: c.filename === 'audio.webm' ? `말-${calls.length}` : '' });
  });
  const out = await transcribeMeeting({
    ...base, fetch, env: {}, stt: { url: LOCAL + '/', model: 'Systran/faster-whisper-small', timeout_s: 60, api_key: 'k' },
    segments: [seg(2, 'u2', 3_725_000), seg(1, 'u1', 12_000), seg(3, 'u1', 20_000, 1000)], minutes: 62,
  });
  assert.equal(out.status, 'draft');
  const lines = out.transcript_md.split('\n');
  assert.match(lines[0], /^\[00:00:12\] 홍길동: 말-\d$/);
  assert.match(lines[1], /^\[01:02:05\] 김철수 \(계정 없음\): 말-\d$/);
  assert.equal(lines.length, 2);
  const tx = calls.filter((c) => c.url.endsWith('/transcriptions'));
  assert.equal(tx.length, 2);
  assert.equal(tx[0].model, 'Systran/faster-whisper-small');
  assert.equal(tx[0].language, 'ko');
  assert.equal(tx[0].prompt, '유달리, 산돌이');
  assert.equal(tx[0].auth, 'Bearer k');
  assert.deepEqual(out.stats, {
    engines: [{ engine: 'local', host: 'stt.local:8000', model: 'Systran/faster-whisper-small', segments: 2, failed: 0 }],
    segments: 3, skipped: 1, failed: 0, minutes: 62,
  });
});

test('로컬 헬스 실패 + OPENAI_API_KEY → OpenAI(기본 gpt-transcribe)', async () => {
  const { fetch, calls } = fakeFetch((url) => {
    if (url.startsWith(LOCAL)) throw new TypeError('fetch failed');
    return json({ text: '안녕하세요' });
  });
  const out = await transcribeMeeting({ ...base, fetch, env: { OPENAI_API_KEY: 'sk' }, stt: { url: LOCAL }, segments: [seg(1, 'u1', 0)] });
  assert.equal(out.transcript_md, '[00:00:00] 홍길동: 안녕하세요');
  const oa = calls.find((c) => c.url.includes('api.openai.com'));
  assert.equal(oa.model, 'gpt-transcribe');
  assert.equal(oa.auth, 'Bearer sk');
  assert.equal(out.stats.engines[0].engine, 'openai');
});

test('전사 수단이 없으면 즉시 failed, stats에 사유', async () => {
  const { fetch, calls } = fakeFetch(() => json({}));
  const out = await transcribeMeeting({ ...base, fetch, env: {}, stt: {}, segments: [seg(1, 'u1', 0)] });
  assert.equal(out.status, 'failed');
  assert.equal(out.stats.reason, '전사 수단이 설정되지 않았습니다.');
  assert.equal(calls.length, 0);
});

test('로컬 415면 wav로 재시도하고 이후 구간은 wav 고정', async () => {
  const { fetch, calls } = fakeFetch((url, c) => {
    if (url.endsWith('/v1/models')) return json({});
    return c.filename === 'audio.wav' ? json({ text: 'ok' }) : json({ detail: 'unsupported' }, 415);
  });
  const out = await transcribeMeeting({ ...base, fetch, env: {}, stt: { url: LOCAL }, segments: [seg(1, 'u1', 0)] });
  assert.equal(out.transcript_md, '[00:00:00] 홍길동: ok');
  const out2 = await transcribeMeeting({ ...base, fetch, env: {}, stt: { url: LOCAL }, segments: [seg(1, 'u1', 0), seg(2, 'u1', 5000)] });
  assert.equal(out2.stats.failed, 0);
  assert.deepEqual(calls.filter((c) => c.filename).map((c) => c.filename).slice(0, 2), ['audio.webm', 'audio.wav']);
});

test('로컬 400에 prompt가 보이면 prompt 없이 재시도', async () => {
  const { fetch, calls } = fakeFetch((url, c) => {
    if (url.endsWith('/v1/models')) return json({});
    return c.prompt ? json({ detail: 'prompt is not supported' }, 400) : json({ text: '됐습니다' });
  });
  const out = await transcribeMeeting({ ...base, fetch, env: {}, stt: { url: LOCAL }, segments: [seg(1, 'u1', 0), seg(2, 'u2', 4000)] });
  assert.equal(out.stats.failed, 0);
  // 동시 3구간의 첫 시도만 prompt를 싣고, 그 뒤(4번째 구간)는 prompt 없이 바로 보낸다
  const out2 = await transcribeMeeting({ ...base, fetch, env: {}, stt: { url: LOCAL }, segments: [1, 2, 3, 4].map((i) => seg(i, 'u1', i * 4000)) });
  assert.equal(out2.stats.failed, 0);
  assert.equal(calls.filter((c) => c.filename).at(-1).prompt, null);
});

test('로컬 연결 실패 2회면 그 구간부터 OpenAI', async () => {
  let n = 0;
  const { fetch, calls } = fakeFetch((url) => {
    if (url.endsWith('/v1/models')) return json({});
    if (url.startsWith(LOCAL)) { n++; throw new TypeError('fetch failed'); }
    return json({ text: 'oa' });
  });
  const out = await transcribeMeeting({
    ...base, fetch, env: { OPENAI_API_KEY: 'sk', OPENAI_TRANSCRIBE_MODEL: 'm2' }, stt: { url: LOCAL },
    segments: [seg(1, 'u1', 0), seg(2, 'u1', 5000), seg(3, 'u1', 9000), seg(4, 'u1', 12000)],
  });
  assert.equal(out.stats.failed, 0);
  assert.ok(n <= 4, `로컬 시도 ${n}회`); // 동시 3구간이 함께 실패를 센다
  assert.ok(calls.filter((c) => c.url.includes('openai')).every((c) => c.model === 'm2'));
  assert.equal(out.stats.engines.length, 1);
  assert.equal(out.stats.engines[0].engine, 'openai');
});

test('일부 실패는 [전사 실패] 줄로 draft, 전부 실패면 failed', async () => {
  const { fetch } = fakeFetch((url, c) => (c.prompt && url.includes('openai') && calls2.n++ === 0 ? json({ text: '첫 구간' }) : json({ error: 'x' }, 400)));
  const calls2 = { n: 0 };
  const out = await transcribeMeeting({ ...base, fetch, env: { OPENAI_API_KEY: 'sk' }, stt: {}, segments: [seg(1, 'u1', 0), seg(2, 'u2', 61_000)] });
  assert.equal(out.status, 'draft');
  assert.equal(out.stats.failed, 1);
  assert.match(out.transcript_md, /\[전사 실패\]/);
  const { fetch: f2 } = fakeFetch(() => json({}, 500));
  const all = await transcribeMeeting({ ...base, fetch: f2, env: { OPENAI_API_KEY: 'sk' }, stt: {}, segments: [seg(1, 'u1', 0)] });
  assert.equal(all.status, 'failed');
  assert.equal(all.stats.engines[0].failed, 1);
});

test('재개: cached 구간은 다시 전사하지 않는다', async () => {
  const { fetch, calls } = fakeFetch(() => json({ text: '새로' }));
  const cached = new Map([[1, { seq: 1, user_id: 'u1', start_ms: 0, text: '예전', engine: 'openai' }]]);
  const saved = [];
  const out = await transcribeMeeting({ ...base, fetch, env: { OPENAI_API_KEY: 'sk' }, stt: {}, cached, onResult: (r) => saved.push(r),
    segments: [seg(1, 'u1', 0), seg(2, 'u1', 3000)] });
  assert.equal(out.transcript_md, '[00:00:00] 홍길동: 예전\n[00:00:03] 홍길동: 새로');
  assert.equal(calls.length, 1);
  assert.deepEqual(saved.map((r) => r.seq), [2]);
});

test('형식 도우미', () => {
  assert.equal(stamp(3_661_999), '01:01:01');
  assert.equal(formatTranscript([{ seq: 1, user_id: 'x', start_ms: 0, text: '' }], {}), ''); // 빈 결과 줄 생략
});
