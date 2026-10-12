// 구간 전사(IMPL-PLAN-9 §3, parallel §4): 로컬 OpenAI 호환 서버 우선 → OpenAI 대체. 결과는 `[HH:MM:SS] 이름: 텍스트`.
import { execFile } from 'node:child_process';
import { join } from 'node:path';
import * as texts from './texts.mjs';

export const MIN_SEGMENT_MS = 1500;
export const CONCURRENCY = 3;
const OPENAI_URL = 'https://api.openai.com/v1/audio/transcriptions';

// ogg(Opus) → webm(재인코딩 없음) 또는 16kHz mono wav. OpenAI는 ogg를 받지 않는다(IMPL-PLAN-9-v1 §1.4).
// g.cut이면 참여자별 트랙에서 그 구간(start_ms부터 duration_ms)만 잘라 낸다(다시 전사, IMPL-PLAN-10-transcribe-menu §5).
export function ffmpegConvert(path, format, g) {
  const cut = g?.cut ? ['-ss', String(g.start_ms / 1000), '-t', String(g.duration_ms / 1000)] : [];
  const args = format === 'wav'
    ? ['-v', 'error', ...cut, '-i', path, '-ar', '16000', '-ac', '1', '-f', 'wav', 'pipe:1']
    : ['-v', 'error', ...cut, '-i', path, '-c:a', 'copy', '-f', 'webm', 'pipe:1'];
  return new Promise((resolve, reject) =>
    execFile('ffmpeg', args, { encoding: 'buffer', maxBuffer: 64 << 20 }, (e, out) => (e ? reject(e) : resolve(out))));
}

// 올린 녹음 구간 나누기(IMPL-PLAN-10-transcribe-menu §12): ffmpeg silencedetect가 stderr에 남긴 무음 구간의 사이를 말한 구간으로 본다.
// 긴 구간은 maxMs로 자른다(whisper 창 30초). ponytail: 고정 잡음 기준(-35dB) — 시끄러운 녹음이면 조직 설정으로 뺀다.
export const SPLIT_MAX_MS = 30000;
export function speechRanges(stderr, { maxMs = SPLIT_MAX_MS } = {}) {
  const d = /Duration: (\d+):(\d+):(\d+(?:\.\d+)?)/.exec(stderr);
  if (!d) return [];
  const total = Math.round(((+d[1] * 60 + +d[2]) * 60 + +d[3]) * 1000);
  const silences = [];
  for (const m of stderr.matchAll(/silence_(start|end): (-?\d+(?:\.\d+)?)/g)) {
    const ms = Math.max(0, Math.round(+m[2] * 1000));
    if (m[1] === 'start') silences.push([ms, total]);
    else if (silences.length) silences.at(-1)[1] = ms;
  }
  const out = [];
  let at = 0;
  const speech = (a, b) => { for (let s = a; s < b; s += maxMs) out.push({ start_ms: s, duration_ms: Math.min(maxMs, b - s) }); };
  for (const [a, b] of silences) { if (a > at) speech(at, a); at = Math.max(at, b); }
  if (at < total) speech(at, total);
  return out;
}

// 파일을 디스크에서 흘려 읽는다(메모리에 올리지 않는다). 디코딩 실패는 그대로 던진다.
export function splitBySilence(path, run = execFile) {
  const args = ['-hide_banner', '-nostats', '-i', path, '-af', 'silencedetect=noise=-35dB:d=0.6', '-f', 'null', '-'];
  return new Promise((resolve, reject) =>
    run('ffmpeg', args, { maxBuffer: 16 << 20 }, (e, _out, err) => (e ? reject(e) : resolve(speechRanges(String(err))))));
}

export function stamp(ms) {
  const s = Math.floor(ms / 1000);
  return [s / 3600, (s % 3600) / 60, s % 60].map((n) => String(Math.floor(n)).padStart(2, '0')).join(':');
}

export function formatTranscript(rows, names) {
  return rows
    .filter((r) => r.failed || r.text)
    .sort((a, b) => a.start_ms - b.start_ms || a.seq - b.seq)
    .map((r) => `[${stamp(r.start_ms)}] ${names[r.user_id] ?? r.user_id}: ${r.failed ? texts.TRANSCRIBE_FAILED : r.text}`)
    .join('\n');
}

class HttpFail extends Error {
  constructor(status, body) { super(`HTTP ${status}`); this.status = status; this.body = body; }
}
const isConnFail = (e) => !(e instanceof HttpFail) || e.status >= 500;

async function post(fetch, url, key, fields, audio, filename, timeoutMs, cancel) {
  const form = new FormData();
  form.append('file', new Blob([audio]), filename);
  for (const [k, v] of Object.entries(fields)) if (v) form.append(k, v);
  const r = await fetch(url, {
    method: 'POST', body: form,
    signal: cancel ? AbortSignal.any([AbortSignal.timeout(timeoutMs), cancel]) : AbortSignal.timeout(timeoutMs),
    headers: key ? { Authorization: `Bearer ${key}` } : {},
  });
  if (!r.ok) throw new HttpFail(r.status, await r.text().catch(() => ''));
  const data = await r.json();
  return String(data.text ?? '').trim();
}

export async function localHealthy({ url, apiKey, fetch, timeoutMs = 3000 }) {
  try {
    const r = await fetch(`${url}/v1/models`, {
      signal: AbortSignal.timeout(timeoutMs), headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
    });
    if (!r.ok) return false;
    await r.json();
    return true;
  } catch {
    return false;
  }
}

/**
 * segments: segments.jsonl 행들. cached: 이미 끝난 결과(seq → row, 재시작 재개용). onResult: 결과 한 줄씩 저장.
 * signal: 취소(AbortSignal). 걸리면 새 구간을 꺼내지 않고 진행 중 요청을 끊는다. onProgress: 구간이 끝날 때마다 진행.
 * 돌려주는 값: { status: 'draft'|'failed', transcript_md, stats, cancelled }
 */
export async function transcribeMeeting({
  dir, segments, names, stt = {}, glossary = '', minutes = 0, env = process.env,
  fetch = globalThis.fetch, convert = ffmpegConvert, cached = new Map(), onResult = () => {},
  retryDelayMs = 10000, log = () => {}, signal = null, onProgress = () => {}, wav = false,
}) {
  const url = (stt.url || '').replace(/\/$/, '');
  const localModel = stt.model || 'whisper-1';
  // 엔진 순서(parallel §7): ① 로컬(stt.url) ② 조직 OpenAI 키(stt.openai_api_key) ③ 녹음만. .env의 OPENAI_API_KEY는 읽지 않는다
  const openaiKey = stt.openai_api_key || '';
  const openaiModel = env.OPENAI_TRANSCRIBE_MODEL || 'whisper-1';
  // wav: 올린 녹음(mp3·m4a 등)은 webm으로 복사할 수 없어 처음부터 16kHz wav로 보낸다
  const s = { localOk: url ? await localHealthy({ url, apiKey: stt.api_key, fetch }) : false, wav, noPrompt: false, connFails: 0 };
  if (url && !s.localOk) log('로컬 전사 서버 헬스 실패, OpenAI로 대체', { host: new URL(url).host });

  const todo = segments.filter((g) => g.duration_ms >= MIN_SEGMENT_MS);
  const skipped = segments.length - todo.length;
  const audioMs = todo.reduce((n, g) => n + g.duration_ms, 0);
  const stats = (rows, extra = {}) => {
    const eng = {};
    for (const r of rows) {
      if (!r.engine) continue;
      const e = (eng[r.engine] ??= r.engine === 'local'
        ? { engine: 'local', host: url ? new URL(url).host : '', model: localModel, segments: 0, failed: 0 }
        : { engine: 'openai', model: openaiModel, segments: 0, failed: 0 });
      e.segments++;
      if (r.failed) e.failed++;
    }
    // stats.engine = 주로 쓴 엔진(구간 수 최다). 쓴 구간이 없으면 고른 엔진, 고를 게 없으면 none
    const main = Object.values(eng).sort((a, b) => b.segments - a.segments)[0]?.engine
      ?? (s.localOk ? 'local' : openaiKey ? 'openai' : 'none');
    return { engine: main, engines: Object.values(eng), segments: segments.length, skipped, failed: rows.filter((r) => r.failed).length, minutes, audio_ms: audioMs, ...extra };
  };
  // 녹음만: 실패가 아니라 빈 전사문의 초안(녹음 파일을 내려받아 직접 전사)
  if (!s.localOk && !openaiKey) return { status: 'draft', transcript_md: '', stats: stats([]) };

  async function viaLocal(g) {
    const sec = g.duration_ms / 1000;
    const timeoutMs = Math.min(stt.timeout_s || 120, 30 + 3 * sec) * 1000;
    const send = (wav, noPrompt) => convert(join(dir, g.file), wav ? 'wav' : 'webm', g).then((audio) =>
      post(fetch, `${url}/v1/audio/transcriptions`, stt.api_key,
        { model: localModel, language: 'ko', response_format: 'json', prompt: noPrompt ? '' : glossary },
        audio, wav ? 'audio.wav' : 'audio.webm', timeoutMs, signal));
    for (let attempt = 0; ; attempt++) {
      try {
        const text = await send(s.wav, s.noPrompt);
        s.connFails = 0;
        return text;
      } catch (e) {
        if (!isConnFail(e)) {
          // ponytail: 응답 본문에 prompt가 보이면 prompt 거부, 아니면 형식 거부로 본다
          if (e.status === 400 && !s.noPrompt && glossary && /prompt/i.test(e.body)) {
            const text = await send(s.wav, true);
            s.noPrompt = true;
            return text;
          }
          if ((e.status === 400 || e.status === 415) && !s.wav) {
            const text = await send(true, s.noPrompt);
            s.wav = true;
            return text;
          }
          throw e;
        }
        if (++s.connFails >= 2) { s.localOk = false; throw e; } // 이후 구간은 OpenAI
        if (attempt === 0) await new Promise((r) => setTimeout(r, retryDelayMs));
        else throw e;
      }
    }
  }

  async function viaOpenai(g) {
    let last;
    for (let i = 0; i < 3; i++) {
      try {
        const audio = await convert(join(dir, g.file), 'webm', g);
        return await post(fetch, OPENAI_URL, openaiKey,
          { model: openaiModel, language: 'ko', response_format: 'json', prompt: glossary }, audio, 'audio.webm', 120000, signal);
      } catch (e) {
        last = e;
        if (e instanceof HttpFail && e.status < 500 && e.status !== 429) break;
        if (i < 2) await new Promise((r) => setTimeout(r, retryDelayMs / 5));
      }
    }
    throw last;
  }

  async function one(g) {
    let engine = null;
    try {
      if (s.localOk) {
        engine = 'local';
        try { return { text: await viaLocal(g), engine }; } catch (e) {
          log('로컬 전사 실패', { seq: g.seq, error: e.message });
          if (!openaiKey) throw e;
        }
      }
      if (!openaiKey) throw new Error('전사 수단 없음');
      engine = 'openai';
      return { text: await viaOpenai(g), engine };
    } catch (e) {
      log('구간 전사 실패', { seq: g.seq, engine, error: e.message });
      return { failed: true, engine };
    }
  }

  const rows = [];
  const queue = [...todo];
  let doneMs = 0;
  await Promise.all(Array.from({ length: CONCURRENCY }, async () => {
    for (let g; !signal?.aborted && (g = queue.shift());) {
      let row = cached.get(g.seq);
      if (!row) {
        row = { seq: g.seq, user_id: g.user_id, start_ms: g.start_ms, ...(await one(g)) };
        if (signal?.aborted) return; // 끊긴 요청의 실패는 결과로 남기지 않는다
        onResult(row);
      }
      rows.push(row);
      doneMs += g.duration_ms;
      onProgress({ done_ms: doneMs, audio_ms: audioMs, segments_total: todo.length,
        segments_done: rows.length, segments_failed: rows.filter((r) => r.failed).length });
    }
  }));
  if (signal?.aborted) return { status: 'draft', transcript_md: '', stats: stats(rows, { cancelled: true }), cancelled: true };
  // 전부 실패해도 draft: 녹음 파일은 이미 올라가 있어 내려받아 직접 전사할 수 있다(failed는 회의 자체 실패만)
  return { status: 'draft', transcript_md: formatTranscript(rows, names), stats: stats(rows) };
}
