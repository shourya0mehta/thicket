import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MAX_FILE_BYTES } from '../config';
import { installFakeBackend } from './fakeBackend';
import { ANALYSIS_ID, buildAnalysis } from './fixtures/analysis';
import { audioFile, chooseFile, fileInput, metricValue, renderApp, runAnalysis } from './utils';

describe('file intake', () => {
  it('opens the one hidden file input from the custom button through the ref', async () => {
    installFakeBackend();
    const { user, container } = renderApp();
    const input = fileInput();
    let opened = 0;
    input.addEventListener('click', () => {
      opened += 1;
    });

    await user.click(screen.getByRole('button', { name: 'Choose file' }));

    expect(opened).toBe(1);
    expect(input).not.toBeVisible();
    expect(container.querySelectorAll('input[type="file"]')).toHaveLength(1);
    // Never a button nested inside a label.
    expect(container.querySelectorAll('label button')).toHaveLength(0);
    expect(input.closest('label')).toBeNull();
  });

  it('rejects unsupported extensions with a readable error', async () => {
    installFakeBackend();
    renderApp();
    chooseFile(audioFile('notes.txt', 1200, 'text/plain'));

    expect(await screen.findByTestId('file-error')).toHaveTextContent(
      '"notes.txt" is not a supported audio file. Choose a .wav, .mp3, .m4a or .flac recording.',
    );
    expect(screen.getByRole('button', { name: 'Run analysis' })).toBeDisabled();
  });

  it('rejects files over 20 MB', async () => {
    installFakeBackend();
    renderApp();
    chooseFile(audioFile('long-night.flac', MAX_FILE_BYTES + 1024 * 1024));

    expect(await screen.findByTestId('file-error')).toHaveTextContent(
      '"long-night.flac" is 21 MB. The limit is 20 MB',
    );
  });

  it('shows name, size and the decoded duration after generating a spectrogram', async () => {
    const backend = installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await user.click(screen.getByRole('button', { name: 'Generate spectrogram' }));

    expect(await screen.findByTestId('decoded-duration')).toHaveTextContent('1 min 00 s');
    expect(screen.getByTestId('file-facts')).toHaveTextContent('hollow-creek-dawn.wav');
    expect(backend.urls('POST')).toEqual(['/api/v1/previews']);
    expect(
      await screen.findByRole('img', { name: /Spectrogram of hollow-creek-dawn.wav/ }),
    ).toBeInTheDocument();
  });

  it('clears spectrogram, results, errors and metadata when a new file is selected', async () => {
    installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await user.type(screen.getByLabelText('Site name'), 'North meadow');
    await runAnalysis(user);
    expect(
      screen.getByRole('heading', { name: 'Species with detection events' }),
    ).toBeInTheDocument();

    // A new recording from the compact setup bar resets everything.
    chooseFile(audioFile('second-visit.mp3', 2048, 'audio/mpeg'));

    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: 'Species with detection events' })).toBeNull(),
    );
    expect(screen.queryByRole('img', { name: /Spectrogram of/ })).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByTestId('file-facts')).toHaveTextContent('second-visit.mp3');
    expect(screen.getByLabelText('Site name')).toHaveValue('');
  });

  it('keeps metadata for the next file when "Keep" is ticked', async () => {
    installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await user.type(screen.getByLabelText('Site name'), 'Plot 3');
    await user.click(screen.getByLabelText('Keep these details for the next file'));
    chooseFile(audioFile('second.wav'));
    expect(screen.getByLabelText('Site name')).toHaveValue('Plot 3');
  });

  it('validates coordinates before running', async () => {
    const backend = installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await user.type(screen.getByLabelText('Latitude'), '123');
    await screen.findByRole('radio', { name: /Birds and more/ });
    await user.click(screen.getByRole('button', { name: 'Run analysis' }));

    expect(screen.getByText('Latitude must be a number between -90 and 90.')).toBeInTheDocument();
    expect(screen.getByLabelText('Latitude')).toHaveAttribute('aria-invalid', 'true');
    expect(backend.urls('POST')).toEqual([]);
  });
});

describe('analysis run', () => {
  it('uploads, polls until complete and sends the analysis parameters', async () => {
    const backend = installFakeBackend({ pollsBeforeComplete: 1 });
    const { user } = renderApp();
    chooseFile(audioFile());
    await user.type(screen.getByLabelText('Latitude'), '42.4531');
    await user.type(screen.getByLabelText('Longitude'), '-76.4735');
    await user.clear(screen.getByLabelText('Time zone'));
    await user.type(screen.getByLabelText('Time zone'), 'America/New_York');
    fireEvent.change(screen.getByLabelText('Recording date and time'), {
      target: { value: '2026-05-14T05:42' },
    });
    await runAnalysis(user);

    const post = backend.requests.find((r) => r.method === 'POST' && r.url.endsWith('/analyses'));
    expect(post?.body).toMatchObject({
      file: 'file:hollow-creek-dawn.wav',
      models: '["birdnet"]',
      threshold: '0.60',
      latitude: '42.4531',
      longitude: '-76.4735',
      captured_at: '2026-05-14T05:42:00-04:00',
      timezone: 'America/New_York',
    });
    expect(backend.urls('GET').filter((u) => u.includes(`/analyses/${ANALYSIS_ID}`)).length).toBe(
      2,
    );
  });

  it('reuses the preview upload instead of sending the file twice', async () => {
    const backend = installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await user.click(screen.getByRole('button', { name: 'Generate spectrogram' }));
    await screen.findByTestId('decoded-duration');
    await runAnalysis(user);
    const post = backend.requests.find((r) => r.method === 'POST' && r.url.endsWith('/analyses'));
    expect(post?.body).toMatchObject({ preview_id: 'pv_51b0e8c2' });
    expect(post?.body).not.toHaveProperty('file');
  });

  it('falls back to uploading the file when the preview expired on the server', async () => {
    const backend = installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await user.click(screen.getByRole('button', { name: 'Generate spectrogram' }));
    await screen.findByTestId('decoded-duration');
    backend.options.createErrors = [
      { status: 404, body: { error_code: 'not_found', message: 'Preview expired' } },
    ];
    await runAnalysis(user);
    const posts = backend.requests.filter(
      (r) => r.method === 'POST' && r.url.endsWith('/analyses'),
    );
    expect(posts).toHaveLength(2);
    expect(posts[0]?.body).toMatchObject({ preview_id: 'pv_51b0e8c2' });
    expect(posts[1]?.body).toMatchObject({ file: 'file:hollow-creek-dawn.wav' });
  });

  it('shows a friendly error with retry when the backend fails, then succeeds', async () => {
    installFakeBackend({
      createErrors: [
        { status: 500, body: { error_code: 'internal_error', message: 'Worker crashed' } },
      ],
    });
    const { user } = renderApp();
    chooseFile(audioFile());
    await screen.findByRole('radio', { name: /Birds and more/ });
    await user.click(screen.getByRole('button', { name: 'Run analysis' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Something went wrong on the server');
    expect(alert).toHaveTextContent('Server message: Worker crashed');
    await user.click(within(alert).getByRole('button', { name: 'Try again' }));
    await screen.findByRole(
      'heading',
      { name: 'Species with detection events' },
      { timeout: 5000 },
    );
  });

  it('shows where a server-side failure happened', async () => {
    installFakeBackend({
      failWith: { code: 'audio_decode_failed', message: 'FFmpeg could not read the stream.' },
    });
    const { user } = renderApp();
    chooseFile(audioFile());
    await screen.findByRole('radio', { name: /Birds and more/ });
    await user.click(screen.getByRole('button', { name: 'Run analysis' }));
    const alert = await screen.findByRole('alert', {}, { timeout: 5000 });
    expect(alert).toHaveTextContent('The audio could not be decoded');
    expect(alert).toHaveTextContent('FFmpeg could not read the stream.');
    expect(within(alert).getByRole('button', { name: 'Choose another file' })).toBeInTheDocument();
    expect(screen.getByText('Where the analysis stopped')).toBeInTheDocument();
  });

  it('maps model_unavailable to its own state', async () => {
    installFakeBackend({
      createErrors: [
        { status: 503, body: { error_code: 'model_unavailable', message: 'BirdNET is loading' } },
      ],
    });
    const { user } = renderApp();
    chooseFile(audioFile());
    await screen.findByRole('radio', { name: /Birds and more/ });
    await user.click(screen.getByRole('button', { name: 'Run analysis' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The model is not available right now',
    );
  });
});

describe('results', () => {
  it('refetches with ?threshold= and updates cards, table, chart and exports from the new analysis', async () => {
    const backend = installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await runAnalysis(user);

    const at60 = buildAnalysis({ threshold: 0.6 });
    const at45 = buildAnalysis({ threshold: 0.45 });
    expect(metricValue('metric-richness')).toBe(String(at60.metrics!.species_richness));
    expect(metricValue('metric-events')).toBe(String(at60.metrics!.total_detection_events));
    expect(screen.getAllByTestId('species-row')).toHaveLength(6);
    expect(screen.getAllByTestId('species-chart-row')).toHaveLength(6);
    expect(screen.getByTestId('export-csv')).toHaveAttribute(
      'href',
      `/api/v1/analyses/${ANALYSIS_ID}/export.csv?threshold=0.60`,
    );

    const slider = screen.getByRole('slider', { name: 'Decision threshold' });
    expect(slider).toHaveAttribute('aria-valuetext', '60%');
    fireEvent.change(slider, { target: { value: '0.45' } });
    expect(slider).toHaveAttribute('aria-valuetext', '45%');

    await waitFor(() =>
      expect(backend.urls('GET')).toContain(`/api/v1/analyses/${ANALYSIS_ID}?threshold=0.45`),
    );
    await waitFor(() =>
      expect(metricValue('metric-richness')).toBe(String(at45.metrics!.species_richness)),
    );
    expect(at45.metrics!.species_richness).toBeGreaterThan(at60.metrics!.species_richness);
    expect(metricValue('metric-events')).toBe(String(at45.metrics!.total_detection_events));
    const counted45 = at45.species.filter((s) => s.plausibility !== 'unlikely').length;
    expect(screen.getAllByTestId('species-row')).toHaveLength(counted45);
    expect(screen.getAllByTestId('species-chart-row')).toHaveLength(counted45);
    expect(screen.getByTestId('applied-threshold')).toHaveTextContent('Showing results at 45%');
    expect(screen.getByTestId('export-csv')).toHaveAttribute(
      'href',
      `/api/v1/analyses/${ANALYSIS_ID}/export.csv?threshold=0.45`,
    );
    expect(screen.getByTestId('export-json')).toHaveAttribute(
      'href',
      `/api/v1/analyses/${ANALYSIS_ID}/export.json?threshold=0.45`,
    );
  });

  it('seeks the audio element to the event start when an event is clicked', async () => {
    installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await runAnalysis(user);

    const audio = screen.getByTestId<HTMLAudioElement>('audio-element');
    expect(audio.src).toMatch(/^blob:/);
    const rows = screen.getAllByTestId('event-row');
    const target = rows.find((row) => row.textContent?.includes('Song Sparrow'))!;
    await user.click(within(target).getByRole('button', { name: /Play Song Sparrow from 0:06/ }));

    expect(audio.currentTime).toBe(6);
    expect(target).toHaveAttribute('aria-current', 'true');
  });

  it('seeks from a timeline bar too', async () => {
    installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await runAnalysis(user);
    await user.click(screen.getByRole('tab', { name: 'Timeline' }));
    const bar = screen.getByRole('button', { name: /Northern Cardinal, 0:12 to 0:15/ });
    await user.click(bar);
    const audio = screen.getByTestId<HTMLAudioElement>('audio-element');
    expect(audio.currentTime).toBe(12);
    expect(bar).toHaveAttribute('aria-current', 'true');
  });

  it('shows the Map tab only with real coordinates', async () => {
    installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await runAnalysis(user);
    expect(screen.getByRole('tab', { name: 'Map' })).toBeInTheDocument();
    expect(screen.getByTestId('location-status')).toHaveTextContent('Location on map');
  });

  it('hides the Map tab and says "Location not provided" without coordinates', async () => {
    installFakeBackend({ analysis: { recording: { latitude: null, longitude: null } } });
    const { user } = renderApp();
    chooseFile(audioFile());
    await runAnalysis(user);
    expect(screen.queryByRole('tab', { name: 'Map' })).toBeNull();
    expect(screen.getByTestId('location-status')).toHaveTextContent('Location not provided');
    expect(screen.getAllByText('Location not provided').length).toBeGreaterThan(0);
  });

  it('renders a calm no-detections state as a valid result', async () => {
    installFakeBackend({ analysis: { confidenceScale: 0.5 } });
    const { user } = renderApp();
    chooseFile(audioFile());
    await screen.findByRole('radio', { name: /Birds and more/ });
    await user.click(screen.getByRole('button', { name: 'Run analysis' }));

    const empty = await screen.findByTestId('no-detections', {}, { timeout: 5000 });
    expect(empty).toHaveTextContent('No detection events above 60%');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(metricValue('metric-richness')).toBe('0');
    expect(screen.getByTestId('export-csv')).toBeInTheDocument();
  });

  it('lists other sounds separately and flags unlikely species without counting them', async () => {
    installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await runAnalysis(user);

    expect(screen.getByText(/detected in 2 windows/)).toHaveTextContent(
      'Human vocal detected in 2 windows',
    );
    expect(
      screen.getByText(/Excluded as unlikely for this place and season \(1\)/),
    ).toBeInTheDocument();
    const table = screen.getByTestId('species-table');
    expect(within(table).queryByText('Painted Bunting')).toBeNull();
    expect(within(table).queryByText('Human vocal')).toBeNull();
  });

  it('sends a review and refetches at the current threshold', async () => {
    const backend = installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await runAnalysis(user);
    const before = metricValue('metric-events');
    const row = screen
      .getAllByTestId('event-row')
      .find((r) => r.textContent?.includes('Red-winged Blackbird'))!;
    await user.click(within(row).getByRole('button', { name: 'Reject' }));

    await waitFor(() =>
      expect(backend.reviews).toEqual({ 'evt_agelaius-phoeniceus_18': 'rejected' }),
    );
    await waitFor(() => expect(metricValue('metric-events')).toBe(String(Number(before) - 1)));
    expect(backend.urls('GET')).toContain(`/api/v1/analyses/${ANALYSIS_ID}?threshold=0.60`);
  });

  it('moves between result tabs with arrow keys', async () => {
    installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await runAnalysis(user);
    const results = screen.getByRole('tab', { name: 'Results' });
    act(() => results.focus());
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Timeline' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Timeline' })).toHaveFocus();
    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: 'Methods' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Settings recorded with this analysis')).toBeInTheDocument();
  });
});

describe('history', () => {
  it('stores a summary after an analysis and reloads it from the server', async () => {
    const backend = installFakeBackend();
    const { user } = renderApp();
    chooseFile(audioFile());
    await runAnalysis(user);
    const stored = JSON.parse(window.localStorage.getItem('thicket-history') ?? '[]') as Array<{
      id: string;
      richness: number;
      top_species: string[];
    }>;
    expect(stored[0]).toMatchObject({ id: ANALYSIS_ID, richness: 6 });
    expect(stored[0]!.top_species[0]).toBe('Northern Cardinal');

    await user.click(screen.getByRole('link', { name: 'History' }));
    await user.click(await screen.findByRole('button', { name: /Hollow Creek Easement/ }));
    await screen.findByRole('heading', { name: 'Species with detection events' });
    expect(backend.urls('GET')).toContain(`/api/v1/analyses/${ANALYSIS_ID}`);
  });

  it('removes an entry the server no longer has', async () => {
    window.localStorage.setItem(
      'thicket-history',
      JSON.stringify([
        {
          id: 'an_gone',
          filename: 'old.wav',
          site: 'Old site',
          created_at: '2026-09-01T10:00:00Z',
          richness: 3,
          top_species: ['Song Sparrow'],
        },
      ]),
    );
    installFakeBackend({
      getAnalysisError: {
        status: 404,
        body: { error_code: 'analysis_not_found', message: 'Gone' },
      },
    });
    const { user } = renderApp();
    await user.click(screen.getByRole('link', { name: 'History' }));
    await user.click(await screen.findByRole('button', { name: /Old site/ }));

    expect(await screen.findByText(/no longer on the server/)).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem('thicket-history') ?? '[]')).toEqual([]);
  });
});
