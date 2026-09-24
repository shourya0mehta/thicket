import { MAX_FILE_BYTES } from '../config';
import { formatBytes } from '../lib/format';
import { ApiError, isAbortError, type ApiErrorCode } from './client';

export type ErrorAction = 'retry' | 'choose_file' | 'choose_model' | 'none';

export interface FriendlyError {
  code: ApiErrorCode | 'unknown';
  title: string;
  body: string;
  /** Server-provided message, shown as secondary detail when it adds something. */
  detail: string | null;
  action: ErrorAction;
}

type Copy = Omit<FriendlyError, 'code' | 'detail'>;

const COPY: Record<ApiErrorCode | 'unknown', Copy> = {
  unsupported_file_type: {
    title: 'This file type is not supported',
    body: 'Choose a .wav, .mp3, .m4a or .flac recording.',
    action: 'choose_file',
  },
  file_too_large: {
    title: 'This file is too large',
    body: `Recordings must be ${formatBytes(MAX_FILE_BYTES)} or smaller. Trim the recording or export it at a lower bitrate.`,
    action: 'choose_file',
  },
  audio_too_long: {
    title: 'This recording is too long',
    body: 'Split it into shorter clips and analyze them one at a time.',
    action: 'choose_file',
  },
  audio_decode_failed: {
    title: 'The audio could not be decoded',
    body: 'The file may be damaged or use an unusual codec. Try exporting it again as WAV or FLAC.',
    action: 'choose_file',
  },
  audio_too_short: {
    title: 'This recording is too short',
    body: 'Models listen in 3 second windows. Use a recording that is at least a few seconds long.',
    action: 'choose_file',
  },
  model_unavailable: {
    title: 'The model is not available right now',
    body: 'It may still be loading or may not be installed on this server. Try again in a moment or choose another model.',
    action: 'choose_model',
  },
  unknown_model: {
    title: 'This server does not recognize that model',
    body: 'Reload the page to refresh the model list, then choose again.',
    action: 'choose_model',
  },
  invalid_parameter: {
    title: 'Some settings were not accepted',
    body: 'Check the location, date and model settings, then try again.',
    action: 'none',
  },
  analysis_not_found: {
    title: 'This analysis is no longer available',
    body: 'It may have been deleted or may have expired on the server.',
    action: 'none',
  },
  event_not_found: {
    title: 'That detection event no longer exists',
    body: 'The results were refreshed. Try the review again.',
    action: 'none',
  },
  analysis_timeout: {
    title: 'The analysis took too long',
    body: 'Try a shorter recording, or try again when the server is less busy.',
    action: 'retry',
  },
  internal_error: {
    title: 'Something went wrong on the server',
    body: 'Try again. If it keeps happening, check the Thicket server logs.',
    action: 'retry',
  },
  unsupported_audio: {
    title: 'This audio cannot be analyzed',
    body: 'Its sample rate, channels or frequency band are not supported by the model. Try a standard WAV or FLAC recording at 22 kHz or higher.',
    action: 'choose_file',
  },
  not_found: {
    title: 'Not found on the server',
    body: 'The item may have been deleted or may have expired.',
    action: 'none',
  },
  rate_limited: {
    title: 'The server is busy',
    body: 'Too many requests arrived at once. Wait a few seconds, then try again.',
    action: 'retry',
  },
  request_timeout: {
    title: 'The upload timed out',
    body: 'The connection was too slow for this file. Try again, ideally on a faster connection.',
    action: 'retry',
  },
  network: {
    title: 'Cannot reach the Thicket server',
    body: 'Make sure the backend is running (by default on port 8000), then try again.',
    action: 'retry',
  },
  backend_unavailable: {
    title: 'The Thicket server is unavailable',
    body: 'The server did not respond normally. Make sure the backend is running, then try again.',
    action: 'retry',
  },
  invalid_response: {
    title: 'Unexpected response from the server',
    body: 'The frontend and backend versions may not match. Try again, or update both.',
    action: 'retry',
  },
  unknown: {
    title: 'Something went wrong',
    body: 'Try again.',
    action: 'retry',
  },
};

export function describeErrorCode(
  code: ApiErrorCode | 'unknown',
  serverMessage?: string | null,
): FriendlyError {
  const copy = COPY[code];
  const detail =
    serverMessage && serverMessage.trim()
      ? serverMessage.trim().replace(/\s*[\u2014\u2013]\s*/g, ' · ')
      : null;
  return {
    code,
    ...copy,
    // Avoid repeating the same sentence twice.
    detail: detail && detail !== copy.body && detail !== copy.title ? detail : null,
  };
}

export function describeError(error: unknown): FriendlyError | null {
  if (isAbortError(error)) return null;
  if (error instanceof ApiError) {
    // Only server responses carry a message worth showing; client-side
    // failures (network, parsing) are fully described by the copy above.
    return describeErrorCode(error.code, error.status != null ? error.message : null);
  }
  if (error instanceof Error) return describeErrorCode('unknown', error.message);
  return describeErrorCode('unknown');
}
