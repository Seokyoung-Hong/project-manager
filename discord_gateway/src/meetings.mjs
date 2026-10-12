// 회의 상태기(IMPL-PLAN-9-parallel §4): 시작·참여자 추적·자동 종료(진행자 퇴장 유예·모두 퇴장·최대 길이·연결 끊김)·
// /stop·진행자 변경·전사 큐·재시작 복구·정리. Discord는 `discord` 어댑터로만 만진다(테스트는 가짜를 넣는다).
import { mkdirSync, writeFileSync, readFileSync, readdirSync, appendFileSync, existsSync, rmSync, renameSync } from 'node:fs';
import { join } from 'node:path';
import { Recorder } from './recorder.mjs';
import { CoreError } from './core.mjs';
import { transcribeMeeting } from './transcribe.mjs';
import { mix, runFfmpeg } from './mix.mjs';
import * as texts from './texts.mjs';

export class HttpErr extends Error {
  constructor(status, detail) { super(detail); this.status = status; this.detail = detail; }
}

const DEBOUNCE_MS = 5000;
const readJsonl = (p) => (existsSync(p) ? readFileSync(p, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)) : []);

export class Meetings {
  constructor({ core, discord, dataDir, siteUrl = '', env = process.env, fetch = globalThis.fetch,
    convert, ffmpeg = runFfmpeg, backoff = (n) => Math.min(60000 * 2 ** (n - 1), 3600000),
    hostBackoff = (n) => Math.min(15000 * 2 ** (n - 1), 300000),
    now = Date.now, minuteMs = 60000, debounceMs = DEBOUNCE_MS, retryDelayMs, log = () => {} }) {
    Object.assign(this, { core, discord, siteUrl, env, fetch, convert, ffmpeg, backoff, hostBackoff, now, minuteMs, debounceMs, retryDelayMs, log });
    this.root = join(dataDir, 'meetings');
    mkdirSync(this.root, { recursive: true });
    this.byGuild = new Map(); // guild_id -> 진행 중인 회의(phase=recording)
    this.queue = Promise.resolve();
  }

  get count() { return this.byGuild.size; }
  byId(id) { return [...this.byGuild.values()].find((m) => m.state && String(m.state.recording_id) === String(id)); }

  view(guildId) {
    const m = this.byGuild.get(String(guildId));
    if (!m?.state) return null; // core 응답 전(시작 중)
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
    // core 호출 전에 길드 자리를 잡는다: 동시에 온 두 번째 시작은 위 409로 돌아간다
    const m = { state: null, timers: {}, graces: new Map(), hostTries: new Map(), deferred: [], ending: false, joining: true };
    this.byGuild.set(guild_id, m);
    let rec;
    try {
      rec = await this.core.startMeeting({ guild_id, discord_user_id, project_id, team_id, title, voice_channel_id: channel });
    } catch (e) {
      this.byGuild.delete(guild_id);
      throw toHttp(e);
    }
    const state = m.state = {
      recording_id: rec.id, note_id: rec.note_id, guild_id, voice_channel_id: channel,
      host_discord_user_id: rec.host?.discord_user_id || discord_user_id,
      started_at: null, ended_at: null, end_reason: '', phase: 'recording', audio_expires_at: null,
      max_minutes: rec.max_minutes ?? 180, leave_grace_s: rec.leave_grace_s ?? 10, prev_nick: null,
      participants: [], noticed: [],
    };
    this.save(state); // 접속 대기 중 재시작돼도 recover()가 이 회의를 마감한다(started_at 없음 → failed)
    const dir = join(this.root, String(rec.id));
    try {
      m.conn = await this.discord.join(guild_id, channel, { onLost: () => this.tryEnd(m, 'failed', '', texts.lost()) });
    } catch (e) {
      this.log('음성 접속 실패', { recording_id: rec.id, error: e.message });
      this.byGuild.delete(guild_id);
      const endedAt = new Date(this.now()).toISOString();
      Object.assign(state, { phase: 'failed', ended_at: endedAt, end_reason: 'failed', end_pending: { status: 'failed', end_reason: 'failed', ended_at: endedAt } });
      this.save(state);
      this.enqueue(state); // core PATCH(failed), 실패하면 재시도 큐(다른 회의 전사를 기다리지 않고 바로 응답)
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
    m.timers.max = setTimeout(() => this.tryEnd(m, 'max_length'), max);
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

  // gateway가 voiceStateUpdate를 이 모양으로 넘긴다. 종료 PATCH를 기다리는 중(ending)에도 참여자 상태는 반영한다
  onVoiceState({ guildId, userId, name, bot, from, to }) {
    const m = this.byGuild.get(String(guildId));
    if (!m || m.joining || bot) return;
    const s = m.state, ch = s.voice_channel_id;
    if (to === ch && from !== ch) {
      let p = s.participants.find((x) => x.discord_user_id === userId);
      if (p) { p.left_at = null; if (name) p.discord_name = name; }
      else s.participants.push((p = { discord_user_id: userId, discord_name: name || userId, joined_at: new Date(this.now()).toISOString(), left_at: null }));
      if (!s.noticed.includes(userId)) { s.noticed.push(userId); this.send(s, texts.joined({ userId })); }
      clearTimeout(m.graces.get(userId)); m.graces.delete(userId); m.hostTries.delete(userId); // 유예·재시도 모두 취소
      this.save(s); this.scheduleParticipants(m);
    } else if (from === ch && to !== ch) {
      const p = s.participants.find((x) => x.discord_user_id === userId);
      if (p) p.left_at = new Date(this.now()).toISOString();
      this.save(s);
      if (!this.present(s).length) return void this.tryEnd(m, 'empty');
      this.scheduleParticipants(m);
      // 누가 진행자인지는 core가 판정한다(Python→Node /host 알림이 빠져도 새 진행자의 퇴장을 놓치지 않게).
      // ponytail: 계정 연결 여부를 몰라 모든 참여자에게 유예를 건다. 진행자가 아닌 사람은 core가 400 → 회의 계속
      clearTimeout(m.graces.get(userId));
      m.graces.set(userId, setTimeout(() => { m.graces.delete(userId); this.tryEnd(m, 'host_left', userId); }, s.leave_grace_s * 1000));
    }
  }

  /** 타이머·이벤트에서 부르는 자동 종료. 다른 종료 PATCH를 기다리는 중이면 미뤄 두고, 그 PATCH가 거절되면 다시 판단한다. */
  tryEnd(m, reason, by = '', notice = null) {
    if (m.ending) { m.deferred.push({ reason, by, notice }); return; }
    this.end(m, reason, by, notice).catch(() => {}); // command·host_left 거절은 end()가 로그·재판단한다
  }

  // 종료가 거절·실패된 뒤: 그 시점의 실제 채널 상태로 다시 판단한다
  reevaluate(m) {
    if (m.ending || !this.byGuild.has(m.state.guild_id)) return;
    if (!this.present(m.state).length) { m.deferred = []; return void this.tryEnd(m, 'empty'); }
    while (m.deferred.length) {
      const d = m.deferred.shift();
      if (d.reason === 'empty') continue; // 사람이 남아 있다
      if (d.reason === 'host_left' && !m.state.participants.find((p) => p.discord_user_id === d.by)?.left_at) continue; // 돌아왔다
      return void this.tryEnd(m, d.reason, d.by, d.notice); // 이것도 거절되면 남은 것으로 다시 reevaluate
    }
  }

  // 사람이 돌아오면 onVoiceState가 이 타이머를 지운다. 보낼 때도 아직 없을 때만 보낸다
  retryHostLeft(m, userId) {
    const n = (m.hostTries.get(userId) ?? 0) + 1;
    m.hostTries.set(userId, n);
    const ms = this.hostBackoff(n);
    this.log('진행자 퇴장 판정 재시도 예약', { recording_id: m.state.recording_id, tries: n, in_ms: ms });
    clearTimeout(m.graces.get(userId));
    m.graces.set(userId, setTimeout(() => {
      m.graces.delete(userId);
      if (m.state.participants.find((p) => p.discord_user_id === userId)?.left_at) this.tryEnd(m, 'host_left', userId);
    }, ms));
  }

  async stop(recordingId, discordUserId) {
    const m = this.byId(recordingId);
    if (!m || m.ending || m.joining) throw new HttpErr(404, texts.noMeeting());
    return { recording: await this.end(m, 'command', String(discordUserId ?? '')) };
  }

  // Python의 /host 알림. 최적화일 뿐이다(퇴장 판정은 core가 한다) — 화면용 진행자만 바꾼다
  setHost(recordingId, discordUserId) {
    const m = this.byId(recordingId);
    if (!m) throw new HttpErr(404, texts.noMeeting());
    m.state.host_discord_user_id = String(discordUserId);
    this.save(m.state);
    return { ok: true };
  }

  /** core PATCH(transcribing) → 음성 퇴장·닉네임 복구·종료 고지·후처리 큐. command·host_left는 core가 거절하면 계속한다.
   * 자동 종료(empty·max_length·failed)의 PATCH가 실패하면 end_pending으로 남겨 후처리 큐가 재시도한다(recording으로 남지 않게). */
  async end(m, reason, by = '', notice = null) {
    if (m.ending) return null;
    m.ending = true;
    const s = m.state;
    const endedAt = new Date(this.now()).toISOString();
    const participants = s.participants.map((p) => ({ ...p, left_at: p.left_at ?? endedAt }));
    const body = { status: 'transcribing', end_reason: reason, discord_user_id: by, ended_at: endedAt, participants };
    let rec = null;
    try {
      rec = await this.core.patchMeeting(s.recording_id, body);
    } catch (e) {
      if (reason === 'command' || reason === 'host_left') {
        m.ending = false;
        this.log('회의 계속', { recording_id: s.recording_id, reason, error: e.message });
        // 진행자 퇴장 판정을 core가 못 받았으면(5xx·연결 실패) 백오프로 같은 판정을 다시 보낸다. 4xx(진행자 아님)만 계속
        if (reason === 'host_left' && retryable(e)) this.retryHostLeft(m, by);
        queueMicrotask(() => this.reevaluate(m)); // 기다리는 동안 들어온 퇴장·최대 길이
        throw toHttp(e);
      }
      this.log('종료 PATCH 실패, 재시도 큐에 넣음', { recording_id: s.recording_id, reason, error: e.message });
      s.end_pending = body;
    }
    for (const t of [...Object.values(m.timers), ...m.graces.values()]) clearTimeout(t);
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

  dir(state) { return join(this.root, String(state.recording_id)); }

  // 후처리는 한 번에 회의 하나(메모리 상한): 종료 PATCH 재시도 → 녹음 파일 올리기 → 전사 → draft PATCH → 로컬 오디오 삭제
  enqueue(state) {
    this.queue = this.queue.then(() => this.process(state)).catch((e) => this.log('후처리 오류', { recording_id: state.recording_id, error: e.message }));
    return this.queue;
  }

  idle() { return this.queue; }

  async process(st) {
    if (!existsSync(join(this.dir(st), 'state.json'))) return; // 7일 정리로 이미 지워짐
    if (st.end_pending) {
      try {
        const rec = await this.core.patchMeeting(st.recording_id, st.end_pending);
        st.audio_expires_at = rec.audio_expires_at ?? st.audio_expires_at;
      } catch (e) {
        if (retryable(e)) return this.retry(st, '종료 PATCH', e);
        this.log('종료 PATCH 거절, 넘어감', { recording_id: st.recording_id, error: e.message });
      }
      delete st.end_pending;
      this.save(st);
    }
    const uploaded = st.uploaded || (await this.upload(st)); // 올리기가 실패해도 전사·PATCH는 진행
    if (st.phase === 'transcribing') {
      try {
        await this.transcribe(st);
      } catch (e) {
        if (retryable(e)) return this.retry(st, '전사·회의록 PATCH', e);
        this.log('회의록 PATCH 거절, 넘어감', { recording_id: st.recording_id, error: e.message });
        st.phase = 'done';
        this.save(st);
      }
    }
    if (!uploaded) return this.retry(st, '녹음 파일 올리기');
    rmSync(join(this.dir(st), 'seg'), { recursive: true, force: true });
    rmSync(join(this.dir(st), 'meeting.ogg'), { force: true });
    st.retries = 0;
    this.save(st);
  }

  retry(st, what, e) {
    st.retries = (st.retries ?? 0) + 1;
    this.save(st);
    const ms = this.backoff(st.retries);
    this.log('후처리 재시도 예약', { recording_id: st.recording_id, what, retries: st.retries, in_ms: ms, error: e?.message });
    setTimeout(() => this.enqueue(st), ms).unref?.();
  }

  /** 구간들을 회의 시작 기준으로 섞어 meeting.ogg를 만들고 core에 올린다. 성공 여부를 돌려준다. */
  async upload(st) {
    const dir = this.dir(st);
    const segs = readJsonl(join(dir, 'segments.jsonl'))
      .filter((g) => g.packets > 0 && existsSync(join(dir, g.file)))
      .sort((a, b) => a.start_ms - b.start_ms);
    try {
      if (segs.length) {
        const out = join(dir, 'meeting.ogg');
        if (!existsSync(out)) await mix(segs.map((g) => ({ path: join(dir, g.file), delay_ms: g.start_ms })), out, { run: this.ffmpeg });
        await this.core.uploadAudio(st.recording_id, out);
        this.log('녹음 파일 올림', { recording_id: st.recording_id, segments: segs.length });
      }
      st.uploaded = true; // 말한 구간이 없으면 올릴 것도 없다
      this.save(st);
      return true;
    } catch (e) {
      this.log('녹음 파일 올리기 실패', { recording_id: st.recording_id, error: e.message });
      return false;
    }
  }

  async transcribe(state) {
    const dir = this.dir(state);
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
    const rec = await this.core.patchMeeting(state.recording_id,
      { status: 'draft', transcript_md: out.transcript_md, stats: out.stats, participants: state.participants });
    Object.assign(state, { phase: 'done', audio_expires_at: rec.audio_expires_at ?? state.audio_expires_at });
    this.save(state);
    this.log('전사 완료', { recording_id: state.recording_id, status: out.status, engine: out.stats.engine, segments: out.stats.segments, failed: out.stats.failed });
  }

  /** 기동 시: recording이던 회의는 재접속 없이 restart로 끝내고(종료 PATCH는 후처리 큐가 재시도까지 맡는다),
   * 남은 후처리(종료 PATCH·올리기·전사)를 이어 간다. */
  async recover() {
    for (const st of this.states()) {
      if (st.phase === 'recording' && !st.started_at) {
        // 음성 접속 대기 중에 멈춤: 녹음 구간이 없으니 failed로 마감(core에 recording이 남아 다음 시작을 막지 않게)
        const endedAt = new Date(this.now()).toISOString();
        Object.assign(st, { phase: 'failed', ended_at: endedAt, end_reason: 'failed', end_pending: { status: 'failed', end_reason: 'failed', ended_at: endedAt } });
        this.save(st);
        this.enqueue(st);
      } else if (st.phase === 'recording') {
        const endedAt = new Date(this.now()).toISOString();
        st.participants = st.participants.map((p) => ({ ...p, left_at: p.left_at ?? endedAt }));
        Object.assign(st, { phase: 'transcribing', ended_at: endedAt, end_reason: 'restart',
          end_pending: { status: 'transcribing', end_reason: 'restart', ended_at: endedAt, participants: st.participants } });
        this.save(st);
        await this.discord.setNick(st.guild_id, st.prev_nick).catch(() => {});
        this.send(st, texts.restarted());
        this.enqueue(st);
      } else if (st.phase === 'transcribing' || st.end_pending || (st.phase === 'done' && !st.uploaded)) this.enqueue(st);
    }
  }

  states() {
    const out = [];
    for (const d of readdirSync(this.root)) {
      try { out.push(JSON.parse(readFileSync(join(this.root, d, 'state.json'), 'utf8'))); } catch { /* 상태 파일 없음 */ }
    }
    return out;
  }

  /** 안전망: audio_expires_at이 지난 폴더 삭제(올리기·전사가 끝내 안 된 것 포함). 값이 없으면 ended_at + 7일. */
  cleanup() {
    const now = this.now();
    for (const st of this.states()) {
      if (st.phase === 'recording') continue;
      const exp = st.audio_expires_at ? Date.parse(st.audio_expires_at) : Date.parse(st.ended_at || 0) + 7 * 86400000;
      if (exp < now) {
        rmSync(join(this.root, String(st.recording_id)), { recursive: true, force: true });
        this.log('오디오 정리', { recording_id: st.recording_id });
      }
    }
  }
}

const retryable = (e) => !(e instanceof CoreError) || e.status === 0 || e.status === 429 || e.status >= 500;

function toHttp(e) {
  if (e instanceof HttpErr) return e;
  if (e instanceof CoreError) return new HttpErr(e.status === 0 ? 502 : e.status, e.detail);
  return new HttpErr(502, texts.coreDown());
}
