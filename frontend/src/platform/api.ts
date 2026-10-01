/**
 * The data source the platform pages talk to. The HTTP implementation wraps
 * src/api/platform.ts; the demo implementation (src/lib/platformDemo.ts)
 * answers from a static JSON file and refuses writes. Pages never import the
 * HTTP module directly, so the same screens render either source.
 */
import { getAnalysis, getModels } from '../api/client';
import type {
  Accumulation,
  AlertPage,
  AlertRules,
  AlertUpdate,
  Analysis,
  BatchJob,
  Dashboard,
  Deployment,
  DeploymentCreate,
  DeploymentUpdate,
  Invite,
  InviteCreate,
  Me,
  Membership,
  MembershipUpdate,
  ModelsResponse,
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
} from '../api/generated';
import * as http from '../api/platform';
import type { Alert } from '../api/generated';
import type { ProgressHandler } from '../api/client';

export interface PlatformApi {
  /** True for the static demo: every write is refused with a friendly message. */
  readOnly: boolean;

  getMe(signal?: AbortSignal): Promise<Me>;
  listOrganizations(signal?: AbortSignal): Promise<Organization[]>;
  createOrganization(body: OrganizationCreate): Promise<Organization>;
  getOrganization(org: string, signal?: AbortSignal): Promise<Organization>;
  updateOrganization(org: string, body: OrganizationUpdate): Promise<Organization>;
  listMembers(org: string, signal?: AbortSignal): Promise<Membership[]>;
  updateMember(org: string, userId: string, body: MembershipUpdate): Promise<Membership>;
  removeMember(org: string, userId: string): Promise<void>;
  listInvites(org: string, signal?: AbortSignal): Promise<Invite[]>;
  createInvite(org: string, body: InviteCreate): Promise<Invite>;
  acceptInvite(token: string): Promise<Organization>;

  listSites(org: string, signal?: AbortSignal): Promise<Site[]>;
  createSite(org: string, body: SiteCreate): Promise<Site>;
  getSite(siteId: string, signal?: AbortSignal): Promise<Site>;
  updateSite(siteId: string, body: SiteUpdate): Promise<Site>;
  deleteSite(siteId: string): Promise<void>;
  getAccumulation(siteId: string, signal?: AbortSignal): Promise<Accumulation>;

  listRecorders(org: string, signal?: AbortSignal): Promise<Recorder[]>;
  createRecorder(org: string, body: RecorderCreate): Promise<Recorder>;
  getRecorder(id: string, signal?: AbortSignal): Promise<Recorder>;
  updateRecorder(id: string, body: RecorderUpdate): Promise<Recorder>;
  deleteRecorder(id: string): Promise<void>;
  getRecorderHealth(id: string, days?: number, signal?: AbortSignal): Promise<RecorderHealth>;
  listDeployments(
    org: string,
    options?: { active?: boolean },
    signal?: AbortSignal,
  ): Promise<Deployment[]>;
  createDeployment(org: string, body: DeploymentCreate): Promise<Deployment>;
  updateDeployment(id: string, body: DeploymentUpdate): Promise<Deployment>;

  createBatchUpload(
    org: string,
    params: http.BatchUploadParams,
    onProgress?: ProgressHandler,
    signal?: AbortSignal,
  ): Promise<BatchJob>;
  getBatchJob(jobId: string, signal?: AbortSignal): Promise<BatchJob>;
  listBatchJobs(org: string, limit?: number, signal?: AbortSignal): Promise<BatchJob[]>;
  listRecordings(
    org: string,
    filters?: http.RecordingFilters,
    signal?: AbortSignal,
  ): Promise<RecordingPage>;
  getRecording(id: string, signal?: AbortSignal): Promise<RecordingSummary>;
  deleteRecording(id: string): Promise<void>;
  getAnalysis(id: string, threshold?: number | null, signal?: AbortSignal): Promise<Analysis>;
  getModels(signal?: AbortSignal): Promise<ModelsResponse>;

  getDashboard(org: string, query?: http.PeriodQuery, signal?: AbortSignal): Promise<Dashboard>;
  getPhenology(
    org: string,
    query: { scientific_name: string; site_id?: string | null; years?: number },
    signal?: AbortSignal,
  ): Promise<Phenology>;
  compareSites(
    org: string,
    query?: { from?: string | null; to?: string | null },
    signal?: AbortSignal,
  ): Promise<SiteComparison>;

  listAlerts(org: string, filters?: http.AlertFilters, signal?: AbortSignal): Promise<AlertPage>;
  updateAlert(id: string, body: AlertUpdate): Promise<Alert>;
  getAlertRules(org: string, signal?: AbortSignal): Promise<AlertRules>;
  putAlertRules(org: string, rules: AlertRules): Promise<AlertRules>;
  evaluateAlerts(org: string): Promise<AlertPage>;

  getReportTemplates(signal?: AbortSignal): Promise<ReportTemplates>;
  listReports(org: string, signal?: AbortSignal): Promise<ReportList>;
  createReport(org: string, body: ReportCreate): Promise<Report>;
  getReport(id: string, signal?: AbortSignal): Promise<Report>;
  deleteReport(id: string): Promise<void>;
  reportDownloadUrl(report: Report, kind: 'pdf' | 'json'): string | null;
  uploadOrgFile(
    org: string,
    file: File,
    onProgress?: ProgressHandler,
    signal?: AbortSignal,
  ): Promise<UploadedFile>;

  getNotifications(unreadOnly?: boolean, signal?: AbortSignal): Promise<NotificationPage>;
  markNotificationsRead(body: { ids: string[] } | { all: true }): Promise<void>;
  getNotificationPrefs(signal?: AbortSignal): Promise<NotificationPrefs>;
  putNotificationPrefs(prefs: NotificationPrefs): Promise<NotificationPrefs>;
}

export const httpPlatformApi: PlatformApi = {
  readOnly: false,
  getMe: http.getMe,
  listOrganizations: http.listOrganizations,
  createOrganization: http.createOrganization,
  getOrganization: http.getOrganization,
  updateOrganization: http.updateOrganization,
  listMembers: http.listMembers,
  updateMember: http.updateMember,
  removeMember: http.removeMember,
  listInvites: http.listInvites,
  createInvite: http.createInvite,
  acceptInvite: http.acceptInvite,
  listSites: http.listSites,
  createSite: http.createSite,
  getSite: http.getSite,
  updateSite: http.updateSite,
  deleteSite: http.deleteSite,
  getAccumulation: http.getAccumulation,
  listRecorders: http.listRecorders,
  createRecorder: http.createRecorder,
  getRecorder: http.getRecorder,
  updateRecorder: http.updateRecorder,
  deleteRecorder: http.deleteRecorder,
  getRecorderHealth: http.getRecorderHealth,
  listDeployments: http.listDeployments,
  createDeployment: http.createDeployment,
  updateDeployment: http.updateDeployment,
  createBatchUpload: http.createBatchUpload,
  getBatchJob: http.getBatchJob,
  listBatchJobs: http.listBatchJobs,
  listRecordings: http.listRecordings,
  getRecording: http.getRecording,
  deleteRecording: http.deleteRecording,
  getAnalysis: (id, threshold, signal) => getAnalysis(id, { threshold, signal }),
  getModels,
  getDashboard: http.getDashboard,
  getPhenology: http.getPhenology,
  compareSites: http.compareSites,
  listAlerts: http.listAlerts,
  updateAlert: http.updateAlert,
  getAlertRules: http.getAlertRules,
  putAlertRules: http.putAlertRules,
  evaluateAlerts: http.evaluateAlerts,
  getReportTemplates: http.getReportTemplates,
  listReports: http.listReports,
  createReport: http.createReport,
  getReport: http.getReport,
  deleteReport: http.deleteReport,
  reportDownloadUrl: http.reportDownloadUrl,
  uploadOrgFile: http.uploadOrgFile,
  getNotifications: http.getNotifications,
  markNotificationsRead: http.markNotificationsRead,
  getNotificationPrefs: http.getNotificationPrefs,
  putNotificationPrefs: http.putNotificationPrefs,
};
