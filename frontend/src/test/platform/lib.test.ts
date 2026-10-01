import { describe, expect, it } from 'vitest';
import { classifyUploadFile, describeTimestamp, parseFilenameTimestamp } from '../../lib/filenames';
import { isoWeek, periodFromQuery } from '../../lib/dates';
import { orgHref, parseAppRoute } from '../../lib/routes';
import { parseSpeciesList } from '../../lib/species';
import { mad, median, rollingBaseline } from '../../lib/stats';

describe('filename timestamps', () => {
  it('parses AudioMoth names as UTC', () => {
    const parsed = parseFilenameTimestamp('20240514_053000.WAV');
    expect(parsed).toMatchObject({
      pattern: 'audiomoth',
      localTimestamp: '2024-05-14T05:30:00',
      clock: 'utc',
    });
    expect(describeTimestamp(parsed)).toBe('2024-05-14 05:30 UTC');
  });

  it('parses prefixed AudioMoth names and Song Meter names', () => {
    expect(parseFilenameTimestamp('PLOT3_20240514_053000.wav')).toMatchObject({
      pattern: 'audiomoth_prefixed',
      localTimestamp: '2024-05-14T05:30:00',
      clock: 'utc',
    });
    expect(parseFilenameTimestamp('SMA12345_20240514_053000.wav')).toMatchObject({
      pattern: 'song_meter',
      clock: 'local',
    });
    expect(parseFilenameTimestamp('SMM01234_20240514_053000.wav').pattern).toBe('song_meter');
  });

  it('parses ISO, spaced and compact names as local time', () => {
    expect(parseFilenameTimestamp('2024-05-14T05-30-00.flac').localTimestamp).toBe(
      '2024-05-14T05:30:00',
    );
    expect(parseFilenameTimestamp('2024-05-14 05.30.00.mp3')).toMatchObject({
      pattern: 'iso_space',
      clock: 'local',
    });
    expect(parseFilenameTimestamp('20240514T053000.wav')).toMatchObject({
      pattern: 'compact',
      clock: 'local',
    });
  });

  it('recognizes Voice Memos names and rejects impossible dates', () => {
    expect(parseFilenameTimestamp('New Recording 7.m4a')).toMatchObject({
      pattern: 'voice_memo',
      localTimestamp: null,
    });
    expect(parseFilenameTimestamp('20241399_053000.WAV').localTimestamp).toBeNull();
    expect(parseFilenameTimestamp('holiday-birds.wav').localTimestamp).toBeNull();
  });

  it('classifies upload files', () => {
    expect(classifyUploadFile('a.WAV')).toBe('audio');
    expect(classifyUploadFile('card.zip')).toBe('zip');
    expect(classifyUploadFile('SMA12345_Summary.txt')).toBe('sidecar');
    expect(classifyUploadFile('CONFIG.TXT')).toBe('sidecar');
    expect(classifyUploadFile('notes.txt')).toBe('unsupported');
    expect(classifyUploadFile('photo.jpg')).toBe('unsupported');
  });
});

describe('routes', () => {
  it('parses hash routes and queries', () => {
    expect(parseAppRoute('')).toEqual({ route: { name: 'home' }, query: new URLSearchParams() });
    expect(parseAppRoute('#/orgs/org_1').route).toEqual({
      name: 'org',
      org: 'org_1',
      page: 'dashboard',
      id: null,
    });
    expect(parseAppRoute('#/orgs/org_1/sites/site_9?period=30').route).toEqual({
      name: 'org',
      org: 'org_1',
      page: 'site',
      id: 'site_9',
    });
    expect(parseAppRoute('#/orgs/org_1/sites/site_9?period=30').query.get('period')).toBe('30');
    expect(parseAppRoute('#/orgs/org_1/reports/new').route).toMatchObject({ page: 'report_new' });
    expect(parseAppRoute('#/invite/tok_1').route).toEqual({ name: 'invite', token: 'tok_1' });
    expect(parseAppRoute('#/methods').route).toEqual({ name: 'methods' });
    expect(parseAppRoute('#/orgs/org_1/nothing').route).toMatchObject({ name: 'not_found' });
  });

  it('builds hrefs with encoded ids and query strings', () => {
    expect(orgHref('org 1', 'recording', 'rc/2', { site_id: 's', empty: null })).toBe(
      '#/orgs/org%201/recordings/rc%2F2?site_id=s',
    );
    expect(orgHref('o', 'report_new')).toBe('#/orgs/o/reports/new');
  });
});

describe('dates and stats', () => {
  it('derives periods from the query with a 90 day default', () => {
    const today = new Date(2026, 8, 30);
    expect(periodFromQuery(new URLSearchParams(''), today)).toEqual({
      preset: '90',
      from: '2026-07-03',
      to: '2026-09-30',
    });
    expect(periodFromQuery(new URLSearchParams('period=30'), today).from).toBe('2026-09-01');
    expect(periodFromQuery(new URLSearchParams('from=2026-05-01&to=2026-05-31'), today)).toEqual({
      preset: 'custom',
      from: '2026-05-01',
      to: '2026-05-31',
    });
  });

  it('computes ISO weeks', () => {
    expect(isoWeek(new Date(2026, 0, 1))).toEqual({ year: 2026, week: 1 });
    expect(isoWeek(new Date(2024, 11, 30))).toEqual({ year: 2025, week: 1 });
  });

  it('uses median and MAD for the baseline band', () => {
    expect(median([5, 1, 3])).toBe(3);
    expect(mad([1, 2, 3, 4, 100])).toBe(1);
    const band = rollingBaseline([1, 2, 3, 4, 5, 6, 7], 7, 5);
    expect(band[3]!.center).toBeNull();
    expect(band[4]).toEqual({ center: 3, low: 2, high: 4 });
  });
});

describe('species list', () => {
  it('normalizes and validates Genus species names', () => {
    const parsed = parseSpeciesList(
      'dolichonyx oryzivorus\nSturnella magna, Bobolink\nSturnella magna',
    );
    expect(parsed.valid).toEqual(['Dolichonyx oryzivorus', 'Sturnella magna']);
    expect(parsed.invalid).toEqual(['Bobolink']);
  });
});
