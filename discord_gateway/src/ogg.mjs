// Opus 패킷을 디코딩하지 않고 Ogg 컨테이너(RFC 3533, RFC 7845)에 그대로 쓴다.
// prism-media 1.x에는 Ogg 라이터가 없고 2.0은 alpha라 직접 쓴다(설계서 v1 §8 P0 결정).
import { openSync, writeSync, closeSync } from 'node:fs';

const CRC_TABLE = new Uint32Array(256);
for (let i = 0; i < 256; i++) {
  let r = i << 24;
  for (let j = 0; j < 8; j++) r = r & 0x80000000 ? (r << 1) ^ 0x04c11db7 : r << 1;
  CRC_TABLE[i] = r >>> 0;
}

export function oggCrc(buf) {
  let crc = 0;
  for (const b of buf) crc = ((crc << 8) ^ CRC_TABLE[((crc >>> 24) ^ b) & 0xff]) >>> 0;
  return crc;
}

// ponytail: Discord 클라이언트는 20ms 프레임만 보낸다고 보고 패킷당 960 샘플로 센다. 다른 프레임 길이가 보이면 TOC 파싱으로 바꾼다.
export const SAMPLES_PER_PACKET = 960;
const PACKETS_PER_PAGE = 50; // 1초마다 페이지를 비운다(강제 종료 시 잃는 양 = 최대 1초)

export class OggOpusWriter {
  constructor(path, { serial = (Math.random() * 0xffffffff) >>> 0 } = {}) {
    this.fd = openSync(path, 'w');
    this.serial = serial;
    this.pageSeq = 0;
    this.granule = 0n;
    this.pending = [];
    this.pendingSegs = 0;
    this.packets = 0;
    const head = Buffer.alloc(19);
    head.write('OpusHead', 0, 'ascii');
    head[8] = 1; // version
    head[9] = 2; // Discord는 스테레오 Opus를 보낸다
    head.writeUInt16LE(0, 10); // pre-skip
    head.writeUInt32LE(48000, 12);
    head.writeInt16LE(0, 16); // output gain
    head[18] = 0; // channel mapping family
    this.#page([head], 0x02, 0n);
    const vendor = Buffer.from('sandol-poc');
    const tags = Buffer.alloc(8 + 4 + vendor.length + 4);
    tags.write('OpusTags', 0, 'ascii');
    tags.writeUInt32LE(vendor.length, 8);
    vendor.copy(tags, 12);
    this.#page([tags], 0, 0n);
  }

  write(packet) {
    const segs = Math.floor(packet.length / 255) + 1;
    if (this.pending.length >= PACKETS_PER_PAGE || this.pendingSegs + segs > 255) this.#flush(0);
    this.pending.push(packet);
    this.pendingSegs += segs;
    this.packets++;
    this.granule += BigInt(SAMPLES_PER_PACKET);
  }

  end() {
    if (this.fd === null) return;
    this.#flush(0x04, true);
    closeSync(this.fd);
    this.fd = null;
  }

  get durationMs() {
    return Number((this.granule * 1000n) / 48000n);
  }

  #flush(flags, force = false) {
    if (!this.pending.length && !force) return;
    this.#page(this.pending, flags, this.granule);
    this.pending = [];
    this.pendingSegs = 0;
  }

  #page(packets, flags, granule) {
    const lacing = [];
    for (const p of packets) {
      let n = p.length;
      while (n >= 255) { lacing.push(255); n -= 255; }
      lacing.push(n);
    }
    const header = Buffer.alloc(27 + lacing.length);
    header.write('OggS', 0, 'ascii');
    header[5] = flags;
    header.writeBigUInt64LE(granule, 6);
    header.writeUInt32LE(this.serial, 14);
    header.writeUInt32LE(this.pageSeq++, 18);
    header[26] = lacing.length;
    Buffer.from(lacing).copy(header, 27);
    const page = Buffer.concat([header, ...packets]);
    page.writeUInt32LE(oggCrc(page), 22);
    writeSync(this.fd, page);
  }
}
