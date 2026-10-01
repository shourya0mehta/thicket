import { useEffect, useState } from 'react';
import { SiteSelect } from '../../components/platform/filters';
import { EmptyState, ReadOnlyNote, Select } from '../../components/platform/primitives';
import { Callout } from '../../components/ui/Callout';
import { useResource } from '../../hooks/useResource';
import { orgHref } from '../../lib/routes';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';
import type { Workspace } from '../../state/useWorkspace';
import { WorkspacePage } from '../WorkspacePage';

/**
 * The single-recording workspace inside an organization: pick a site (which
 * prefills the location and name) and the result is filed under it.
 */
export function AnalyzePage({
  workspace,
  query,
}: {
  workspace: Workspace;
  query: URLSearchParams;
}) {
  const { api } = usePlatform();
  const { org, sites, permissions, recorders } = useOrg();
  const [siteId, setSiteId] = useState<string | null>(query.get('site_id'));
  const [deploymentId, setDeploymentId] = useState<string>('');
  const deployments = useResource(
    (signal) => api.listDeployments(org.id, { active: true }, signal),
    `analyze-deployments:${org.id}`,
  );
  const site = sites.data?.find((s) => s.id === siteId) ?? null;
  const siteDeployments = (deployments.data ?? []).filter((d) => d.site_id === siteId);
  const deployment = siteDeployments.find((d) => d.id === deploymentId) ?? null;

  useEffect(() => {
    workspace.setOrgContext({
      organizationId: org.id,
      siteId,
      deploymentId: deployment?.id ?? null,
      recorderId: deployment?.recorder_id ?? null,
    });
    return () => workspace.setOrgContext(null);
  }, [workspace, org.id, siteId, deployment]);

  useEffect(() => {
    if (!site) return;
    workspace.setMetadata({
      siteName: site.name,
      latitude: site.latitude != null ? String(site.latitude) : '',
      longitude: site.longitude != null ? String(site.longitude) : '',
      timezone: org.timezone,
    });
    workspace.setKeepMetadata(true);
    // Only when the chosen site changes; the user may edit the fields afterwards.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [site?.id]);

  if (!permissions.canManage) {
    return (
      <EmptyState title="Analyzing needs the manager role">
        <ReadOnlyNote>
          Viewers and reviewers can open existing recordings but not add new ones.
        </ReadOnlyNote>
      </EmptyState>
    );
  }

  return (
    <div className="space-y-6">
      <div
        className="flex flex-wrap items-center gap-x-5 gap-y-3 rounded-2xl border border-line bg-surface-muted px-4 py-3"
        data-testid="analyze-context"
      >
        <span className="text-sm font-medium text-ink">File this analysis under</span>
        <SiteSelect
          sites={sites.data ?? []}
          value={siteId}
          onChange={(id) => {
            setSiteId(id);
            setDeploymentId('');
          }}
          allLabel="No site (organization only)"
        />
        {siteDeployments.length ? (
          <label className="flex items-center gap-2 text-xs text-muted">
            Deployment
            <Select
              className="h-8 w-auto py-1"
              value={deploymentId}
              onChange={(e) => setDeploymentId(e.target.value)}
            >
              <option value="">None</option>
              {siteDeployments.map((d) => (
                <option key={d.id} value={d.id}>
                  {(recorders.data ?? []).find((r) => r.id === d.recorder_id)?.label ??
                    d.recorder_id}
                </option>
              ))}
            </Select>
          </label>
        ) : null}
        <a className="link text-xs" href={orgHref(org.id, 'upload', null, { site_id: siteId })}>
          Many files? Use batch upload
        </a>
      </div>
      {!sites.data?.length && sites.data ? (
        <Callout tone="info">
          No sites yet. You can still analyze a file; add a site later to see it on the dashboard.
        </Callout>
      ) : null}
      <WorkspacePage workspace={workspace} />
    </div>
  );
}
