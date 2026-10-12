// core 봇 API(/api/integrations/discord/meetings*) 클라이언트. 인증은 CORE_TOKEN Bearer(봇 범위 토큰).
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
  async function call(method, path, body) {
    let r;
    try {
      r = await fetch(base + path, {
        method,
        headers: { Authorization: `Bearer ${token}`, 'X-Source': 'api', 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(timeoutMs),
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
  };
}
