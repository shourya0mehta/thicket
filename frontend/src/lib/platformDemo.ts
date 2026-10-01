/**
 * Read-only platform demo for static hosting. If `${BASE_URL}demo/platform.json`
 * exists, the demo build shows a dashboard, sites, alerts, recorders and
 * recordings from it (no API calls, no writes). The file layout:
 *
 *   {
 *     "organization": Organization,
 *     "user": User (optional; a placeholder is used otherwise),
 *     "dashboard": Dashboard,
 *     "sites": Site[],
 *     "alerts": Alert[],
 *     "recorders": Recorder[],
 *     "recorder_health": { "<recorder id>": RecorderHealth } (optional),
 *     "deployments": Deployment[] (optional),
 *     "recordings": RecordingSummary[] (optional),
 *     "accumulation": { "<site id>": Accumulation } (optional),
 *     "phenology": Phenology[] (optional, one per species),
 *     "site_comparison": SiteComparison (optional),
 *     "reports": Report[] (optional),
 *     "report_templates": ReportTemplates (optional),
 *     "alert_rules": AlertRules (optional)
 *   }
 *
 * Recording rows whose `analysis_id` matches a demo analysis id (demo/index.json)
 * open that analysis; everything else is listed without a detail view.
 */
import { ApiError, isAbortError } from '../api/client';
import type {
  Accumulation,
  Alert,
  AlertPage,
  AlertRules,
  Dashboard,
  Deployment,
  Me,
  Organization,
  Phenology,
  Recorder,
  RecorderHealth,
  RecordingSummary,
  Report,
  ReportTemplates,
  Site,
  SiteComparison,
  User,
} from '../api/generated';
import type { PlatformApi } from '../platform/api';
import { MODELS_FALLBACK } from './demoModels';
import { demoPath, loadDemoAnalysis } from './demo';

export interface PlatformDemoFile {
  organization: Organization;
  user?: User;
  dashboard: Dashboard;
  sites: Site[];
  alerts: Alert[];
  recorders: Recorder[];
  recorder_health?: Record<string, RecorderHealth>;
  deployments?: Deployment[];
  recordings?: RecordingSummary[];
  accumulation?: Record<string, Accumulation>;
  phenology?: Phenology[];
  site_comparison?: SiteComparison;
  reports?: Report[];
  report_templates?: ReportTemplates;
  alert_rules?: AlertRules;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isPlatformDemoFile(value: unknown): value is PlatformDemoFile {
  if (!isObject(value)) return false;
  return (
    isObject(value.organization) &&
    typeof value.organization.id === 'string' &&
    isObject(value.dashboard) &&
    Array.isArray(value.sites) &&
    Array.isArray(value.alerts) &&
    Array.isArray(value.recorders)
  );
}

/** Resolves to null when the file is absent (404) so the single-recording demo keeps working. */
export async function loadPlatformDemo(signal?: AbortSignal): Promise<PlatformDemoFile | null> {
  let response: Response;
  try {
    response = await fetch(demoPath('platform.json'), {
      signal,
      headers: { Accept: 'application/json' },
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    return null;
  }
  if (!response.ok) return null;
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return null;
  }
  return isPlatformDemoFile(body) ? body : null;
}

const READ_ONLY = () =>
  Promise.reject(
    new ApiError(
      'forbidden',
      'This is a read-only demo. Run Thicket locally to make changes.',
      403,
    ),
  );

const PLACEHOLDER_USER: User = {
  id: 'demo_user',
  email: 'demo@thicket.example',
  name: 'Demo visitor',
  created_at: '2026-01-01T00:00:00Z',
};

export function demoMe(file: PlatformDemoFile): Me {
  return {
    auth_mode: 'disabled',
    user: file.user ?? PLACEHOLDER_USER,
    organizations: [file.organization],
    roles: { [file.organization.id]: 'viewer' },
    unread_notifications: 0,
  };
}

function alertPage(items: Alert[]): AlertPage {
  const counts_by_category: Record<string, number> = {};
  const counts_by_status: Record<string, number> = {};
  for (const alert of items) {
    counts_by_category[alert.category] = (counts_by_category[alert.category] ?? 0) + 1;
    counts_by_status[alert.status] = (counts_by_status[alert.status] ?? 0) + 1;
  }
  return { items, total: items.length, counts_by_category, counts_by_status };
}

function notFound(what: string): Promise<never> {
  return Promise.reject(new ApiError('not_found', `${what} is not part of the demo.`, 404));
}

export function demoPlatformApi(file: PlatformDemoFile): PlatformApi {
  const org = file.organization;
  const me = demoMe(file);
  const recordings = file.recordings ?? [];

  return {
    readOnly: true,
    getMe: () => Promise.resolve(me),
    listOrganizations: () => Promise.resolve([org]),
    createOrganization: READ_ONLY,
    getOrganization: () => Promise.resolve(org),
    updateOrganization: READ_ONLY,
    listMembers: () =>
      Promise.resolve([{ user: me.user, role: 'viewer' as const, joined_at: org.created_at }]),
    updateMember: READ_ONLY,
    removeMember: READ_ONLY,
    listInvites: () => Promise.resolve([]),
    createInvite: READ_ONLY,
    revokeInvite: READ_ONLY,
    acceptInvite: READ_ONLY,

    listSites: () => Promise.resolve(file.sites),
    createSite: READ_ONLY,
    getSite: (id) => {
      const site = file.sites.find((s) => s.id === id);
      return site ? Promise.resolve(site) : notFound('That site');
    },
    updateSite: READ_ONLY,
    deleteSite: READ_ONLY,
    getAccumulation: (id) => {
      const acc = file.accumulation?.[id];
      return Promise.resolve(acc ?? { site_id: id, points: [], note: 'Not included in the demo.' });
    },

    listRecorders: () => Promise.resolve(file.recorders),
    createRecorder: READ_ONLY,
    getRecorder: (id) => {
      const recorder = file.recorders.find((r) => r.id === id);
      return recorder ? Promise.resolve(recorder) : notFound('That recorder');
    },
    updateRecorder: READ_ONLY,
    deleteRecorder: READ_ONLY,
    getRecorderHealth: (id) => {
      const health = file.recorder_health?.[id];
      return health ? Promise.resolve(health) : notFound('Health for that recorder');
    },
    listDeployments: (_org, options) => {
      const all = file.deployments ?? [];
      return Promise.resolve(
        options?.active === undefined ? all : all.filter((d) => !d.ended_at === options.active),
      );
    },
    createDeployment: READ_ONLY,
    updateDeployment: READ_ONLY,

    createBatchUpload: READ_ONLY,
    getBatchJob: () => notFound('That upload'),
    listBatchJobs: () => Promise.resolve([]),
    listRecordings: (_org, filters = {}) => {
      let items = recordings;
      if (filters.site_id) items = items.filter((r) => r.site_id === filters.site_id);
      if (filters.quality) items = items.filter((r) => r.quality_status === filters.quality);
      if (filters.from) items = items.filter((r) => (r.captured_at ?? '') >= filters.from!);
      if (filters.to)
        items = items.filter((r) => (r.captured_at ?? '').slice(0, 10) <= filters.to!);
      const pageSize = filters.page_size ?? 25;
      const page = filters.page ?? 1;
      return Promise.resolve({
        items: items.slice((page - 1) * pageSize, page * pageSize),
        page,
        page_size: pageSize,
        total: items.length,
      });
    },
    getRecording: (id) => {
      const row = recordings.find((r) => r.id === id);
      return row ? Promise.resolve(row) : notFound('That recording');
    },
    deleteRecording: READ_ONLY,
    getAnalysis: (id, threshold, signal) => loadDemoAnalysis(id, threshold ?? 0.6, signal),
    getModels: () => Promise.resolve(MODELS_FALLBACK),

    getDashboard: (_org, query = {}) => {
      const d = file.dashboard;
      if (!query.site_id) return Promise.resolve(d);
      const site = query.site_id;
      return Promise.resolve({
        ...d,
        site_ids: [site],
        richness_by_day: d.richness_by_day.filter((p) => !p.site_id || p.site_id === site),
        indices_by_day: d.indices_by_day.filter((p) => !p.site_id || p.site_id === site),
        species: d.species.filter((s) => s.site_ids.length === 0 || s.site_ids.includes(site)),
      });
    },
    getPhenology: (_org, query) => {
      const found = file.phenology?.find(
        (p) => p.species.scientific_name === query.scientific_name,
      );
      return found ? Promise.resolve(found) : notFound('Phenology for that species');
    },
    compareSites: () =>
      Promise.resolve(
        file.site_comparison ?? {
          period_start: file.dashboard.period_start,
          period_end: file.dashboard.period_end,
          rows: [],
        },
      ),

    listAlerts: (_org, filters = {}) => {
      let items = file.alerts;
      if (filters.status) items = items.filter((a) => a.status === filters.status);
      if (filters.category) items = items.filter((a) => a.category === filters.category);
      if (filters.site_id) items = items.filter((a) => a.site_id === filters.site_id);
      if (filters.recorder_id) items = items.filter((a) => a.recorder_id === filters.recorder_id);
      return Promise.resolve(alertPage(items));
    },
    updateAlert: READ_ONLY,
    getAlertRules: () => Promise.resolve(file.alert_rules ?? {}),
    putAlertRules: READ_ONLY,
    evaluateAlerts: READ_ONLY,

    getReportTemplates: () => Promise.resolve(file.report_templates ?? { templates: [] }),
    listReports: () => Promise.resolve({ items: file.reports ?? [] }),
    createReport: READ_ONLY,
    getReport: (id) => {
      const report = file.reports?.find((r) => r.id === id);
      return report ? Promise.resolve(report) : notFound('That report');
    },
    deleteReport: READ_ONLY,
    reportDownloadUrl: () => null,
    uploadOrgFile: READ_ONLY,

    getNotifications: () => Promise.resolve({ items: [], unread: 0 }),
    markNotificationsRead: () => Promise.resolve(),
    getNotificationPrefs: () => Promise.resolve({}),
    putNotificationPrefs: READ_ONLY,
  };
}
