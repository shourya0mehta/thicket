import { apiBaseUrl } from '../config';
import type {
  Analysis,
  AnalysisList,
  CreateAnalysisParams,
  ErrorCode,
  EventReviewUpdate,
  HealthResponse,
  ModelsResponse,
  Preview,
} from './types';

/**
 * Server error codes plus client-side failure kinds. `unauthenticated` (401),
 * `forbidden` (403) and `conflict` (409) come from the platform routes.
 */
export type ApiErrorCode =
  | ErrorCode
  | 'unauthenticated'
  | 'forbidden'
  | 'conflict'
  | 'network'
  | 'backend_unavailable'
  | 'invalid_response';

/** Header required by the backend on every mutating request (CSRF guard). */
export const REQUESTED_WITH_HEADER = { 'X-Requested-With': 'thicket' } as const;

const MUTATING = new Set(['POST', 'PATCH', 'PUT', 'DELETE']);

type UnauthenticatedHandler = () => void;
let onUnauthenticated: UnauthenticatedHandler | null = null;

/** The auth provider registers itself here so any 401 routes the app to sign-in. */
export function setUnauthenticatedHandler(handler: UnauthenticatedHandler | null): void {
  onUnauthenticated = handler;
}

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number | null;
  readonly detail: Record<string, unknown> | null;

  constructor(
    code: ApiErrorCode,
    message: string,
    status: number | null = null,
    detail: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

export function isAbortError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'name' in error &&
    (error as { name?: unknown }).name === 'AbortError'
  );
}

function abortError(): Error {
  const error = new Error('The request was cancelled.');
  error.name = 'AbortError';
  return error;
}

const KNOWN_CODES: ReadonlySet<string> = new Set<ErrorCode>([
  'unsupported_file_type',
  'file_too_large',
  'audio_too_long',
  'audio_decode_failed',
  'audio_too_short',
  'model_unavailable',
  'unknown_model',
  'invalid_parameter',
  'analysis_not_found',
  'event_not_found',
  'analysis_timeout',
  'internal_error',
  'unsupported_audio',
  'not_found',
  'rate_limited',
  'request_timeout',
]);

export function apiUrl(path: string): string {
  return `${apiBaseUrl()}/api/v1${path}`;
}

/**
 * Asset URLs from the API are usually root-relative (/api/v1/...). Prefix them
 * with the configured API base; leave absolute, blob and data URLs alone.
 */
export function resolveApiUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (/^(https?:|blob:|data:)/i.test(url) || url.startsWith('//')) return url;
  if (url.startsWith('/')) return `${apiBaseUrl()}${url}`;
  return url;
}

export function formatThresholdParam(threshold: number): string {
  return threshold.toFixed(2);
}

/** Adds or replaces the `threshold` query parameter, keeping any other params. */
export function withThreshold(url: string, threshold: number): string {
  const hashIndex = url.indexOf('#');
  const hash = hashIndex >= 0 ? url.slice(hashIndex) : '';
  const beforeHash = hashIndex >= 0 ? url.slice(0, hashIndex) : url;
  const queryIndex = beforeHash.indexOf('?');
  const path = queryIndex >= 0 ? beforeHash.slice(0, queryIndex) : beforeHash;
  const params = new URLSearchParams(queryIndex >= 0 ? beforeHash.slice(queryIndex + 1) : '');
  params.set('threshold', formatThresholdParam(threshold));
  return `${path}?${params.toString()}${hash}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Builds an ApiError from a non-2xx response body (JSON ErrorResponse when possible). */
export function errorFromResponse(status: number, bodyText: string): ApiError {
  let body: unknown = null;
  try {
    body = bodyText ? JSON.parse(bodyText) : null;
  } catch {
    body = null;
  }

  const bodyMessage =
    isRecord(body) && typeof body.message === 'string' ? body.message.trim() || null : null;
  if (status === 401) {
    return new ApiError('unauthenticated', bodyMessage ?? 'Sign in to continue.', status);
  }
  if (status === 403) {
    return new ApiError(
      'forbidden',
      bodyMessage ?? 'Your role in this organization does not allow that.',
      status,
    );
  }
  if (status === 409) {
    return new ApiError(
      'conflict',
      bodyMessage ?? 'That change conflicts with existing data.',
      status,
    );
  }

  if (isRecord(body) && typeof body.error_code === 'string') {
    const code = KNOWN_CODES.has(body.error_code)
      ? (body.error_code as ErrorCode)
      : 'internal_error';
    const message = bodyMessage ?? `Request failed (${status}).`;
    const detail = isRecord(body.detail) ? body.detail : null;
    return new ApiError(code, message, status, detail);
  }

  // Not a Thicket ErrorResponse: a proxy, gateway or framework default error.
  const detailMessage = isRecord(body) && typeof body.detail === 'string' ? body.detail : null;
  if (status === 413) {
    return new ApiError('file_too_large', detailMessage ?? 'The file is too large.', status);
  }
  if (status === 422 || status === 400) {
    return new ApiError(
      'invalid_parameter',
      detailMessage ?? 'Some settings were not accepted.',
      status,
    );
  }
  if (status === 404) {
    return new ApiError('analysis_not_found', detailMessage ?? 'Not found.', status);
  }
  if (status >= 500 || status === 0) {
    return new ApiError(
      'backend_unavailable',
      detailMessage ?? 'The Thicket server did not respond normally.',
      status,
    );
  }
  return new ApiError('internal_error', detailMessage ?? `Request failed (${status}).`, status);
}

/**
 * JSON request against the API. Mutating methods carry the CSRF header; a 401
 * also notifies the registered handler so the app can show the sign-in page.
 * Exported for the platform client (src/api/platform.ts).
 */
export async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase();
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...init,
      credentials: apiBaseUrl() ? 'include' : 'same-origin',
      headers: {
        Accept: 'application/json',
        ...(MUTATING.has(method) ? REQUESTED_WITH_HEADER : {}),
        ...(init.headers ?? {}),
      },
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError('network', 'Could not reach the Thicket server.');
  }

  if (!response.ok) {
    let text = '';
    try {
      text = await response.text();
    } catch {
      text = '';
    }
    const error = errorFromResponse(response.status, text);
    if (error.code === 'unauthenticated') onUnauthenticated?.();
    throw error;
  }

  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError('invalid_response', 'The server sent a response Thicket could not read.');
  }
}

/** JSON body helper for POST, PATCH and PUT. */
export function requestWithBody<T>(
  method: 'POST' | 'PATCH' | 'PUT',
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  return requestJson<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
    signal,
  });
}

export type ProgressHandler = (fraction: number) => void;

/** Multipart POST with upload progress (fetch cannot report upload progress). */
export function uploadForm<T>(
  path: string,
  form: FormData,
  onProgress?: ProgressHandler,
  signal?: AbortSignal,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open('POST', apiUrl(path));
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.setRequestHeader('X-Requested-With', 'thicket');
    // The session cookie must travel when the API lives on another origin.
    xhr.withCredentials = apiBaseUrl() !== '';

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress?.(event.loaded / event.total);
    };
    xhr.upload.onload = () => onProgress?.(1);

    xhr.onload = () => {
      const text = typeof xhr.responseText === 'string' ? xhr.responseText : '';
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(text) as T);
        } catch {
          reject(
            new ApiError('invalid_response', 'The server sent a response Thicket could not read.'),
          );
        }
        return;
      }
      const error = errorFromResponse(xhr.status, text);
      if (error.code === 'unauthenticated') onUnauthenticated?.();
      reject(error);
    };
    xhr.onerror = () => reject(new ApiError('network', 'Could not reach the Thicket server.'));
    xhr.ontimeout = () => reject(new ApiError('network', 'The upload timed out.'));
    xhr.onabort = () => reject(abortError());

    signal?.addEventListener('abort', () => xhr.abort(), { once: true });
    xhr.send(form);
  });
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return requestJson<HealthResponse>('/health', { signal });
}

export function getModels(signal?: AbortSignal): Promise<ModelsResponse> {
  return requestJson<ModelsResponse>('/models', { signal });
}

export function createPreview(
  file: File,
  onProgress?: ProgressHandler,
  signal?: AbortSignal,
): Promise<Preview> {
  const form = new FormData();
  form.append('file', file, file.name);
  return uploadForm<Preview>('/previews', form, onProgress, signal);
}

export function buildAnalysisForm(params: CreateAnalysisParams): FormData {
  const form = new FormData();
  if (params.previewId) {
    form.append('preview_id', params.previewId);
  } else if (params.file) {
    form.append('file', params.file, params.file.name);
  }
  form.append('models', JSON.stringify(params.models));
  form.append('threshold', formatThresholdParam(params.threshold));
  if (params.latitude != null && params.longitude != null) {
    form.append('latitude', String(params.latitude));
    form.append('longitude', String(params.longitude));
  }
  if (params.capturedAt) form.append('captured_at', params.capturedAt);
  if (params.timezone) form.append('timezone', params.timezone);
  if (params.siteName) form.append('site_name', params.siteName);
  if (params.organizationId) form.append('organization_id', params.organizationId);
  if (params.siteId) form.append('site_id', params.siteId);
  if (params.deploymentId) form.append('deployment_id', params.deploymentId);
  if (params.recorderId) form.append('recorder_id', params.recorderId);
  return form;
}

export function createAnalysis(
  params: CreateAnalysisParams,
  onProgress?: ProgressHandler,
  signal?: AbortSignal,
): Promise<Analysis> {
  return uploadForm<Analysis>('/analyses', buildAnalysisForm(params), onProgress, signal);
}

export function getAnalysis(
  id: string,
  options: { threshold?: number | null; signal?: AbortSignal } = {},
): Promise<Analysis> {
  const base = `/analyses/${encodeURIComponent(id)}`;
  const path =
    options.threshold == null
      ? base
      : `${base}?threshold=${formatThresholdParam(options.threshold)}`;
  return requestJson<Analysis>(path, { signal: options.signal });
}

export function listAnalyses(signal?: AbortSignal): Promise<AnalysisList> {
  return requestJson<AnalysisList>('/analyses', { signal });
}

/** Deletes a preview's uploaded audio and spectrogram on the server now, not at expiry. */
export async function deletePreview(id: string): Promise<void> {
  await requestJson<unknown>(`/previews/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function deleteAnalysis(id: string): Promise<void> {
  await requestJson<unknown>(`/analyses/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function reviewEvent(eventId: string, update: EventReviewUpdate): Promise<void> {
  await requestJson<unknown>(`/events/${encodeURIComponent(eventId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  });
}
