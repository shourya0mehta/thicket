/**
 * Minimal PNG encoder plus a synthetic spectrogram, so e2e tests and
 * screenshots have a realistic image without a backend.
 */
import { deflateSync } from 'node:zlib';

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const typed = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(typed));
  return Buffer.concat([length, typed, crc]);
}

export function encodePng(width: number, height: number, rgb: Uint8Array): Buffer {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8; // bit depth
  header[9] = 2; // RGB
  const raw = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (width * 3 + 1)] = 0;
    Buffer.from(rgb.buffer, rgb.byteOffset + y * width * 3, width * 3).copy(
      raw,
      y * (width * 3 + 1) + 1,
    );
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(raw, { level: 6 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

// Dark green to warm cream, matched to the app's visualization background.
const STOPS: Array<[number, [number, number, number]]> = [
  [0, [11, 19, 16]],
  [0.3, [24, 52, 41]],
  [0.55, [55, 113, 87]],
  [0.78, [155, 191, 170]],
  [1, [246, 240, 214]],
];

function colormap(v: number): [number, number, number] {
  const x = Math.min(1, Math.max(0, v));
  for (let i = 1; i < STOPS.length; i++) {
    const [p1, c1] = STOPS[i]!;
    const [p0, c0] = STOPS[i - 1]!;
    if (x <= p1) {
      const t = (x - p0) / (p1 - p0);
      return [0, 1, 2].map((k) => Math.round(c0[k]! + (c1[k]! - c0[k]!) * t)) as [
        number,
        number,
        number,
      ];
    }
  }
  return STOPS[STOPS.length - 1]![1];
}

function rand(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

export interface CallSpec {
  start: number;
  end: number;
  /** Frequency path in Hz: [startHz, endHz] per syllable. */
  lowHz: number;
  highHz: number;
  kind: 'whistle' | 'trill' | 'buzz' | 'tone';
  strength: number;
}

export function syntheticSpectrogram(
  durationSeconds: number,
  maxHz: number,
  calls: CallSpec[],
  width = 1200,
  height = 400,
): Buffer {
  const field = new Float32Array(width * height);
  const random = rand(11);
  const secToX = (sec: number) => (sec / durationSeconds) * width;
  const hzToY = (hz: number) => height - (hz / maxHz) * height;

  // Smooth background: coarse noise upsampled bilinearly, more energy at low frequencies.
  const gw = 80;
  const gh = 24;
  const grid = Array.from({ length: gw * gh }, () => random());
  const sample = (x: number, y: number) => {
    const fx = (x / width) * (gw - 1);
    const fy = (y / height) * (gh - 1);
    const x0 = Math.floor(fx);
    const y0 = Math.floor(fy);
    const x1 = Math.min(gw - 1, x0 + 1);
    const y1 = Math.min(gh - 1, y0 + 1);
    const tx = fx - x0;
    const ty = fy - y0;
    const a = grid[y0 * gw + x0]! * (1 - tx) + grid[y0 * gw + x1]! * tx;
    const b = grid[y1 * gw + x0]! * (1 - tx) + grid[y1 * gw + x1]! * tx;
    return a * (1 - ty) + b * ty;
  };
  for (let y = 0; y < height; y++) {
    const hz = maxHz * (1 - y / height);
    const low = Math.exp(-hz / 700);
    for (let x = 0; x < width; x++) {
      const t = (x / width) * durationSeconds;
      const wind = t < 20 ? 0.35 * Math.exp(-hz / 260) * (0.6 + 0.4 * sample(x * 3, y)) : 0;
      field[y * width + x] = 0.02 + 0.035 * sample(x, y) + 0.12 * low + wind + random() * 0.015;
    }
  }

  const stamp = (cx: number, cy: number, rx: number, ry: number, amount: number) => {
    const x0 = Math.max(0, Math.floor(cx - rx * 2.5));
    const x1 = Math.min(width - 1, Math.ceil(cx + rx * 2.5));
    const y0 = Math.max(0, Math.floor(cy - ry * 2.5));
    const y1 = Math.min(height - 1, Math.ceil(cy + ry * 2.5));
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        const d = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2;
        field[y * width + x] = (field[y * width + x] ?? 0) + amount * Math.exp(-d);
      }
    }
  };

  /** Draws a note following hzAt(f) for f in 0..1 between t0 and t1 seconds. */
  const note = (
    t0: number,
    t1: number,
    hzAt: (f: number) => number,
    amount: number,
    thickness = 2.4,
  ) => {
    const dx = secToX(t1) - secToX(t0);
    const dy =
      Math.abs(hzToY(hzAt(0)) - hzToY(hzAt(1))) + Math.abs(hzToY(hzAt(0.5)) - hzToY(hzAt(0)));
    const steps = Math.max(6, Math.round(Math.max(dx, dy) * 1.6));
    for (let k = 0; k <= steps; k++) {
      const f = k / steps;
      const envelope = Math.sin(Math.PI * Math.min(1, Math.max(0, f))) ** 0.6;
      const t = t0 + (t1 - t0) * f;
      const hz = hzAt(f);
      stamp(secToX(t), hzToY(hz), 1.5, thickness, (amount * envelope * 0.9 * 24) / steps);
      if (hz * 2 < maxHz)
        stamp(
          secToX(t),
          hzToY(hz * 2),
          1.5,
          thickness * 0.8,
          (amount * envelope * 0.22 * 24) / steps,
        );
    }
  };

  for (const call of calls) {
    const a = call.strength;
    const lo = call.lowHz;
    const hi = call.highHz;
    const span = call.end - call.start;
    const jitter = () => (random() - 0.5) * 0.25;
    if (call.kind === 'whistle') {
      for (let i = 0; i < 3; i++) {
        const t0 = call.start + 0.3 + i * (span / 3.4) + jitter();
        note(t0, t0 + 0.38, (f) => hi - (hi - lo) * f ** 0.8, a, 2.6);
      }
    } else if (call.kind === 'trill') {
      for (let i = 0; i < 4; i++) {
        const t0 = call.start + 0.2 + i * (span / 4.3) + jitter();
        const base = lo + (hi - lo) * (0.3 + 0.4 * random());
        note(t0, t0 + 0.32, (f) => base + (hi - lo) * 0.28 * Math.sin(f * Math.PI * 3), a, 2.4);
      }
    } else if (call.kind === 'buzz') {
      const t0 = call.start + 0.5 + jitter();
      note(t0, t0 + 0.12, () => hi * 0.8, a * 0.8, 1.4);
      note(t0 + 0.25, t0 + 0.37, () => hi * 0.8, a * 0.8, 1.4);
      for (let k = 0; k < 90; k++) {
        const t = t0 + 0.55 + (k / 90) * 0.9;
        stamp(secToX(t), hzToY(lo + (hi - lo) * random()), 1.4, 6, a * 0.2);
      }
    } else {
      for (let i = 0; i < 5; i++) {
        const t0 = call.start + 0.15 + i * (span / 5.2) + jitter() * 0.3;
        note(t0, t0 + 0.14, (f) => lo + (hi - lo) * f, a, 2.2);
      }
    }
  }

  const rgb = new Uint8Array(width * height * 3);
  for (let i = 0; i < field.length; i++) {
    const v = Math.log1p(6 * (field[i] ?? 0)) / Math.log1p(6 * 0.9);
    const [r, g, b] = colormap(v);
    rgb[i * 3] = r;
    rgb[i * 3 + 1] = g;
    rgb[i * 3 + 2] = b;
  }
  return encodePng(width, height, rgb);
}

/** 16-bit mono PCM WAV with a quiet tone, long enough to seek within. */
export function syntheticWav(seconds: number, sampleRate = 8000): Buffer {
  const samples = Math.floor(seconds * sampleRate);
  const data = Buffer.alloc(samples * 2);
  for (let i = 0; i < samples; i++) {
    const v = Math.sin((2 * Math.PI * 440 * i) / sampleRate) * 0.05;
    data.writeInt16LE(Math.round(v * 32767), i * 2);
  }
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write('WAVE', 8);
  header.write('fmt ', 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(1, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(sampleRate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36);
  header.writeUInt32LE(data.length, 40);
  return Buffer.concat([header, data]);
}
