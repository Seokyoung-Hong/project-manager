// 참여자별 발화 구간 녹음: speaking 시작마다 구독을 열고, 침묵 2초면 라이브러리가 스트림을 닫는다.
// 구간 하나 = Ogg 파일 하나 + segments.jsonl 한 줄. Opus는 디코딩하지 않는다.
import { mkdirSync, appendFileSync } from 'node:fs';
import { join } from 'node:path';
import { EndBehaviorType } from '@discordjs/voice';
import { OggOpusWriter } from './ogg.mjs';

export const SILENCE_MS = 2000;

export class Recorder {
  constructor({ receiver, dir, startedAt = Date.now(), now = Date.now, log = () => {} }) {
    this.receiver = receiver;
    this.dir = dir;
    this.startedAt = startedAt;
    this.now = now;
    this.log = log;
    this.seq = 0;
    this.active = new Map(); // userId -> { stream, finish }
    this.segments = []; // 끝난 구간 메타
    this.rtp = new Map(); // ssrc -> { userId, last, received, lost }
    mkdirSync(join(dir, 'seg'), { recursive: true });
    this.onStart = (userId) => this.open(userId);
    receiver.speaking.on('start', this.onStart);
  }

  open(userId) {
    if (this.active.has(userId)) return;
    const seq = ++this.seq;
    const startMs = this.now() - this.startedAt;
    const file = `seg/${String(seq).padStart(5, '0')}-${userId}-${startMs}.ogg`;
    const writer = new OggOpusWriter(join(this.dir, file));
    const stream = this.receiver.subscribe(userId, {
      end: { behavior: EndBehaviorType.AfterSilence, duration: SILENCE_MS },
    });
    let done = false;
    const finish = (error) => {
      if (done) return;
      done = true;
      writer.end();
      this.active.delete(userId);
      const meta = {
        seq, user_id: userId, start_ms: startMs, started_at: new Date(this.startedAt + startMs).toISOString(),
        duration_ms: writer.durationMs, packets: writer.packets, file,
        ...(error ? { error: String(error.message ?? error) } : {}),
      };
      this.segments.push(meta);
      appendFileSync(join(this.dir, 'segments.jsonl'), JSON.stringify(meta) + '\n');
    };
    stream.on('data', (packet) => writer.write(packet));
    stream.once('end', () => finish());
    stream.once('close', () => finish());
    stream.once('error', (e) => { this.log(`구간 ${seq} 스트림 오류: ${e.message}`); finish(e); });
    this.active.set(userId, { stream, finish });
  }

  // RTP 헤더의 sequence로 사용자별 손실을 센다(복호화 전, 수신 경로 앞에서 부른다).
  onRtp(msg, userId) {
    if (msg.length < 12) return;
    const ssrc = msg.readUInt32BE(8);
    const seq = msg.readUInt16BE(2);
    let s = this.rtp.get(ssrc);
    if (!s) this.rtp.set(ssrc, (s = { userId, last: seq, received: 0, lost: 0 }));
    else {
      const gap = (seq - s.last - 1) & 0xffff;
      // 순서 뒤바뀜·재전송(gap이 매우 큼)은 손실로 세지 않는다
      if (gap > 0 && gap < 1000) s.lost += gap;
      if (gap < 1000) s.last = seq;
    }
    s.received++;
  }

  stop() {
    this.receiver.speaking.off('start', this.onStart);
    for (const { stream, finish } of [...this.active.values()]) {
      finish();
      stream.destroy();
    }
  }

  get counts() {
    let received = 0, lost = 0;
    for (const s of this.rtp.values()) { received += s.received; lost += s.lost; }
    return { segments: this.segments.length, active: this.active.size, rtp_received: received, rtp_lost: lost };
  }
}

// 종료 리포트: 사용자별 구간 수·총 길이·패킷 손실, 그리고 DAVE·메모리 지표.
export function buildReport({ segments, rtp, startedAt, endedAt, extra = {} }) {
  const users = {};
  const user = (id) => (users[id] ??= { segments: 0, duration_ms: 0, packets: 0, rtp_received: 0, rtp_lost: 0, errors: 0 });
  for (const s of segments) {
    const u = user(s.user_id);
    u.segments++;
    u.duration_ms += s.duration_ms;
    u.packets += s.packets;
    if (s.error) u.errors++;
  }
  for (const r of rtp.values()) {
    if (!r.userId) continue;
    const u = user(r.userId);
    u.rtp_received += r.received;
    u.rtp_lost += r.lost;
  }
  for (const u of Object.values(users)) {
    const total = u.rtp_received + u.rtp_lost;
    u.loss_pct = total ? Math.round((u.rtp_lost / total) * 10000) / 100 : 0;
  }
  return {
    started_at: new Date(startedAt).toISOString(),
    ended_at: new Date(endedAt).toISOString(),
    minutes: Math.round(((endedAt - startedAt) / 60000) * 10) / 10,
    segments: segments.length,
    users,
    ...extra,
  };
}
