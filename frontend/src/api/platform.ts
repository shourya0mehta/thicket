/**
 * Typed client for the multi-tenant platform routes (docs/PLATFORM_API.md).
 * Every response shape comes from the generated contract; mutating requests
 * carry `X-Requested-With: thicket` and a 401 routes the app to sign-in
 * (both handled in requestJson).
 */
import {
  apiUrl,
  requestJson,
  requestWithBody,
  resolveApiUrl,
  uploadForm,
  type ProgressHandler,
} from './client';
import type {
  Accumulation,
  Alert,
  AlertPage,
  AlertRules,
  AlertUpdate,
  AuthConfig,
  BatchJob,
  Dashboard,
  Deployment,
  DeploymentCreate,
  DeploymentUpdate,
  DevLogin,
  Invite,
  InviteCreate,
  Me,
  Membership,
  MembershipUpdate,
  NotificationPage,
  NotificationPrefs,
  Organization,
  OrganizationCreate,
  OrganizationUpdate,
  Phenology,
  Recorder,
  RecorderCreate,
  RecorderHealth,
  RecorderUpdate,
  RecordingPage,
  RecordingSummary,
  Report,
  ReportCreate,
  ReportList,
  ReportTemplates,
  Site,
  SiteComparison,
  SiteCreate,
  SiteUpdate,
  UploadedFile,
} from './generated';

type QueryValue = string | number | boolean | null | undefined;

function withQuery(path: string, query?: object): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query as Record<string, QueryValue>)) {
    if (value === null || value === undefined || value === '') continue;
    params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

const enc = encodeURIComponent;

/* Auth and account */

export function getAuthConfig(signal?: AbortSignal): Promise<AuthConfig> {
  return requestJson<AuthConfig>('/auth/config', { signal });
}

export function getMe(signal?: AbortSignal): Promise<Me> {
  return requestJson<Me>('/auth/me', { signal });
}

export function devLogin(body: DevLogin): Promise<Me> {
  return requestWithBody<Me>('POST', '/auth/dev', body);
}

export async function logout(): Promise<void> {
  await requestJson<unknown>('/auth/logout', { method: 'POST' });
}

export function getNotifications(
  unreadOnly = false,
  signal?: AbortSignal,
): Promise<NotificationPage> {
  return requestJson<NotificationPage>(
    withQuery('/me/notifications', { unread_only: unreadOnly ? 'true' : undefined }),
    { signal },
  );
}

export async function markNotificationsRead(body: { ids: string[] } | { all: true }) {
  await requestWithBody<unknown>('POST', '/me/notifications/read', body);
}

export function getNotificationPrefs(signal?: AbortSignal): Promise<NotificationPrefs> {
  return requestJson<NotificationPrefs>('/me/notification-prefs', { signal });
}

export function putNotificationPrefs(prefs: NotificationPrefs): Promise<NotificationPrefs> {
  return requestWithBody<NotificationPrefs>('PUT', '/me/notification-prefs', prefs);
}

/* Organizations and members */

export function listOrganizations(signal?: AbortSignal): Promise<Organization[]> {
  return requestJson<Organization[]>('/orgs', { signal });
}

export function createOrganization(body: OrganizationCreate): Promise<Organization> {
  return requestWithBody<Organization>('POST', '/orgs', body);
}

export function getOrganization(org: string, signal?: AbortSignal): Promise<Organization> {
  return requestJson<Organization>(`/orgs/${enc(org)}`, { signal });
}

export function updateOrganization(org: string, body: OrganizationUpdate): Promise<Organization> {
  return requestWithBody<Organization>('PATCH', `/orgs/${enc(org)}`, body);
}

export function listMembers(org: string, signal?: AbortSignal): Promise<Membership[]> {
  return requestJson<Membership[]>(`/orgs/${enc(org)}/members`, { signal });
}

export function updateMember(
  org: string,
  userId: string,
  body: MembershipUpdate,
): Promise<Membership> {
  return requestWithBody<Membership>('PATCH', `/orgs/${enc(org)}/members/${enc(userId)}`, body);
}

export async function removeMember(org: string, userId: string): Promise<void> {
  await requestJson<unknown>(`/orgs/${enc(org)}/members/${enc(userId)}`, { method: 'DELETE' });
}

export function listInvites(org: string, signal?: AbortSignal): Promise<Invite[]> {
  return requestJson<Invite[]>(`/orgs/${enc(org)}/invites`, { signal });
}

export function createInvite(org: string, body: InviteCreate): Promise<Invite> {
  return requestWithBody<Invite>('POST', `/orgs/${enc(org)}/invites`, body);
}

export function acceptInvite(token: string): Promise<Organization> {
  return requestWithBody<Organization>('POST', `/invites/${enc(token)}/accept`, {});
}

/* Sites, recorders, deployments */

export function listSites(org: string, signal?: AbortSignal): Promise<Site[]> {
  return requestJson<Site[]>(`/orgs/${enc(org)}/sites`, { signal });
}

export function createSite(org: string, body: SiteCreate): Promise<Site> {
  return requestWithBody<Site>('POST', `/orgs/${enc(org)}/sites`, body);
}

export function getSite(siteId: string, signal?: AbortSignal): Promise<Site> {
  return requestJson<Site>(`/sites/${enc(siteId)}`, { signal });
}

export function updateSite(siteId: string, body: SiteUpdate): Promise<Site> {
  return requestWithBody<Site>('PATCH', `/sites/${enc(siteId)}`, body);
}

export async function deleteSite(siteId: string): Promise<void> {
  await requestJson<unknown>(`/sites/${enc(siteId)}`, { method: 'DELETE' });
}

export function getAccumulation(siteId: string, signal?: AbortSignal): Promise<Accumulation> {
  return requestJson<Accumulation>(`/sites/${enc(siteId)}/accumulation`, { signal });
}

export function listRecorders(org: string, signal?: AbortSignal): Promise<Recorder[]> {
  return requestJson<Recorder[]>(`/orgs/${enc(org)}/recorders`, { signal });
}

export function createRecorder(org: string, body: RecorderCreate): Promise<Recorder> {
  return requestWithBody<Recorder>('POST', `/orgs/${enc(org)}/recorders`, body);
}

export function getRecorder(id: string, signal?: AbortSignal): Promise<Recorder> {
  return requestJson<Recorder>(`/recorders/${enc(id)}`, { signal });
}

export function updateRecorder(id: string, body: RecorderUpdate): Promise<Recorder> {
  return requestWithBody<Recorder>('PATCH', `/recorders/${enc(id)}`, body);
}

export async function deleteRecorder(id: string): Promise<void> {
  await requestJson<unknown>(`/recorders/${enc(id)}`, { method: 'DELETE' });
}

export function getRecorderHealth(
  id: string,
  days = 30,
  signal?: AbortSignal,
): Promise<RecorderHealth> {
  return requestJson<RecorderHealth>(withQuery(`/recorders/${enc(id)}/health`, { days }), {
    signal,
  });
}

export function listDeployments(
  org: string,
  options: { active?: boolean } = {},
  signal?: AbortSignal,
): Promise<Deployment[]> {
  return requestJson<Deployment[]>(
    withQuery(`/orgs/${enc(org)}/deployments`, {
      active: options.active === undefined ? undefined : String(options.active),
    }),
    { signal },
  );
}

export function createDeployment(org: string, body: DeploymentCreate): Promise<Deployment> {
  return requestWithBody<Deployment>('POST', `/orgs/${enc(org)}/deployments`, body);
}

export function updateDeployment(id: string, body: DeploymentUpdate): Promise<Deployment> {
  return requestWithBody<Deployment>('PATCH', `/deployments/${enc(id)}`, body);
}

/* Recordings and batch ingestion */

export interface BatchUploadParams {
  files: File[];
  siteId: string;
  deploymentId?: string | null;
  recorderId?: string | null;
  timezone: string;
  models: string[];
  threshold: number;
  capturedAtOverride?: string | null;
}

export function buildBatchForm(params: BatchUploadParams): FormData {
  const form = new FormData();
  for (const file of params.files) form.append('files', file, file.name);
  for (const file of params.files) form.append('last_modified', String(file.lastModified));
  form.append('site_id', params.siteId);
  if (params.deploymentId) form.append('deployment_id', params.deploymentId);
  if (params.recorderId) form.append('recorder_id', params.recorderId);
  form.append('timezone', params.timezone);
  form.append('models', JSON.stringify(params.models));
  form.append('threshold', params.threshold.toFixed(2));
  if (params.capturedAtOverride) form.append('captured_at_override', params.capturedAtOverride);
  return form;
}

export function createBatchUpload(
  org: string,
  params: BatchUploadParams,
  onProgress?: ProgressHandler,
  signal?: AbortSignal,
): Promise<BatchJob> {
  return uploadForm<BatchJob>(
    `/orgs/${enc(org)}/uploads`,
    buildBatchForm(params),
    onProgress,
    signal,
  );
}

export function getBatchJob(jobId: string, signal?: AbortSignal): Promise<BatchJob> {
  return requestJson<BatchJob>(`/uploads/${enc(jobId)}`, { signal });
}

export function listBatchJobs(org: string, limit = 20, signal?: AbortSignal): Promise<BatchJob[]> {
  return requestJson<BatchJob[]>(withQuery(`/orgs/${enc(org)}/uploads`, { limit }), { signal });
}

export interface RecordingFilters {
  site_id?: string | null;
  from?: string | null;
  to?: string | null;
  page?: number;
  page_size?: number;
  quality?: string | null;
  species?: string | null;
}

export function listRecordings(
  org: string,
  filters: RecordingFilters = {},
  signal?: AbortSignal,
): Promise<RecordingPage> {
  return requestJson<RecordingPage>(withQuery(`/orgs/${enc(org)}/recordings`, filters), {
    signal,
  });
}

export function getRecording(id: string, signal?: AbortSignal): Promise<RecordingSummary> {
  return requestJson<RecordingSummary>(`/recordings/${enc(id)}`, { signal });
}

export async function deleteRecording(id: string): Promise<void> {
  await requestJson<unknown>(`/recordings/${enc(id)}`, { method: 'DELETE' });
}

/* Dashboard and seasonal series */

export interface PeriodQuery {
  from?: string | null;
  to?: string | null;
  site_id?: string | null;
}

export function getDashboard(
  org: string,
  query: PeriodQuery = {},
  signal?: AbortSignal,
): Promise<Dashboard> {
  return requestJson<Dashboard>(withQuery(`/orgs/${enc(org)}/dashboard`, query), { signal });
}

export function getPhenology(
  org: string,
  query: { scientific_name: string; site_id?: string | null; years?: number },
  signal?: AbortSignal,
): Promise<Phenology> {
  return requestJson<Phenology>(withQuery(`/orgs/${enc(org)}/phenology`, query), { signal });
}

export function compareSites(
  org: string,
  query: { from?: string | null; to?: string | null } = {},
  signal?: AbortSignal,
): Promise<SiteComparison> {
  return requestJson<SiteComparison>(withQuery(`/orgs/${enc(org)}/sites/compare`, query), {
    signal,
  });
}

/* Alerts */

export interface AlertFilters {
  status?: string | null;
  category?: string | null;
  kind?: string | null;
  site_id?: string | null;
  recorder_id?: string | null;
  page?: number;
}

export function listAlerts(
  org: string,
  filters: AlertFilters = {},
  signal?: AbortSignal,
): Promise<AlertPage> {
  return requestJson<AlertPage>(withQuery(`/orgs/${enc(org)}/alerts`, filters), { signal });
}

export function updateAlert(id: string, body: AlertUpdate): Promise<Alert> {
  return requestWithBody<Alert>('PATCH', `/alerts/${enc(id)}`, body);
}

export function getAlertRules(org: string, signal?: AbortSignal): Promise<AlertRules> {
  return requestJson<AlertRules>(`/orgs/${enc(org)}/alert-rules`, { signal });
}

export function putAlertRules(org: string, rules: AlertRules): Promise<AlertRules> {
  return requestWithBody<AlertRules>('PUT', `/orgs/${enc(org)}/alert-rules`, rules);
}

export function evaluateAlerts(org: string): Promise<AlertPage> {
  return requestWithBody<AlertPage>('POST', `/orgs/${enc(org)}/alerts/evaluate`, {});
}

/* Reports and files */

export function getReportTemplates(signal?: AbortSignal): Promise<ReportTemplates> {
  return requestJson<ReportTemplates>('/reports/templates', { signal });
}

export function listReports(org: string, signal?: AbortSignal): Promise<ReportList> {
  return requestJson<ReportList>(`/orgs/${enc(org)}/reports`, { signal });
}

export function createReport(org: string, body: ReportCreate): Promise<Report> {
  return requestWithBody<Report>('POST', `/orgs/${enc(org)}/reports`, body);
}

export function getReport(id: string, signal?: AbortSignal): Promise<Report> {
  return requestJson<Report>(`/reports/${enc(id)}`, { signal });
}

export async function deleteReport(id: string): Promise<void> {
  await requestJson<unknown>(`/reports/${enc(id)}`, { method: 'DELETE' });
}

/** Download link for a finished report; the server-given URL wins over the convention. */
export function reportDownloadUrl(report: Report, kind: 'pdf' | 'json'): string {
  const given = resolveApiUrl(kind === 'pdf' ? report.pdf_url : report.json_url);
  return given ?? apiUrl(`/reports/${enc(report.id)}.${kind}`);
}

export function uploadOrgFile(
  org: string,
  file: File,
  onProgress?: ProgressHandler,
  signal?: AbortSignal,
): Promise<UploadedFile> {
  const form = new FormData();
  form.append('file', file, file.name);
  return uploadForm<UploadedFile>(`/orgs/${enc(org)}/files`, form, onProgress, signal);
}
