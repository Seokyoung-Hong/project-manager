// 내부 HTTP 8082(IMPL-PLAN-9-parallel §3). discord-bot만 부른다. /healthz 말고는 Bearer VOICE_CONTROL_SECRET.
import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { HttpErr } from './meetings.mjs';
import * as texts from './texts.mjs';

function authorized(header, secret) {
  if (!secret) return false; // 비밀값이 없으면 전부 거절(기동 시 경고)
  const a = Buffer.from(String(header || '')), b = Buffer.from(`Bearer ${secret}`);
  return a.length === b.length && timingSafeEqual(a, b);
}

async function readJson(req) {
  let raw = '';
  for await (const c of req) { raw += c; if (raw.length > 65536) throw new HttpErr(400, texts.badRequest()); }
  if (!raw) return {};
  try {
    const v = JSON.parse(raw);
    if (v && typeof v === 'object' && !Array.isArray(v)) return v;
  } catch { /* 아래에서 거절 */ }
  throw new HttpErr(400, texts.badRequest());
}

export function createControl({ meetings, discord, secret, isReady = () => true, log = () => {} }) {
  const routes = [
    ['GET', /^\/guilds\/(\d+)\/meeting$/, async ([g]) => [200, { meeting: meetings.view(g) }]],
    ['GET', /^\/guilds\/(\d+)\/members\/(\d+)\/voice$/, async ([g, u]) => [200, { channel_id: discord.voiceChannelOf(g, u) ?? null }]],
    ['POST', /^\/meetings$/, async (_, body) => [201, await meetings.start(body)]],
    ['POST', /^\/meetings\/(\d+)\/stop$/, async ([id], body) => [200, await meetings.stop(id, body.discord_user_id)]],
    ['POST', /^\/meetings\/(\d+)\/host$/, async ([id], body) => [200, meetings.setHost(id, body.discord_user_id)]],
  ];
  return createServer(async (req, res) => {
    const reply = (status, data) => {
      res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(data));
    };
    const path = new URL(req.url, 'http://x').pathname;
    try {
      if (req.method === 'GET' && path === '/healthz') return reply(200, { ok: true, ready: isReady(), meetings: meetings.count });
      if (!authorized(req.headers.authorization, secret)) return reply(401, { detail: texts.unauthorized() });
      for (const [method, re, fn] of routes) {
        const hit = req.method === method && re.exec(path);
        if (!hit) continue;
        const body = method === 'POST' ? await readJson(req) : {};
        const [status, data] = await fn(hit.slice(1), body);
        return reply(status, data);
      }
      reply(404, { detail: texts.notFound() });
    } catch (e) {
      if (e instanceof HttpErr) return reply(e.status, { detail: e.detail });
      log('control 오류', { path, error: e.message });
      reply(500, { detail: texts.coreDown() });
    }
  });
}
