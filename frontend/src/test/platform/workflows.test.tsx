import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import {
  groupFields,
  buildReportCreate,
  collectFieldValues,
  fieldError,
} from '../../lib/reportFields';
import { installFakeBackend } from '../fakeBackend';
import { ORG, REPORT_TEMPLATES, SITE_NORTH } from '../fixtures/platform';
import { renderApp } from '../utils';

function chooseBatch(files: File[]) {
  const input = screen.getByTestId<HTMLInputElement>('batch-input');
  Object.defineProperty(input, 'files', { value: files, configurable: true });
  fireEvent.change(input);
}

function file(name: string, lastModified = 1715664600000): File {
  return new File(['RIFF0000WAVEfmt '], name, { type: 'audio/wav', lastModified });
}

describe('batch upload', () => {
  it('previews timestamps parsed from file names before uploading', async () => {
    window.location.hash = `#/orgs/${ORG.id}/upload`;
    installFakeBackend({ platform: {} });
    renderApp();
    await screen.findByRole('heading', { level: 1, name: 'Upload recordings' });
    chooseBatch([
      file('20240514_053000.WAV'),
      file('SMA12345_20240514_053000.wav'),
      file('New Recording 7.m4a'),
      file('CONFIG.TXT'),
      file('card.zip'),
      file('notes.pdf'),
    ]);
    const rows = await screen.findAllByTestId('batch-row');
    expect(rows).toHaveLength(6);
    expect(within(rows[0]!).getByTestId('timestamp-preview')).toHaveTextContent(
      '2024-05-14 05:30 UTC',
    );
    expect(within(rows[1]!).getByTestId('timestamp-preview')).toHaveTextContent(
      '2024-05-14 05:30 local',
    );
    expect(within(rows[2]!).getByTestId('timestamp-preview')).toHaveTextContent('Not in the name');
    expect(within(rows[3]!).getByText('Recorder log')).toBeInTheDocument();
    expect(within(rows[4]!).getByText('Archive')).toBeInTheDocument();
    expect(within(rows[5]!).getByText('Unsupported')).toBeInTheDocument();
    expect(screen.getByTestId('batch-summary')).toHaveTextContent('2 of 3 names carry a timestamp');
  });

  it('requires a site, then uploads with last_modified per file and polls the job to the end', async () => {
    window.location.hash = `#/orgs/${ORG.id}/upload`;
    const backend = installFakeBackend({ platform: { pollsBeforeComplete: 1 } });
    const { user } = renderApp();
    await screen.findByRole('heading', { level: 1, name: 'Upload recordings' });
    chooseBatch([file('20240514_053000.WAV', 111), file('20240514_060000.WAV', 222)]);
    await screen.findAllByTestId('batch-row');
    await screen.findByRole('radio', { name: /Birds and more/ });
    await user.click(screen.getByTestId('start-batch'));
    expect(screen.getByTestId('batch-form-error')).toHaveTextContent('Choose the site');

    await user.selectOptions(screen.getByLabelText(/^Site/), SITE_NORTH);
    await user.click(screen.getByTestId('start-batch'));

    expect(await screen.findByText(/Batch batch_1/, {}, { timeout: 6000 })).toBeInTheDocument();
    await waitFor(
      () => expect(screen.getByTestId('batch-progress')).toHaveTextContent('2 of 2 files finished'),
      {
        timeout: 8000,
      },
    );
    const post = backend.requests.find((r) => r.method === 'POST' && r.url.endsWith('/uploads'));
    expect(post?.body).toMatchObject({
      files: ['file:20240514_053000.WAV', 'file:20240514_060000.WAV'],
      last_modified: ['111', '222'],
      site_id: SITE_NORTH,
      timezone: 'America/New_York',
      models: '["birdnet"]',
      threshold: '0.60',
    });
    expect(post?.headers['x-requested-with']).toBe('thicket');
    expect(screen.getAllByRole('link', { name: 'Open recording' }).length).toBe(2);
  });
});

describe('batch upload polling', () => {
  it('rides out failed polls instead of failing the batch, and never uploads twice', async () => {
    window.location.hash = `#/orgs/${ORG.id}/upload`;
    const backend = installFakeBackend({
      platform: { pollsBeforeComplete: 1, failingJobPolls: 2 },
    });
    const { user } = renderApp();
    await screen.findByRole('heading', { level: 1, name: 'Upload recordings' });
    chooseBatch([file('20240514_053000.WAV', 111)]);
    await screen.findAllByTestId('batch-row');
    await screen.findByRole('radio', { name: /Birds and more/ });
    await user.selectOptions(screen.getByLabelText(/^Site/), SITE_NORTH);
    await user.click(screen.getByTestId('start-batch'));
    await waitFor(
      () => expect(screen.getByTestId('batch-progress')).toHaveTextContent('1 of 1 files finished'),
      { timeout: 15000 },
    );
    const posts = backend.requests.filter(
      (r) => r.method === 'POST' && r.url.endsWith('/uploads'),
    );
    expect(posts).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /Try again|Retry/ })).toBeNull();
  }, 20000);
});

describe('alerts', () => {
  it('clears the unread badge when the inbox is opened', async () => {
    window.location.hash = `#/orgs/${ORG.id}`;
    const backend = installFakeBackend({ platform: {} });
    const { user } = renderApp();
    expect(await screen.findByTestId('unread-badge')).toHaveTextContent('2');
    await user.click(screen.getByTestId('notification-bell'));
    await screen.findByTestId('alerts-ecology');
    await waitFor(() => expect(screen.queryByTestId('unread-badge')).toBeNull());
    const read = backend.requests.find((r) => r.url.endsWith('/me/notifications/read'));
    // Only this organization's notifications: another farm's stay unread.
    expect(read?.body).toEqual({ all: true, organization_id: ORG.id });
    const unread = backend.requests.find((r) => r.url.includes('/me/notifications?'));
    expect(unread?.url).toContain(`organization_id=${ORG.id}`);
    expect(read?.headers['x-requested-with']).toBe('thicket');
  });

  it('groups alerts by category and acknowledges one with a PATCH', async () => {
    window.location.hash = `#/orgs/${ORG.id}/alerts`;
    const backend = installFakeBackend({ platform: {} });
    const { user } = renderApp();
    const ecology = await screen.findByTestId('alerts-ecology');
    expect(within(ecology).getAllByTestId('alert-row')).toHaveLength(2);
    expect(screen.getByTestId('alerts-quality')).toBeInTheDocument();
    expect(screen.getByTestId('alerts-recorder')).toBeInTheDocument();

    const row = within(ecology).getAllByTestId('alert-row')[0]!;
    await user.click(within(row).getByRole('button', { expanded: false }));
    const evidence = within(row).getByTestId('evidence-table');
    expect(within(evidence).getByText('Baseline (median)')).toBeInTheDocument();
    expect(within(evidence).getByText('13')).toBeInTheDocument();
    expect(within(row).getByText(/Suggested next step/)).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: 'North pasture' })).toBeInTheDocument();

    await user.click(within(row).getByRole('button', { name: 'Acknowledge' }));
    await waitFor(() => expect(within(row).getByText('Acknowledged')).toBeInTheDocument());
    const patch = backend.requests.find(
      (r) => r.method === 'PATCH' && r.url.includes('/alerts/al_richness_north'),
    );
    expect(patch?.body).toEqual({ status: 'acknowledged', note: null });
    expect(patch?.headers['x-requested-with']).toBe('thicket');
  });

  it('snoozes and resolves alerts', async () => {
    window.location.hash = `#/orgs/${ORG.id}/alerts`;
    const backend = installFakeBackend({ platform: {} });
    const { user } = renderApp();
    const quality = await screen.findByTestId('alerts-quality');
    const row = within(quality).getByTestId('alert-row');
    await user.selectOptions(within(row).getByLabelText('Snooze for'), '3');
    await user.click(within(row).getByRole('button', { name: 'Snooze' }));
    await waitFor(() => expect(within(row).getByText('Snoozed')).toBeInTheDocument());
    const snooze = backend.requests.find((r) => r.method === 'PATCH');
    const body = snooze?.body as { status: string; snoozed_until: string };
    expect(body.status).toBe('snoozed');
    expect(new Date(body.snoozed_until).getTime()).toBeGreaterThan(Date.now() + 2 * 86_400_000);

    const recorder = screen.getByTestId('alerts-recorder');
    await user.click(within(recorder).getAllByRole('button', { name: 'Resolve' })[0]!);
    await waitFor(() => expect(within(recorder).getByText('Resolved')).toBeInTheDocument());
  });

  it('shows a readable message when the server refuses an action', async () => {
    window.location.hash = `#/orgs/${ORG.id}/alerts`;
    installFakeBackend({ platform: { forbidWrites: true } });
    const { user } = renderApp();
    const ecology = await screen.findByTestId('alerts-ecology');
    await user.click(within(ecology).getAllByRole('button', { name: 'Resolve' })[0]!);
    expect(await screen.findByText('Your role does not allow this')).toBeInTheDocument();
  });
});

describe('role gating', () => {
  it('hides edit controls from viewers', async () => {
    window.location.hash = `#/orgs/${ORG.id}/alerts`;
    installFakeBackend({ platform: { role: 'viewer' } });
    renderApp();
    await screen.findByTestId('alerts-ecology');
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Resolve' })).toBeNull();
    expect(screen.getByTestId('read-only-note')).toBeInTheDocument();

    window.location.hash = `#/orgs/${ORG.id}/sites`;
    expect(await screen.findByTestId('site-list')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Add site/ })).toBeNull();

    window.location.hash = `#/orgs/${ORG.id}/upload`;
    expect(await screen.findByText('Uploads need the manager role')).toBeInTheDocument();
    expect(screen.queryByTestId('batch-input')).toBeNull();

    window.location.hash = `#/orgs/${ORG.id}/settings`;
    expect(await screen.findByTestId('members-table')).toBeInTheDocument();
    expect(screen.queryByTestId('invite-form')).toBeNull();
    expect(screen.queryByRole('combobox', { name: /Role for/ })).toBeNull();
    await screen.findByTestId('alert-rules-form');
    expect(screen.queryByTestId('save-rules')).toBeNull();
    expect(screen.getByTestId('priority-species')).toBeDisabled();
  });

  it('lets owners change roles and managers invite', async () => {
    window.location.hash = `#/orgs/${ORG.id}/settings`;
    const backend = installFakeBackend({ platform: { role: 'owner' } });
    const { user } = renderApp();
    const table = await screen.findByTestId('members-table');
    await user.selectOptions(
      within(table).getByRole('combobox', { name: 'Role for Lee Park' }),
      'reviewer',
    );
    await waitFor(() =>
      expect(
        backend.requests.some((r) => r.method === 'PATCH' && r.url.endsWith('/members/usr_lee')),
      ).toBe(true),
    );
    const form = screen.getByTestId('invite-form');
    await user.type(within(form).getByLabelText(/Invite by email/), 'planner2@example.org');
    await user.click(within(form).getByRole('button', { name: 'Send invitation' }));
    expect(
      await screen.findByText(/Invitation created for planner2@example.org/),
    ).toBeInTheDocument();
    expect(screen.getByText(/#\/invite\/tok_new_1/)).toBeInTheDocument();
  });

  it('revokes a pending invitation with a DELETE and drops it from the list', async () => {
    window.location.hash = `#/orgs/${ORG.id}/settings`;
    const backend = installFakeBackend({ platform: { role: 'manager' } });
    const { user } = renderApp();
    const list = await screen.findByTestId('invite-list');
    expect(within(list).getByText('planner@example.org')).toBeInTheDocument();
    expect(within(list).queryByRole('button', { name: /Copy link/ })).toBeNull();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    try {
      await user.click(
        within(list).getByRole('button', { name: 'Revoke the invitation for planner@example.org' }),
      );
    } finally {
      confirm.mockRestore();
    }
    await waitFor(() => expect(screen.queryByText('planner@example.org')).toBeNull());
    const del = backend.requests.find((r) => r.method === 'DELETE');
    expect(del?.url).toMatch(/\/orgs\/[^/]+\/invites\/inv_7a2b$/);
    expect(del?.headers['x-requested-with']).toBe('thicket');
  });

  it('validates priority species names before saving the alert rules', async () => {
    window.location.hash = `#/orgs/${ORG.id}/settings`;
    const backend = installFakeBackend({ platform: { role: 'manager' } });
    const { user } = renderApp();
    const field = await screen.findByTestId('priority-species');
    await user.clear(field);
    await user.type(field, 'dolichonyx oryzivorus{enter}Bobolink');
    expect(screen.getByText(/Not in Genus species form: Bobolink/)).toBeInTheDocument();
    await user.click(screen.getByTestId('save-rules'));
    await waitFor(() =>
      expect(
        backend.requests.some((r) => r.method === 'PUT' && r.url.endsWith('/alert-rules')),
      ).toBe(true),
    );
    const put = backend.requests.find((r) => r.method === 'PUT' && r.url.endsWith('/alert-rules'));
    expect((put?.body as { priority_species: string[] }).priority_species).toEqual([
      'Dolichonyx oryzivorus',
    ]);
  });
});

describe('report wizard', () => {
  it('groups template fields in order and marks required ones', () => {
    const nrcs = REPORT_TEMPLATES.templates.find((t) => t.key === 'nrcs')!;
    const groups = groupFields(nrcs);
    expect(groups.map((g) => g.group)).toEqual([
      'identity',
      'location',
      'deployment',
      'nrcs',
      'statements',
    ]);
    expect(groups[0]!.label).toBe('Who and what');
    expect(groups.flatMap((g) => g.fields).every((f) => f.templates.includes('nrcs'))).toBe(true);
    const participant = nrcs.fields.find((f) => f.name === 'participant_name')!;
    expect(fieldError(participant, '')).toBe('Required for this template.');
    const fiscal = nrcs.fields.find((f) => f.name === 'fiscal_year')!;
    expect(fieldError(fiscal, '2027.5')).toBe('Enter a whole number.');
  });

  it('coerces values by field type and leaves blanks out', () => {
    const nrcs = REPORT_TEMPLATES.templates.find((t) => t.key === 'nrcs')!;
    const values = collectFieldValues(nrcs.fields, {
      fiscal_year: '2027',
      fsa_field_numbers: '3\n4',
      participant_name: '  Jane Farmer ',
      caveats_acknowledged: true,
      county: '',
    });
    expect(values).toEqual({
      fiscal_year: 2027,
      fsa_field_numbers: ['3', '4'],
      participant_name: 'Jane Farmer',
      caveats_acknowledged: true,
    });
    const body = buildReportCreate(
      {
        template: 'nrcs',
        title: 'CSP annex',
        periodStart: '2026-05-01',
        periodEnd: '2026-07-31',
        siteIds: [SITE_NORTH],
        baselineStart: '',
        baselineEnd: '',
        threshold: 0.7,
        includeReviewLog: true,
        includeRawManifest: false,
      },
      nrcs,
      {},
    );
    expect(body).toMatchObject({
      template: 'nrcs',
      baseline_start: null,
      decision_threshold: 0.7,
      site_ids: [SITE_NORTH],
      fields: {},
    });
  });

  it('builds a form from the chosen template, submits, polls and links the downloads', async () => {
    window.location.hash = `#/orgs/${ORG.id}/reports/new`;
    const backend = installFakeBackend({ platform: { pollsBeforeComplete: 1 } });
    const { user } = renderApp();
    const cards = await screen.findByTestId('template-cards');
    expect(within(cards).getAllByRole('button')).toHaveLength(5);
    await user.click(within(cards).getByTestId('template-aem'));
    await user.click(screen.getByTestId('to-fields'));

    const aemGroup = await screen.findByTestId('group-aem');
    expect(within(aemGroup).getByLabelText(/AEM ID/)).toBeInTheDocument();
    expect(within(aemGroup).getByLabelText(/AEM tier/)).toHaveRole('combobox');
    expect(screen.queryByTestId('field-participant_name')).toBeNull();
    expect(screen.getByRole('heading', { name: 'AEM evaluation' })).toBeInTheDocument();

    await user.type(screen.getByTestId('field-aem_id'), 'T-0456');
    await user.selectOptions(screen.getByTestId('field-aem_tier'), '5B');
    await user.click(screen.getByTestId('build-report'));
    expect(await screen.findByText('Some required details are missing')).toBeInTheDocument();
    expect(backend.requests.some((r) => r.method === 'POST' && r.url.endsWith('/reports'))).toBe(
      false,
    );
    await user.click(screen.getByRole('button', { name: 'Build with blanks' }));

    const pdf = await screen.findByTestId('download-pdf', {}, { timeout: 8000 });
    expect(pdf).toHaveAttribute('href', '/api/v1/reports/rp_new_1.pdf');
    expect(screen.getByTestId('download-json')).toHaveAttribute(
      'href',
      '/api/v1/reports/rp_new_1.json',
    );
    expect(screen.getByText('Left blank')).toBeInTheDocument();
    // checksum_sha256 is the PDF's hash; the footer's "bundle sha256" is a different file.
    expect(screen.getByText(/PDF sha256 [0-9a-f]{12}/)).toBeInTheDocument();
    expect(screen.queryByText(/bundle [0-9a-f]{12}/)).toBeNull();
    const post = backend.requests.find((r) => r.method === 'POST' && r.url.endsWith('/reports'));
    expect(post?.body).toMatchObject({
      template: 'aem',
      fields: { aem_id: 'T-0456', aem_tier: '5B' },
    });
  });
});
