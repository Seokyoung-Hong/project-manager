// M0 PoC 진입점: 지정 음성 채널에 들어가 참여자별 발화 구간을 Ogg로 저장하고 지표를 남긴다.
// 사용: DISCORD_BOT_TOKEN=... node poc.mjs --guild <id> --channel <id> [--minutes 30] [--out /data/poc]
import { parseArgs } from 'node:util';
import { mkdirSync, appendFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { Client, GatewayIntentBits, Options, Events } from 'discord.js';
import { joinVoiceChannel, entersState, VoiceConnectionStatus } from '@discordjs/voice';
import { Recorder, buildReport } from './src/recorder.mjs';

const { values: args } = parseArgs({
  options: {
    guild: { type: 'string', default: process.env.POC_GUILD_ID || process.env.DISCORD_GUILD_ID },
    channel: { type: 'string', default: process.env.POC_CHANNEL_ID },
    minutes: { type: 'string', default: process.env.POC_MINUTES ?? '30' },
    out: { type: 'string', default: process.env.POC_OUT ?? './poc-out' },
    'metrics-sec': { type: 'string', default: '60' },
  },
});
const token = process.env.DISCORD_BOT_TOKEN;
if (!token || !args.guild || !args.channel) {
  console.error('DISCORD_BOT_TOKEN 환경변수와 --guild, --channel이 필요합니다.');
  process.exit(2);
}

const startedAt = Date.now();
const dir = join(args.out, new Date(startedAt).toISOString().replace(/[:.]/g, '-'));
mkdirSync(dir, { recursive: true });
const log = (msg, data) => {
  const line = JSON.stringify({ t: new Date().toISOString(), msg, ...data });
  console.log(line);
  appendFileSync(join(dir, 'poc.log'), line + '\n');
};

const dave = { transitions: 0, decrypt_failures: 0, protocol_version: null, privacy_code: null };
const voiceEvents = { join: 0, leave: 0, move: 0 };
let maxRssMb = 0;
let recorder;
let connection;

const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates],
  // 메시지·프레즌스는 쓰지 않는다(M1과 같은 메모리 조건)
  makeCache: Options.cacheWithLimits({ MessageManager: 0, PresenceManager: 0, ReactionManager: 0 }),
});

client.on(Events.VoiceStateUpdate, (before, after) => {
  if (after.guild.id !== args.guild || before.channelId === after.channelId) return;
  const kind = !before.channelId ? 'join' : !after.channelId ? 'leave' : 'move';
  voiceEvents[kind]++;
  const ev = { t: new Date().toISOString(), kind, user_id: after.id, from: before.channelId, to: after.channelId,
    bot: after.id === client.user.id };
  appendFileSync(join(dir, 'events.jsonl'), JSON.stringify(ev) + '\n');
  log('voiceStateUpdate', ev);
});

client.once(Events.ClientReady, async () => {
  log('ready', { user: client.user.tag, guild: args.guild, channel: args.channel, minutes: Number(args.minutes) });
  const guild = await client.guilds.fetch(args.guild);
  connection = joinVoiceChannel({
    guildId: args.guild, channelId: args.channel, adapterCreator: guild.voiceAdapterCreator,
    selfDeaf: false, selfMute: true, debug: true,
  });
  recorder = new Recorder({ receiver: connection.receiver, dir, startedAt, log: (m) => log(m) });
  // 수신 경로 앞에 RTP sequence 집계를 끼운다. UDP 소켓이 붙기 전(지금)에 바꿔야 새 함수가 등록된다.
  const receiver = connection.receiver;
  const original = receiver.onUdpMessage;
  receiver.onUdpMessage = (msg) => {
    if (msg.length > 12) recorder.onRtp(msg, receiver.ssrcMap.get(msg.readUInt32BE(8))?.userId);
    original(msg);
  };
  connection.on('debug', (m) => {
    if (m.includes('Failed to decrypt')) { dave.decrypt_failures++; return; } // 패킷마다 나오므로 세기만
    // [DAVE] 줄만 남긴다. WS 원문(Identify·Session Description)에는 음성 토큰·secret_key가 있어 쓰지 않는다
    if (m.includes('[DAVE]')) log('dave', { m });
  });
  connection.on('transitioned', (id) => {
    dave.transitions++;
    const d = connection.state.networking?.state?.dave;
    dave.protocol_version = d?.protocolVersion ?? null;
    dave.privacy_code = connection.voicePrivacyCode ?? null;
    log('dave transitioned', { transition_id: id, protocol_version: dave.protocol_version, privacy_code: dave.privacy_code });
  });
  connection.on('stateChange', (a, b) => log('voice state', { from: a.status, to: b.status }));
  connection.on('error', (e) => log('voice error', { error: e.message }));
  connection.on(VoiceConnectionStatus.Disconnected, async () => {
    try {
      // 채널 이동·서버 이동이면 곧 다시 연결 중으로 바뀐다
      await Promise.race([
        entersState(connection, VoiceConnectionStatus.Signalling, 5000),
        entersState(connection, VoiceConnectionStatus.Connecting, 5000),
      ]);
    } catch {
      log('disconnected, 재접속 실패로 종료합니다');
      shutdown('disconnected');
    }
  });
  try {
    await entersState(connection, VoiceConnectionStatus.Ready, 30000);
    log('voice ready', { privacy_code: connection.voicePrivacyCode ?? null });
  } catch (e) {
    log('voice 접속 실패', { error: e.message });
    return shutdown('join-failed');
  }
  setTimeout(() => shutdown('time'), Number(args.minutes) * 60000);
});

const metrics = setInterval(() => {
  const m = process.memoryUsage();
  const rss = Math.round(m.rss / 1048576);
  maxRssMb = Math.max(maxRssMb, rss);
  log('metrics', { rss_mb: rss, heap_mb: Math.round(m.heapUsed / 1048576), max_rss_mb: maxRssMb,
    ...recorder?.counts, dave_transitions: dave.transitions, decrypt_failures: dave.decrypt_failures, voice_events: voiceEvents });
}, Number(args['metrics-sec']) * 1000);

let stopping = false;
function shutdown(reason) {
  if (stopping) return;
  stopping = true;
  clearInterval(metrics);
  recorder?.stop();
  connection?.destroy();
  const endedAt = Date.now();
  maxRssMb = Math.max(maxRssMb, Math.round(process.memoryUsage().rss / 1048576));
  const report = buildReport({
    segments: recorder?.segments ?? [], rtp: recorder?.rtp ?? new Map(), startedAt, endedAt,
    extra: { end_reason: reason, max_rss_mb: maxRssMb, voice_events: voiceEvents, dave },
  });
  writeFileSync(join(dir, 'report.json'), JSON.stringify(report, null, 2));
  log('report', report);
  client.destroy().finally(() => process.exit(0));
}
process.on('SIGINT', () => shutdown('signal'));
process.on('SIGTERM', () => shutdown('signal'));
process.on('unhandledRejection', (e) => { log('처리되지 않은 오류', { error: String(e?.message ?? e) }); shutdown('error'); });

client.login(token).catch((e) => { log('login 실패', { error: e.message }); shutdown('login-failed'); });
