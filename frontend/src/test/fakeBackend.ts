/**
 * An in-memory Thicket API for component tests. It answers both fetch and
 * XMLHttpRequest (used for uploads) from the shared fixtures and records every
 * request so tests can assert on URLs and bodies.
 */
import { vi } from 'vitest';
import type { ErrorResponse, ModelsResponse, ReviewStatus } from '../api/generated';
import {
  MODELS,
  PREVIEW,
  buildAnalysis,
  failedAnalysis,
  pendingAnalysis,
  type BuildOptions,
} from './fixtures/analysis';
import {
  createPlatformServer,
  handlePlatformRequest,
  type PlatformServerOptions,
  type PlatformServerState,
} from './fixtures/platformServer';

export interface RecordedRequest {
  method: string;
  url: string;
  body: unknown;
  headers: Record<string, string>;
}

export interface FakeBackendOptions {
  models?: ModelsResponse;
  analysis?: BuildOptions;
  /** Poll responses still processing before completion. */
  pollsBeforeComplete?: number;
  /** Queue of error responses for POST /analyses. */
  createErrors?: Array<{ status: number; body: ErrorResponse }>;
  /** Status to return for GET /analyses/{id} (e.g. 404). */
  getAnalysisError?: { status: number; body: ErrorResponse } | null;
  modelsError?: boolean;
  /** The analysis fails server-side with this code (returned by the first poll). */
  failWith?: { code: NonNullable<ErrorResponse['error_code']>; message: string } | null;
  /**
   * Serve the platform routes (auth, organizations, dashboard...). Without
   * this the backend behaves like an older server: /auth/config is a 404 and
   * the app shows the standalone workspace.
   */
  platform?: PlatformServerOptions;
}

export interface FakeBackend {
  requests: RecordedRequest[];
  reviews: Record<string, ReviewStatus>;
  options: FakeBackendOptions;
  urls: (method?: string) => string[];
  /** In-memory platform state (sites created, alerts updated...), when enabled. */
  platform: PlatformServerState | null;
}

interface Reply {
  status: number;
  body: unknown;
}

function handle(backend: FakeBackend, method: string, rawUrl: string, body: unknown): Reply {
  const url = new URL(rawUrl, 'http://localhost');
  const path = url.pathname.replace(/^.*\/api\/v1/, '');
  const opts = backend.options;

  if (backend.platform) {
    const reply = handlePlatformRequest(backend.platform, method, path, url.searchParams, body);
    if (reply) return reply;
  }

  if (method === 'GET' && path === '/models') {
    if (opts.modelsError) return { status: 503, body: 'Service Unavailable' };
    return { status: 200, body: opts.models ?? MODELS };
  }
  if (method === 'POST' && path === '/previews') return { status: 201, body: PREVIEW };
  if (method === 'DELETE' && /^\/previews\/[^/]+$/.test(path)) return { status: 204, body: null };
  if (method === 'POST' && path === '/analyses') {
    const error = opts.createErrors?.shift();
    if (error) return { status: error.status, body: error.body };
    return { status: 202, body: pendingAnalysis('queued', 'queued') };
  }
  if (method === 'GET' && path === '/analyses') return { status: 200, body: { items: [] } };
  const analysis = /^\/analyses\/([^/]+)$/.exec(path);
  if (analysis && method === 'GET') {
    if (opts.getAnalysisError) return opts.getAnalysisError;
    if (opts.failWith) {
      return { status: 200, body: failedAnalysis(opts.failWith.code, opts.failWith.message) };
    }
    if ((opts.pollsBeforeComplete ?? 0) > 0) {
      opts.pollsBeforeComplete = (opts.pollsBeforeComplete ?? 0) - 1;
      return { status: 200, body: pendingAnalysis('model:birdnet') };
    }
    const threshold = url.searchParams.has('threshold')
      ? Number(url.searchParams.get('threshold'))
      : (opts.analysis?.threshold ?? 0.6);
    return {
      status: 200,
      body: buildAnalysis({ ...opts.analysis, threshold, reviews: backend.reviews }),
    };
  }
  if (analysis && method === 'DELETE') return { status: 204, body: null };
  const event = /^\/events\/([^/]+)$/.exec(path);
  if (event && method === 'PATCH') {
    const update = body as { review_status: ReviewStatus };
    backend.reviews[decodeURIComponent(event[1]!)] = update.review_status;
    return { status: 200, body: { id: event[1], review_status: update.review_status } };
  }
  return { status: 404, body: { error_code: 'analysis_not_found', message: 'Not found' } };
}

/**
 * Holds fetch requests whose URL matches until `release()`, so tests can order
 * responses (for example a slow threshold recompute). Held requests honour
 * their AbortSignal. Call after `installFakeBackend()`.
 */
export function holdRequests(match: (url: string) => boolean): {
  count: () => number;
  release: () => void;
} {
  const base = globalThis.fetch;
  const pending: Array<() => void> = [];
  let count = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (!match(url)) return base(input, init);
      count += 1;
      return new Promise<Response>((resolve, reject) => {
        const onAbort = () => {
          const error = new Error('Aborted');
          error.name = 'AbortError';
          reject(error);
        };
        init?.signal?.addEventListener('abort', onAbort, { once: true });
        pending.push(() => {
          init?.signal?.removeEventListener('abort', onAbort);
          base(input, init).then(resolve, reject);
        });
      });
    }),
  );
  return { count: () => count, release: () => pending.splice(0).forEach((go) => go()) };
}

function serialize(body: unknown): string {
  if (body === null || body === undefined) return '';
  return typeof body === 'string' ? body : JSON.stringify(body);
}

export function installFakeBackend(options: FakeBackendOptions = {}): FakeBackend {
  const backend: FakeBackend = {
    requests: [],
    reviews: {},
    options: { ...options, createErrors: [...(options.createErrors ?? [])] },
    urls: (method?: string) =>
      backend.requests.filter((r) => !method || r.method === method).map((r) => r.url),
    platform: options.platform ? createPlatformServer(options.platform) : null,
  };

  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const method = (init?.method ?? 'GET').toUpperCase();
      if (init?.signal?.aborted) {
        const error = new Error('Aborted');
        error.name = 'AbortError';
        return Promise.reject(error);
      }
      const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : null;
      const headers: Record<string, string> = {};
      new Headers(init?.headers).forEach((value, key) => {
        headers[key.toLowerCase()] = value;
      });
      backend.requests.push({ method, url, body, headers });
      const reply = handle(backend, method, url, body);
      const text = serialize(reply.body);
      return Promise.resolve(
        new Response(reply.status === 204 ? null : text, {
          status: reply.status,
          headers: {
            'Content-Type': typeof reply.body === 'string' ? 'text/plain' : 'application/json',
          },
        }),
      );
    }),
  );

  class FakeXHR {
    status = 0;
    responseText = '';
    upload: { onprogress: ((e: ProgressEvent) => void) | null; onload: (() => void) | null } = {
      onprogress: null,
      onload: null,
    };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    ontimeout: (() => void) | null = null;
    onabort: (() => void) | null = null;
    private method = 'GET';
    private url = '';
    private aborted = false;
    private headers: Record<string, string> = {};

    open(method: string, url: string) {
      this.method = method.toUpperCase();
      this.url = url;
    }
    setRequestHeader(name: string, value: string) {
      this.headers[name.toLowerCase()] = value;
    }
    abort() {
      this.aborted = true;
      this.onabort?.();
    }
    send(body: FormData) {
      const fields: Record<string, unknown> = {};
      body.forEach((value, key) => {
        const item = value instanceof File ? `file:${value.name}` : value;
        const existing = fields[key];
        // Repeated keys (files, last_modified) become arrays.
        if (existing === undefined) fields[key] = item;
        else if (Array.isArray(existing)) existing.push(item);
        else fields[key] = [existing, item];
      });
      backend.requests.push({
        method: this.method,
        url: this.url,
        body: fields,
        headers: this.headers,
      });
      setTimeout(() => {
        if (this.aborted) return;
        this.upload.onprogress?.({
          lengthComputable: true,
          loaded: 50,
          total: 100,
        } as ProgressEvent);
        this.upload.onprogress?.({
          lengthComputable: true,
          loaded: 100,
          total: 100,
        } as ProgressEvent);
        this.upload.onload?.();
        const reply = handle(backend, this.method, this.url, fields);
        this.status = reply.status;
        this.responseText = serialize(reply.body);
        this.onload?.();
      }, 5);
    }
  }
  vi.stubGlobal('XMLHttpRequest', FakeXHR);

  return backend;
}
