// 구간 전사(IMPL-PLAN-9 §3, parallel §4): 로컬 OpenAI 호환 서버 우선 → OpenAI 대체. 결과는 `[HH:MM:SS] 이름: 텍스트`.
import { execFile } from 'node:child_process';
import { join } from 'node:path';
import * as texts from './texts.mjs';

export const MIN_SEGMENT_MS = 1500;
export const CONCURRENCY = 3;
const OPENAI_URL = 'https://api.openai.com/v1/audio/transcriptions';

// ogg(Opus) → webm(재인코딩 없음) 또는 16kHz mono wav. OpenAI는 ogg를 받지 않는다(IMPL-PLAN-9-v1 §1.4).
export function ffmpegConvert(path, format) {
  const args = format === 'wav'
    ? ['-v', 'error', '-i', path, '-ar', '16000', '-ac', '1', '-f', 'wav', 'pipe:1']
    : ['-v', 'error', '-i', path, '-c:a', 'copy', '-f', 'webm', 'pipe:1'];
  return new Promise((resolve, reject) =>
    execFile('ffmpeg', args, { encoding: 'buffer', maxBuffer: 64 << 20 }, (e, out) => (e ? reject(e) : resolve(out))));
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

async function post(fetch, url, key, fields, audio, filename, timeoutMs) {
  const form = new FormData();
  form.append('file', new Blob([audio]), filename);
  for (const [k, v] of Object.entries(fields)) if (v) form.append(k, v);
  const r = await fetch(url, {
    method: 'POST', body: form, signal: AbortSignal.timeout(timeoutMs),
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
 * 돌려주는 값: { status: 'draft'|'failed', transcript_md, stats }
 */
export async function transcribeMeeting({
  dir, segments, names, stt = {}, glossary = '', minutes = 0, env = process.env,
  fetch = globalThis.fetch, convert = ffmpegConvert, cached = new Map(), onResult = () => {},
  retryDelayMs = 10000, log = () => {},
}) {
  const url = (stt.url || '').replace(/\/$/, '');
  const localModel = stt.model || 'whisper-1';
  const openaiKey = env.OPENAI_API_KEY || '';
  const openaiModel = env.OPENAI_TRANSCRIBE_MODEL || 'gpt-transcribe';
  const s = { localOk: url ? await localHealthy({ url, apiKey: stt.api_key, fetch }) : false, wav: false, noPrompt: false, connFails: 0 };
  if (url && !s.localOk) log('로컬 전사 서버 헬스 실패, OpenAI로 대체', { host: new URL(url).host });

  const todo = segments.filter((g) => g.duration_ms >= MIN_SEGMENT_MS);
  const skipped = segments.length - todo.length;
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
    return { engines: Object.values(eng), segments: segments.length, skipped, failed: rows.filter((r) => r.failed).length, minutes, ...extra };
  };
  if (todo.length && !s.localOk && !openaiKey) {
    return { status: 'failed', transcript_md: '', stats: stats([], { reason: texts.noEngine() }) };
  }

  async function viaLocal(g) {
    const sec = g.duration_ms / 1000;
    const timeoutMs = Math.min(stt.timeout_s || 120, 30 + 3 * sec) * 1000;
    const send = (wav, noPrompt) => convert(join(dir, g.file), wav ? 'wav' : 'webm').then((audio) =>
      post(fetch, `${url}/v1/audio/transcriptions`, stt.api_key,
        { model: localModel, language: 'ko', response_format: 'json', prompt: noPrompt ? '' : glossary },
        audio, wav ? 'audio.wav' : 'audio.webm', timeoutMs));
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
        const audio = await convert(join(dir, g.file), 'webm');
        return await post(fetch, OPENAI_URL, openaiKey,
          { model: openaiModel, language: 'ko', response_format: 'json', prompt: glossary }, audio, 'audio.webm', 120000);
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
  await Promise.all(Array.from({ length: CONCURRENCY }, async () => {
    for (let g; (g = queue.shift());) {
      let row = cached.get(g.seq);
      if (!row) {
        row = { seq: g.seq, user_id: g.user_id, start_ms: g.start_ms, ...(await one(g)) };
        onResult(row);
      }
      rows.push(row);
    }
  }));
  const failed = rows.filter((r) => r.failed).length;
  if (rows.length && failed === rows.length) {
    return { status: 'failed', transcript_md: '', stats: stats(rows, { reason: texts.allFailed() }) };
  }
  return { status: 'draft', transcript_md: formatTranscript(rows, names), stats: stats(rows) };
}
