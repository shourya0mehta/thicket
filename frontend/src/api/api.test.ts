import { describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  buildAnalysisForm,
  errorFromResponse,
  getAnalysis,
  resolveApiUrl,
  withThreshold,
} from './client';
import { describeError, describeErrorCode } from './errors';
import type { ErrorCode } from './types';

describe('URLs', () => {
  it('adds or replaces the threshold parameter with two decimals', () => {
    expect(withThreshold('/api/v1/analyses/a1/export.csv', 0.45)).toBe(
      '/api/v1/analyses/a1/export.csv?threshold=0.45',
    );
    expect(withThreshold('/x/export.json?threshold=0.6&x=1', 0.6)).toBe(
      '/x/export.json?threshold=0.60&x=1',
    );
    expect(withThreshold('/x/export.csv?x=1#top', 0.1)).toBe(
      '/x/export.csv?x=1&threshold=0.10#top',
    );
  });

  it('prefixes root-relative asset URLs with the API base', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://thicket.example.org/');
    expect(resolveApiUrl('/api/v1/analyses/a/spectrogram.png')).toBe(
      'https://thicket.example.org/api/v1/analyses/a/spectrogram.png',
    );
    expect(resolveApiUrl('https://cdn.example.org/a.png')).toBe('https://cdn.example.org/a.png');
    expect(resolveApiUrl('blob:abc')).toBe('blob:abc');
    expect(resolveApiUrl(null)).toBeNull();
  });

  it('requests an analysis at a threshold', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify({ id: 'a' }), { status: 200 })),
    );
    vi.stubGlobal('fetch', fetchMock);
    await getAnalysis('a b', { threshold: 0.45 });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/analyses/a%20b?threshold=0.45',
      expect.anything(),
    );
  });
});

describe('analysis form', () => {
  it('sends the preview id instead of the file when reusing a preview', () => {
    const file = new File(['x'], 'a.wav');
    const form = buildAnalysisForm({ file, previewId: 'pv1', models: ['birdnet'], threshold: 0.6 });
    expect(form.get('preview_id')).toBe('pv1');
    expect(form.get('file')).toBeNull();
    expect(form.get('models')).toBe('["birdnet"]');
    expect(form.get('threshold')).toBe('0.60');
  });

  it('only sends coordinates as a pair and skips empty metadata', () => {
    const file = new File(['x'], 'a.wav');
    const form = buildAnalysisForm({
      file,
      models: ['birdnet', 'perch'],
      threshold: 0.55,
      latitude: 41.2,
      longitude: null,
      siteName: null,
    });
    expect(form.get('file')).toBeInstanceOf(File);
    expect(form.get('latitude')).toBeNull();
    expect(form.get('site_name')).toBeNull();
    expect(form.get('models')).toBe('["birdnet","perch"]');
  });
});

describe('error mapping', () => {
  const cases: Array<[ErrorCode, string]> = [
    ['unsupported_file_type', 'This file type is not supported'],
    ['file_too_large', 'This file is too large'],
    ['audio_too_long', 'This recording is too long'],
    ['audio_decode_failed', 'The audio could not be decoded'],
    ['audio_too_short', 'This recording is too short'],
    ['model_unavailable', 'The model is not available right now'],
    ['unknown_model', 'This server does not recognize that model'],
    ['analysis_timeout', 'The analysis took too long'],
    ['unsupported_audio', 'This audio cannot be analyzed'],
    ['rate_limited', 'The server is busy'],
    ['request_timeout', 'The upload timed out'],
    ['internal_error', 'Something went wrong on the server'],
  ];

  it.each(cases)('%s has its own friendly title', (code, title) => {
    const friendly = describeErrorCode(code);
    expect(friendly.title).toBe(title);
    expect(friendly.body.length).toBeGreaterThan(10);
    expect(`${friendly.title} ${friendly.body}`).not.toMatch(/—/);
  });

  it('parses ErrorResponse bodies', () => {
    const error = errorFromResponse(
      413,
      JSON.stringify({ error_code: 'file_too_large', message: 'Limit is 20 MB' }),
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe('file_too_large');
    expect(describeError(error)?.detail).toBe('Limit is 20 MB');
  });

  it('treats gateway failures and network errors as backend unavailable', () => {
    expect(errorFromResponse(502, '<html>Bad gateway</html>').code).toBe('backend_unavailable');
    expect(errorFromResponse(500, '').code).toBe('backend_unavailable');
    const network = describeError(new ApiError('network', 'failed'));
    expect(network?.title).toBe('Cannot reach the Thicket server');
    expect(network?.action).toBe('retry');
    expect(network?.detail).toBeNull();
  });

  it('maps unknown server codes to internal_error and ignores aborts', () => {
    expect(
      errorFromResponse(500, JSON.stringify({ error_code: 'new_thing', message: 'x' })).code,
    ).toBe('internal_error');
    const abort = new Error('aborted');
    abort.name = 'AbortError';
    expect(describeError(abort)).toBeNull();
  });

  it('maps a network failure from fetch', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
    );
    await expect(getAnalysis('a')).rejects.toMatchObject({ code: 'network' });
  });
});
