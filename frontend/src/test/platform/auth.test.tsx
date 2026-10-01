import { render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SignInPage } from '../../pages/platform/SignInPage';
import { installFakeBackend } from '../fakeBackend';
import { AUTH_DISABLED, AUTH_GOOGLE, ORG, SECOND_ORG } from '../fixtures/platform';
import { renderApp } from '../utils';

describe('sign-in flows', () => {
  it('shows the dev email form when the session is missing and opens the only organization after sign-in', async () => {
    const backend = installFakeBackend({ platform: { signedIn: false } });
    const { user } = renderApp();

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Email/), 'jane@hollowcreek.example');
    await user.type(screen.getByLabelText(/^Name/), 'Jane Farmer');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument();
    expect(window.location.hash).toBe(`#/orgs/${ORG.id}`);
    const login = backend.requests.find((r) => r.url.endsWith('/auth/dev'));
    expect(login?.body).toEqual({ email: 'jane@hollowcreek.example', name: 'Jane Farmer' });
    expect(window.localStorage.getItem('thicket-last-org')).toBe(ORG.id);
  });

  it('validates the dev email before posting', async () => {
    const backend = installFakeBackend({ platform: { signedIn: false } });
    const { user } = renderApp();
    await screen.findByRole('heading', { name: 'Sign in' });
    await user.type(screen.getByLabelText(/Email/), 'not-an-email');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(screen.getByText(/Enter an email address/)).toBeInTheDocument();
    expect(backend.requests.some((r) => r.url.endsWith('/auth/dev'))).toBe(false);
  });

  it('offers the Google button with the server sign-in URL in google mode', async () => {
    installFakeBackend({ platform: { auth: AUTH_GOOGLE, signedIn: false } });
    renderApp();
    const link = await screen.findByTestId('google-sign-in');
    expect(link).toHaveAttribute('href', expect.stringContaining('/api/v1/auth/google/start'));
    expect(screen.getByText(/hollowcreek.example can sign in/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Email/)).toBeNull();
  });

  it('points the Google button at the API origin when the API lives elsewhere', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.thicket.example.org/');
    try {
      render(
        <SignInPage
          config={AUTH_GOOGLE}
          onDevSignIn={() => Promise.resolve()}
          nextHash="/orgs/org_1/alerts"
        />,
      );
      const href = screen.getByTestId('google-sign-in').getAttribute('href') ?? '';
      expect(href.startsWith('https://api.thicket.example.org/api/v1/auth/google/start')).toBe(
        true,
      );
      expect(href).toContain(`next=${encodeURIComponent('/orgs/org_1/alerts')}`);
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it('skips sign-in entirely when auth is disabled', async () => {
    installFakeBackend({ platform: { auth: AUTH_DISABLED } });
    renderApp();
    expect(await screen.findByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Sign in' })).toBeNull();
    // No sign-out without a real session.
    expect(screen.getByTestId('user-menu')).toBeInTheDocument();
  });

  it('falls back to the standalone workspace when the server has no platform routes', async () => {
    installFakeBackend({ platform: { noPlatform: true } });
    renderApp();
    expect(screen.getByRole('button', { name: 'Choose file' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('link', { name: 'History' })).toBeInTheDocument());
    expect(screen.queryByRole('heading', { name: 'Sign in' })).toBeNull();
  });

  it('asks a new user to create their farm or project and opens it', async () => {
    const backend = installFakeBackend({ platform: { organizations: [] } });
    const { user } = renderApp();
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Create your farm or project' }),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^Name/), 'Hilltop Farm');
    await user.click(screen.getByRole('button', { name: 'Create organization' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.getByTestId('org-name')).toHaveTextContent('Hilltop Farm');
    const post = backend.requests.find((r) => r.method === 'POST' && r.url.endsWith('/orgs'));
    expect(post?.body).toMatchObject({ name: 'Hilltop Farm', kind: 'farm' });
  });

  it('lists several organizations and remembers the last one opened', async () => {
    installFakeBackend({ platform: { organizations: [ORG, SECOND_ORG] } });
    const { user, unmount } = renderApp();
    const list = await screen.findByTestId('org-list');
    expect(within(list).getAllByRole('link')).toHaveLength(2);
    await user.click(within(list).getByRole('link', { name: /Fall Creek Land Trust/ }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument();
    expect(window.localStorage.getItem('thicket-last-org')).toBe(SECOND_ORG.id);
    unmount();

    window.location.hash = '#/';
    installFakeBackend({ platform: { organizations: [ORG, SECOND_ORG] } });
    renderApp();
    await waitFor(() => expect(window.location.hash).toBe(`#/orgs/${SECOND_ORG.id}`));
  });

  it('sends every mutating request with the CSRF header and routes a 401 back to sign-in', async () => {
    const backend = installFakeBackend({ platform: {} });
    const { user } = renderApp();
    await screen.findByRole('heading', { level: 1, name: 'Dashboard' });
    await user.click(screen.getByTestId('user-menu'));
    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }));
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    const logout = backend.requests.find((r) => r.url.endsWith('/auth/logout'));
    expect(logout?.method).toBe('POST');
    expect(logout?.headers['x-requested-with']).toBe('thicket');
    const reads = backend.requests.filter((r) => r.method === 'GET');
    expect(reads.length).toBeGreaterThan(0);
    expect(reads.every((r) => r.headers['x-requested-with'] === undefined)).toBe(true);
  });

  it('explains when the user is not a member of the organization in the URL', async () => {
    window.location.hash = '#/orgs/org_other';
    installFakeBackend({ platform: {} });
    renderApp();
    expect(await screen.findByTestId('org-forbidden')).toBeInTheDocument();
  });
});
