/**
 * Typed fixtures for the multi-tenant platform (docs/PLATFORM_API.md). Series
 * are generated deterministically from a seed so the dashboard, site and
 * recorder pages always have a full, plausible season of data regardless of
 * the current date. Used by unit tests, Playwright route mocks and screenshots.
 */
import type {
  Accumulation,
  Alert,
  AlertRules,
  AuthConfig,
  BatchJob,
  Dashboard,
  DayPoint,
  Deployment,
  HeatCell,
  IndexPoint,
  Invite,
  Me,
  Membership,
  NotificationPage,
  NotificationPrefs,
  Organization,
  Phenology,
  PhenologyCell,
  Recorder,
  RecorderHealth,
  RecordingSummary,
  Report,
  ReportField,
  ReportTemplate,
  ReportTemplates,
  SeriesPoint,
  Site,
  SiteComparison,
  SpeciesRollup,
  Taxon,
  User,
} from '../../api/generated';

/* Deterministic pseudo-random numbers (mulberry32 seeded from a string). */

function hashString(text: string): number {
  let h = 1779033703 ^ text.length;
  for (let i = 0; i < text.length; i += 1) {
    h = Math.imul(h ^ text.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return h >>> 0;
}

export function rng(seed: string): () => number {
  let a = hashString(seed);
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const pad = (n: number) => String(n).padStart(2, '0');
export function dateKey(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function dayOfYear(d: Date): number {
  const start = new Date(d.getFullYear(), 0, 0);
  return Math.floor((d.getTime() - start.getTime()) / 86_400_000);
}

/* Tenancy */

export const ORG_ID = 'org_hollow_creek';
export const USER_ID = 'usr_jane';

export const USER: User = {
  id: USER_ID,
  email: 'jane@hollowcreek.example',
  name: 'Jane Farmer',
  created_at: '2026-03-02T14:00:00Z',
  last_login_at: '2026-09-29T11:20:00Z',
};

export const ORG: Organization = {
  id: ORG_ID,
  slug: 'hollow-creek-farm',
  name: 'Hollow Creek Farm',
  kind: 'farm',
  timezone: 'America/New_York',
  region: 'New York',
  country: 'US',
  created_at: '2026-03-02T14:05:00Z',
  member_count: 3,
  site_count: 3,
};

export const SECOND_ORG: Organization = {
  id: 'org_fall_creek',
  slug: 'fall-creek-land-trust',
  name: 'Fall Creek Land Trust',
  kind: 'land_trust',
  timezone: 'America/New_York',
  region: 'New York',
  country: 'US',
  created_at: '2026-05-10T09:00:00Z',
  member_count: 6,
  site_count: 5,
};

export function me(
  options: {
    organizations?: Organization[];
    role?: Me['roles'][string];
    mode?: AuthConfig['mode'];
  } = {},
): Me {
  const organizations = options.organizations ?? [ORG];
  const roles: Me['roles'] = {};
  for (const o of organizations) roles[o.id] = options.role ?? 'owner';
  return {
    auth_mode: options.mode ?? 'dev',
    user: USER,
    organizations,
    roles,
    unread_notifications: 2,
  };
}

export const AUTH_DEV: AuthConfig = { mode: 'dev' };
export const AUTH_GOOGLE: AuthConfig = {
  mode: 'google',
  google_client_id: 'test-client',
  sign_in_url: '/api/v1/auth/google/start',
  allowed_domains: ['hollowcreek.example'],
};
export const AUTH_DISABLED: AuthConfig = { mode: 'disabled' };

export const MEMBERS: Membership[] = [
  { user: USER, role: 'owner', joined_at: '2026-03-02T14:05:00Z' },
  {
    user: {
      id: 'usr_sam',
      email: 'sam@hollowcreek.example',
      name: 'Sam Ortiz',
      created_at: '2026-03-10T10:00:00Z',
    },
    role: 'manager',
    joined_at: '2026-03-10T10:00:00Z',
  },
  {
    user: {
      id: 'usr_lee',
      email: 'lee.swcd@example.org',
      name: 'Lee Park',
      created_at: '2026-04-01T10:00:00Z',
    },
    role: 'viewer',
    joined_at: '2026-04-01T10:00:00Z',
  },
];

export const INVITES: Invite[] = [
  {
    id: 'inv_7a2b',
    organization_id: ORG_ID,
    email: 'planner@example.org',
    role: 'reviewer',
    invited_by: USER_ID,
    expires_at: '2026-10-14T00:00:00Z',
    accept_url: 'http://localhost:5173/#/invite/tok_planner_7a2b',
  },
];

/* Sites, recorders, deployments */

export const SITE_NORTH = 'site_north_pasture';
export const SITE_POND = 'site_mill_pond';
export const SITE_HEDGE = 'site_hedgerow';

export const SITES: Site[] = [
  {
    id: SITE_NORTH,
    organization_id: ORG_ID,
    name: 'North pasture',
    habitat_type: 'pasture',
    latitude: 42.4531,
    longitude: -76.4735,
    area_hectares: 18.4,
    fsa_field_number: '4',
    paddock_id: 'P4',
    notes: 'Rotationally grazed, 12 paddocks. Recorder on the fence post by the water trough.',
    created_at: '2026-03-03T15:00:00Z',
    stats: {
      recordings: 412,
      minutes_recorded: 2061,
      species_counted: 31,
      first_recording_at: '2026-04-02T09:30:00Z',
      last_recording_at: '2026-09-29T10:05:00Z',
      open_alerts: 2,
      health: 'good',
    },
  },
  {
    id: SITE_POND,
    organization_id: ORG_ID,
    name: 'Mill pond edge',
    habitat_type: 'pond',
    latitude: 42.4498,
    longitude: -76.4802,
    area_hectares: 2.1,
    fsa_field_number: '7',
    paddock_id: null,
    notes: 'Spring peeper chorus in April; the recorder sits 3 m from the water.',
    created_at: '2026-03-03T15:10:00Z',
    stats: {
      recordings: 298,
      minutes_recorded: 1490,
      species_counted: 24,
      first_recording_at: '2026-04-05T23:00:00Z',
      last_recording_at: '2026-09-28T02:10:00Z',
      open_alerts: 1,
      health: 'watch',
    },
  },
  {
    id: SITE_HEDGE,
    organization_id: ORG_ID,
    name: 'Hedgerow lane',
    habitat_type: 'shrubland',
    latitude: null,
    longitude: null,
    area_hectares: null,
    fsa_field_number: null,
    paddock_id: null,
    notes: null,
    created_at: '2026-06-20T12:00:00Z',
    stats: {
      recordings: 36,
      minutes_recorded: 180,
      species_counted: 12,
      first_recording_at: '2026-07-01T09:00:00Z',
      last_recording_at: '2026-08-14T09:00:00Z',
      open_alerts: 1,
      health: 'attention',
    },
  },
];

export const RECORDER_MOTH1 = 'rec_moth_1';
export const RECORDER_MOTH2 = 'rec_moth_2';
export const RECORDER_SM = 'rec_sm_mini';

export const RECORDERS: Recorder[] = [
  {
    id: RECORDER_MOTH1,
    organization_id: ORG_ID,
    label: 'Moth 1',
    make: 'audiomoth',
    model: 'AudioMoth 1.2.0',
    serial: '24A1D5F3C9',
    firmware: '1.11.0',
    notes: 'Medium gain, 48 kHz.',
    created_at: '2026-03-20T10:00:00Z',
    active_deployment_id: 'dep_1',
    last_recording_at: '2026-09-29T10:05:00Z',
    health: 'good',
  },
  {
    id: RECORDER_MOTH2,
    organization_id: ORG_ID,
    label: 'Moth 2',
    make: 'audiomoth',
    model: 'AudioMoth 1.2.0',
    serial: '24A1D5F3D1',
    firmware: '1.11.0',
    notes: null,
    created_at: '2026-03-20T10:05:00Z',
    active_deployment_id: 'dep_2',
    last_recording_at: '2026-09-28T02:10:00Z',
    health: 'watch',
  },
  {
    id: RECORDER_SM,
    organization_id: ORG_ID,
    label: 'SM Mini (hedgerow)',
    make: 'song_meter',
    model: 'Song Meter Mini 2',
    serial: 'SMM01234',
    firmware: '2.3',
    notes: 'Borrowed from the SWCD.',
    created_at: '2026-06-20T12:05:00Z',
    active_deployment_id: 'dep_3',
    last_recording_at: '2026-08-14T09:00:00Z',
    health: 'attention',
  },
];

export const DEPLOYMENTS: Deployment[] = [
  {
    id: 'dep_1',
    organization_id: ORG_ID,
    recorder_id: RECORDER_MOTH1,
    site_id: SITE_NORTH,
    started_at: '2026-04-02T09:00:00Z',
    ended_at: null,
    expected_interval_minutes: 30,
    expected_clip_seconds: 300,
    schedule_description: '5 min every 30 min, 04:30 to 09:30 and 19:00 to 22:00',
    gain_setting: 'Medium',
    mount_height_m: 1.5,
    orientation: 'Facing south, open aspect',
    notes: null,
    created_at: '2026-04-02T09:00:00Z',
  },
  {
    id: 'dep_2',
    organization_id: ORG_ID,
    recorder_id: RECORDER_MOTH2,
    site_id: SITE_POND,
    started_at: '2026-04-05T22:00:00Z',
    ended_at: null,
    expected_interval_minutes: 60,
    expected_clip_seconds: 300,
    schedule_description: '5 min every hour, dusk to dawn',
    gain_setting: 'Medium',
    mount_height_m: 1.2,
    orientation: 'Facing the water',
    notes: null,
    created_at: '2026-04-05T22:00:00Z',
  },
  {
    id: 'dep_3',
    organization_id: ORG_ID,
    recorder_id: RECORDER_SM,
    site_id: SITE_HEDGE,
    started_at: '2026-07-01T08:00:00Z',
    ended_at: null,
    expected_interval_minutes: 60,
    expected_clip_seconds: 300,
    schedule_description: null,
    gain_setting: null,
    mount_height_m: null,
    orientation: null,
    notes: null,
    created_at: '2026-07-01T08:00:00Z',
  },
];

/* Species */

interface SpeciesSpec {
  sci: string;
  common: string;
  taxon: Taxon;
  presence: number;
  events: number;
  priority?: boolean;
  sites?: string[];
}

export const SPECIES_SPECS: SpeciesSpec[] = [
  {
    sci: 'Turdus migratorius',
    common: 'American Robin',
    taxon: 'bird',
    presence: 0.82,
    events: 1840,
  },
  { sci: 'Melospiza melodia', common: 'Song Sparrow', taxon: 'bird', presence: 0.74, events: 1312 },
  {
    sci: 'Cardinalis cardinalis',
    common: 'Northern Cardinal',
    taxon: 'bird',
    presence: 0.66,
    events: 980,
  },
  {
    sci: 'Agelaius phoeniceus',
    common: 'Red-winged Blackbird',
    taxon: 'bird',
    presence: 0.61,
    events: 1105,
    sites: [SITE_NORTH, SITE_POND],
  },
  {
    sci: 'Dolichonyx oryzivorus',
    common: 'Bobolink',
    taxon: 'bird',
    presence: 0.38,
    events: 412,
    priority: true,
    sites: [SITE_NORTH],
  },
  {
    sci: 'Sturnella magna',
    common: 'Eastern Meadowlark',
    taxon: 'bird',
    presence: 0.29,
    events: 260,
    priority: true,
    sites: [SITE_NORTH],
  },
  {
    sci: 'Passerculus sandwichensis',
    common: 'Savannah Sparrow',
    taxon: 'bird',
    presence: 0.44,
    events: 530,
    sites: [SITE_NORTH],
  },
  {
    sci: 'Dumetella carolinensis',
    common: 'Gray Catbird',
    taxon: 'bird',
    presence: 0.52,
    events: 640,
  },
  {
    sci: 'Poecile atricapillus',
    common: 'Black-capped Chickadee',
    taxon: 'bird',
    presence: 0.47,
    events: 455,
  },
  {
    sci: 'Geothlypis trichas',
    common: 'Common Yellowthroat',
    taxon: 'bird',
    presence: 0.41,
    events: 398,
  },
  {
    sci: 'Pseudacris crucifer',
    common: 'Spring Peeper',
    taxon: 'amphibian',
    presence: 0.33,
    events: 2210,
    sites: [SITE_POND],
  },
  {
    sci: 'Hyla versicolor',
    common: 'Gray Treefrog',
    taxon: 'amphibian',
    presence: 0.21,
    events: 640,
    sites: [SITE_POND],
  },
  {
    sci: 'Lithobates clamitans',
    common: 'Green Frog',
    taxon: 'amphibian',
    presence: 0.18,
    events: 310,
    sites: [SITE_POND],
  },
  {
    sci: 'Oecanthus fultoni',
    common: 'Snowy Tree Cricket',
    taxon: 'insect',
    presence: 0.27,
    events: 1540,
  },
  {
    sci: 'Neoconocephalus ensiger',
    common: 'Sword-bearing Conehead',
    taxon: 'insect',
    presence: 0.12,
    events: 220,
  },
  {
    sci: 'Tamias striatus',
    common: 'Eastern Chipmunk',
    taxon: 'mammal',
    presence: 0.09,
    events: 48,
  },
];

export function speciesRollups(siteId?: string | null): SpeciesRollup[] {
  const totalRecordings = siteId
    ? (SITES.find((s) => s.id === siteId)?.stats.recordings ?? 100)
    : SITES.reduce((a, s) => a + (s.stats.recordings ?? 0), 0);
  return SPECIES_SPECS.filter((s) => !siteId || !s.sites || s.sites.includes(siteId)).map((s) => {
    const withDetection = Math.round(s.presence * totalRecordings);
    return {
      scientific_name: s.sci,
      common_name: s.common,
      taxon: s.taxon,
      detection_events: siteId ? Math.round(s.events / 2.4) : s.events,
      recordings_with_detection: withDetection,
      recordings_total: totalRecordings,
      presence_fraction: s.presence,
      max_confidence: 0.97 - (s.events % 7) * 0.01,
      first_detected_at: '2026-04-06T09:30:00Z',
      last_detected_at: '2026-09-28T10:05:00Z',
      is_priority: s.priority ?? false,
      plausibility: 'plausible',
      site_ids: s.sites ?? [SITE_NORTH, SITE_POND, SITE_HEDGE],
    };
  });
}

/* Dashboard */

function seasonalRichness(d: Date, base: number): number {
  // Peaks around the solstice and fades through late summer.
  const doy = dayOfYear(d);
  const season = Math.max(0, Math.cos(((doy - 165) / 365) * 2 * Math.PI));
  return base * (0.45 + 0.75 * season);
}

export function dayPoints(from: string, to: string, siteId?: string | null): DayPoint[] {
  const random = rng(`days:${from}:${to}:${siteId ?? 'all'}`);
  const points: DayPoint[] = [];
  const start = new Date(`${from}T00:00:00`);
  const end = new Date(`${to}T00:00:00`);
  const base = siteId === SITE_POND ? 9 : siteId === SITE_HEDGE ? 7 : siteId ? 13 : 16;
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const r = random();
    // A few quiet days with no recordings (card swaps, flat battery).
    if (r < 0.07) continue;
    if (siteId === SITE_HEDGE && d > new Date('2026-08-14')) continue;
    const recordings = siteId ? 4 + Math.floor(random() * 5) : 9 + Math.floor(random() * 10);
    const minutes = recordings * 5;
    const richness = Math.max(1, Math.round(seasonalRichness(d, base) + (random() - 0.5) * 4));
    const eventsPerMinute = 1.2 + richness * 0.35 + (random() - 0.5) * 0.8;
    const events = Math.round(eventsPerMinute * minutes);
    points.push({
      date: dateKey(d),
      site_id: siteId ?? null,
      recordings,
      minutes,
      species_richness: richness,
      detection_events: events,
      events_per_minute: Math.round(eventsPerMinute * 100) / 100,
      shannon_index:
        Math.round((1.2 + Math.log(richness) * 0.55 + (random() - 0.5) * 0.2) * 100) / 100,
      usable_fraction: Math.round((0.8 + random() * 0.2) * 100) / 100,
    });
  }
  return points;
}

export function heatCells(seed = 'heat'): HeatCell[] {
  const random = rng(seed);
  const cells: HeatCell[] = [];
  for (let weekday = 0; weekday < 7; weekday += 1) {
    for (let hour = 0; hour < 24; hour += 1) {
      const dawn = Math.exp(-((hour - 5.5) ** 2) / 3);
      const dusk = 0.55 * Math.exp(-((hour - 20) ** 2) / 4);
      const scheduled = (hour >= 4 && hour <= 9) || (hour >= 19 && hour <= 22);
      if (!scheduled && random() < 0.85) continue;
      const recordings = scheduled ? 10 + Math.floor(random() * 6) : 1 + Math.floor(random() * 2);
      const epm = Math.max(0.1, (dawn + dusk) * 6 + random() * 0.6);
      cells.push({
        weekday,
        hour,
        recordings,
        events_per_minute: Math.round(epm * 100) / 100,
      });
    }
  }
  return cells;
}

export function indexPoints(days: DayPoint[]): IndexPoint[] {
  const random = rng('indices');
  return days.map((d) => ({
    date: d.date,
    site_id: d.site_id ?? null,
    acoustic_complexity_index: Math.round(1500 + d.species_richness * 25 + random() * 120),
    acoustic_diversity_index:
      Math.round((1.4 + d.species_richness * 0.05 + random() * 0.2) * 100) / 100,
    bioacoustic_index: Math.round((20 + d.events_per_minute * 3 + random() * 6) * 10) / 10,
    ndsi: Math.round((0.3 + random() * 0.5) * 100) / 100,
  }));
}

export function buildDashboard(options: {
  from: string;
  to: string;
  siteId?: string | null;
}): Dashboard {
  const days = dayPoints(options.from, options.to, options.siteId);
  const species = speciesRollups(options.siteId);
  const recordings = days.reduce((a, d) => a + d.recordings, 0);
  const byTaxon = (['bird', 'amphibian', 'insect', 'mammal'] as Taxon[]).map((taxon) => {
    const rows = species.filter((s) => s.taxon === taxon);
    return {
      taxon,
      species: rows.length,
      detection_events: rows.reduce((a, s) => a + s.detection_events, 0),
    };
  });
  return {
    organization_id: ORG_ID,
    period_start: options.from,
    period_end: options.to,
    site_ids: options.siteId ? [options.siteId] : SITES.map((s) => s.id),
    generated_at: new Date().toISOString(),
    recordings,
    minutes_recorded: days.reduce((a, d) => a + d.minutes, 0),
    species_counted: species.length,
    detection_events: days.reduce((a, d) => a + d.detection_events, 0),
    open_alerts: options.siteId
      ? (SITES.find((s) => s.id === options.siteId)?.stats.open_alerts ?? 0)
      : 4,
    richness_by_day: days,
    activity_heatmap: heatCells(`heat:${options.siteId ?? 'all'}`),
    species,
    by_taxon: byTaxon,
    indices_by_day: indexPoints(days),
    quality: {
      usable: Math.round(recordings * 0.81),
      usable_with_warnings: Math.round(recordings * 0.14),
      not_usable: recordings - Math.round(recordings * 0.81) - Math.round(recordings * 0.14),
    },
    baseline_note:
      'Baselines compare each recording with earlier recordings from the same site, the same part of the day (dawn, day, dusk, night) and the same weeks of the year across seasons, using the median and MAD. Richness is species with at least one counted detection event.',
  };
}

export function buildAccumulation(siteId: string): Accumulation {
  const random = rng(`acc:${siteId}`);
  const points: Accumulation['points'] = [];
  let cumulative = 0;
  const total = siteId === SITE_HEDGE ? 36 : 120;
  const start = new Date('2026-04-02T09:30:00Z').getTime();
  for (let i = 1; i <= total; i += 1) {
    const chance = Math.max(0.02, 0.6 * Math.exp(-i / 18));
    if (random() < chance) cumulative += 1 + (random() < 0.3 ? 1 : 0);
    points.push({
      recording_index: i,
      captured_at: new Date(start + i * 86_400_000 * 1.4).toISOString(),
      cumulative_species: cumulative,
    });
  }
  return {
    site_id: siteId,
    points,
    note: 'Cumulative species counted in capture order. A flattening curve means more of the same effort would add few species; it says nothing about species this method cannot hear.',
  };
}

export function buildPhenology(scientificName: string, siteId?: string | null): Phenology {
  const spec = SPECIES_SPECS.find((s) => s.sci === scientificName) ?? SPECIES_SPECS[0]!;
  const random = rng(`phen:${scientificName}:${siteId ?? 'all'}`);
  const cells: PhenologyCell[] = [];
  const first: Record<string, string> = {};
  const last: Record<string, string> = {};
  for (const year of [2025, 2026]) {
    const peak = spec.taxon === 'amphibian' ? 16 : spec.taxon === 'insect' ? 34 : 22;
    const width = spec.taxon === 'insect' ? 7 : 9;
    for (let week = 1; week <= 53; week += 1) {
      if (year === 2026 && week > 39) break;
      if (week < 12 || week > 44) {
        if (random() < 0.7) continue;
      }
      const recordings = 6 + Math.floor(random() * 10);
      const shape = Math.exp(-((week - peak) ** 2) / (2 * width * width));
      const presence = Math.min(
        1,
        Math.max(0, shape * spec.presence * 1.4 + (random() - 0.5) * 0.12),
      );
      const withDetection = Math.round(presence * recordings);
      cells.push({
        year,
        iso_week: week,
        recordings,
        recordings_with_detection: withDetection,
        presence_fraction: Math.round((withDetection / recordings) * 100) / 100,
        events_per_minute: Math.round(presence * 3 * 100) / 100,
      });
      if (withDetection > 0) {
        const key = String(year);
        const iso = `${year}-W${pad(week)}`;
        if (!first[key]) first[key] = iso;
        last[key] = iso;
      }
    }
  }
  return {
    organization_id: ORG_ID,
    site_ids: siteId ? [siteId] : SITES.map((s) => s.id),
    species: { scientific_name: spec.sci, common_name: spec.common },
    taxon: spec.taxon,
    cells,
    first_detection_by_year: first,
    last_detection_by_year: last,
  };
}

export function buildSiteComparison(from: string, to: string): SiteComparison {
  return {
    period_start: from,
    period_end: to,
    rows: SITES.map((site) => {
      const days = dayPoints(from, to, site.id);
      const minutes = days.reduce((a, d) => a + d.minutes, 0);
      const events = days.reduce((a, d) => a + d.detection_events, 0);
      return {
        site,
        recordings: days.reduce((a, d) => a + d.recordings, 0),
        minutes,
        species_richness: speciesRollups(site.id).length,
        shannon_index: site.id === SITE_HEDGE ? null : 2.31,
        events_per_minute: minutes ? Math.round((events / minutes) * 100) / 100 : 0,
        usable_fraction: site.id === SITE_POND ? 0.78 : 0.9,
        top_species: speciesRollups(site.id)
          .slice(0, 3)
          .map((s) => ({ scientific_name: s.scientific_name, common_name: s.common_name })),
      };
    }),
  };
}

/* Alerts */

export const ALERTS: Alert[] = [
  {
    id: 'al_richness_north',
    organization_id: ORG_ID,
    kind: 'richness_drop',
    category: 'ecology',
    severity: 'warning',
    status: 'open',
    title: 'Dawn species richness fell at North pasture',
    detail:
      'The last 6 dawn recordings at North pasture counted a median of 7 species. The baseline for dawn recordings in these weeks across 2025 and 2026 is 13 species (MAD 2, from 48 comparable recordings). That is 3 MADs below the baseline.',
    evidence: {
      observed: 7,
      baseline_median: 13,
      baseline_mad: 2,
      sample_size: 48,
      consecutive: 6,
    },
    suggested_action:
      'Check whether the first hay cut or grazing moved the birds, listen to two of the recordings, and compare with Mill pond edge for the same mornings.',
    site_id: SITE_NORTH,
    recorder_id: RECORDER_MOTH1,
    deployment_id: 'dep_1',
    species: null,
    recording_ids: ['rc_0931', 'rc_0932', 'rc_0933'],
    first_seen_at: '2026-09-26T10:40:00Z',
    last_seen_at: '2026-09-29T10:40:00Z',
    occurrences: 4,
    created_at: '2026-09-26T10:40:00Z',
    updated_at: '2026-09-29T10:40:00Z',
  },
  {
    id: 'al_priority_bobolink',
    organization_id: ORG_ID,
    kind: 'priority_species_detected',
    category: 'ecology',
    severity: 'info',
    status: 'open',
    title: 'Bobolink detected at North pasture',
    detail:
      'Bobolink (Dolichonyx oryzivorus), a priority species for this organization, produced 4 detection events with a maximum confidence of 0.91 in the recording of Sep 28, 06:00.',
    evidence: { detection_events: 4, max_confidence: 0.91, threshold: 0.6 },
    suggested_action: 'Listen to the events and accept or reject them so the record is reviewed.',
    site_id: SITE_NORTH,
    recorder_id: RECORDER_MOTH1,
    deployment_id: 'dep_1',
    species: { scientific_name: 'Dolichonyx oryzivorus', common_name: 'Bobolink' },
    recording_ids: ['rc_0940'],
    first_seen_at: '2026-09-28T10:20:00Z',
    last_seen_at: '2026-09-28T10:20:00Z',
    occurrences: 1,
    created_at: '2026-09-28T10:20:00Z',
    updated_at: '2026-09-28T10:20:00Z',
  },
  {
    id: 'al_quality_pond',
    organization_id: ORG_ID,
    kind: 'low_quality_streak',
    category: 'quality',
    severity: 'watch',
    status: 'open',
    title: 'Three recordings in a row rated not usable at Mill pond edge',
    detail:
      'The last 3 recordings from Mill pond edge were rated not usable: energy below 200 Hz was 61%, 58% and 66% of the total, which usually means wind or rain on the microphone.',
    evidence: { consecutive: 3, threshold: 3, low_frequency_energy_fraction: 0.62 },
    suggested_action:
      'Check the windscreen and whether the recorder is still shielded by the bank.',
    site_id: SITE_POND,
    recorder_id: RECORDER_MOTH2,
    deployment_id: 'dep_2',
    species: null,
    recording_ids: ['rc_0881', 'rc_0882', 'rc_0883'],
    first_seen_at: '2026-09-27T03:10:00Z',
    last_seen_at: '2026-09-28T02:10:00Z',
    occurrences: 2,
    created_at: '2026-09-27T03:10:00Z',
    updated_at: '2026-09-28T02:10:00Z',
  },
  {
    id: 'al_gap_hedge',
    organization_id: ORG_ID,
    kind: 'recording_gap',
    category: 'recorder',
    severity: 'warning',
    status: 'open',
    title: 'SM Mini (hedgerow) has not recorded for 46 days',
    detail:
      'The last recording from SM Mini (hedgerow) arrived on Aug 14. With the deployment interval of 60 minutes, about 1,100 recordings were expected since then. The gap rule is 3 times the median interval and at least 6 hours.',
    evidence: { hours: 1104, expected_recordings: 1104, median_interval_minutes: 60 },
    suggested_action:
      'Collect the card and check the batteries; end the deployment if the recorder was removed.',
    site_id: SITE_HEDGE,
    recorder_id: RECORDER_SM,
    deployment_id: 'dep_3',
    species: null,
    recording_ids: [],
    first_seen_at: '2026-08-15T06:00:00Z',
    last_seen_at: '2026-09-29T06:00:00Z',
    occurrences: 46,
    created_at: '2026-08-15T06:00:00Z',
    updated_at: '2026-09-29T06:00:00Z',
  },
  {
    id: 'al_battery_moth2',
    organization_id: ORG_ID,
    kind: 'battery_low',
    category: 'recorder',
    severity: 'watch',
    status: 'acknowledged',
    title: 'Moth 2 battery at 3.7 V',
    detail: 'The latest AudioMoth comment reports 3.7 V. The low threshold for AudioMoth is 3.6 V.',
    evidence: { battery_v: 3.7, threshold: 3.6 },
    suggested_action: 'Plan a battery change at the next card swap.',
    site_id: SITE_POND,
    recorder_id: RECORDER_MOTH2,
    deployment_id: 'dep_2',
    species: null,
    recording_ids: ['rc_0883'],
    first_seen_at: '2026-09-25T02:10:00Z',
    last_seen_at: '2026-09-28T02:10:00Z',
    occurrences: 4,
    acknowledged_by: 'Sam Ortiz',
    note: 'Batteries ordered.',
    created_at: '2026-09-25T02:10:00Z',
    updated_at: '2026-09-26T14:00:00Z',
  },
  {
    id: 'al_new_species',
    organization_id: ORG_ID,
    kind: 'new_species_for_site',
    category: 'ecology',
    severity: 'info',
    status: 'resolved',
    title: 'First Gray Treefrog at Mill pond edge',
    detail:
      'Gray Treefrog (Hyla versicolor) was counted at Mill pond edge for the first time: 3 detection events, maximum confidence 0.84.',
    evidence: { detection_events: 3, max_confidence: 0.84 },
    suggested_action: null,
    site_id: SITE_POND,
    recorder_id: RECORDER_MOTH2,
    deployment_id: 'dep_2',
    species: { scientific_name: 'Hyla versicolor', common_name: 'Gray Treefrog' },
    recording_ids: ['rc_0412'],
    first_seen_at: '2026-05-30T02:10:00Z',
    last_seen_at: '2026-05-30T02:10:00Z',
    occurrences: 1,
    note: 'Confirmed by ear.',
    created_at: '2026-05-30T02:10:00Z',
    updated_at: '2026-06-01T09:00:00Z',
  },
];

export const ALERT_RULES: AlertRules = {
  enabled: true,
  min_baseline_recordings: 20,
  richness_drop_mad: 3,
  activity_drop_mad: 3,
  species_surge_mad: 3,
  expected_species_min_presence: 0.5,
  expected_species_missing_recordings: 10,
  low_quality_streak: 3,
  consecutive_recordings: 5,
  gap_multiplier: 3,
  gap_min_hours: 6,
  battery_low_v: { audiomoth: 3.6, song_meter: 3.3, other: 3.5 },
  temperature_min_c: -20,
  temperature_max_c: 45,
  priority_species: ['Dolichonyx oryzivorus', 'Sturnella magna'],
};

export const NOTIFICATION_PREFS: NotificationPrefs = {
  categories: ['ecology', 'quality', 'recorder'],
  min_severity: 'info',
  email_enabled: true,
  email_digest: 'daily',
};

export const NOTIFICATIONS: NotificationPage = {
  unread: 2,
  items: [
    {
      id: 'nt_1',
      channel: 'in_app',
      alert: ALERTS[0]!,
      created_at: '2026-09-29T10:40:00Z',
      read_at: null,
    },
    {
      id: 'nt_2',
      channel: 'in_app',
      alert: ALERTS[1]!,
      created_at: '2026-09-28T10:20:00Z',
      read_at: null,
    },
  ],
};

/* Recorder health */

function series(
  seed: string,
  days: number,
  base: number,
  spread: number,
  drift = 0,
  perDay = 2,
): SeriesPoint[] {
  const random = rng(seed);
  const out: SeriesPoint[] = [];
  const now = Date.now();
  const n = days * perDay;
  for (let i = 0; i < n; i += 1) {
    const t = now - (n - i) * (86_400_000 / perDay);
    const value = base + (random() - 0.5) * spread + drift * (i / n);
    out.push({ t: new Date(t).toISOString(), v: Math.round(value * 1000) / 1000 });
  }
  return out;
}

export function buildRecorderHealth(recorderId: string, days = 30): RecorderHealth {
  const recorder = RECORDERS.find((r) => r.id === recorderId) ?? RECORDERS[0]!;
  const deployment = DEPLOYMENTS.find((d) => d.recorder_id === recorder.id) ?? null;
  const degraded = recorder.id === RECORDER_MOTH2;
  const dead = recorder.id === RECORDER_SM;
  const now = Date.now();
  const gaps = dead
    ? [
        {
          start: '2026-08-14T09:00:00Z',
          end: new Date(now).toISOString(),
          hours: Math.round((now - new Date('2026-08-14T09:00:00Z').getTime()) / 3_600_000),
          expected_recordings: 1104,
        },
      ]
    : degraded
      ? [
          {
            start: new Date(now - 9 * 86_400_000).toISOString(),
            end: new Date(now - 8.3 * 86_400_000).toISOString(),
            hours: 17,
            expected_recordings: 17,
          },
          {
            start: new Date(now - 3 * 86_400_000).toISOString(),
            end: new Date(now - 2.6 * 86_400_000).toISOString(),
            hours: 9,
            expected_recordings: 9,
          },
        ]
      : [];
  const checks: RecorderHealth['checks'] = [
    {
      name: 'muffled_audio',
      status: degraded ? 'watch' : dead ? 'unknown' : 'good',
      value: degraded ? 0.11 : 0.19,
      baseline: 0.18,
      message: degraded
        ? 'High-band energy is 2.4 MADs below the deployment baseline in the last 5 recordings.'
        : dead
          ? 'No recent recordings to check.'
          : 'High-band energy matches the deployment baseline.',
    },
    {
      name: 'level_drift',
      status: dead ? 'unknown' : 'good',
      value: -31.4,
      baseline: -30.8,
      message: dead
        ? 'No recent recordings to check.'
        : 'RMS level within 1 dB of the deployment median for this hour bucket.',
    },
    {
      name: 'recording_gap',
      status: dead ? 'attention' : degraded ? 'watch' : 'good',
      value: gaps.length,
      baseline: null,
      message: dead
        ? 'No recordings for 46 days against a 60 minute schedule.'
        : degraded
          ? 'Two gaps longer than 3 intervals in the window.'
          : 'No gaps longer than 3 intervals.',
    },
    {
      name: 'clipping_increase',
      status: 'good',
      value: 0.002,
      baseline: 0.002,
      message: 'Clipped samples stay under 0.5%.',
    },
    {
      name: 'battery_low',
      status: degraded ? 'watch' : dead ? 'unknown' : 'good',
      value: degraded ? 3.7 : 4.1,
      baseline: 3.6,
      message: degraded
        ? '3.7 V, close to the 3.6 V threshold.'
        : dead
          ? 'No telemetry since Aug 14.'
          : '4.1 V.',
    },
    {
      name: 'temperature_extreme',
      status: 'good',
      value: 14.2,
      baseline: null,
      message: 'Within -20 to 45 C.',
    },
    {
      name: 'clock_suspect',
      status: 'good',
      value: null,
      baseline: null,
      message: 'Timestamps are monotonic with no duplicates.',
    },
    {
      name: 'schedule_deviation',
      status: dead ? 'attention' : 'good',
      value: null,
      baseline: null,
      message: dead
        ? 'Nothing arrives on the 60 minute schedule.'
        : 'Recordings follow the 30 minute schedule.',
    },
  ];
  const empty: SeriesPoint[] = [];
  return {
    recorder,
    deployment,
    status: dead ? 'attention' : degraded ? 'watch' : 'good',
    checks,
    last_recording_at: recorder.last_recording_at ?? null,
    recordings_last_7d: dead ? 0 : degraded ? 148 : 336,
    expected_last_7d: dead ? 168 : degraded ? 168 : 336,
    uptime_fraction_7d: dead ? 0 : degraded ? 0.88 : 1,
    median_interval_minutes: dead ? null : degraded ? 60 : 30,
    battery: dead
      ? empty
      : series(
          `bat:${recorder.id}`,
          days,
          degraded ? 3.95 : 4.25,
          0.06,
          degraded ? -0.28 : -0.1,
          2,
        ),
    temperature: dead ? empty : series(`temp:${recorder.id}`, days, 14, 9, -4, 2),
    level_dbfs: dead ? empty : series(`lvl:${recorder.id}`, days, -31, 4, degraded ? -5 : 0, 3),
    high_band_fraction: dead
      ? empty
      : series(`hb:${recorder.id}`, days, 0.18, 0.06, degraded ? -0.09 : 0, 3),
    spectral_centroid_hz: dead
      ? empty
      : series(`sc:${recorder.id}`, days, 3200, 600, degraded ? -900 : 0, 3),
    clipping_fraction: dead
      ? empty
      : series(`clip:${recorder.id}`, days, 0.002, 0.003, 0, 3).map((p) => ({
          ...p,
          v: Math.max(0, p.v),
        })),
    gaps,
    open_alerts: ALERTS.filter((a) => a.recorder_id === recorder.id && a.status === 'open'),
    baseline_note:
      'Baselines are the median and MAD of this deployment, per hour bucket. Checks need 5 consecutive recordings outside the band before they change status.',
  };
}

/* Recordings */

export const ANALYZED_RECORDING_ID = 'rc_0940';

export function buildRecordings(total = 60): RecordingSummary[] {
  const random = rng('recordings');
  const rows: RecordingSummary[] = [];
  const now = new Date('2026-09-29T10:05:00Z').getTime();
  for (let i = 0; i < total; i += 1) {
    const site = SITES[i % 3 === 2 ? (i > 40 ? 0 : 2) : i % 3]!;
    const recorder = RECORDERS[SITES.indexOf(site)]!;
    const captured = new Date(now - i * 13 * 3_600_000 - Math.floor(random() * 1800) * 1000);
    const stamp = `${captured.getUTCFullYear()}${pad(captured.getUTCMonth() + 1)}${pad(captured.getUTCDate())}_${pad(captured.getUTCHours())}${pad(captured.getUTCMinutes())}00`;
    const filename = recorder.make === 'song_meter' ? `SMM01234_${stamp}.wav` : `${stamp}.WAV`;
    const q = random();
    const quality: RecordingSummary['quality_status'] =
      q < 0.8 ? 'usable' : q < 0.94 ? 'usable_with_warnings' : 'not_usable';
    const richness = Math.max(0, Math.round(seasonalRichness(captured, 12) + (random() - 0.5) * 4));
    rows.push({
      id: i === 0 ? ANALYZED_RECORDING_ID : `rc_${String(1000 - i).padStart(4, '0')}`,
      organization_id: ORG_ID,
      site_id: site.id,
      site_name: site.name,
      recorder_id: recorder.id,
      deployment_id: DEPLOYMENTS[SITES.indexOf(site)]!.id,
      filename,
      captured_at: captured.toISOString(),
      captured_at_source:
        recorder.make === 'song_meter' ? 'filename' : i % 11 === 0 ? 'file_metadata' : 'filename',
      timezone: 'America/New_York',
      duration_seconds: 300,
      latitude: site.latitude ?? null,
      longitude: site.longitude ?? null,
      analysis_id: i === 0 ? 'an_7f3c2a91d4' : `an_${String(1000 - i).padStart(4, '0')}`,
      analysis_status: 'completed',
      quality_status: quality,
      species_richness: richness,
      total_detection_events: richness * 4 + Math.floor(random() * 10),
      decision_threshold: 0.6,
      telemetry: {
        source: recorder.make === 'song_meter' ? 'song_meter_summary' : 'audiomoth_comment',
        battery_v: Math.round((4.2 - i * 0.004) * 100) / 100,
        temperature_c: Math.round((14 + (random() - 0.5) * 8) * 10) / 10,
        gain: 'medium',
        device_id: recorder.serial ?? null,
      },
      created_at: new Date(captured.getTime() + 6 * 3_600_000).toISOString(),
    });
  }
  return rows;
}

export const RECORDINGS = buildRecordings();

/* Batch ingestion */

export function buildBatchJob(
  id: string,
  filenames: string[],
  stage: 'queued' | 'processing' | 'completed',
  siteId = SITE_NORTH,
): BatchJob {
  const audio = filenames.filter((f) => !/\.txt$/i.test(f));
  const sidecars = filenames.filter((f) => /\.txt$/i.test(f));
  const items = audio.map((filename, i) => {
    const failed = stage === 'completed' && /bad/i.test(filename);
    const done = stage === 'completed' || (stage === 'processing' && i === 0);
    return {
      filename,
      status: failed
        ? ('failed' as const)
        : done
          ? ('completed' as const)
          : stage === 'processing' && i === 1
            ? ('processing' as const)
            : ('queued' as const),
      recording_id: done && !failed ? `rc_new_${i + 1}` : null,
      analysis_id: done && !failed ? `an_new_${i + 1}` : null,
      captured_at: done ? '2026-05-14T05:30:00Z' : null,
      captured_at_source: done ? ('filename' as const) : undefined,
      error_code: failed ? 'audio_decode_failed' : null,
      error_message: failed ? 'The file could not be decoded.' : null,
      telemetry:
        done && !failed
          ? {
              source: 'audiomoth_comment' as const,
              battery_v: 4.0,
              temperature_c: 12.3,
              gain: 'medium',
              device_id: '24A1D5F3C9',
            }
          : null,
    };
  });
  const doneCount = items.filter((i) => i.status === 'completed').length;
  const failedCount = items.filter((i) => i.status === 'failed').length;
  return {
    id,
    organization_id: ORG_ID,
    site_id: siteId,
    deployment_id: 'dep_1',
    status: stage === 'completed' ? (failedCount ? 'completed_with_errors' : 'completed') : stage,
    total: items.length,
    done: doneCount,
    failed: failedCount,
    skipped: 0,
    items,
    sidecars_parsed: stage === 'completed' ? sidecars : [],
    settings: { threshold: 0.6, models: ['birdnet'], timezone: 'America/New_York' },
    created_at: '2026-09-29T12:00:00Z',
    completed_at: stage === 'completed' ? '2026-09-29T12:04:00Z' : null,
  };
}

/* Reports */

function field(
  name: string,
  type: ReportField['type'],
  group: string,
  templates: ReportField['templates'],
  extra: Partial<ReportField> = {},
): ReportField {
  return {
    name,
    type,
    group,
    templates,
    label: extra.label ?? name.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()),
    help: extra.help ?? null,
    required: extra.required ?? false,
    options: extra.options ?? null,
    example: extra.example,
  };
}

const ALL: ReportField['templates'] = ['evidence', 'nrcs', 'aem', 'certification', 'credit'];

export const REPORT_FIELDS: ReportField[] = [
  field('report_title', 'string', 'identity', ALL, {
    required: true,
    example: 'Spring 2027 acoustic survey, north pasture',
  }),
  field('organization_name', 'string', 'identity', ALL, {
    required: true,
    example: 'Fall Creek Grazing LLC',
  }),
  field('preparer_name', 'string', 'identity', ALL, { required: true, example: 'Jane Farmer' }),
  field('preparer_role', 'string', 'identity', ALL, { example: 'Farm manager' }),
  field('prepared_for', 'string', 'identity', ['evidence', 'certification', 'credit'], {
    example: 'Tompkins County SWCD',
  }),
  field('monitoring_objective', 'text', 'identity', ['evidence', 'certification', 'credit'], {
    example: 'Document grassland bird use of the rotationally grazed north pasture',
  }),
  field('property_name', 'string', 'location', ALL, { example: 'Hilltop Farm' }),
  field('county', 'string', 'location', ['evidence', 'nrcs', 'aem'], { example: 'Tompkins' }),
  field('state', 'string', 'location', ['evidence', 'nrcs', 'aem'], { example: 'NY' }),
  field('habitat_type', 'enum', 'location', ALL, {
    options: [
      'pasture',
      'hayfield',
      'cropland',
      'shrubland',
      'forest',
      'wetland',
      'riparian buffer',
      'farmstead',
      'other',
    ],
    example: 'pasture',
  }),
  field('recorder_make', 'string', 'deployment', ALL, { example: 'Open Acoustic Devices' }),
  field('recorder_model', 'string', 'deployment', ALL, { example: 'AudioMoth 1.2.0' }),
  field('mount_height_m', 'number', 'deployment', ['evidence', 'aem', 'certification', 'credit'], {
    label: 'Mount height (m)',
    example: 1.5,
  }),
  field(
    'recording_schedule',
    'string',
    'deployment',
    ['evidence', 'aem', 'certification', 'credit'],
    { example: '1 min every 5 min, 04:30 to 09:30' },
  ),
  field('deployment_start', 'datetime', 'deployment', ALL, {
    example: '2027-05-10T18:00:00-04:00',
  }),
  field('deployment_photo', 'file', 'deployment', ['evidence', 'nrcs', 'aem', 'credit'], {
    example: 'north_pasture_recorder.jpg',
  }),
  field('weather_summary', 'text', 'deployment', ['evidence', 'nrcs', 'credit'], {
    example: 'Clear, 8 to 14 C, wind under 3 m/s on survey mornings',
  }),
  field('reviewer_name', 'string', 'review', ['evidence', 'certification', 'credit'], {
    example: 'J. Doe',
  }),
  field('review_date', 'date', 'review', ['evidence', 'certification', 'credit'], {
    example: '2027-05-20',
  }),
  field('validation_method', 'text', 'review', ['evidence', 'credit'], {
    example: 'All events above 0.60 listened to',
  }),
  field('participant_name', 'string', 'nrcs', ['nrcs'], {
    required: true,
    example: 'Jane Farmer',
    help: 'Exactly as it appears on the contract.',
  }),
  field('nrcs_program', 'enum', 'nrcs', ['nrcs'], {
    label: 'NRCS program',
    options: ['EQIP', 'CSP', 'RCPP', 'other'],
    example: 'CSP',
    required: true,
  }),
  field('nrcs_contract_number', 'string', 'nrcs', ['nrcs'], {
    label: 'NRCS contract number',
    example: '74-2B29-26-123',
  }),
  field('fsa_field_numbers', 'list', 'nrcs', ['nrcs', 'aem'], {
    label: 'FSA field numbers',
    example: ['3', '4'],
  }),
  field('practice_code', 'string', 'nrcs', ['nrcs', 'aem'], { example: '645' }),
  field('fiscal_year', 'integer', 'nrcs', ['nrcs'], { example: 2027 }),
  field('target_species', 'list', 'nrcs', ['nrcs', 'certification'], {
    example: ['Bobolink', 'Eastern Meadowlark'],
  }),
  field('aem_id', 'string', 'aem', ['aem'], { label: 'AEM ID', required: true, example: 'T-0456' }),
  field('aem_tier', 'enum', 'aem', ['aem'], {
    label: 'AEM tier',
    options: ['5A', '5B'],
    example: '5B',
    required: true,
  }),
  field('bmp_system', 'enum', 'aem', ['aem'], {
    label: 'BMP system',
    options: [
      'Riparian Buffer System',
      'Access Control System',
      'Prescribed Rotational Grazing System',
      'other',
    ],
    example: 'Access Control System',
  }),
  field('level_of_concern_before', 'integer', 'aem', ['aem'], {
    example: 4,
    help: '1 to 4 from the Tier 2 worksheet.',
  }),
  field('planner_notes', 'text', 'aem', ['aem'], {
    example: 'Buffer vegetation established; fence intact',
  }),
  field('certification_program', 'enum', 'certification', ['certification'], {
    options: ['ROC', 'Land to Market EOV', 'Audubon Conservation Ranching', 'Regenified', 'other'],
    required: true,
  }),
  field('certifier_name', 'string', 'certification', ['certification'], {
    example: 'FoodChain ID',
  }),
  field('land_base_acres', 'number', 'certification', ['certification'], { example: 180 }),
  field('project_id', 'string', 'credit', ['credit'], {
    label: 'Project ID',
    required: true,
    example: 'PV-N-0042',
  }),
  field('registry', 'enum', 'credit', ['credit'], {
    options: ['Verra', 'Plan Vivo', 'Wallacea Trust aligned', 'internal', 'other'],
    example: 'Plan Vivo',
  }),
  field('sampling_design_description', 'text', 'credit', ['credit'], {
    example: '1 point per 10 ha, stratified by habitat',
  }),
  field('uncertainty_method', 'text', 'credit', ['credit'], {
    example: 'Bootstrap over recordings, 95% CI',
  }),
  field('data_license', 'enum', 'statements', ['evidence', 'credit'], {
    options: ['CC BY 4.0', 'CC BY-NC 4.0', 'CC0', 'all rights reserved'],
    example: 'CC BY 4.0',
  }),
  field('landowner_consent', 'boolean', 'statements', ['evidence', 'credit'], { example: true }),
  field('caveats_acknowledged', 'boolean', 'statements', ALL, {
    required: true,
    example: true,
    help: 'You confirm the report will be read as detection evidence, not a census.',
  }),
  field('attestation_name', 'string', 'statements', ALL, {
    required: true,
    example: 'Jane Farmer',
  }),
  field('attestation_date', 'date', 'statements', ALL, { required: true, example: '2027-08-01' }),
];

function template(
  key: ReportTemplate['key'],
  title: string,
  audience: string,
  description: string,
  pages: string[],
): ReportTemplate {
  return {
    key,
    title,
    audience,
    description,
    pages,
    fields: REPORT_FIELDS.filter((f) => f.templates.includes(key)),
  };
}

export const REPORT_TEMPLATES: ReportTemplates = {
  templates: [
    template(
      'evidence',
      'Thicket Evidence Package',
      'Anyone who needs the full chain of evidence',
      'The most rigorous package: every species table with plausibility and review columns, methods, quality, provenance and a data dictionary.',
      [
        'Cover',
        'Summary',
        'Site and deployment',
        'Methods',
        'Results: species',
        'Results: timeline and metrics',
        'Quality',
        'Review log',
        'Limitations',
        'Provenance appendix',
        'Data dictionary and attestation',
      ],
    ),
    template(
      'nrcs',
      'NRCS practice documentation annex',
      'NRCS planners and the participant case file',
      'Field log, map, photos and target species presence to support EQIP or CSP paperwork. Not a practice certification.',
      [
        'Header',
        'Field log',
        'Map and photos',
        'Target species presence',
        'Habitat context',
        'Provenance and statement',
      ],
    ),
    template(
      'aem',
      'NY AEM Tier 5 evaluation annex',
      'County SWCD planners',
      'Evidence offered for the planner-owned Tier 5 evaluation, with a season-matched before and after comparison.',
      [
        'Header',
        'BMP under evaluation',
        'Worksheet linkage',
        'Before and after',
        'Field evidence',
        'Planner notes and provenance',
      ],
    ),
    template(
      'certification',
      'Certification monitoring summary',
      'Certifiers and verifiers (ROC, EOV, ACR, Regenified, AGW)',
      'Native fauna record by taxon with priority species flagged, monitoring design and indicators, for the certifier to review.',
      [
        'Header',
        'Management context',
        'Native fauna record',
        'Monitoring design',
        'Indicators and trend',
        'Limits and provenance',
      ],
    ),
    template(
      'credit',
      'Biodiversity credit monitoring report',
      'Registries and validation bodies',
      'Monitoring plan versus implemented, identification method, per-stratum results with uncertainty, QA/QC and safeguards. No credit arithmetic.',
      [
        'Project details',
        'Monitoring plan vs implemented',
        'Equipment and data capture',
        'Identification method',
        'Results',
        'Baseline comparison and uncertainty',
        'QA/QC',
        'Data provenance',
        'Safeguards and public summary',
        'Attestation',
      ],
    ),
  ],
};

export const REPORTS: Report[] = [
  {
    id: 'rp_spring',
    organization_id: ORG_ID,
    template: 'evidence',
    title: 'Spring 2026 evidence package, North pasture',
    status: 'ready',
    period_start: '2026-04-01',
    period_end: '2026-06-30',
    site_ids: [SITE_NORTH],
    analysis_count: 212,
    page_count: 14,
    pdf_url: '/api/v1/reports/rp_spring.pdf',
    json_url: '/api/v1/reports/rp_spring.json',
    checksum_sha256: '9f2c1e7b4d3a5c6e8f0a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e4f5a6',
    missing_fields: ['reviewer_name'],
    warnings: ['12 recordings were excluded as not usable.'],
    created_by: USER_ID,
    created_at: '2026-07-02T15:00:00Z',
    completed_at: '2026-07-02T15:01:12Z',
  },
  {
    id: 'rp_failed',
    organization_id: ORG_ID,
    template: 'nrcs',
    title: 'CSP annex draft',
    status: 'failed',
    period_start: '2026-05-01',
    period_end: '2026-05-31',
    site_ids: [SITE_NORTH],
    analysis_count: 0,
    error_message: 'No completed analyses in the period for the selected sites.',
    created_by: USER_ID,
    created_at: '2026-06-03T10:00:00Z',
    completed_at: '2026-06-03T10:00:03Z',
  },
];

export function buildReport(
  id: string,
  body: {
    title: string;
    template: Report['template'];
    period_start: string;
    period_end: string;
    site_ids?: string[];
  },
  status: Report['status'],
): Report {
  return {
    id,
    organization_id: ORG_ID,
    template: body.template,
    title: body.title,
    status,
    period_start: body.period_start,
    period_end: body.period_end,
    site_ids: body.site_ids ?? [],
    analysis_count: status === 'ready' ? 58 : 0,
    page_count: status === 'ready' ? 11 : null,
    pdf_url: status === 'ready' ? `/api/v1/reports/${id}.pdf` : null,
    json_url: status === 'ready' ? `/api/v1/reports/${id}.json` : null,
    checksum_sha256:
      status === 'ready'
        ? 'a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e'
        : null,
    missing_fields: status === 'ready' ? ['preparer_role'] : [],
    warnings:
      status === 'ready' ? ['Effort differs between sites; compare presence, not totals.'] : [],
    created_by: USER_ID,
    created_at: '2026-09-29T12:10:00Z',
    completed_at: status === 'ready' ? '2026-09-29T12:11:00Z' : null,
  };
}

/** A complete `public/demo/platform.json` for the static demo build. */
export function buildDemoPlatformFile(from: string, to: string) {
  return {
    organization: ORG,
    user: { ...USER, name: 'Demo visitor', email: 'demo@thicket.example' },
    dashboard: buildDashboard({ from, to }),
    sites: SITES,
    alerts: ALERTS,
    recorders: RECORDERS,
    recorder_health: Object.fromEntries(RECORDERS.map((r) => [r.id, buildRecorderHealth(r.id)])),
    deployments: DEPLOYMENTS,
    recordings: RECORDINGS.slice(0, 20).map((r, i) =>
      i === 0 ? { ...r, analysis_id: 'hollow-creek' } : r,
    ),
    accumulation: Object.fromEntries(SITES.map((s) => [s.id, buildAccumulation(s.id)])),
    phenology: SPECIES_SPECS.slice(0, 8).map((s) => buildPhenology(s.sci)),
    site_comparison: buildSiteComparison(from, to),
    reports: REPORTS.filter((r) => r.status === 'ready'),
    report_templates: REPORT_TEMPLATES,
    alert_rules: ALERT_RULES,
  };
}
