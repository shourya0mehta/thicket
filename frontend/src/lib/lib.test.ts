import { describe, expect, it } from 'vitest';
import { buildAnalysis } from '../test/fixtures/analysis';
import {
  buildTimelineLanes,
  countedSpecies,
  eventsAtTime,
  hasNoDetections,
  hasValidCoordinates,
  otherSoundGroups,
  runLabel,
  unlikelyGroups,
} from './analysis';
import { CSV_COLUMNS, analysisToCsv, csvCell } from './csv';
import { demoThresholdFile } from './demo';
import { formatBytes, formatClock, formatClockPrecise, formatDuration } from './format';
import { addToHistory, entryFromAnalysis, readHistory, removeFromHistory } from './history';
import {
  defaultSelection,
  modelDisplay,
  modelShortName,
  modelsForSelection,
  visibleModels,
} from './models';
import { snapThreshold, thresholdBounds } from './threshold';
import { validateAudioFile, validateMetadata, zonedLocalToIso } from './validation';
import { MODELS } from '../test/fixtures/analysis';
import type { DetectionEvent } from '../api/types';

describe('format', () => {
  it('formats sizes, clocks and durations', () => {
    expect(formatBytes(20 * 1024 * 1024)).toBe('20 MB');
    expect(formatBytes(5_760_044)).toBe('5.5 MB');
    expect(formatClock(62)).toBe('1:02');
    expect(formatClock(3723)).toBe('1:02:03');
    expect(formatClockPrecise(12.5)).toBe('0:12.5');
    expect(formatDuration(60)).toBe('1 min 00 s');
    expect(formatDuration(4.25)).toBe('4.3 s');
  });
});

describe('threshold', () => {
  it('snaps to the 0.05 grid from the ingestion floor', () => {
    expect(snapThreshold(0.4499999, 0.1)).toBe(0.45);
    expect(snapThreshold(0.03, 0.1)).toBe(0.1);
    expect(snapThreshold(0.99, 0.1)).toBe(0.95);
    expect(thresholdBounds(0.1)).toEqual({ min: 0.1, max: 0.95 });
    expect(thresholdBounds(undefined).min).toBe(0.1);
  });

  it('names demo files with two decimals', () => {
    expect(demoThresholdFile(0.6)).toBe('threshold-0.60.json');
    expect(demoThresholdFile(0.15000000000000002)).toBe('threshold-0.15.json');
    expect(demoThresholdFile(0.02)).toBe('threshold-0.10.json');
  });
});

describe('validation', () => {
  it('validates coordinate ranges and pairs', () => {
    const base = { siteName: '', latitude: '', longitude: '', capturedAt: '', timezone: 'UTC' };
    expect(validateMetadata(base)).toEqual({});
    expect(validateMetadata({ ...base, latitude: '91', longitude: '0' }).latitude).toMatch(
      /-90 and 90/,
    );
    expect(validateMetadata({ ...base, latitude: '10', longitude: '-181' }).longitude).toMatch(
      /-180 and 180/,
    );
    expect(validateMetadata({ ...base, latitude: 'abc', longitude: '1' }).latitude).toBeDefined();
    expect(validateMetadata({ ...base, latitude: '10' }).longitude).toMatch(/Add a longitude/);
    expect(validateMetadata({ ...base, timezone: 'Mars/Olympus' }).timezone).toBeDefined();
  });

  it('converts site wall-clock time to ISO with the zone offset', () => {
    expect(zonedLocalToIso('2026-05-14T05:42', 'America/New_York')).toBe(
      '2026-05-14T05:42:00-04:00',
    );
    expect(zonedLocalToIso('2026-01-14T05:42', 'America/New_York')).toBe(
      '2026-01-14T05:42:00-05:00',
    );
    expect(zonedLocalToIso('2026-07-01T12:00', 'Asia/Kolkata')).toBe('2026-07-01T12:00:00+05:30');
    expect(zonedLocalToIso('2026-07-01T12:00', 'UTC')).toBe('2026-07-01T12:00:00+00:00');
    expect(zonedLocalToIso('nope', 'UTC')).toBeNull();
  });

  it('checks extension and size case-insensitively', () => {
    expect(validateAudioFile(new File(['x'], 'A.WAV')).ok).toBe(true);
    expect(validateAudioFile(new File(['x'], 'clip.m4a')).ok).toBe(true);
    expect(validateAudioFile(new File(['x'], 'clip.ogg')).ok).toBe(false);
    expect(validateAudioFile(new File([], 'empty.wav')).ok).toBe(false);
  });
});

describe('analysis view helpers', () => {
  const analysis = buildAnalysis({ threshold: 0.45 });

  it('never counts other sounds or unlikely species', () => {
    const names = countedSpecies(analysis).map((s) => s.common_name);
    expect(names).not.toContain('Painted Bunting');
    expect(names).not.toContain('Human vocal');
    expect(unlikelyGroups(analysis).map((g) => g.commonName)).toEqual(['Painted Bunting']);
    const other = otherSoundGroups(analysis);
    expect(other.map((g) => [g.commonName, g.windows])).toEqual([
      ['Human vocal', 2],
      ['Engine', 1],
    ]);
  });

  it('rejects fake or missing coordinates', () => {
    const rec = analysis.recording!;
    expect(hasValidCoordinates(rec)).toBe(true);
    expect(hasValidCoordinates({ ...rec, latitude: null })).toBe(false);
    expect(hasValidCoordinates({ ...rec, latitude: 0, longitude: 0 })).toBe(false);
    expect(hasValidCoordinates({ ...rec, latitude: 95, longitude: 10 })).toBe(false);
    expect(hasValidCoordinates({ ...rec, latitude: Number.NaN, longitude: 10 })).toBe(false);
    expect(hasValidCoordinates(null)).toBe(false);
  });

  it('puts overlapping events of one species on separate rows', () => {
    const base = analysis.events.find((e) => e.common_name === 'American Robin')!;
    const events: DetectionEvent[] = [
      { ...base, id: 'a', start_seconds: 0, end_seconds: 6 },
      { ...base, id: 'b', start_seconds: 3, end_seconds: 9 },
      { ...base, id: 'c', start_seconds: 9, end_seconds: 12 },
    ];
    const [lane] = buildTimelineLanes(events);
    expect(lane!.rows.map((row) => row.map((e) => e.id))).toEqual([['a', 'c'], ['b']]);
    expect(eventsAtTime(events, 4)).toEqual(new Set(['a', 'b']));
  });

  it('detects the no-detections state', () => {
    expect(hasNoDetections(buildAnalysis({ confidenceScale: 0.5 }))).toBe(true);
    expect(hasNoDetections(analysis)).toBe(false);
  });
});

describe('CSV export', () => {
  it('uses the backend column order and escapes cells', () => {
    const csv = analysisToCsv(buildAnalysis({ threshold: 0.6 }));
    const [header, first] = csv.split('\n');
    // Python float formatting and formula-safe text, exactly like the backend.
    const robin = csv.split('\n').find((line) => line.includes('Turdus migratorius'))!;
    expect(robin).toContain(',0.0,9.0,0.91,');
    expect(robin).toContain(',-76.4735,');
    expect(robin).toContain(',0.6,plausible,unreviewed');
    expect(csvCell('=SUM(A1)')).toBe("'=SUM(A1)");
    expect(csvCell(-3)).toBe('-3');
    expect(header).toBe(CSV_COLUMNS.join(','));
    expect(first).toContain('"Hollow Creek Easement, north meadow"');
    expect(first).toContain(',0.6,');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell(null)).toBe('');
  });
});

describe('history', () => {
  it('keeps the last three summaries, newest first, without duplicates', () => {
    const a = entryFromAnalysis(buildAnalysis());
    for (const id of ['1', '2', '3', '4']) addToHistory({ ...a, id });
    addToHistory({ ...a, id: '3' });
    expect(readHistory().map((e) => e.id)).toEqual(['3', '4', '2']);
    removeFromHistory('4');
    expect(readHistory().map((e) => e.id)).toEqual(['3', '2']);
  });

  it('ignores corrupt storage', () => {
    window.localStorage.setItem('thicket-history', '{not json');
    expect(readHistory()).toEqual([]);
    window.localStorage.setItem('thicket-history', JSON.stringify([{ id: 1 }]));
    expect(readHistory()).toEqual([]);
  });
});

describe('run labels', () => {
  it('does not repeat a version already in the model name', () => {
    expect(runLabel('BirdNET GLOBAL 6K V2.4', '2.4')).toBe('BirdNET GLOBAL 6K V2.4');
    expect(runLabel('Perch', '2.0')).toBe('Perch 2.0');
    expect(runLabel('Birds and more \u2014 BirdNET', 'v2.4')).toBe('Birds and more · BirdNET v2.4');
  });
});

describe('models', () => {
  it('labels BirdNET without em dashes and hides experimental models by default', () => {
    const birdnet = MODELS.models[0]!;
    expect(modelDisplay(birdnet)).toMatchObject({
      title: 'Birds and more',
      subtitle: 'BirdNET v2.4',
    });
    expect(visibleModels(MODELS.models, false).map((m) => m.key)).toEqual(['birdnet']);
    expect(visibleModels(MODELS.models, true).map((m) => m.key)).toEqual([
      'birdnet',
      'frogs_insects',
      'perch',
    ]);
    expect(defaultSelection(MODELS.models)).toBe('birdnet');
    expect(modelsForSelection('combined', MODELS.models)).toEqual(['birdnet', 'perch']);
  });
});

describe('model short names', () => {
  it('uses readable titles for stage labels', () => {
    const odd = {
      ...MODELS.models[1]!,
      key: 'frog_insect',
      name: 'Frogs and insects',
      version: 'unvalidated',
    };
    expect(modelShortName('birdnet')).toBe('BirdNET');
    expect(modelShortName('frog_insect', [odd])).toBe('Frogs and insects');
    expect(modelDisplay(odd).subtitle).toBe('Version: unvalidated');
    expect(modelShortName('perch', MODELS.models)).toBe('Perch 2.0');
    expect(modelShortName('mystery')).toBe('mystery');
  });
});
