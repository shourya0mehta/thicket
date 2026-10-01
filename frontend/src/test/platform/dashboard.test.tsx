import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ActivityHeatmap } from '../../components/charts/Heatmap';
import { RankedBars } from '../../components/charts/RankedBars';
import { StackedBar } from '../../components/charts/StackedBar';
import { TimeSeriesChart } from '../../components/charts/TimeSeriesChart';
import { buildDaySeries, bucketize } from '../../lib/dashboard';
import { installFakeBackend } from '../fakeBackend';
import { ORG, SITE_NORTH, buildDashboard, dayPoints, heatCells } from '../fixtures/platform';
import { renderApp } from '../utils';

describe('dashboard', () => {
  it('renders the KPI tiles, charts and the baseline note from the fixture', async () => {
    window.location.hash = `#/orgs/${ORG.id}?period=30`;
    const backend = installFakeBackend({ platform: {} });
    renderApp();
    const dashboard = await screen.findByTestId('dashboard');
    const expected = buildDashboard({ from: '2026-01-01', to: '2026-01-30' });
    expect(
      within(screen.getByTestId('kpi-recordings')).getByRole('definition'),
    ).not.toHaveTextContent('n/a');
    expect(screen.getByTestId('kpi-species')).toHaveTextContent(String(expected.species_counted));
    expect(screen.getByTestId('kpi-alerts')).toHaveTextContent('4');
    expect(within(dashboard).getByText(/Baselines compare each recording/)).toBeInTheDocument();

    // Every chart ships an accessible name and a table twin.
    const richness = screen.getByTestId('richness-chart');
    expect(
      within(richness).getByRole('img', { name: /Species richness by day/ }),
    ).toBeInTheDocument();
    expect(
      within(richness).getByRole('table', { name: /Species richness, baseline band/ }),
    ).toBeInTheDocument();
    expect(within(screen.getByTestId('heatmap-chart')).getByRole('table')).toBeInTheDocument();
    expect(
      within(screen.getByTestId('species-chart')).getByRole('img', {
        name: /^Species ranked by presence/,
      }),
    ).toBeInTheDocument();
    expect(
      within(
        within(screen.getByTestId('taxon-chart')).getByRole('list', { name: 'Legend' }),
      ).getByText('Amphibian'),
    ).toBeInTheDocument();
    expect(
      within(
        within(screen.getByTestId('quality-chart')).getByRole('list', { name: 'Legend' }),
      ).getByText('Usable with warnings'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('recent-alerts')).toHaveTextContent('Dawn species richness fell');
    expect(screen.getByTestId('period-summary')).toHaveTextContent('30 days');
    // The dashboard request carried the period.
    const url = backend.urls('GET').find((u) => u.includes('/dashboard'))!;
    expect(url).toMatch(/from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}/);
    // Never the banned words.
    expect(document.body.textContent).not.toMatch(/\bindividuals\b|\bpopulation\b|\babundance\b/i);
  });

  it('changes the period and site through the hash query', async () => {
    window.location.hash = `#/orgs/${ORG.id}`;
    const backend = installFakeBackend({ platform: {} });
    const { user } = renderApp();
    await screen.findByTestId('dashboard');
    await user.click(screen.getByRole('button', { name: '1 year' }));
    expect(window.location.hash).toContain('period=365');
    expect(await screen.findByText(/365 days/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Site'), SITE_NORTH);
    expect(window.location.hash).toContain(`site_id=${SITE_NORTH}`);
    expect(
      await screen.findByRole('heading', { level: 1, name: 'North pasture' }),
    ).toBeInTheDocument();
    expect(backend.urls('GET').some((u) => u.includes(`site_id=${SITE_NORTH}`))).toBe(true);
  });

  it('shows the empty state for an organization without recordings', async () => {
    window.location.hash = `#/orgs/${ORG.id}`;
    installFakeBackend({ platform: { empty: true } });
    renderApp();
    expect(await screen.findByTestId('dashboard-empty')).toBeInTheDocument();
  });
});

describe('dashboard series helpers', () => {
  it('fills missing days and computes a rolling median band', () => {
    const points = dayPoints('2026-05-01', '2026-05-31');
    const series = buildDaySeries(points, '2026-05-01', '2026-05-31');
    expect(series.dates).toHaveLength(31);
    expect(series.dates[0]).toBe('2026-05-01');
    expect(series.richness.filter((v) => v === null).length).toBeGreaterThan(0);
    const bands = series.baseline.filter((b) => b.center !== null);
    expect(bands.length).toBeGreaterThan(10);
    for (const b of bands) expect(b.low!).toBeLessThanOrEqual(b.high!);
  });

  it('buckets a long series for sparklines', () => {
    const values = Array.from({ length: 90 }, (_, i) => i);
    const buckets = bucketize(values, 12);
    expect(buckets).toHaveLength(12);
    expect(buckets[0]).toBe(0 + 1 + 2 + 3 + 4 + 5 + 6);
  });
});

describe('chart components', () => {
  it('time series chart has y axis labels, x axis dates, a legend-free single series and a data table', () => {
    const points = dayPoints('2026-06-01', '2026-06-30').map((p) => ({
      x: p.date,
      y: p.species_richness,
    }));
    render(
      <TimeSeriesChart
        points={points}
        bars={points.map(() => 3)}
        yLabel="Species richness"
        title="Richness test"
        description="Test series"
        caption="Richness by day"
      />,
    );
    const svg = screen.getByRole('img', { name: /Richness test/ });
    expect(svg).toHaveAttribute('tabindex', '0');
    expect(within(svg).getByText('Jun 1')).toBeInTheDocument();
    expect(within(svg).getAllByText(/^\d+$/).length).toBeGreaterThan(2);
    const table = screen.getByRole('table', { name: 'Richness by day' });
    expect(within(table).getAllByRole('row')).toHaveLength(points.length + 1);
    expect(
      within(table).getByRole('columnheader', { name: 'Species richness' }),
    ).toBeInTheDocument();
  });

  it('heatmap labels hours and weekdays and lists cells in its table', () => {
    render(<ActivityHeatmap cells={heatCells()} title="Heat test" caption="Heat table" />);
    const svg = screen.getByRole('img', { name: /^Heat test/ });
    expect(within(svg).getByText('Mon')).toBeInTheDocument();
    expect(within(svg).getByText('12p')).toBeInTheDocument();
    expect(screen.getByText(/No recordings/)).toBeInTheDocument();
    expect(
      within(screen.getByRole('table', { name: 'Heat table' })).getAllByRole('row').length,
    ).toBeGreaterThan(20);
  });

  it('stacked bar has a legend entry per segment and labels only segments that fit', () => {
    render(
      <StackedBar
        segments={[
          { key: 'a', label: 'Bird', value: 900, color: 'red' },
          { key: 'b', label: 'Insect', value: 5, color: 'blue' },
        ]}
        title="Stack"
        description="Stack description"
        caption="Stack table"
        valueLabel="Events"
      />,
    );
    const legend = screen.getByRole('list', { name: 'Legend' });
    expect(within(legend).getAllByRole('listitem')).toHaveLength(2);
    expect(within(screen.getByRole('img', { name: /^Stack/ })).getAllByText(/%/)).toHaveLength(1);
  });

  it('ranked bars pair taxon icons with labels and flag priority species', () => {
    render(
      <RankedBars
        rows={[
          {
            key: 'a',
            label: 'Bobolink',
            taxon: 'bird',
            value: 0.4,
            valueText: '40%',
            flagged: true,
          },
          { key: 'b', label: 'Spring Peeper', taxon: 'amphibian', value: 0.2, valueText: '20%' },
        ]}
        asFraction
        valueLabel="Presence"
        title="Ranked"
        description="Ranked description"
        caption="Ranked table"
      />,
    );
    expect(screen.getByText('Priority species')).toBeInTheDocument();
    const table = screen.getByRole('table', { name: 'Ranked table' });
    expect(within(table).getByText('Amphibian')).toBeInTheDocument();
    expect(within(table).getByText('Priority')).toBeInTheDocument();
  });
});
