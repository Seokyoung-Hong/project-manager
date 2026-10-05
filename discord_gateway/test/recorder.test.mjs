// 실제 Discord 없이 가짜 receiver(speaking 이벤트 + 구독 스트림)로 구간 분할·메타·리포트를 확인한다.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { Readable } from 'node:stream';
import { mkdtempSync, readFileSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { EndBehaviorType } from '@discordjs/voice';
import { Recorder, buildReport, SILENCE_MS } from '../src/recorder.mjs';
import { oggCrc } from '../src/ogg.mjs';

const OPUS_SILENCE = Buffer.from([0xf8, 0xff, 0xfe]); // 20ms 무음 Opus 프레임

function fakeReceiver() {
  const subs = new Map();
  const options = [];
  return {
    speaking: new EventEmitter(),
    subs, options,
    subscribe(userId, opts) {
      options.push(opts);
      const s = new Readable({ objectMode: true, read() {} });
      s.once('close', () => subs.delete(userId));
      subs.set(userId, s);
      return s;
    },
  };
}
const tick = () => new Promise((r) => setImmediate(r));
const rtpPacket = (ssrc, seq) => {
  const b = Buffer.alloc(16);
  b[0] = 0x80; b[1] = 0x78; b.writeUInt16BE(seq, 2); b.writeUInt32BE(ssrc, 8);
  return b;
};

test('speaking 시작마다 구간 하나, 같은 사용자가 말하는 중이면 새 구간을 열지 않는다', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'poc-'));
  let clock = 1000;
  const rx = fakeReceiver();
  const rec = new Recorder({ receiver: rx, dir, startedAt: 1000, now: () => clock });

  clock = 3500;
  rx.speaking.emit('start', 'u1');
  rx.speaking.emit('start', 'u1'); // 100ms 끊김 뒤 다시 start — 같은 구간
  assert.equal(rx.options.length, 1);
  assert.deepEqual(rx.options[0].end, { behavior: EndBehaviorType.AfterSilence, duration: 2000 });
  assert.equal(SILENCE_MS, 2000);
  for (let i = 0; i < 100; i++) rx.subs.get('u1').push(OPUS_SILENCE);
  clock = 4000;
  rx.speaking.emit('start', 'u2');
  for (let i = 0; i < 10; i++) rx.subs.get('u2').push(OPUS_SILENCE);
  rx.subs.get('u1').push(null); // 침묵 2초 → 라이브러리가 스트림을 닫는다
  await tick();
  clock = 9000;
  rx.speaking.emit('start', 'u1'); // 침묵 뒤 다시 말함 → 새 구간
  rx.subs.get('u1').push(OPUS_SILENCE);
  rx.subs.get('u2').destroy(new Error('Failed to parse packet')); // 수신 오류도 구간을 닫는다
  await tick();
  rec.stop();
  await tick();

  assert.equal(rec.segments.length, 3);
  const lines = readFileSync(join(dir, 'segments.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  assert.deepEqual(lines.map((s) => [s.seq, s.user_id, s.start_ms, s.packets, s.duration_ms]), [
    [1, 'u1', 2500, 100, 2000],
    [2, 'u2', 3000, 10, 200],
    [3, 'u1', 8000, 1, 20],
  ]);
  assert.equal(lines[1].error, 'Failed to parse packet');
  assert.equal(lines[0].file, 'seg/00001-u1-2500.ogg');
  assert.equal(lines[0].started_at, new Date(3500).toISOString());
  assert.ok(statSync(join(dir, lines[0].file)).size > 100 * 3);
  assert.equal(rec.active.size, 0);
});

test('RTP sequence 간격으로 손실을 세고 리포트가 사용자별로 합친다', () => {
  const dir = mkdtempSync(join(tmpdir(), 'poc-'));
  const rx = fakeReceiver();
  const rec = new Recorder({ receiver: rx, dir });
  for (const seq of [65534, 65535, 0, 3, 4, 2]) rec.onRtp(rtpPacket(11, seq), 'u1'); // 1,2 손실, 2는 늦게 도착(손실로 안 셈)
  for (const seq of [10, 11, 12]) rec.onRtp(rtpPacket(22, seq), 'u2');
  assert.deepEqual(rec.counts, { segments: 0, active: 0, rtp_received: 9, rtp_lost: 2 });

  const report = buildReport({
    segments: [
      { user_id: 'u1', duration_ms: 1000, packets: 50 },
      { user_id: 'u1', duration_ms: 500, packets: 25, error: 'x' },
      { user_id: 'u2', duration_ms: 60, packets: 3 },
    ],
    rtp: rec.rtp, startedAt: 0, endedAt: 30 * 60000,
    extra: { dave: { transitions: 4 } },
  });
  assert.equal(report.minutes, 30);
  assert.equal(report.segments, 3);
  assert.deepEqual(report.users.u1, { segments: 2, duration_ms: 1500, packets: 75, rtp_received: 6, rtp_lost: 2, errors: 1, loss_pct: 25 });
  assert.equal(report.users.u2.loss_pct, 0);
  assert.equal(report.dave.transitions, 4);
});

test('Ogg 파일: 페이지 CRC가 맞고 ffprobe가 Opus로 읽는다', async (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'poc-'));
  const rx = fakeReceiver();
  const rec = new Recorder({ receiver: rx, dir });
  rx.speaking.emit('start', 'u1');
  for (let i = 0; i < 150; i++) rx.subs.get('u1').push(i % 7 ? OPUS_SILENCE : Buffer.alloc(600, i)); // 255바이트 넘는 패킷 포함
  rx.subs.get('u1').push(null);
  await tick();
  const buf = readFileSync(join(dir, rec.segments[0].file));
  let off = 0, pages = 0, granule = 0n, flags = 0;
  while (off < buf.length) {
    assert.equal(buf.toString('ascii', off, off + 4), 'OggS');
    const nseg = buf[off + 26];
    let len = 27 + nseg;
    for (let i = 0; i < nseg; i++) len += buf[off + 27 + i];
    const page = Buffer.from(buf.subarray(off, off + len));
    const crc = page.readUInt32LE(22);
    page.writeUInt32LE(0, 22);
    assert.equal(oggCrc(page), crc, `page ${pages} crc`);
    granule = page.readBigUInt64LE(6);
    flags = page[5];
    if (pages === 0) assert.equal(flags, 0x02);
    off += len; pages++;
  }
  assert.equal(granule, 150n * 960n);
  assert.equal(flags, 0x04); // 마지막 페이지 EOS

  let probe;
  try { probe = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_name,channels:format=duration', '-of', 'json', join(dir, rec.segments[0].file)], { encoding: 'utf8' }); }
  catch (e) { if (e.code === 'ENOENT') return t.skip('ffprobe 없음'); throw e; }
  const info = JSON.parse(probe);
  assert.equal(info.streams[0].codec_name, 'opus');
  assert.equal(info.streams[0].channels, 2);
  assert.ok(Math.abs(Number(info.format.duration) - 3) < 0.05, info.format.duration);

  // 유효한 Opus 프레임만 담은 구간은 ffmpeg가 끝까지 디코딩한다(= 재생 가능)
  rx.speaking.emit('start', 'u2');
  for (let i = 0; i < 100; i++) rx.subs.get('u2').push(OPUS_SILENCE);
  rx.subs.get('u2').push(null);
  await tick();
  const err = execFileSync('ffmpeg', ['-v', 'error', '-xerror', '-i', join(dir, rec.segments[1].file), '-f', 'null', '-'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  assert.equal(err, '');
});
