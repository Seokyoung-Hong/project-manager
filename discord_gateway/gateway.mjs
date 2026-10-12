// discord-voice 진입점(IMPL-PLAN-9-parallel §1): 같은 봇 토큰의 두 번째 게이트웨이 세션.
// 음성 상태·녹음·전사만 한다. interactionCreate를 듣지 않고 명령도 등록하지 않는다(슬래시·버튼은 Python discord-bot).
import { Client, GatewayIntentBits, Options, Events } from 'discord.js';
import { joinVoiceChannel, entersState, VoiceConnectionStatus } from '@discordjs/voice';
import { createCore } from './src/core.mjs';
import { Meetings } from './src/meetings.mjs';
import { createControl } from './src/control.mjs';

const env = process.env;
// 토큰·secret·음성 WS 원문은 로그에 쓰지 않는다
const log = (msg, data) => console.log(JSON.stringify({ t: new Date().toISOString(), msg, ...data }));
for (const k of ['DISCORD_BOT_TOKEN', 'CORE_TOKEN']) {
  if (!env[k]) { console.error(`${k} 환경변수가 필요합니다.`); process.exit(2); }
}
if (!env.VOICE_CONTROL_SECRET) log('경고: VOICE_CONTROL_SECRET이 없어 내부 HTTP 요청을 모두 거절합니다');

const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates],
  makeCache: Options.cacheWithLimits({ MessageManager: 0, PresenceManager: 0, ReactionManager: 0 }),
});

const guild = (id) => client.guilds.cache.get(String(id));
const discord = {
  voiceChannelOf: (g, u) => guild(g)?.voiceStates.cache.get(String(u))?.channelId ?? null,
  membersIn: (g, ch) => [...(guild(g)?.voiceStates.cache.values() ?? [])]
    .filter((vs) => vs.channelId === ch)
    .map((vs) => ({ id: vs.id, name: vs.member?.displayName ?? vs.id, bot: vs.id === client.user.id || !!vs.member?.user.bot })),
  getNick: (g) => guild(g)?.members.me?.nickname ?? null,
  setNick: async (g, nick) => { await (guild(g)?.members.me ?? await guild(g)?.members.fetchMe())?.setNickname(nick); },
  send: async (ch, content) => {
    const c = await client.channels.fetch(ch);
    await c.send({ content, allowedMentions: { parse: ['users'] } });
  },
  async join(g, ch, { onLost }) {
    const conn = joinVoiceChannel({
      guildId: g, channelId: ch, adapterCreator: guild(g).voiceAdapterCreator, selfDeaf: false, selfMute: true,
    });
    let closing = false;
    conn.on('error', (e) => log('음성 오류', { guild_id: g, error: e.message }));
    conn.on(VoiceConnectionStatus.Disconnected, async () => {
      try {
        await Promise.race([
          entersState(conn, VoiceConnectionStatus.Signalling, 5000),
          entersState(conn, VoiceConnectionStatus.Connecting, 5000),
        ]);
      } catch {
        if (closing) return;
        log('음성 연결 끊김, 재접속 실패', { guild_id: g });
        onLost();
      }
    });
    try {
      await entersState(conn, VoiceConnectionStatus.Ready, 30000);
    } catch (e) {
      closing = true;
      conn.destroy();
      throw e;
    }
    return { receiver: conn.receiver, destroy: () => { closing = true; conn.destroy(); } };
  },
};

const core = createCore({ url: env.CORE_URL || 'http://web:8000', token: env.CORE_TOKEN });
const meetings = new Meetings({ core, discord, dataDir: env.VOICE_DATA || '/data', siteUrl: env.SITE_URL || '', log });

client.on(Events.VoiceStateUpdate, (before, after) => {
  if (before.channelId === after.channelId) return;
  meetings.onVoiceState({
    guildId: after.guild.id, userId: after.id, name: after.member?.displayName ?? '',
    bot: after.id === client.user?.id || !!after.member?.user.bot, from: before.channelId, to: after.channelId,
  });
});

client.once(Events.ClientReady, () => {
  log('ready', { user: client.user.tag, guilds: client.guilds.cache.size });
  meetings.recover().catch((e) => log('재시작 복구 오류', { error: e.message }));
});

const port = Number(env.VOICE_CONTROL_PORT || 8082);
createControl({ meetings, discord, secret: env.VOICE_CONTROL_SECRET, isReady: () => client.isReady(), log })
  .listen(port, () => log('control listen', { port }));

setInterval(() => { try { meetings.cleanup(); } catch (e) { log('정리 오류', { error: e.message }); } }, 3600000).unref();
// 다시 전사 대기열(core). 후처리 큐가 빌 때만 가져간다
setInterval(() => { meetings.pollJobs(); }, 20000).unref();

let stopping = false;
function shutdown() {
  if (stopping) return;
  stopping = true;
  for (const m of meetings.byGuild.values()) m.recorder?.stop(); // 열린 구간을 segments.jsonl에 마감
  // 녹음 중이던 회의는 state.json(phase=recording)으로 남겨 다음 기동의 recover()가 restart로 마감한다
  client.destroy().finally(() => process.exit(0));
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
process.on('unhandledRejection', (e) => log('처리되지 않은 오류', { error: String(e?.message ?? e) }));

client.login(env.DISCORD_BOT_TOKEN).catch((e) => { log('login 실패', { error: e.message }); process.exit(1); });
