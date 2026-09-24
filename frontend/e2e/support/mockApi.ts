/**
 * Playwright route mocks for the Thicket API, so e2e tests run without a
 * backend. Responses come from the shared typed fixtures.
 */
import type { Page, Route } from '@playwright/test';
import type {
  AnalysisList,
  ErrorResponse,
  EventReviewUpdate,
  ModelsResponse,
  ReviewStatus,
} from '../../src/api/generated';
import {
  ANALYSIS_ID,
  DURATION,
  MODELS,
  PREVIEW,
  buildAnalysis,
  pendingAnalysis,
  rawDetections,
  type BuildOptions,
} from '../../src/test/fixtures/analysis';
import { syntheticSpectrogram, type CallSpec } from './png';

const CALL_STYLE: Record<string, Omit<CallSpec, 'start' | 'end' | 'strength'>> = {
  'Turdus migratorius': { lowHz: 2000, highHz: 3600, kind: 'trill' },
  'Cardinalis cardinalis': { lowHz: 1800, highHz: 5200, kind: 'whistle' },
  'Melospiza melodia': { lowHz: 2600, highHz: 7200, kind: 'buzz' },
  'Agelaius phoeniceus': { lowHz: 2400, highHz: 4800, kind: 'trill' },
  'Pseudacris crucifer': { lowHz: 2800, highHz: 3100, kind: 'tone' },
  'Dumetella carolinensis': { lowHz: 1500, highHz: 5000, kind: 'buzz' },
  'Poecile atricapillus': { lowHz: 3200, highHz: 4200, kind: 'whistle' },
  'Oecanthus fultoni': { lowHz: 2600, highHz: 2800, kind: 'tone' },
  'Passerina ciris': { lowHz: 3000, highHz: 6000, kind: 'trill' },
  'Human vocal': { lowHz: 200, highHz: 1200, kind: 'buzz' },
  Engine: { lowHz: 80, highHz: 600, kind: 'buzz' },
};

let spectrogramCache: Buffer | null = null;

export function spectrogramPng(): Buffer {
  if (!spectrogramCache) {
    const calls: CallSpec[] = rawDetections().map((d) => ({
      start: d.start_seconds,
      end: d.end_seconds,
      strength: d.confidence,
      ...(CALL_STYLE[d.scientific_name] ?? { lowHz: 2000, highHz: 4000, kind: 'whistle' as const }),
    }));
    spectrogramCache = syntheticSpectrogram(DURATION, 12000, calls);
  }
  return spectrogramCache;
}

const PROCESSING_STAGES = [
  'normalizing',
  'quality',
  'spectrogram',
  'model:birdnet',
  'consolidating',
  'metrics',
];

export interface MockOptions {
  models?: ModelsResponse;
  /** Poll responses that are still processing before the result is completed. */
  pollsBeforeComplete?: number;
  /** Applied to every completed analysis. */
  analysis?: BuildOptions;
  /** Responses for POST /analyses before it succeeds (e.g. a 500 to test retry). */
  createFailures?: Array<{ status: number; body: ErrorResponse | string }>;
  /** Milliseconds to delay analysis GETs (to observe loading states). */
  analysisDelayMs?: number;
}

export interface MockState {
  createCalls: number;
  previewCalls: number;
  analysisGets: string[];
  reviews: Record<string, ReviewStatus>;
  deleted: string[];
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

export async function mockApi(page: Page, options: MockOptions = {}): Promise<MockState> {
  const state: MockState = {
    createCalls: 0,
    previewCalls: 0,
    analysisGets: [],
    reviews: {},
    deleted: [],
  };
  const failures = [...(options.createFailures ?? [])];
  let pollsLeft = options.pollsBeforeComplete ?? 3;
  let stageIndex = 0;

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^.*\/api\/v1/, '');
    const method = request.method();

    if (method === 'GET' && path === '/health') {
      return json(route, 200, {
        status: 'ok',
        version: '0.1.0',
        environment: 'test',
        models: { birdnet: 'ready' },
        ffmpeg: true,
      });
    }
    if (method === 'GET' && path === '/models') {
      return json(route, 200, options.models ?? MODELS);
    }
    if (method === 'POST' && path === '/previews') {
      state.previewCalls += 1;
      return json(route, 201, PREVIEW);
    }
    if (path.endsWith('/spectrogram.png')) {
      return route.fulfill({ status: 200, contentType: 'image/png', body: spectrogramPng() });
    }
    if (method === 'POST' && path === '/analyses') {
      state.createCalls += 1;
      const failure = failures.shift();
      if (failure) return json(route, failure.status, failure.body);
      pollsLeft = options.pollsBeforeComplete ?? 3;
      stageIndex = 0;
      return json(route, 202, pendingAnalysis('queued', 'queued'));
    }
    if (method === 'GET' && path === '/analyses') {
      const list: AnalysisList = {
        items: [
          {
            id: ANALYSIS_ID,
            status: 'completed',
            filename: 'hollow-creek-dawn.wav',
            site_name: 'Hollow Creek Easement, north meadow',
            created_at: '2026-09-24T13:12:08Z',
            duration_seconds: DURATION,
            species_richness: 6,
            total_detection_events: 14,
            decision_threshold: 0.6,
            top_species: ['American Robin', 'Northern Cardinal', 'Song Sparrow'],
          },
        ],
      };
      return json(route, 200, list);
    }
    const exportMatch = /^\/analyses\/([^/]+)\/export\.(csv|json)$/.exec(path);
    if (method === 'GET' && exportMatch) {
      const threshold = Number(url.searchParams.get('threshold') ?? '0.6');
      const analysis = buildAnalysis({ ...options.analysis, threshold, reviews: state.reviews });
      if (exportMatch[2] === 'json') return json(route, 200, analysis);
      return route.fulfill({
        status: 200,
        contentType: 'text/csv',
        headers: { 'Content-Disposition': `attachment; filename="thicket-${analysis.id}.csv"` },
        body: 'analysis_id,taxon\n',
      });
    }
    const analysisMatch = /^\/analyses\/([^/]+)$/.exec(path);
    if (analysisMatch && method === 'DELETE') {
      state.deleted.push(analysisMatch[1]!);
      return route.fulfill({ status: 204, body: '' });
    }
    if (analysisMatch && method === 'GET') {
      state.analysisGets.push(url.search);
      if (options.analysisDelayMs) await new Promise((r) => setTimeout(r, options.analysisDelayMs));
      if (pollsLeft > 0) {
        pollsLeft -= 1;
        const stage = PROCESSING_STAGES[Math.min(stageIndex, PROCESSING_STAGES.length - 1)]!;
        stageIndex += 2;
        return json(route, 200, pendingAnalysis(stage));
      }
      const threshold = url.searchParams.has('threshold')
        ? Number(url.searchParams.get('threshold'))
        : 0.6;
      return json(
        route,
        200,
        buildAnalysis({ ...options.analysis, threshold, reviews: state.reviews }),
      );
    }
    const eventMatch = /^\/events\/([^/]+)$/.exec(path);
    if (eventMatch && method === 'PATCH') {
      const body = request.postDataJSON() as EventReviewUpdate;
      state.reviews[decodeURIComponent(eventMatch[1]!)] = body.review_status;
      return json(route, 200, { id: eventMatch[1], review_status: body.review_status });
    }
    return json(route, 404, {
      error_code: 'analysis_not_found',
      message: `No mock for ${method} ${path}`,
    });
  });

  return state;
}
