/**
 * An in-memory platform API shared by the Vitest fake backend and the
 * Playwright route mocks. `handlePlatformRequest` answers one request from
 * the fixtures (and mutates its own state for creates and updates) or returns
 * null when the path is not a platform route, so the caller can fall through
 * to the single-recording mocks.
 */
import type {
  AlertUpdate,
  AuthConfig,
  DeploymentCreate,
  DeploymentUpdate,
  InviteCreate,
  Me,
  MembershipUpdate,
  Organization,
  OrganizationCreate,
  OrganizationUpdate,
  RecorderCreate,
  RecorderUpdate,
  ReportCreate,
  SiteCreate,
  SiteUpdate,
} from '../../api/generated';
import {
  ALERTS,
  ALERT_RULES,
  AUTH_DEV,
  DEPLOYMENTS,
  INVITES,
  MEMBERS,
  NOTIFICATIONS,
  NOTIFICATION_PREFS,
  ORG,
  RECORDERS,
  RECORDINGS,
  REPORTS,
  REPORT_TEMPLATES,
  SITES,
  USER,
  buildAccumulation,
  buildBatchJob,
  buildDashboard,
  buildPhenology,
  buildRecorderHealth,
  buildReport,
  buildSiteComparison,
  me as buildMe,
} from './platform';

export interface PlatformServerOptions {
  auth?: AuthConfig;
  /** Start signed in (a session cookie exists). Default true for dev, false for google. */
  signedIn?: boolean;
  /** Role of the signed-in user in every organization. */
  role?: Me['roles'][string];
  /** Organizations the user belongs to; [] shows the create form. */
  organizations?: Organization[];
  /** Polls before a batch job or report finishes. */
  pollsBeforeComplete?: number;
  /** The first N batch job polls answer 503 (a restart or network blip). */
  failingJobPolls?: number;
  /** Respond 403 to every mutating request (to test forbidden handling). */
  forbidWrites?: boolean;
  /** Return 404 for /auth/config (an older backend). */
  noPlatform?: boolean;
  /** Start without any data (fresh organization). */
  empty?: boolean;
}

export interface PlatformServerState {
  options: PlatformServerOptions;
  signedIn: boolean;
  me: Me;
  sites: typeof SITES;
  recorders: typeof RECORDERS;
  deployments: typeof DEPLOYMENTS;
  alerts: typeof ALERTS;
  rules: typeof ALERT_RULES;
  prefs: typeof NOTIFICATION_PREFS;
  members: typeof MEMBERS;
  invites: typeof INVITES;
  reports: typeof REPORTS;
  batches: Record<string, { files: string[]; polls: number; siteId: string }>;
  reportPolls: Record<string, number>;
  counters: {
    site: number;
    recorder: number;
    deployment: number;
    batch: number;
    report: number;
    invite: number;
    org: number;
  };
  /** Every request, for assertions. */
  log: Array<{ method: string; path: string; body: unknown }>;
  notificationsRead: boolean;
}

export interface Reply {
  status: number;
  body: unknown;
}

export function createPlatformServer(options: PlatformServerOptions = {}): PlatformServerState {
  const auth = options.auth ?? AUTH_DEV;
  const signedIn = options.signedIn ?? auth.mode !== 'google';
  const organizations = options.organizations ?? [ORG];
  return {
    options,
    signedIn,
    me: buildMe({ organizations, role: options.role, mode: auth.mode }),
    sites: options.empty ? [] : SITES.map((s) => ({ ...s, stats: { ...s.stats } })),
    recorders: options.empty ? [] : RECORDERS.map((r) => ({ ...r })),
    deployments: options.empty ? [] : DEPLOYMENTS.map((d) => ({ ...d })),
    alerts: options.empty ? [] : ALERTS.map((a) => ({ ...a })),
    rules: { ...ALERT_RULES },
    prefs: { ...NOTIFICATION_PREFS },
    members: MEMBERS.map((m) => ({ ...m })),
    invites: options.empty ? [] : INVITES.map((i) => ({ ...i })),
    reports: options.empty ? [] : REPORTS.map((r) => ({ ...r })),
    batches: {},
    reportPolls: {},
    counters: { site: 0, recorder: 0, deployment: 0, batch: 0, report: 0, invite: 0, org: 0 },
    log: [],
    notificationsRead: false,
  };
}

const json = (status: number, body: unknown): Reply => ({ status, body });
const notFound = (what = 'Not found'): Reply =>
  json(404, { error_code: 'not_found', message: what });
const unauthenticated = (): Reply =>
  json(401, { error_code: 'unauthenticated', message: 'Sign in to continue.' });
const forbidden = (): Reply =>
  json(403, { error_code: 'forbidden', message: 'Your role does not allow that.' });

function alertPage(items: typeof ALERTS) {
  const counts_by_category: Record<string, number> = {};
  const counts_by_status: Record<string, number> = {};
  for (const a of items) {
    counts_by_category[a.category] = (counts_by_category[a.category] ?? 0) + 1;
    counts_by_status[a.status] = (counts_by_status[a.status] ?? 0) + 1;
  }
  return { items, total: items.length, counts_by_category, counts_by_status };
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * Answers a platform request. `body` is parsed JSON for JSON requests, or a
 * record of form fields for multipart (files as "file:<name>").
 */
export function handlePlatformRequest(
  state: PlatformServerState,
  method: string,
  path: string,
  params: URLSearchParams,
  body: unknown,
): Reply | null {
  const opts = state.options;
  const auth = opts.auth ?? AUTH_DEV;
  const m = method.toUpperCase();
  state.log.push({ method: m, path, body });

  if (path === '/auth/config') {
    if (opts.noPlatform) return notFound();
    return json(200, auth);
  }
  if (path === '/auth/dev' && m === 'POST') {
    const login = body as { email: string; name?: string | null };
    state.signedIn = true;
    state.me = {
      ...state.me,
      user: { ...USER, email: login.email, name: login.name?.trim() || login.email.split('@')[0]! },
    };
    return json(200, state.me);
  }
  if (path === '/auth/me') return state.signedIn ? json(200, state.me) : unauthenticated();
  if (path === '/auth/logout' && m === 'POST') {
    state.signedIn = false;
    return json(204, null);
  }

  const platformPaths =
    /^\/(me\/|orgs|sites\/|recorders\/|deployments\/|uploads\/|recordings\/|alerts\/|reports|invites\/|files\/)/;
  if (!platformPaths.test(path)) return null;
  if (!state.signedIn) return unauthenticated();
  if (opts.forbidWrites && m !== 'GET') return forbidden();
  const roleOf = (org: string) => state.me.roles[org] ?? 'viewer';
  const rank: Record<string, number> = { viewer: 0, reviewer: 1, manager: 2, owner: 3 };
  const needs = (org: string, role: string) => (rank[roleOf(org)] ?? 0) >= (rank[role] ?? 0);
  /** Item routes (/sites/{id}...) are checked against the user's highest role. */
  const needsAny = (role: string) =>
    Object.values(state.me.roles).some((r) => (rank[r] ?? 0) >= (rank[role] ?? 0));

  /* Account */
  if (path === '/me/notifications' && m === 'GET') {
    return json(200, state.notificationsRead ? { items: [], unread: 0 } : NOTIFICATIONS);
  }
  if (path === '/me/notifications/read' && m === 'POST') {
    state.notificationsRead = true;
    return json(204, null);
  }
  if (path === '/me/notification-prefs' && m === 'GET') return json(200, state.prefs);
  if (path === '/me/notification-prefs' && m === 'PUT') {
    state.prefs = { ...state.prefs, ...(body as object) };
    return json(200, state.prefs);
  }

  /* Organizations */
  if (path === '/orgs' && m === 'GET') return json(200, state.me.organizations);
  if (path === '/orgs' && m === 'POST') {
    const create = body as OrganizationCreate;
    state.counters.org += 1;
    const org: Organization = {
      id: `org_new_${state.counters.org}`,
      slug: create.name.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
      name: create.name,
      kind: create.kind ?? 'farm',
      timezone: create.timezone ?? 'UTC',
      region: create.region ?? null,
      country: create.country ?? null,
      created_at: new Date().toISOString(),
      member_count: 1,
      site_count: 0,
    };
    state.me = {
      ...state.me,
      organizations: [...state.me.organizations, org],
      roles: { ...state.me.roles, [org.id]: 'owner' },
    };
    return json(201, org);
  }

  let match = /^\/orgs\/([^/]+)(\/.*)?$/.exec(path);
  if (match) {
    const orgKey = decodeURIComponent(match[1]!);
    const rest = match[2] ?? '';
    const org = state.me.organizations.find((o) => o.id === orgKey || o.slug === orgKey);
    if (!org) return forbidden();
    const orgId = org.id;

    if (!rest) {
      if (m === 'GET') return json(200, org);
      if (m === 'PATCH') {
        if (!needs(orgId, 'manager')) return forbidden();
        const update = body as OrganizationUpdate;
        const next: Organization = {
          ...org,
          name: update.name ?? org.name,
          kind: update.kind ?? org.kind,
          timezone: update.timezone ?? org.timezone,
          region: update.region === undefined ? org.region : update.region,
          country: update.country === undefined ? org.country : update.country,
        };
        state.me = {
          ...state.me,
          organizations: state.me.organizations.map((o) => (o.id === orgId ? next : o)),
        };
        return json(200, next);
      }
    }
    if (rest === '/members' && m === 'GET') return json(200, state.members);
    const member = /^\/members\/([^/]+)$/.exec(rest);
    if (member) {
      if (!needs(orgId, 'owner')) return forbidden();
      const userId = decodeURIComponent(member[1]!);
      if (m === 'PATCH') {
        const update = body as MembershipUpdate;
        state.members = state.members.map((x) =>
          x.user.id === userId ? { ...x, role: update.role } : x,
        );
        return json(200, state.members.find((x) => x.user.id === userId) ?? null);
      }
      if (m === 'DELETE') {
        state.members = state.members.filter((x) => x.user.id !== userId);
        return json(204, null);
      }
    }
    if (rest === '/invites' && m === 'GET') return json(200, state.invites);
    if (rest === '/invites' && m === 'POST') {
      if (!needs(orgId, 'manager')) return forbidden();
      const create = body as InviteCreate;
      state.counters.invite += 1;
      const invite = {
        id: `inv_new_${state.counters.invite}`,
        organization_id: orgId,
        email: create.email,
        role: create.role ?? ('viewer' as const),
        invited_by: USER.id,
        expires_at: new Date(Date.now() + 14 * 86_400_000).toISOString(),
        accept_url: `http://localhost:5173/#/invite/tok_new_${state.counters.invite}`,
      };
      state.invites = [invite, ...state.invites];
      return json(201, invite);
    }
    const inviteMatch = /^\/invites\/([^/]+)$/.exec(rest);
    if (inviteMatch && m === 'DELETE') {
      if (!needs(orgId, 'manager')) return forbidden();
      const id = decodeURIComponent(inviteMatch[1]!);
      const found = state.invites.find((i) => i.id === id);
      if (!found) return notFound('No invite with that id exists in this organization.');
      if (found.accepted_at) {
        return json(409, { error_code: 'conflict', message: 'This invite was already accepted.' });
      }
      state.invites = state.invites.filter((i) => i.id !== id);
      return json(204, null);
    }

    /* Sites */
    if (rest === '/sites' && m === 'GET') return json(200, state.sites);
    if (rest === '/sites' && m === 'POST') {
      if (!needs(orgId, 'manager')) return forbidden();
      const create = body as SiteCreate;
      state.counters.site += 1;
      const site = {
        id: `site_new_${state.counters.site}`,
        organization_id: orgId,
        name: create.name,
        habitat_type: create.habitat_type ?? null,
        latitude: create.latitude ?? null,
        longitude: create.longitude ?? null,
        area_hectares: create.area_hectares ?? null,
        fsa_field_number: create.fsa_field_number ?? null,
        paddock_id: create.paddock_id ?? null,
        notes: create.notes ?? null,
        created_at: new Date().toISOString(),
        stats: {
          recordings: 0,
          minutes_recorded: 0,
          species_counted: 0,
          open_alerts: 0,
          health: 'unknown' as const,
        },
      };
      state.sites = [...state.sites, site];
      return json(201, site);
    }
    if (rest.startsWith('/sites/compare'))
      return json(
        200,
        buildSiteComparison(params.get('from') ?? daysAgo(89), params.get('to') ?? today()),
      );

    /* Recorders and deployments */
    if (rest === '/recorders' && m === 'GET') return json(200, state.recorders);
    if (rest === '/recorders' && m === 'POST') {
      if (!needs(orgId, 'manager')) return forbidden();
      const create = body as RecorderCreate;
      state.counters.recorder += 1;
      const recorder = {
        id: `rec_new_${state.counters.recorder}`,
        organization_id: orgId,
        label: create.label,
        make: create.make ?? ('audiomoth' as const),
        model: create.model ?? null,
        serial: create.serial ?? null,
        firmware: create.firmware ?? null,
        notes: create.notes ?? null,
        created_at: new Date().toISOString(),
        active_deployment_id: null,
        last_recording_at: null,
        health: 'unknown' as const,
      };
      state.recorders = [...state.recorders, recorder];
      return json(201, recorder);
    }
    if (rest.startsWith('/deployments') && m === 'GET') {
      const active = params.get('active');
      const list =
        active === null
          ? state.deployments
          : state.deployments.filter((d) => !d.ended_at === (active === 'true'));
      return json(200, list);
    }
    if (rest === '/deployments' && m === 'POST') {
      if (!needs(orgId, 'manager')) return forbidden();
      const create = body as DeploymentCreate;
      state.counters.deployment += 1;
      const deployment = {
        id: `dep_new_${state.counters.deployment}`,
        organization_id: orgId,
        ...create,
        ended_at: create.ended_at ?? null,
        created_at: new Date().toISOString(),
      };
      state.deployments = [deployment, ...state.deployments];
      return json(201, deployment);
    }

    /* Uploads and recordings */
    if (rest === '/uploads' && m === 'POST') {
      if (!needs(orgId, 'manager')) return forbidden();
      const fields = body as Record<string, unknown>;
      const raw = fields.files;
      const list: unknown[] = Array.isArray(raw)
        ? (raw as unknown[])
        : raw === undefined
          ? []
          : [raw];
      const files = list.map((v) => (typeof v === 'string' ? v : 'file').replace(/^file:/, ''));
      state.counters.batch += 1;
      const id = `batch_${state.counters.batch}`;
      const siteId = typeof fields.site_id === 'string' ? fields.site_id : '';
      state.batches[id] = { files, polls: opts.pollsBeforeComplete ?? 2, siteId };
      return json(202, buildBatchJob(id, files, 'queued', siteId));
    }
    if (rest.startsWith('/uploads') && m === 'GET') {
      return json(
        200,
        Object.entries(state.batches).map(([id, b]) => ({
          ...buildBatchJob(id, b.files, 'completed', b.siteId),
          items: [],
        })),
      );
    }
    if (rest.startsWith('/recordings') && m === 'GET') {
      let items = opts.empty ? [] : RECORDINGS;
      const siteId = params.get('site_id');
      const quality = params.get('quality');
      const species = params.get('species');
      const from = params.get('from');
      const to = params.get('to');
      if (siteId) items = items.filter((r) => r.site_id === siteId);
      if (quality) items = items.filter((r) => r.quality_status === quality);
      if (species) items = items.filter(() => true);
      if (from) items = items.filter((r) => (r.captured_at ?? '') >= from);
      if (to) items = items.filter((r) => (r.captured_at ?? '').slice(0, 10) <= to);
      const page = Number(params.get('page') ?? '1') || 1;
      const pageSize = Number(params.get('page_size') ?? '25') || 25;
      return json(200, {
        items: items.slice((page - 1) * pageSize, page * pageSize),
        page,
        page_size: pageSize,
        total: items.length,
      });
    }

    /* Dashboard and series */
    if (rest.startsWith('/dashboard')) {
      if (opts.empty) {
        const d = buildDashboard({
          from: params.get('from') ?? daysAgo(89),
          to: params.get('to') ?? today(),
        });
        return json(200, {
          ...d,
          recordings: 0,
          minutes_recorded: 0,
          species_counted: 0,
          detection_events: 0,
          open_alerts: 0,
          richness_by_day: [],
          activity_heatmap: [],
          species: [],
          by_taxon: [],
          indices_by_day: [],
          quality: {},
        });
      }
      return json(
        200,
        buildDashboard({
          from: params.get('from') ?? daysAgo(89),
          to: params.get('to') ?? today(),
          siteId: params.get('site_id'),
        }),
      );
    }
    if (rest.startsWith('/phenology')) {
      return json(
        200,
        buildPhenology(
          params.get('scientific_name') ?? 'Turdus migratorius',
          params.get('site_id'),
        ),
      );
    }

    /* Alerts */
    if (rest.startsWith('/alerts/evaluate') && m === 'POST')
      return json(200, alertPage(state.alerts.filter((a) => a.status === 'open')));
    if (rest.startsWith('/alerts') && m === 'GET') {
      let items = state.alerts;
      const status = params.get('status');
      const category = params.get('category');
      const siteId = params.get('site_id');
      const recorderId = params.get('recorder_id');
      if (status) items = items.filter((a) => a.status === status);
      if (category) items = items.filter((a) => a.category === category);
      if (siteId) items = items.filter((a) => a.site_id === siteId);
      if (recorderId) items = items.filter((a) => a.recorder_id === recorderId);
      return json(200, alertPage(items));
    }
    if (rest === '/alert-rules' && m === 'GET') return json(200, state.rules);
    if (rest === '/alert-rules' && m === 'PUT') {
      if (!needs(orgId, 'manager')) return forbidden();
      state.rules = { ...(body as object) };
      return json(200, state.rules);
    }

    /* Reports and files */
    if (rest === '/reports' && m === 'GET') return json(200, { items: state.reports });
    if (rest === '/reports' && m === 'POST') {
      if (!needs(orgId, 'reviewer')) return forbidden();
      const create = body as ReportCreate;
      state.counters.report += 1;
      const id = `rp_new_${state.counters.report}`;
      state.reportPolls[id] = opts.pollsBeforeComplete ?? 1;
      const report = buildReport(id, create, 'queued');
      state.reports = [report, ...state.reports];
      return json(202, report);
    }
    if (rest === '/files' && m === 'POST') {
      const fields = body as Record<string, unknown>;
      return json(201, {
        id: 'file_1',
        organization_id: orgId,
        filename: (typeof fields.file === 'string' ? fields.file : 'file').replace(/^file:/, ''),
        content_type: 'image/png',
        byte_size: 1024,
        url: '/api/v1/files/file_1',
        created_at: new Date().toISOString(),
      });
    }
    return notFound(`No mock for ${m} ${path}`);
  }

  /* Item routes */
  match = /^\/sites\/([^/]+)(\/accumulation)?$/.exec(path);
  if (match) {
    const id = decodeURIComponent(match[1]!);
    const site = state.sites.find((s) => s.id === id);
    if (!site) return notFound('That site does not exist.');
    if (match[2]) return json(200, buildAccumulation(id));
    if (m === 'GET') return json(200, site);
    if (m === 'PATCH') {
      if (!needsAny('manager')) return forbidden();
      const update = body as SiteUpdate;
      const next = {
        ...site,
        ...Object.fromEntries(Object.entries(update).filter(([, v]) => v !== undefined)),
      };
      state.sites = state.sites.map((s) => (s.id === id ? next : s));
      return json(200, next);
    }
    if (m === 'DELETE') {
      if ((site.stats.recordings ?? 0) > 0)
        return json(409, {
          error_code: 'conflict',
          message: 'The site has recordings. End its deployments instead.',
        });
      state.sites = state.sites.filter((s) => s.id !== id);
      return json(204, null);
    }
  }
  match = /^\/recorders\/([^/]+)(\/health)?$/.exec(path);
  if (match) {
    const id = decodeURIComponent(match[1]!);
    const recorder = state.recorders.find((r) => r.id === id);
    if (!recorder) return notFound('That recorder does not exist.');
    if (match[2])
      return json(200, buildRecorderHealth(id, Number(params.get('days') ?? '30') || 30));
    if (m === 'GET') return json(200, recorder);
    if (m === 'PATCH') {
      const update = body as RecorderUpdate;
      const next = {
        ...recorder,
        ...Object.fromEntries(Object.entries(update).filter(([, v]) => v !== undefined)),
      };
      state.recorders = state.recorders.map((r) => (r.id === id ? next : r));
      return json(200, next);
    }
    if (m === 'DELETE') {
      state.recorders = state.recorders.filter((r) => r.id !== id);
      return json(204, null);
    }
  }
  match = /^\/deployments\/([^/]+)$/.exec(path);
  if (match) {
    const id = decodeURIComponent(match[1]!);
    const deployment = state.deployments.find((d) => d.id === id);
    if (!deployment) return notFound();
    if (m === 'GET') return json(200, deployment);
    if (m === 'PATCH') {
      const update = body as DeploymentUpdate;
      const next = { ...deployment, ...update };
      state.deployments = state.deployments.map((d) => (d.id === id ? next : d));
      return json(200, next);
    }
  }
  match = /^\/uploads\/([^/]+)$/.exec(path);
  if (match && m === 'GET') {
    const id = decodeURIComponent(match[1]!);
    const batch = state.batches[id];
    if (!batch) return notFound();
    if ((opts.failingJobPolls ?? 0) > 0) {
      opts.failingJobPolls = (opts.failingJobPolls ?? 0) - 1;
      return json(503, { error_code: 'backend_unavailable', message: 'Restarting.' });
    }
    if (batch.polls > 0) {
      batch.polls -= 1;
      return json(200, buildBatchJob(id, batch.files, 'processing', batch.siteId));
    }
    return json(200, buildBatchJob(id, batch.files, 'completed', batch.siteId));
  }
  match = /^\/recordings\/([^/]+)$/.exec(path);
  if (match) {
    const id = decodeURIComponent(match[1]!);
    const row =
      RECORDINGS.find((r) => r.id === id) ??
      (id.startsWith('rc_new') ? { ...RECORDINGS[0]!, id, filename: 'uploaded.WAV' } : null);
    if (!row) return notFound('That recording does not exist.');
    if (m === 'GET') return json(200, row);
    if (m === 'DELETE') return json(204, null);
  }
  match = /^\/alerts\/([^/]+)$/.exec(path);
  if (match && m === 'PATCH') {
    const id = decodeURIComponent(match[1]!);
    const alert = state.alerts.find((a) => a.id === id);
    if (!alert) return notFound();
    if (!needsAny('reviewer')) return forbidden();
    const update = body as AlertUpdate;
    const next = {
      ...alert,
      status: update.status,
      note: update.note === undefined ? alert.note : update.note,
      snoozed_until: update.snoozed_until ?? null,
      acknowledged_by:
        update.status === 'acknowledged' ? state.me.user.name : alert.acknowledged_by,
      updated_at: new Date().toISOString(),
    };
    state.alerts = state.alerts.map((a) => (a.id === id ? next : a));
    return json(200, next);
  }
  if (path === '/reports/templates') return json(200, REPORT_TEMPLATES);
  match = /^\/reports\/([^/]+?)(\.pdf|\.json)?$/.exec(path);
  if (match) {
    const id = decodeURIComponent(match[1]!);
    const report = state.reports.find((r) => r.id === id);
    if (!report) return notFound();
    if (match[2] === '.json') return json(200, { report_id: id, note: 'data bundle' });
    if (match[2] === '.pdf') return { status: 200, body: '%PDF-1.4 mock' };
    if (m === 'DELETE') {
      state.reports = state.reports.filter((r) => r.id !== id);
      return json(204, null);
    }
    const polls = state.reportPolls[id];
    if (polls !== undefined && polls > 0) {
      state.reportPolls[id] = polls - 1;
      return json(200, { ...report, status: 'rendering' });
    }
    if (polls !== undefined) {
      const ready = buildReport(id, report, 'ready');
      state.reports = state.reports.map((r) => (r.id === id ? ready : r));
      return json(200, ready);
    }
    return json(200, report);
  }
  match = /^\/invites\/([^/]+)\/accept$/.exec(path);
  if (match && m === 'POST') {
    const org: Organization = {
      ...ORG,
      id: 'org_invited',
      slug: 'invited-farm',
      name: 'Fall Creek Land Trust',
    };
    state.me = {
      ...state.me,
      organizations: [...state.me.organizations.filter((o) => o.id !== org.id), org],
      roles: { ...state.me.roles, [org.id]: 'reviewer' },
    };
    return json(200, org);
  }
  if (path.startsWith('/files/')) return { status: 200, body: 'PNG' };
  return notFound(`No mock for ${m} ${path}`);
}
