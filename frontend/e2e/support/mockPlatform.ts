/**
 * Playwright route mocks for the platform routes, answered by the same
 * in-memory server the Vitest fake backend uses. Requests that are not
 * platform routes fall through to the single-recording mocks in mockApi.ts,
 * so call mockApi() first and mockPlatform() second (the last route wins).
 */
import type { Page, Request } from '@playwright/test';
import {
  createPlatformServer,
  handlePlatformRequest,
  type PlatformServerOptions,
  type PlatformServerState,
} from '../../src/test/fixtures/platformServer';
import { encodePng } from './png';

let tileCache: Buffer | null = null;

/** A plain paper-colored map tile with a faint field grid, so maps never hit the network. */
export function mapTile(): Buffer {
  if (tileCache) return tileCache;
  const size = 256;
  const rgb = new Uint8Array(size * size * 3);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const i = (y * size + x) * 3;
      const field = Math.floor(x / 64) + Math.floor(y / 64);
      const base = field % 2 === 0 ? [226, 232, 214] : [218, 228, 206];
      const line = x % 64 === 0 || y % 64 === 0;
      rgb[i] = line ? 200 : base[0]!;
      rgb[i + 1] = line ? 206 : base[1]!;
      rgb[i + 2] = line ? 190 : base[2]!;
    }
  }
  tileCache = encodePng(size, size, rgb);
  return tileCache;
}

/** Minimal multipart/form-data reader: text fields as strings, files as "file:<name>". */
export function parseMultipart(request: Request): Record<string, unknown> {
  const type = request.headers()['content-type'] ?? '';
  const boundary = /boundary=([^;]+)/.exec(type)?.[1];
  const buffer = request.postDataBuffer();
  const fields: Record<string, unknown> = {};
  if (!boundary || !buffer) return fields;
  const text = buffer.toString('latin1');
  for (const part of text.split(`--${boundary}`)) {
    const headerEnd = part.indexOf('\r\n\r\n');
    if (headerEnd < 0) continue;
    const headers = part.slice(0, headerEnd);
    const name = /name="([^"]+)"/.exec(headers)?.[1];
    if (!name) continue;
    const filename = /filename="([^"]*)"/.exec(headers)?.[1];
    const value =
      filename !== undefined ? `file:${filename}` : part.slice(headerEnd + 4).replace(/\r\n$/, '');
    const existing = fields[name];
    if (existing === undefined) fields[name] = value;
    else if (Array.isArray(existing)) existing.push(value);
    else fields[name] = [existing, value];
  }
  return fields;
}

export async function mockPlatform(
  page: Page,
  options: PlatformServerOptions = {},
): Promise<PlatformServerState> {
  const state = createPlatformServer(options);

  await page.route(/tile\.openstreetmap\.org/, (route) =>
    route.fulfill({ status: 200, contentType: 'image/png', body: mapTile() }),
  );

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^.*\/api\/v1/, '');
    const method = request.method();
    const contentType = request.headers()['content-type'] ?? '';
    let body: unknown = null;
    if (method !== 'GET') {
      if (contentType.includes('multipart/form-data')) body = parseMultipart(request);
      else {
        try {
          body = request.postDataJSON() as unknown;
        } catch {
          body = null;
        }
      }
    }
    const reply = handlePlatformRequest(state, method, path, url.searchParams, body);
    if (!reply) return route.fallback();
    if (reply.status === 204) return route.fulfill({ status: 204, body: '' });
    if (typeof reply.body === 'string') {
      return route.fulfill({
        status: reply.status,
        contentType: path.endsWith('.pdf') ? 'application/pdf' : 'text/plain',
        body: reply.body,
      });
    }
    return route.fulfill({
      status: reply.status,
      contentType: 'application/json',
      body: JSON.stringify(reply.body),
    });
  });

  return state;
}
