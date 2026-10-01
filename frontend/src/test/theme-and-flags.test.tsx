import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ModelSelector } from '../components/intake/ModelSelector';
import type { ModelsState } from '../hooks/useModels';
import { installFakeBackend } from './fakeBackend';
import { MODELS } from './fixtures/analysis';
import { media } from './setup';
import { renderApp } from './utils';

describe('theme', () => {
  it('follows the system preference on first visit', () => {
    media.dark = true;
    installFakeBackend();
    renderApp();
    expect(document.documentElement).toHaveClass('dark');
    expect(screen.getByRole('button', { name: 'Switch to light theme' })).toBeInTheDocument();
    expect(window.localStorage.getItem('thicket-theme')).toBeNull();
  });

  it('persists the toggled theme to localStorage', async () => {
    installFakeBackend();
    const { user, unmount } = renderApp();
    expect(document.documentElement).not.toHaveClass('dark');

    await user.click(screen.getByRole('button', { name: 'Switch to dark theme' }));
    expect(document.documentElement).toHaveClass('dark');
    expect(window.localStorage.getItem('thicket-theme')).toBe('dark');
    unmount();

    // A stored choice wins over the system preference.
    media.dark = false;
    renderApp();
    expect(document.documentElement).toHaveClass('dark');
  });

  it('keeps working when storage is unavailable', async () => {
    installFakeBackend();
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceeded');
    });
    const { user } = renderApp();
    await user.click(screen.getByRole('button', { name: 'Switch to dark theme' }));
    expect(document.documentElement).toHaveClass('dark');
    getItem.mockRestore();
    setItem.mockRestore();
  });
});

function modelsState(overrides: Partial<ModelsState> = {}): ModelsState {
  return {
    status: 'ready',
    models: MODELS.models,
    error: null,
    reload: () => undefined,
    ...overrides,
  };
}

describe('model selector', () => {
  it('hides experimental models unless the flag is on', () => {
    render(
      <ModelSelector
        modelsState={modelsState()}
        selection="birdnet"
        onSelect={() => undefined}
        experimentalEnabled={false}
      />,
    );
    const group = screen.getByRole('radiogroup', { name: 'Model' });
    expect(within(group).getAllByRole('radio')).toHaveLength(1);
    expect(screen.getByRole('radio', { name: /Birds and more/ })).toBeChecked();
    expect(screen.getByText('BirdNET v2.4')).toBeInTheDocument();
    expect(screen.queryByText('Perch 2.0')).toBeNull();
    expect(screen.queryByText('Experimental')).toBeNull();
    expect(screen.queryByText('Combined')).toBeNull();
  });

  it('shows experimental models with a badge, explanation, disabled reason and Combined when enabled', async () => {
    const onSelect = vi.fn();
    render(
      <ModelSelector
        modelsState={modelsState()}
        selection="birdnet"
        onSelect={onSelect}
        experimentalEnabled
      />,
    );
    expect(screen.getAllByText('Experimental').length).toBe(3); // frogs/insects, Perch, Combined
    const disabled = screen.getByRole('radio', { name: /Frogs and insects/ });
    expect(disabled).toBeDisabled();
    expect(screen.getByTestId('model-status-frogs_insects')).toHaveTextContent(
      'Disabled until it passes the validation benchmark.',
    );
    const info = screen.getByRole('button', { name: 'About experimental model Perch 2.0' });
    await userEvent.setup().hover(info);
    expect(
      screen
        .getAllByRole('tooltip', { hidden: true })
        .some((t) => /validation benchmark/.test(t.textContent ?? '')),
    ).toBe(true);
    await userEvent.setup().click(screen.getByRole('radio', { name: /Combined/ }));
    expect(onSelect).toHaveBeenCalledWith('combined');
  });

  it('never shows an em dash from server model names', () => {
    render(
      <ModelSelector
        modelsState={modelsState()}
        selection="birdnet"
        onSelect={() => undefined}
        experimentalEnabled
      />,
    );
    expect(document.body.textContent).not.toMatch(/—/);
  });

  it('respects VITE_ENABLE_EXPERIMENTAL_MODELS in the app', async () => {
    vi.stubEnv('VITE_ENABLE_EXPERIMENTAL_MODELS', 'true');
    installFakeBackend();
    renderApp();
    expect(await screen.findByRole('radio', { name: /Perch 2.0/ })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Combined/ })).toBeInTheDocument();
  });

  it('hides experimental models when the build sets the flag to false', async () => {
    installFakeBackend();
    renderApp();
    await screen.findByRole('radio', { name: /Birds and more/ });
    expect(screen.queryByRole('radio', { name: /Perch/ })).toBeNull();
  });

  it('shows experimental models, badged, when the flag is unset, and defaults to Combined', async () => {
    vi.stubEnv('VITE_ENABLE_EXPERIMENTAL_MODELS', '');
    installFakeBackend();
    renderApp();
    expect(await screen.findByRole('radio', { name: /Perch 2.0/ })).toBeInTheDocument();
    expect(screen.getAllByText('Experimental').length).toBeGreaterThan(0);
    expect(screen.getByRole('radio', { name: /Combined/ })).toBeChecked();
  });

  it('explains when the model list cannot be loaded', async () => {
    installFakeBackend({ modelsError: true });
    renderApp();
    expect(await screen.findByText('The Thicket server is unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});

describe('model loading', () => {
  it('refreshes the list while a model is still loading on the server', async () => {
    const loading = {
      models: [{ ...MODELS.models[0]!, status: 'loading' as const }],
    };
    const backend = installFakeBackend({ models: loading });
    renderApp();
    expect(
      await screen.findByText('Loading on the server. Try again in a moment.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Birds and more/ })).toBeDisabled();
    backend.options.models = MODELS;
    expect(
      await screen.findByRole(
        'radio',
        { name: /Birds and more/, checked: true },
        { timeout: 5000 },
      ),
    ).toBeEnabled();
  });
});
