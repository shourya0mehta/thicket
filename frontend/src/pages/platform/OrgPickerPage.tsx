import { useState, type FormEvent } from 'react';
import { describeError, type FriendlyError } from '../../api/errors';
import type { Organization, OrganizationCreate, OrganizationKind, Role } from '../../api/generated';
import { ErrorCallout } from '../../components/feedback/ErrorCallout';
import { Field, PageHeader, Select, TextInput } from '../../components/platform/primitives';
import { Button } from '../../components/ui/Button';
import { ArrowRightIcon, PlusIcon } from '../../components/ui/icons';
import { Panel } from '../../components/ui/Panel';
import { ORG_KINDS, orgKindLabel } from '../../lib/labels';
import { ROLE_LABEL } from '../../lib/roles';
import { orgHref } from '../../lib/routes';
import { browserTimeZone, isValidTimeZone, timeZoneOptions } from '../../lib/validation';

export function CreateOrgForm({
  onCreate,
  compact,
}: {
  onCreate: (body: OrganizationCreate) => Promise<void>;
  compact?: boolean;
}) {
  const [name, setName] = useState('');
  const [kind, setKind] = useState<OrganizationKind>('farm');
  const [timezone, setTimezone] = useState(browserTimeZone());
  const [region, setRegion] = useState('');
  const [country, setCountry] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ name?: string; timezone?: string }>({});
  const zones = timeZoneOptions();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const errors: typeof fieldErrors = {};
    if (!name.trim()) errors.name = 'Give your farm or project a name.';
    if (!isValidTimeZone(timezone))
      errors.timezone = 'Use an IANA time zone such as America/Chicago.';
    setFieldErrors(errors);
    if (Object.keys(errors).length) return;
    setBusy(true);
    setError(null);
    try {
      await onCreate({
        name: name.trim(),
        kind,
        timezone: timezone.trim(),
        region: region.trim() || null,
        country: country.trim() || null,
      });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate>
      <Field label="Name" required error={fieldErrors.name}>
        {(props) => (
          <TextInput
            {...props}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Hollow Creek Farm"
            maxLength={120}
          />
        )}
      </Field>
      <div className={compact ? 'grid gap-4' : 'grid gap-4 sm:grid-cols-2'}>
        <Field label="Kind">
          {(props) => (
            <Select
              {...props}
              value={kind}
              onChange={(e) => setKind(e.target.value as OrganizationKind)}
            >
              {ORG_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field
          label="Time zone"
          required
          error={fieldErrors.timezone}
          hint="Daily rollups and recording times use this zone."
        >
          {(props) => (
            <>
              <TextInput
                {...props}
                list={`${props.id}-zones`}
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                autoComplete="off"
              />
              <datalist id={`${props.id}-zones`}>
                {zones.map((z) => (
                  <option key={z} value={z} />
                ))}
              </datalist>
            </>
          )}
        </Field>
        <Field label="Region or state" hint="Optional, for reports.">
          {(props) => (
            <TextInput {...props} value={region} onChange={(e) => setRegion(e.target.value)} />
          )}
        </Field>
        <Field label="Country" hint="Optional.">
          {(props) => (
            <TextInput {...props} value={country} onChange={(e) => setCountry(e.target.value)} />
          )}
        </Field>
      </div>
      {error ? <ErrorCallout error={error} /> : null}
      <Button type="submit" variant="primary" disabled={busy}>
        <PlusIcon size={15} />
        {busy ? 'Creating...' : 'Create organization'}
      </Button>
    </form>
  );
}

export function OrgPickerPage({
  organizations,
  roles,
  onCreate,
}: {
  organizations: Organization[];
  roles: Record<string, Role>;
  onCreate: (body: OrganizationCreate) => Promise<void>;
}) {
  const [creating, setCreating] = useState(organizations.length === 0);
  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 py-6">
      <PageHeader
        title={organizations.length ? 'Your organizations' : 'Create your farm or project'}
        description={
          organizations.length
            ? 'Choose where to work. Each organization has its own sites, recorders, alerts and reports.'
            : 'An organization groups your sites, recorders, members and reports. You become its owner and can invite others.'
        }
      />
      {organizations.length ? (
        <ul className="grid gap-3 sm:grid-cols-2" data-testid="org-list">
          {organizations.map((org) => (
            <li key={org.id}>
              <a
                href={orgHref(org.id)}
                className="group flex h-full flex-col rounded-2xl border border-line-strong bg-raised p-4 transition-colors hover:border-mark/60"
              >
                <span className="text-base font-semibold text-ink">{org.name}</span>
                <span className="mt-0.5 text-xs text-muted">
                  {orgKindLabel(org.kind)}
                  {org.region ? ` · ${org.region}` : ''}
                  {roles[org.id] ? ` · ${ROLE_LABEL[roles[org.id]!]}` : ''}
                </span>
                <span className="mt-3 text-sm text-muted">
                  {org.site_count ?? 0} sites · {org.member_count ?? 1} members
                </span>
                <span className="mt-auto inline-flex items-center gap-1 pt-3 text-xs font-medium text-accent">
                  Open dashboard
                  <ArrowRightIcon
                    size={13}
                    className="transition-transform group-hover:translate-x-0.5"
                  />
                </span>
              </a>
            </li>
          ))}
        </ul>
      ) : null}
      <Panel className="p-5 sm:p-6" label="Create an organization">
        {creating ? (
          <>
            <h2 className="mb-4 text-base font-semibold tracking-tight text-ink">
              {organizations.length ? 'Create another organization' : 'Details'}
            </h2>
            <CreateOrgForm onCreate={onCreate} />
          </>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted">Manage a second property or project separately.</p>
            <Button variant="secondary" size="sm" onClick={() => setCreating(true)}>
              <PlusIcon size={14} /> New organization
            </Button>
          </div>
        )}
      </Panel>
    </div>
  );
}
