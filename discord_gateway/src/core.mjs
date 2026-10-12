// core 봇 API(/api/integrations/discord/meetings*) 클라이언트. 인증은 CORE_TOKEN Bearer(봇 범위 토큰).
import { openAsBlob, createWriteStream } from 'node:fs';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import * as texts from './texts.mjs';

export class CoreError extends Error {
  // status 0 = 연결 실패. detail = 사용자에게 그대로 보일 한국어 문장
  constructor(status, detail) {
    super(`core ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

// core의 detail은 문자열(HttpError), {필드: 문장}(ServiceError·Forbidden), [{msg}](검증 422) 중 하나다.
export function detailText(d) {
  if (d == null) return '';
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => (typeof x === 'string' ? x : x?.msg ?? detailText(x))).join(' ');
  if (typeof d === 'object') return Object.values(d).map(detailText).filter(Boolean).join(' ');
  return String(d);
}

export function createCore({ url, token, fetch = globalThis.fetch, timeoutMs = 20000 }) {
  const base = `${url.replace(/\/$/, '')}/api/integrations/discord`;
  async function call(method, path, body, ms = timeoutMs) {
    const form = body instanceof FormData;
    let r;
    try {
      r = await fetch(base + path, {
        method,
        // FormData면 fetch가 multipart 경계를 붙인 Content-Type을 정한다
        headers: { Authorization: `Bearer ${token}`, 'X-Source': 'api', ...(form ? {} : { 'Content-Type': 'application/json' }) },
        body: body === undefined || form ? body : JSON.stringify(body),
        signal: AbortSignal.timeout(ms),
      });
    } catch {
      throw new CoreError(0, texts.coreDown());
    }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new CoreError(r.status, detailText(data.detail) || texts.coreDown());
    return data;
  }
  return {
    startMeeting: (body) => call('POST', '/meetings', body),
    patchMeeting: (id, body) => call('PATCH', `/meetings/${id}`, body),
    names: (id) => call('GET', `/meetings/${id}/names`),
    // 혼합 녹음 파일. 파일 기반 Blob이라 메모리에 통째로 올리지 않는다. 응답 형식은 2xx만 본다
    async uploadAudio(id, path) {
      const form = new FormData();
      form.append('file', await openAsBlob(path, { type: 'audio/ogg' }), 'meeting.ogg');
      return call('PUT', `/meetings/${id}/audio`, form, 600000);
    },
    // 참여자별 트랙(회의 시작 기준 정렬). 같은 사람에게 다시 올리면 바꾼다
    async uploadTrack(id, discordUserId, path) {
      const form = new FormData();
      form.append('file', await openAsBlob(path, { type: 'audio/ogg' }), 'track.ogg');
      return call('PUT', `/meetings/${id}/tracks/${encodeURIComponent(discordUserId)}`, form, 600000);
    },
    // 전사 작업(IMPL-PLAN-10-transcribe-menu). 진행 PATCH 응답의 cancel이 true면 멈춘다
    reportJob: (id, body) => call('PATCH', `/transcriptions/${id}`, body),
    claimJob: () => call('POST', '/transcriptions/claim', {}),
    requeueJobs: () => call('POST', '/transcriptions/requeue', {}),
    // 다시 전사용 참여자별 트랙을 파일로 받는다(메모리에 통째로 올리지 않는다)
    async downloadTrack(id, discordUserId, path) {
      let r;
      try {
        r = await fetch(`${base}/meetings/${id}/tracks/${encodeURIComponent(discordUserId)}`, {
          headers: { Authorization: `Bearer ${token}`, 'X-Source': 'api' }, signal: AbortSignal.timeout(600000),
        });
      } catch {
        throw new CoreError(0, texts.coreDown());
      }
      if (!r.ok) throw new CoreError(r.status, detailText((await r.json().catch(() => ({}))).detail) || texts.coreDown());
      await pipeline(Readable.fromWeb(r.body), createWriteStream(path));
    },
  };
}
