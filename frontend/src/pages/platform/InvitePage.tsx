import { useState } from 'react';
import { describeError, type FriendlyError } from '../../api/errors';
import type { Organization } from '../../api/generated';
import { ErrorCallout } from '../../components/feedback/ErrorCallout';
import { PageHeader } from '../../components/platform/primitives';
import { Button, ButtonLink } from '../../components/ui/Button';
import { Callout } from '../../components/ui/Callout';
import { Panel } from '../../components/ui/Panel';
import { orgHref } from '../../lib/routes';

export function InvitePage({
  token,
  onAccept,
}: {
  token: string;
  onAccept: (token: string) => Promise<Organization>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [joined, setJoined] = useState<Organization | null>(null);

  const accept = async () => {
    setBusy(true);
    setError(null);
    try {
      setJoined(await onAccept(token));
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-xl space-y-6 py-8">
      <PageHeader
        title="You have been invited"
        description="Accepting adds this organization to your account with the role the inviter chose."
      />
      <Panel className="p-6" label="Invitation">
        {joined ? (
          <Callout
            tone="ok"
            role="status"
            title={`You joined ${joined.name}`}
            actions={
              <ButtonLink href={orgHref(joined.id)} variant="primary" size="sm">
                Open the dashboard
              </ButtonLink>
            }
          >
            Sites, recordings and alerts for {joined.name} are now available to you.
          </Callout>
        ) : (
          <div className="space-y-4">
            <p className="text-sm text-muted">
              Invitation token:{' '}
              <code className="rounded bg-surface-muted px-1.5 py-0.5 text-xs">{token}</code>
            </p>
            {error ? <ErrorCallout error={error} /> : null}
            <Button variant="primary" onClick={() => void accept()} disabled={busy}>
              {busy ? 'Joining...' : 'Accept invitation'}
            </Button>
          </div>
        )}
      </Panel>
    </div>
  );
}
