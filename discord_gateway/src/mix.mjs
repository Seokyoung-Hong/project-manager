// 구간 Ogg들을 회의 시작 기준 시각에 맞춰 하나의 혼합 파일(meeting.ogg, Opus 모노 32kbps)로 만든다(parallel §7).
// mem_limit 256MB 안에서 돌도록 입력이 BATCH개를 넘으면 묶음마다 중간 트랙을 만들고 다시 섞는다.
import { execFile } from 'node:child_process';
import { renameSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';

export const BATCH = 40;

export const runFfmpeg = (args) => new Promise((resolve, reject) =>
  execFile('ffmpeg', args, { maxBuffer: 1 << 20 }, (e) => (e ? reject(e) : resolve())));

function argsFor(inputs, out, bitrate) {
  const args = ['-v', 'error', '-y'];
  for (const i of inputs) args.push('-i', i.path);
  const chains = inputs.map((i, n) => `[${n}:a]adelay=${Math.max(0, Math.round(i.delay_ms))}:all=1[a${n}]`);
  const labels = inputs.map((_, n) => `[a${n}]`).join('');
  const filter = `${chains.join(';')};${labels}amix=inputs=${inputs.length}:duration=longest:dropout_transition=0:normalize=0[m]`;
  return [...args, '-filter_complex', filter, '-map', '[m]', '-ac', '1', '-c:a', 'libopus', '-b:a', bitrate, '-f', 'ogg', out];
}

/** inputs: [{path, delay_ms}]. 결과를 out에 쓴다(중간 파일은 지운다). */
export async function mix(inputs, out, { run = runFfmpeg, batch = BATCH, level = 0 } = {}) {
  batch = Math.max(2, batch); // 1이면 묶음 수가 줄지 않아 끝나지 않는다
  const tmp = `${out}.part`;
  if (inputs.length <= batch) {
    await run(argsFor(inputs, tmp, '32k')); // 결과만 32kbps, 중간 트랙은 64kbps로 덜 깎는다
    renameSync(tmp, out);
    return;
  }
  const parts = [];
  try {
    for (let i = 0; i < inputs.length; i += batch) {
      const p = join(dirname(out), `mix-${level}-${parts.length}.ogg`);
      await run(argsFor(inputs.slice(i, i + batch), p, '64k'));
      parts.push({ path: p, delay_ms: 0 }); // 중간 트랙은 이미 회의 시작 기준으로 밀려 있다
    }
    await mix(parts, out, { run, batch, level: level + 1 });
  } finally {
    for (const p of parts) rmSync(p.path, { force: true });
  }
}
