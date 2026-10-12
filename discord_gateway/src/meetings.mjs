// 회의 상태기(IMPL-PLAN-9-parallel §4): 시작·참여자 추적·자동 종료(진행자 퇴장 유예·모두 퇴장·최대 길이·연결 끊김)·
// /stop·진행자 변경·전사 큐·재시작 복구·정리. Discord는 `discord` 어댑터로만 만진다(테스트는 가짜를 넣는다).
import { mkdirSync, writeFileSync, readFileSync, readdirSync, appendFileSync, existsSync, rmSync, renameSync } from 'node:fs';
import { join } from 'node:path';
import { Recorder } from './recorder.mjs';
import { CoreError } from './core.mjs';
import { transcribeMeeting } from './transcribe.mjs';
import * as texts from './texts.mjs';

export class HttpErr extends Error {
  constructor(status, detail) { super(detail); this.status = status; this.detail = detail; }
}

const DEBOUNCE_MS = 5000;
const readJsonl = (p) => (existsSync(p) ? readFileSync(p, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)) : []);

export class Meetings {
  constructor({ core, discord, dataDir, siteUrl = '', env = process.env, fetch = globalThis.fetch,
    convert, now = Date.now, minuteMs = 60000, debounceMs = DEBOUNCE_MS, retryDelayMs, log = () => {} }) {
    Object.assign(this, { core, discord, siteUrl, env, fetch, convert, now, minuteMs, debounceMs, retryDelayMs, log });
    this.root = join(dataDir, 'meetings');
    mkdirSync(this.root, { recursive: true });
    this.byGuild = new Map(); // guild_id -> 진행 중인 회의(phase=recording)
    this.queue = Promise.resolve(); // 전사는 한 번에 회의 하나(메모리 상한)
  }

  get count() { return this.byGuild.size; }
  byId(id) { return [...this.byGuild.values()].find((m) => String(m.state.recording_id) === String(id)); }

  view(guildId) {
    const m = this.byGuild.get(String(guildId));
    if (!m) return null;
    const { recording_id, note_id, voice_channel_id, host_discord_user_id, started_at, participants } = m.state;
    return { recording_id, note_id, voice_channel_id, host_discord_user_id, started_at, participants };
  }

  save(state) {
    const dir = join(this.root, String(state.recording_id));
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, 'state.tmp'), JSON.stringify(state, null, 2));
    renameSync(join(dir, 'state.tmp'), join(dir, 'state.json'));
  }

  async start({ guild_id, discord_user_id, project_id = null, team_id = null, title = '' }) {
    guild_id = String(guild_id ?? ''); discord_user_id = String(discord_user_id ?? '');
    if (!guild_id || !discord_user_id) throw new HttpErr(400, texts.badRequest());
    if (this.byGuild.has(guild_id)) throw new HttpErr(409, texts.alreadyRunning());
    const channel = this.discord.voiceChannelOf(guild_id, discord_user_id);
    if (!channel) throw new HttpErr(409, texts.notInVoice());
    const rec = await this.core.startMeeting({ guild_id, discord_user_id, project_id, team_id, title, voice_channel_id: channel })
      .catch((e) => { throw toHttp(e); });
    const state = {
      recording_id: rec.id, note_id: rec.note_id, guild_id, voice_channel_id: channel,
      host_discord_user_id: rec.host?.discord_user_id || discord_user_id,
      started_at: null, ended_at: null, end_reason: '', phase: 'recording', audio_expires_at: null,
      max_minutes: rec.max_minutes ?? 180, leave_grace_s: rec.leave_grace_s ?? 10, prev_nick: null,
      participants: [], noticed: [],
    };
    const m = { state, timers: {}, ending: false, joining: true };
    this.byGuild.set(guild_id, m); // 접속 중 같은 길드 중복 시작을 막는다
    const dir = join(this.root, String(rec.id));
    try {
      m.conn = await this.discord.join(guild_id, channel, { onLost: () => this.end(m, 'failed', '', texts.lost()) });
    } catch (e) {
      this.log('음성 접속 실패', { recording_id: rec.id, error: e.message });
      this.byGuild.delete(guild_id);
      state.phase = 'failed'; state.ended_at = new Date(this.now()).toISOString();
      this.save(state);
      await this.core.patchMeeting(rec.id, { status: 'failed', end_reason: 'failed' })
        .catch((err) => this.log('failed 보고 실패', { error: err.message }));
      throw new HttpErr(502, texts.joinFailed());
    }
    const startedAt = this.now();
    state.started_at = new Date(startedAt).toISOString();
    m.recorder = new Recorder({ receiver: m.conn.receiver, dir, startedAt, now: this.now, log: (x) => this.log(x) });
    state.prev_nick = this.discord.getNick(guild_id);
    await this.discord.setNick(guild_id, texts.NICK_RECORDING).catch(() => {});
    this.send(state, texts.started({ hostId: state.host_discord_user_id, maxMinutes: state.max_minutes, siteUrl: this.siteUrl }));
    for (const p of this.discord.membersIn(guild_id, channel)) {
      if (p.bot) continue;
      state.participants.push({ discord_user_id: p.id, discord_name: p.name, joined_at: state.started_at, left_at: null });
      state.noticed.push(p.id);
    }
    m.joining = false;
    this.save(state);
    await this.flushParticipants(m);
    const max = state.max_minutes * this.minuteMs;
    if (state.max_minutes > 5) m.timers.warn = setTimeout(() => this.send(state, texts.maxWarning({ maxMinutes: state.max_minutes })), max - 5 * this.minuteMs);
    m.timers.max = setTimeout(() => this.end(m, 'max_length'), max);
    return { meeting: this.view(guild_id), recording: rec };
  }

  send(state, text) {
    Promise.resolve().then(() => this.discord.send(state.voice_channel_id, text))
      .catch((e) => this.log('채널 고지 실패', { error: e.message }));
  }

  present(state) { return state.participants.filter((p) => !p.left_at); }

  scheduleParticipants(m) {
    clearTimeout(m.timers.debounce);
    m.timers.debounce = setTimeout(() => this.flushParticipants(m), this.debounceMs);
  }

  async flushParticipants(m) {
    clearTimeout(m.timers.debounce);
    await this.core.patchMeeting(m.state.recording_id, { participants: m.state.participants })
      .catch((e) => this.log('참여자 PATCH 실패', { error: e.message }));
  }

  // gateway가 voiceStateUpdate를 이 모양으로 넘긴다
  onVoiceState({ guildId, userId, name, bot, from, to }) {
    const m = this.byGuild.get(String(guildId));
    if (!m || m.ending || m.joining || bot) return;
    const s = m.state, ch = s.voice_channel_id;
    if (to === ch && from !== ch) {
      let p = s.participants.find((x) => x.discord_user_id === userId);
      if (p) { p.left_at = null; if (name) p.discord_name = name; }
      else s.participants.push((p = { discord_user_id: userId, discord_name: name || userId, joined_at: new Date(this.now()).toISOString(), left_at: null }));
      if (!s.noticed.includes(userId)) { s.noticed.push(userId); this.send(s, texts.joined({ userId })); }
      if (userId === s.host_discord_user_id && m.timers.grace) { clearTimeout(m.timers.grace); m.timers.grace = null; }
      this.save(s); this.scheduleParticipants(m);
    } else if (from === ch && to !== ch) {
      const p = s.participants.find((x) => x.discord_user_id === userId);
      if (p) p.left_at = new Date(this.now()).toISOString();
      this.save(s);
      if (!this.present(s).length) return void this.end(m, 'empty');
      this.scheduleParticipants(m);
      if (userId === s.host_discord_user_id) {
        clearTimeout(m.timers.grace);
        m.timers.grace = setTimeout(() => { m.timers.grace = null; this.end(m, 'host_left', userId).catch(() => {}); }, s.leave_grace_s * 1000);
      }
    }
  }

  async stop(recordingId, discordUserId) {
    const m = this.byId(recordingId);
    if (!m || m.ending || m.joining) throw new HttpErr(404, texts.noMeeting());
    return { recording: await this.end(m, 'command', String(discordUserId ?? '')) };
  }

  setHost(recordingId, discordUserId) {
    const m = this.byId(recordingId);
    if (!m) throw new HttpErr(404, texts.noMeeting());
    m.state.host_discord_user_id = String(discordUserId);
    clearTimeout(m.timers.grace); m.timers.grace = null; // 이전 진행자의 퇴장 유예는 더 보지 않는다
    this.save(m.state);
    return { ok: true };
  }

  /** core PATCH(transcribing) → 성공하면 음성 퇴장·닉네임 복구·종료 고지·전사 큐. command·host_left는 core가 거절하면 계속한다. */
  async end(m, reason, by = '', notice = null) {
    if (m.ending) return null;
    m.ending = true;
    const s = m.state;
    const endedAt = new Date(this.now()).toISOString();
    const participants = s.participants.map((p) => ({ ...p, left_at: p.left_at ?? endedAt }));
    let rec = null;
    try {
      rec = await this.core.patchMeeting(s.recording_id, { status: 'transcribing', end_reason: reason, discord_user_id: by, ended_at: endedAt, participants });
    } catch (e) {
      if (reason === 'command' || reason === 'host_left') {
        m.ending = false;
        this.log('회의 계속', { recording_id: s.recording_id, reason, error: e.message });
        throw toHttp(e);
      }
      this.log('종료 PATCH 실패, 로컬 종료는 진행', { recording_id: s.recording_id, reason, error: e.message });
    }
    for (const t of Object.values(m.timers)) clearTimeout(t);
    m.recorder?.stop();
    try { m.conn?.destroy(); } catch { /* 이미 끊김 */ }
    await this.discord.setNick(s.guild_id, s.prev_nick).catch(() => {});
    if (rec?.channel_notice) this.send(s, rec.channel_notice);
    const minutes = Math.max(0, Math.round((Date.parse(endedAt) - Date.parse(s.started_at)) / 60000));
    this.send(s, notice ?? texts.ended({ minutes, count: participants.length }));
    Object.assign(s, { participants, ended_at: endedAt, end_reason: reason, phase: 'transcribing', audio_expires_at: rec?.audio_expires_at ?? null });
    this.save(s);
    this.byGuild.delete(s.guild_id);
    this.enqueue(s);
    return rec;
  }

  enqueue(state) {
    this.queue = this.queue.then(() => this.transcribe(state)).catch((e) => this.log('전사 작업 오류', { recording_id: state.recording_id, error: e.message }));
    return this.queue;
  }

  idle() { return this.queue; }

  async transcribe(state) {
    const dir = join(this.root, String(state.recording_id));
    const { names = [], stt, glossary } = await this.core.names(state.recording_id);
    const nameMap = Object.fromEntries(names.map((n) => [n.discord_user_id, n.display_name]));
    for (const p of state.participants) nameMap[p.discord_user_id] ??= p.discord_name;
    const cached = new Map(readJsonl(join(dir, 'results.jsonl')).map((r) => [r.seq, r]));
    const minutes = Math.round(((Date.parse(state.ended_at) - Date.parse(state.started_at)) / 60000) * 10) / 10 || 0;
    const out = await transcribeMeeting({
      dir, segments: readJsonl(join(dir, 'segments.jsonl')), names: nameMap, stt, glossary, minutes,
      env: this.env, fetch: this.fetch, ...(this.convert ? { convert: this.convert } : {}), cached,
      ...(this.retryDelayMs != null ? { retryDelayMs: this.retryDelayMs } : {}),
      onResult: (r) => appendFileSync(join(dir, 'results.jsonl'), JSON.stringify(r) + '\n'), log: this.log,
    });
    const body = out.status === 'failed'
      ? { status: 'failed', stats: out.stats, participants: state.participants }
      : { status: 'draft', transcript_md: out.transcript_md, stats: out.stats, participants: state.participants };
    const rec = await this.core.patchMeeting(state.recording_id, body);
    Object.assign(state, { phase: 'done', audio_expires_at: rec.audio_expires_at ?? state.audio_expires_at });
    this.save(state);
    this.log('전사 완료', { recording_id: state.recording_id, status: out.status, ...out.stats, engines: out.stats.engines.length });
  }

  /** 기동 시: recording이던 회의는 재접속 없이 restart로 끝내고, transcribing은 전사를 이어 간다. */
  async recover() {
    for (const st of this.states()) {
      if (st.phase === 'recording') {
        const endedAt = new Date(this.now()).toISOString();
        st.participants = st.participants.map((p) => ({ ...p, left_at: p.left_at ?? endedAt }));
        try {
          const rec = await this.core.patchMeeting(st.recording_id, { status: 'transcribing', end_reason: 'restart', ended_at: endedAt, participants: st.participants });
          st.audio_expires_at = rec.audio_expires_at ?? null;
        } catch (e) {
          this.log('restart PATCH 실패', { recording_id: st.recording_id, error: e.message });
          if (e instanceof CoreError && e.status >= 400 && e.status < 500) { st.phase = 'done'; this.save(st); continue; }
        }
        Object.assign(st, { phase: 'transcribing', ended_at: endedAt, end_reason: 'restart', started_at: st.started_at ?? endedAt });
        this.save(st);
        await this.discord.setNick(st.guild_id, st.prev_nick).catch(() => {});
        this.send(st, texts.restarted());
        this.enqueue(st);
      } else if (st.phase === 'transcribing') this.enqueue(st);
    }
  }

  states() {
    const out = [];
    for (const d of readdirSync(this.root)) {
      try { out.push(JSON.parse(readFileSync(join(this.root, d, 'state.json'), 'utf8'))); } catch { /* 상태 파일 없음 */ }
    }
    return out;
  }

  /** audio_expires_at이 지난 폴더 삭제. 값이 없는 끝난 회의는 ended_at + 7일. */
  cleanup() {
    const now = this.now();
    for (const st of this.states()) {
      if (st.phase === 'recording' || st.phase === 'transcribing') continue;
      const exp = st.audio_expires_at ? Date.parse(st.audio_expires_at) : Date.parse(st.ended_at || 0) + 7 * 86400000;
      if (exp < now) {
        rmSync(join(this.root, String(st.recording_id)), { recursive: true, force: true });
        this.log('오디오 정리', { recording_id: st.recording_id });
      }
    }
  }
}

function toHttp(e) {
  if (e instanceof HttpErr) return e;
  if (e instanceof CoreError) return new HttpErr(e.status === 0 ? 502 : e.status, e.detail);
  return new HttpErr(502, texts.coreDown());
}
