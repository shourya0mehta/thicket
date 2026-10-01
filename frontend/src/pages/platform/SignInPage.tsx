import { useState, type FormEvent } from 'react';
import { resolveApiUrl } from '../../api/client';
import { describeError, type FriendlyError } from '../../api/errors';
import type { AuthConfig } from '../../api/generated';
import { ErrorCallout } from '../../components/feedback/ErrorCallout';
import { LeafMark } from '../../components/layout/LeafMark';
import { Field, TextInput } from '../../components/platform/primitives';
import { Button, ButtonLink } from '../../components/ui/Button';
import { Panel } from '../../components/ui/Panel';

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z"
      />
      <path
        fill="#FBBC05"
        d="M3.97 10.72A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.18.29-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33Z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.9 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z"
      />
    </svg>
  );
}

export function SignInPage({
  config,
  onDevSignIn,
  nextHash,
}: {
  config: AuthConfig;
  onDevSignIn: (email: string, name: string) => Promise<void>;
  /** Hash to return to after Google sign-in. */
  nextHash?: string;
}) {
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);

  const googleUrl = (() => {
    // The server returns a root-relative path; it lives on the API origin, which
    // differs from this page's when VITE_API_BASE_URL is set.
    const start = resolveApiUrl(config.sign_in_url);
    if (!start) return null;
    if (!nextHash) return start;
    const joiner = start.includes('?') ? '&' : '?';
    return `${start}${joiner}next=${encodeURIComponent(nextHash)}`;
  })();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = email.trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(trimmed)) {
      setEmailError('Enter an email address such as you@farm.example.');
      return;
    }
    setEmailError(null);
    setBusy(true);
    setError(null);
    try {
      await onDevSignIn(trimmed, name);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-md flex-col justify-center py-10">
      <div className="mb-6 flex items-center gap-3">
        <LeafMark className="h-10 w-10" />
        <div>
          <p className="text-lg font-semibold tracking-tight text-ink">Thicket</p>
          <p className="text-sm text-muted">Listen to Nature</p>
        </div>
      </div>
      <Panel className="p-6 sm:p-8" label="Sign in">
        <h1 className="text-xl font-semibold tracking-tight text-ink">Sign in</h1>
        <p className="mt-1 text-sm text-muted">
          Acoustic monitoring for farms and land stewards: recordings, species detection events,
          alerts and reports for your sites.
        </p>

        {config.mode === 'google' ? (
          <div className="mt-6 space-y-3">
            {googleUrl ? (
              <ButtonLink
                href={googleUrl}
                variant="secondary"
                className="w-full"
                data-testid="google-sign-in"
              >
                <GoogleMark />
                Continue with Google
              </ButtonLink>
            ) : (
              <p className="text-sm text-danger">
                Google sign-in is not configured on this server (no sign-in URL).
              </p>
            )}
            {config.allowed_domains?.length ? (
              <p className="text-xs text-muted">
                Accounts from {config.allowed_domains.join(', ')} can sign in.
              </p>
            ) : null}
          </div>
        ) : null}

        {config.mode === 'dev' ? (
          <form onSubmit={(e) => void submit(e)} className="mt-6 space-y-4" noValidate>
            <p className="rounded-xl bg-warn-soft px-3 py-2 text-xs text-ink">
              Development sign-in: any email works and no password is checked. Do not use this mode
              on a public server.
            </p>
            <Field label="Email" required error={emailError}>
              {(props) => (
                <TextInput
                  {...props}
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@farm.example"
                />
              )}
            </Field>
            <Field label="Name" hint="Shown to other members of your organizations.">
              {(props) => (
                <TextInput
                  {...props}
                  type="text"
                  autoComplete="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              )}
            </Field>
            {error ? <ErrorCallout error={error} /> : null}
            <Button type="submit" variant="primary" className="w-full" disabled={busy}>
              {busy ? 'Signing in...' : 'Sign in'}
            </Button>
          </form>
        ) : null}
      </Panel>
      <p className="mt-4 text-center text-xs text-muted">
        <a className="link" href="#/methods">
          How Thicket turns recordings into evidence
        </a>
      </p>
    </div>
  );
}
